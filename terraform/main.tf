terraform {
  required_version = ">= 1.6"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "~> 0.189.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  backend "s3" {
    # Yandex Object Storage is S3-compatible (S3 backend).
    # bucket and key are supplied at `terraform init` time via -backend-config.
    # Credentials come from AWS_PROFILE (plankabot-dev / plankabot-prod)
    # or explicit AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars.
    #
    # Example init command (dev):
    #   AWS_PROFILE=plankabot-dev terraform init \
    #     -backend-config="bucket=plankabot-tfstate-dev" \
    #     -backend-config="key=terraform.tfstate" \
    #     -backend-config="region=ru-central1" \
    #     -backend-config="skip_region_validation=true" \
    #     -backend-config="skip_credentials_validation=true" \
    #     -backend-config="skip_metadata_api_check=true" \
    #     -backend-config="skip_requesting_account_id=true" \
    #     -backend-config="force_path_style=true"
    #
    # Do not hardcode bucket/key/credentials here.
    skip_region_validation      = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    force_path_style            = true
    region                      = "ru-central1"
    endpoints = {
      s3 = "https://storage.yandexcloud.net"
    }
  }
}

provider "yandex" {
  cloud_id                 = var.cloud_id
  folder_id                = var.folder_id
  service_account_key_file = var.sa_key_file
}

variable "sa_key_file" {
  description = "Path to the deployer service account authorized key JSON file"
  type        = string
  default     = ""
}