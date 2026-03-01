output "api_gateway_url" {
  description = "URL to configure as the VK callback endpoint"
  value       = "https://${yandex_api_gateway.plankabot.domain}/"
}

output "function_id" {
  description = "Yandex Cloud Function ID"
  value       = yandex_function.plankabot.id
}

output "ydb_endpoint" {
  description = "YDB API endpoint (grpcs://...)"
  value       = yandex_ydb_database_serverless.plankabot.ydb_api_endpoint
}

output "ydb_database_path" {
  description = "YDB database path (/ru-central1/...)"
  value       = yandex_ydb_database_serverless.plankabot.database_path
}