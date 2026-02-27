# Service account used by the bot to call Yandex AI Studio (LLM API).
# The API key for this SA is created MANUALLY in the YC Console and stored
# as a GitHub secret — it is NOT managed here.
resource "yandex_iam_service_account" "llm" {
  name      = "plankabot-llm-${var.environment}"
  folder_id = var.folder_id
}

resource "yandex_resourcemanager_folder_iam_member" "llm_language_models" {
  folder_id = var.folder_id
  role      = "ai.languageModels.user"
  member    = "serviceAccount:${yandex_iam_service_account.llm.id}"
}