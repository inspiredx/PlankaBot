variable "cloud_id" {
  description = "Yandex Cloud cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Yandex Cloud folder ID for this environment"
  type        = string
}

variable "environment" {
  description = "Environment name (dev or prod)"
  type        = string
}

variable "function_name" {
  description = "Name of the Yandex Cloud Function"
  type        = string
  default     = "plankabot-vk-callback"
}

variable "vk_group_token" {
  description = "VK group API token (sensitive)"
  type        = string
  sensitive   = true
}

variable "vk_confirmation_token" {
  description = "VK callback confirmation token (sensitive)"
  type        = string
  sensitive   = true
}

variable "tfstate_bucket" {
  description = "Object Storage bucket name used for Terraform state"
  type        = string
}

variable "yandex_llm_api_key" {
  description = "API key for the plankabot-llm-<env> service account (created manually in YC Console)"
  type        = string
  sensitive   = true
}
