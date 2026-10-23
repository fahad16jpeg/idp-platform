resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${local.name_prefix}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.tags
}

# The app pulls from the registry with its own identity: no registry passwords anywhere.
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# Role assignments take a while to propagate. Without this pause the very first
# image pull can be refused and the first revision never starts.
resource "time_sleep" "wait_for_acr_pull" {
  create_duration = "60s"

  depends_on = [azurerm_role_assignment.acr_pull]
}

resource "azurerm_container_app" "this" {
  name                         = "ca-${local.name_prefix}"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name  = "appinsights-connection-string"
    value = azurerm_application_insights.this.connection_string
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "app"
      image  = var.container_image
      cpu    = var.container_cpu
      memory = var.container_memory

      env {
        name  = "APP_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "APP_LOG_LEVEL"
        value = var.log_level
      }

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }

      # Startup and liveness use /health (process is up); readiness uses /ready
      # (dependencies are reachable) so traffic only reaches replicas that can serve it.
      startup_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 8000
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 8000
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/ready"
        port      = 8000
      }
    }
  }

  depends_on = [time_sleep.wait_for_acr_pull]
}
