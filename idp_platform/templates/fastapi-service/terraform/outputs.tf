output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "acr_name" {
  value = azurerm_container_registry.this.name
}

output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "container_app_name" {
  value = azurerm_container_app.this.name
}

output "container_app_url" {
  description = "Public HTTPS URL of the service"
  value       = "https://${azurerm_container_app.this.ingress[0].fqdn}"
}

output "application_insights_name" {
  value = azurerm_application_insights.this.name
}
