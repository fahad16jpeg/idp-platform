locals {
  name_prefix = "${var.project_name}-${var.environment}"

  tags = {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = local.tags
}

# Makes globally unique names (the container registry) unlikely to collide.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}
