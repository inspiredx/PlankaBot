locals {
  # Root of the repo — one level above terraform/
  repo_root = "${path.module}/.."
  zip_path  = "${path.module}/../dist/function.zip"
}

# Package src/ + requirements.txt into a zip for deployment
data "archive_file" "function_zip" {
  type        = "zip"
  output_path = local.zip_path

  source {
    content  = file("${local.repo_root}/src/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${local.repo_root}/src/bot.py")
    filename = "bot.py"
  }
  source {
    content  = file("${local.repo_root}/src/config.py")
    filename = "config.py"
  }
  source {
    content  = file("${local.repo_root}/requirements.txt")
    filename = "requirements.txt"
  }
  source {
    content  = file("${local.repo_root}/src/prompts/geese_story_prompt.txt")
    filename = "prompts/geese_story_prompt.txt"
  }
}

resource "yandex_logging_group" "plankabot" {
  name      = "${var.function_name}-logs-${var.environment}"
  folder_id = var.folder_id
}

resource "yandex_iam_service_account" "invoker" {
  name      = "${var.function_name}-invoker-${var.environment}"
  folder_id = var.folder_id
}

resource "yandex_function_iam_binding" "invoker" {
  function_id = yandex_function.plankabot.id
  role        = "functions.functionInvoker"
  members     = ["serviceAccount:${yandex_iam_service_account.invoker.id}"]
}

resource "yandex_function" "plankabot" {
  name               = "${var.function_name}-${var.environment}"
  description        = "PlankaBot VK callback handler (${var.environment})"
  runtime            = "python312"
  entrypoint         = "handler.handler"
  memory             = 128
  execution_timeout  = "10"
  concurrency        = 3
  folder_id          = var.folder_id

  user_hash = data.archive_file.function_zip.output_sha256

  content {
    zip_filename = data.archive_file.function_zip.output_path
  }

  environment = {
    VK_GROUP_TOKEN        = var.vk_group_token
    VK_CONFIRMATION_TOKEN = var.vk_confirmation_token
    YANDEX_FOLDER_ID      = var.folder_id
    YANDEX_LLM_API_KEY    = var.yandex_llm_api_key
  }

  log_options {
    log_group_id = yandex_logging_group.plankabot.id
    min_level    = "LEVEL_UNSPECIFIED"
  }
}
