#!/usr/bin/env bash
# One-time Azure setup for the CI/CD pipeline. Safe to re-run.
#
#   1. Storage account for Terraform remote state
#   2. An Entra ID app that GitHub Actions logs in as via OIDC (no stored passwords)
#   3. The role assignments that identity needs
#   4. The GitHub repository variables the workflows read (set automatically if
#      the GitHub CLI is logged in, otherwise printed for you to add)
#
# Usage:   ./scripts/bootstrap-azure.sh <github-owner>/<repo> [azure-region]
# Needs:   az CLI logged in (`az login`) as a subscription Owner. Runs in Git Bash,
#          WSL, macOS/Linux or Azure Cloud Shell.
set -euo pipefail

REPO="${1:?Usage: $0 <github-owner>/<repo> [azure-region]}"
LOCATION="${2:-__AZURE_REGION__}"
PROJECT="__PROJECT_NAME__"
ENVIRONMENT="dev"

STATE_RG="rg-${PROJECT}-tfstate"
STATE_CONTAINER="tfstate"
APP_NAME="github-${PROJECT}"

say() { printf '\n==> %s\n' "$*"; }

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
say "Using subscription ${SUBSCRIPTION_ID}"

# ---- 1. Terraform state storage ----------------------------------------------
say "Terraform state storage"
az group create --name "$STATE_RG" --location "$LOCATION" --output none

STATE_SA="$(az storage account list --resource-group "$STATE_RG" --query "[0].name" -o tsv)"
if [ -z "$STATE_SA" ]; then
  # 3-24 lowercase alphanumerics, globally unique. (od reads a fixed number of
  # bytes; `tr < /dev/urandom | head` would die of SIGPIPE under pipefail.)
  suffix="$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  STATE_SA="st$(echo "${PROJECT//-/}" | cut -c1-12)tf${suffix}"
  az storage account create \
    --name "$STATE_SA" --resource-group "$STATE_RG" --location "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --allow-blob-public-access false --output none
  # Versioning lets you recover a previous state file if something goes wrong.
  az storage account blob-service-properties update \
    --account-name "$STATE_SA" --resource-group "$STATE_RG" \
    --enable-versioning true --output none
fi
az storage container-rm create \
  --storage-account "$STATE_SA" --resource-group "$STATE_RG" \
  --name "$STATE_CONTAINER" --output none
echo "Storage account: ${STATE_SA}"

# ---- 2. GitHub OIDC identity -------------------------------------------------
say "GitHub Actions identity (${APP_NAME})"
APP_ID="$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)"
if [ -z "$APP_ID" ]; then
  APP_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
fi
if ! az ad sp show --id "$APP_ID" --output none 2>/dev/null; then
  az ad sp create --id "$APP_ID" --output none
fi
SP_OBJECT_ID="$(az ad sp show --id "$APP_ID" --query id -o tsv)"

add_federated_credential() {
  local name="$1" subject="$2"
  if [ -z "$(az ad app federated-credential list --id "$APP_ID" \
        --query "[?name=='${name}'].name" -o tsv)" ]; then
    az ad app federated-credential create --id "$APP_ID" --output none --parameters \
      "{\"name\":\"${name}\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"${subject}\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
  fi
}
# build job runs on main; deploy job runs in the "dev" GitHub environment.
add_federated_credential "github-main" "repo:${REPO}:ref:refs/heads/main"
add_federated_credential "github-env-${ENVIRONMENT}" "repo:${REPO}:environment:${ENVIRONMENT}"

# ---- 3. Role assignments -------------------------------------------------------
say "Role assignments"
assign_role() {
  local role="$1" scope="$2"
  if [ -z "$(az role assignment list --assignee "$SP_OBJECT_ID" --role "$role" \
        --scope "$scope" --query "[0].id" -o tsv)" ]; then
    az role assignment create --assignee-object-id "$SP_OBJECT_ID" \
      --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$scope" --output none
  fi
  echo "  ${role}"
}
SUBSCRIPTION_SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
STATE_SA_ID="$(az storage account show --name "$STATE_SA" --resource-group "$STATE_RG" --query id -o tsv)"
# Create and manage the app's resources (and push images to its registry).
assign_role "Contributor" "$SUBSCRIPTION_SCOPE"
# Terraform grants the app's managed identity AcrPull, which needs this role.
# Tighten later with an ABAC condition limiting it to AcrPull if you like.
assign_role "Role Based Access Control Administrator" "$SUBSCRIPTION_SCOPE"
# Read/write the Terraform state blob with Entra ID auth (no storage keys).
assign_role "Storage Blob Data Contributor" "$STATE_SA_ID"

# You need the same data access to run Terraform from your own machine.
if USER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null)"; then
  if [ -z "$(az role assignment list --assignee "$USER_OBJECT_ID" \
        --role "Storage Blob Data Contributor" --scope "$STATE_SA_ID" --query "[0].id" -o tsv)" ]; then
    az role assignment create --assignee-object-id "$USER_OBJECT_ID" \
      --assignee-principal-type User --role "Storage Blob Data Contributor" \
      --scope "$STATE_SA_ID" --output none
  fi
  echo "  Storage Blob Data Contributor (you, for local terraform)"
fi

# ---- 4. GitHub repository variables ------------------------------------------
say "GitHub repository variables"
VARIABLES=(
  "AZURE_CLIENT_ID=${APP_ID}"
  "AZURE_TENANT_ID=${TENANT_ID}"
  "AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}"
  "TFSTATE_RESOURCE_GROUP=${STATE_RG}"
  "TFSTATE_STORAGE_ACCOUNT=${STATE_SA}"
)
if command -v gh > /dev/null && gh auth status > /dev/null 2>&1; then
  gh api --method PUT "repos/${REPO}/environments/${ENVIRONMENT}" --silent
  for pair in "${VARIABLES[@]}"; do
    gh variable set "${pair%%=*}" --repo "$REPO" --body "${pair#*=}"
  done
  echo "Set on ${REPO} (and created the '${ENVIRONMENT}' environment)."
else
  echo "Add these under GitHub > Settings > Secrets and variables > Actions > Variables:"
  printf '  %s\n' "${VARIABLES[@]}"
  echo "Also create an environment named '${ENVIRONMENT}' under Settings > Environments."
fi

cat <<EOF

Optional:
  - Variable ALERT_EMAIL: email address for Azure Monitor alerts
  - Secret   ALERT_WEBHOOK_URL: Slack/Teams webhook for failed-deployment messages

For local Terraform, create terraform/backend.hcl containing:
  resource_group_name  = "${STATE_RG}"
  storage_account_name = "${STATE_SA}"
  container_name       = "${STATE_CONTAINER}"
  key                  = "${PROJECT}-${ENVIRONMENT}.tfstate"
  use_azuread_auth     = true

Role assignments can take a few minutes to apply. Then push to main to deploy.
EOF
