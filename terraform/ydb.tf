resource "yandex_ydb_database_serverless" "plankabot" {
  name      = "plankabot-db-${var.environment}"
  folder_id = var.folder_id

  serverless_database {
    enable_throttling_rcu_limit = false
    provisioned_rcu_limit       = 0
    storage_size_limit          = 10
    throttling_rcu_limit        = 0
  }
}

resource "yandex_ydb_table" "users" {
  path              = "users"
  connection_string = yandex_ydb_database_serverless.plankabot.ydb_full_endpoint

  column {
    name     = "user_id"
    type     = "Int64"
    not_null = true
  }
  column {
    name     = "name"
    type     = "Utf8"
    not_null = true
  }
  column {
    name     = "is_bot_admin"
    type     = "Bool"
    not_null = true
  }
  column {
    name = "last_activity"
    type = "Timestamp"
  }
  column {
    name     = "created_at"
    type     = "Timestamp"
    not_null = true
  }

  primary_key = ["user_id"]
}

resource "yandex_ydb_table" "plank_records" {
  path              = "plank_records"
  connection_string = yandex_ydb_database_serverless.plankabot.ydb_full_endpoint

  column {
    name     = "user_id"
    type     = "Int64"
    not_null = true
  }
  column {
    name     = "plank_date"
    type     = "Utf8"
    not_null = true
  }
  column {
    name = "actual_seconds"
    type = "Int32"
  }
  column {
    name     = "created_at"
    type     = "Timestamp"
    not_null = true
  }

  # No secondary index on plank_date: with 10-20 users and 90-day TTL the table
  # holds at most ~1,800 rows. A full scan by plank_date (second PK column) is
  # single-digit milliseconds at this scale — an index would add write overhead
  # and Terraform complexity with zero practical benefit.
  primary_key = ["user_id", "plank_date"]

  ttl {
    column_name     = "created_at"
    expire_interval = "P90D"
  }
}
