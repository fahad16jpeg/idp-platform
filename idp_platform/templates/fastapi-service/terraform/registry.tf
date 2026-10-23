# Registry names are global and alphanumeric only, hence the random suffix.
resource "azurerm_container_registry" "this" {
  name                = substr("acr${replace(var.project_name, "-", "")}${random_string.suffix.result}", 0, 50)
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = var.acr_sku
  admin_enabled       = false
  tags                = local.tags
}
