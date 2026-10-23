variable "project_name" {
  description = "Service name; used as a prefix for every resource"
  type        = string
  default     = "__PROJECT_NAME__"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.project_name))
    error_message = "Use 3-20 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod."
  }
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "__AZURE_REGION__"
}

variable "acr_sku" {
  description = "Azure Container Registry SKU"
  type        = string
  default     = "__ACR_SKU__"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.acr_sku)
    error_message = "acr_sku must be Basic, Standard or Premium."
  }
}

variable "container_image" {
  description = "Image to run, e.g. <acr>.azurecr.io/<name>:<git-sha>. Set by the deploy workflow."
  type        = string
}

variable "container_cpu" {
  description = "vCPU per replica; must pair with container_memory (0.25/0.5Gi, 0.5/1Gi, 1/2Gi...)"
  type        = number
  default     = 0.5
}

variable "container_memory" {
  description = "Memory per replica"
  type        = string
  default     = "1Gi"
}

variable "min_replicas" {
  description = "Minimum replicas. Keep at least 1 so the 'no replicas' alert means the app is down."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum replicas"
  type        = number
  default     = 3
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"
}

variable "log_retention_days" {
  description = "Log Analytics retention in days"
  type        = number
  default     = 30
}

variable "alert_email" {
  description = "Email for alert notifications. Empty = alerts are created but notify nobody."
  type        = string
  default     = ""
}
