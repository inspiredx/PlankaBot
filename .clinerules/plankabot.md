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
- `планка X` — record plank with a numeric value X (actual seconds); if a record already exists for today, **updates** `actual_seconds` in place
- `стата` — show today's plank stats: who did it and who hasn't (today = UTC+3 by default)
- `гайд` — show command help
- `ебать гусей [context]` — generate a goose-wisdom story via LLM
- `кто сегодня [question]` — analyze today's chat messages and pick a winner based on the question (e.g. "кто сегодня больше всех похож на Цоя?")
- `объясни [как]` — explain a replied-to or forwarded message in the requested style (e.g. "объясни по-пацански"); if no style given, one is chosen at random

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

### `chat_messages` table
- `message_id` Utf8 PK — VK message ID (cast to string), globally unique; natural dedup via UPSERT
- `user_id` Int64 not null — sender VK user ID
- `user_name` Utf8 not null — display name (denormalized to avoid joins)
- `msg_date` Utf8 not null — ISO date string in configured timezone; used for day filtering
- `text` Utf8 not null — message text
- `created_at` Timestamp not null — TTL column
- TTL: P1D (1 day — only today's messages are needed)
- No secondary index: at most ~2,000 rows at any time; full scan is trivially fast

## Key Design Decisions — `кто сегодня`
- **Message tracking**: every incoming group chat message is saved to `chat_messages` via `db.save_message()` in `process_message()`, before command routing. **Bot commands are excluded** (`планка`, `стата`, `гайд`, `ебать гусей`, `кто сегодня`) — only organic free-form chat content is stored. Best-effort: exceptions are logged and never block the bot response.
- **Token economy**: `_build_who_is_today_input()` divides a fixed char budget (~93,000 chars ≈ 31,000 tokens) equally among N users. Within each user's share, newest messages are kept first (reversed iteration) so fresh context survives trimming when a user has many messages.
- **Prompt**: `src/prompts/who_is_today_prompt.txt` — Russian-language judge prompt; picks exactly one winner by name with ironic explanation. General enough for any context question.
- **No context → hint**: if `кто сегодня` is sent without a question, a usage hint is returned immediately without hitting the DB or LLM.

## Key Design Decisions
- **`PlankMarkResult(is_new, was_updated)`**: `mark_plank` returns a NamedTuple instead of bool; `is_new=True` → first insert, `was_updated=True` → existing record's `actual_seconds` updated, both False → no-op duplicate
- **Explicit YDB transactions**: all writes use `SerializableReadWrite` tx with explicit begin/commit
- **Session pool**: initialized once at module level (outside handler) to survive warm invocations
- **Auth**: `ydb.iam.MetadataUrlCredentials()` in cloud; no local YDB auth (tests use mocks)
- **Timezone**: `PLANK_TIMEZONE` env var (default `Europe/Moscow`) for day boundary calculation
- **Duplicate detection**: if user already has a `plank_records` row for today and no new value → return "already done" (no stale value echoed)
- **Auto-update**: if user sends `планка X` and already has a record for today → UPDATE `actual_seconds`, return "планка обновлена (X) 💪"
- **Stats**: `стата` queries only today's records (not all-time)
- **`actual_seconds` stored as Int32**: the numeric value from `планка X`; NULL if no value given; overwritten on re-submission with a value

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
| `VK_SECRET_KEY` | VK Callback API secret key for request validation | required |
| `YANDEX_FOLDER_ID` | Yandex Cloud folder ID | required |
| `YANDEX_LLM_API_KEY` | API key for LLM SA | required |
| `YDB_ENDPOINT` | YDB endpoint (grpcs://...) | required |
| `YDB_DATABASE` | YDB database path (/ru-central1/...) | required |
| `PLANK_TIMEZONE` | Timezone for day calculation | `Europe/Moscow` |

## Testing
- Tests live in `tests/`, run with `pytest`
- YDB layer is fully mocked in tests — no real YDB connection needed
- CI runs `pip install -r requirements.txt -r requirements-dev.txt && pytest tests/ -v`
- Use venv ./.venv/bin/activate defined in project directory for tests and other things

## Deployment
- Push to any branch triggers `deploy-dev.yml`
- Deployer SA key stored in `YC_SA_KEY_JSON_DEV` GitHub secret (has wide IAM role)
- No manual steps needed — Terraform provisions YDB DB, tables, IAM, function all at once
- Function's runtime SA gets `ydb.editor` role via Terraform

## Rules for Updating This File
- **Update this cline rule** whenever new commands are added, data schema changes, new env vars are introduced, or the deployment process changes.
- Keep the command list, data architecture, and env var table in sync with the actual code.
- **Keep `README.md` up to date**: update the README whenever env vars, commands, deployment steps, or setup instructions change.
- **Keep the in-bot guide up to date**: update `handle_guide()` in `src/bot.py` whenever commands are added, removed, or their syntax changes.
- **All three must be updated together** when bot commands change: `.clinerules/plankabot.md`, `README.md`, and `handle_guide()` in `src/bot.py`.

## General rules 
- **Non-Invasive Changes**: Avoid breaking changes or massive refactorings when implementing small features or fixes.
- **Refactoring**: Only refactor to the "proper" architecture if explicitly requested or if the current state blocks the task.
- **Testing**: Always write tests
- After each task, provide git-commitable summary