resource "yandex_logging_group" "plankabot_gw" {
  name             = "${var.function_name}-gw-logs-${var.environment}"
  folder_id        = var.folder_id
  retention_period = "24h"
}

resource "yandex_api_gateway" "plankabot" {
  name        = "${var.function_name}-gw-${var.environment}"
  description = "PlankaBot VK callback API gateway (${var.environment})"
  folder_id   = var.folder_id

  log_options {
    log_group_id = yandex_logging_group.plankabot_gw.id
    min_level    = "ERROR"
  }

  spec = <<-EOT
openapi: "3.0.0"
info:
  title: PlankaBot VK Callback
  version: "1.0"
paths:
  /:
    post:
      summary: VK callback endpoint
      operationId: vkCallback
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id: ${yandex_function.plankabot.id}
        tag: $latest
        service_account_id: ${yandex_iam_service_account.invoker.id}
      responses:
        "200":
          description: OK
          content:
            text/plain:
              schema:
                type: string
  /current-story.txt:
    get:
      summary: Export current active story as plain text
      operationId: exportStory
      parameters:
        - name: peer_id
          in: query
          required: false
          schema:
            type: integer
            default: 2000000001
      x-yc-apigateway-integration:
        type: cloud_functions
        function_id: ${yandex_function.plankabot.id}
        tag: $latest
        service_account_id: ${yandex_iam_service_account.invoker.id}
      responses:
        "200":
          description: Story text or "no active story" message
          content:
            text/plain:
              schema:
                type: string
EOT
}
