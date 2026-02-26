output "api_gateway_url" {
  description = "URL to configure as the VK callback endpoint"
  value       = "https://${yandex_api_gateway.plankabot.domain}/"
}

output "function_id" {
  description = "Yandex Cloud Function ID"
  value       = yandex_function.plankabot.id
}