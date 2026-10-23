locals {
  action_group_ids = azurerm_monitor_action_group.this[*].id
}

resource "azurerm_monitor_action_group" "this" {
  count = var.alert_email == "" ? 0 : 1

  name                = "ag-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  short_name          = substr(replace(var.project_name, "-", ""), 0, 12)
  tags                = local.tags

  email_receiver {
    name                    = "on-call"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

# Unhealthy application: no replica is running (crash loop, failing probes, bad image).
resource "azurerm_monitor_metric_alert" "no_replicas" {
  name                = "alert-${local.name_prefix}-no-replicas"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_container_app.this.id]
  description         = "No running replicas: the app is down or failing its health probes."
  severity            = 0
  frequency           = "PT1M"
  window_size         = "PT5M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Maximum"
    operator         = "LessThan"
    threshold        = 1
  }

  dynamic "action" {
    for_each = local.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

# Unhealthy application: containers keep restarting (liveness failures, crashes, OOM).
resource "azurerm_monitor_metric_alert" "restarts" {
  name                = "alert-${local.name_prefix}-restarts"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_container_app.this.id]
  description         = "Containers restarted more than 3 times in 15 minutes."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 3
  }

  dynamic "action" {
    for_each = local.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

# Unhealthy application: requests are failing (from Application Insights telemetry).
resource "azurerm_monitor_metric_alert" "failed_requests" {
  name                = "alert-${local.name_prefix}-failed-requests"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_application_insights.this.id]
  description         = "More than 5 failed requests in 15 minutes."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = local.tags

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 5
  }

  dynamic "action" {
    for_each = local.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}

# Failed deployment: Azure rejected or failed an update to the Container App.
# (The deploy workflow also fails, and notifies, when a new revision isn't healthy.)
resource "azurerm_monitor_activity_log_alert" "deployment_failed" {
  name                = "alert-${local.name_prefix}-deployment-failed"
  resource_group_name = azurerm_resource_group.this.name
  location            = "global"
  scopes              = [azurerm_resource_group.this.id]
  description         = "Creating or updating the Container App failed."
  tags                = local.tags

  criteria {
    category       = "Administrative"
    operation_name = "Microsoft.App/containerApps/write"
    status         = "Failed"
  }

  dynamic "action" {
    for_each = local.action_group_ids
    content {
      action_group_id = action.value
    }
  }
}
