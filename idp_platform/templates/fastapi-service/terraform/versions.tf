terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # Remote state in Azure Storage, so CI and your laptop share one state.
  # Values are supplied at init time: terraform init -backend-config=backend.hcl
  backend "azurerm" {}
}

# Credentials and subscription come from the environment: `az login` locally,
# ARM_CLIENT_ID / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID / ARM_USE_OIDC in CI.
provider "azurerm" {
  features {}
}
