# PlankaBot Project Rules

## What This Project Is
PlankaBot is a VK group chat bot that tracks daily plank exercises for a group of users. It runs as a **Yandex Cloud Function** triggered via VK Callback API through an **API Gateway**. Infrastructure is managed with **Terraform** and deployed via **GitHub Actions**.

## Tech Stack
- **Runtime**: Python 3.12, Yandex Cloud Functions
- **VK integration**: `vk-api` library, Callback API (webhook, not longpoll)
- **Database**: YDB Serverless (row-oriented tables, YSQL), accessed via `ydb` Python SDK
- **LLM**: Yandex AI Studio (OpenAI-compatible API) for "ебать гусей" feature
- **IaC**: Terraform with Yandex Cloud provider, state in Yandex Object Storage
- **CI/CD**: GitHub Actions (`.github/workflows/deploy-dev.yml`) — runs tests then `terraform apply`

## Bot Commands (Russian)
All commands are in Russian and work in VK group chats only (peer_id ≥ 2000000000):
- `планка` — record today's plank for the user (no value)
- `планка X` — record plank with a numeric value X (actual seconds)
- `стата` — show today's plank stats: who did it and who hasn't (today = UTC+3 by default)
- `гайд` — show command help
- `ебать гусей [context]` — generate a goose-wisdom story via LLM

## Data Architecture (YDB Serverless, row-oriented)
### `users` table
- `user_id` Int64 PK — VK user ID
- `name` Utf8 — display name from VK
- `is_bot_admin` Bool — admin flag
- `last_activity` Timestamp — updated on each interaction
- `created_at` Timestamp

### `plank_records` table
- `user_id` Int64 PK part — references users.user_id
- `plank_date` Utf8 PK part — ISO date string in configured timezone (e.g. `2026-03-01`)
- `actual_seconds` Int32 nullable — the value provided by user
- `created_at` Timestamp
- PK: (`user_id`, `plank_date`) — one record per user per day, natural dedup

## Key Design Decisions
- **Explicit YDB transactions**: all writes use `SerializableReadWrite` tx with explicit begin/commit
- **Session pool**: initialized once at module level (outside handler) to survive warm invocations
- **Auth**: `ydb.iam.MetadataUrlCredentials()` in cloud; no local YDB auth (tests use mocks)
- **Timezone**: `PLANK_TIMEZONE` env var (default `Europe/Moscow`) for day boundary calculation
- **Duplicate detection**: if user already has a `plank_records` row for today → return "already done"
- **Stats**: `стата` queries only today's records (not all-time)
- **`actual_seconds` stored as Int32**: the numeric value from `планка X`; NULL if no value given

## Project Structure
```
src/
  handler.py     — Cloud Function entrypoint
  bot.py         — VK message routing and command handlers
  db.py          — YDB driver, session pool, all DB operations
  config.py      — env var config
  prompts/       — LLM system prompts
tests/
  test_bot.py    — bot routing tests (mocked db)
  test_db.py     — db layer tests (mocked YDB)
terraform/
  main.tf        — provider, backend
  function.tf    — Cloud Function + zip packaging
  ydb.tf         — YDB serverless DB + tables
  iam.tf         — service accounts and IAM bindings
  variables.tf   — input variables
  outputs.tf     — outputs
  environments/  — tfvars examples
.github/workflows/deploy-dev.yml — CI/CD pipeline
```

## Environment Variables
| Variable | Description | Default |
|---|---|---|
| `VK_GROUP_TOKEN` | VK group API token | required |
| `VK_CONFIRMATION_TOKEN` | VK callback confirmation token | required |
| `YANDEX_FOLDER_ID` | Yandex Cloud folder ID | required |
| `YANDEX_LLM_API_KEY` | API key for LLM SA | required |
| `YDB_ENDPOINT` | YDB endpoint (grpcs://...) | required |
| `YDB_DATABASE` | YDB database path (/ru-central1/...) | required |
| `PLANK_TIMEZONE` | Timezone for day calculation | `Europe/Moscow` |

## Testing
- Tests live in `tests/`, run with `pytest`
- YDB layer is fully mocked in tests — no real YDB connection needed
- CI runs `pip install -r requirements.txt -r requirements-dev.txt && pytest tests/ -v`

## Deployment
- Push to any branch triggers `deploy-dev.yml`
- Deployer SA key stored in `YC_SA_KEY_JSON_DEV` GitHub secret (has wide IAM role)
- No manual steps needed — Terraform provisions YDB DB, tables, IAM, function all at once
- Function's runtime SA gets `ydb.editor` role via Terraform

## Rules for Updating This File
- **Update this cline rule** whenever new commands are added, data schema changes, new env vars are introduced, or the deployment process changes.
- Keep the command list, data architecture, and env var table in sync with the actual code.