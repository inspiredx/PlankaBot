# PlankaBot

VK group chat bot tracking daily plank exercises. Runs as a **Yandex Cloud Function** (Python 3.12) triggered via VK Callback API through an API Gateway.

## Tech Stack
- **Runtime**: Python 3.12, Yandex Cloud Functions
- **VK**: `vk-api` library, Callback API (webhook, not longpoll)
- **Database**: YDB Serverless (row-oriented, YSQL), `ydb` Python SDK
- **LLM**: Yandex AI Studio (OpenAI-compatible API)
- **IaC**: Terraform (Yandex Cloud provider), state in Yandex Object Storage
- **CI/CD**: GitHub Actions (`.github/workflows/deploy-dev.yml`) — tests then `terraform apply`

## Project Structure
```
src/
  handler.py     — Cloud Function entrypoint
  bot.py         — VK message routing and command handlers
  db.py          — YDB driver, session pool, all DB operations
  config.py      — env var config
  prompts/       — LLM system prompts (gossip, advice, toast, story, who_is_today)
tests/
  test_bot.py    — bot routing tests (mocked db)
  test_db.py     — db layer tests (mocked YDB)
terraform/       — YDB, Cloud Function, IAM, API Gateway
.github/workflows/deploy-dev.yml — CI/CD pipeline
```

## Development

### Python Environment
Use the project venv: `./.venv/bin/activate`

### Testing
- Run: `pytest tests/ -v`
- YDB is fully mocked — no real connection needed
- CI: `pip install -r requirements.txt -r requirements-dev.txt && pytest tests/ -v`
- **Always write tests** for new features and changes

### Deployment
- Push to any branch triggers `deploy-dev.yml`
- No manual steps — Terraform provisions everything (YDB, tables, IAM, function)

## Bot Commands (Russian)
All commands work in VK group chats only (`peer_id >= 2000000000`):
- `планка [X|+X]` — record/update/increment today's plank
- `стата` — today's plank stats
- `гайд` — command help
- `ебать гусей [context]` — LLM goose-wisdom story
- `кто сегодня [question]` — LLM picks a winner from today's chat
- `объясни [стиль]` — explain a replied-to message in a given style
- `начать историю [тема]` / `кончить историю` — collaborative story mode
- `сплетня` — LLM gossip based on today's chat
- `совет [тема]` — absurd life advice from random persona
- `тост [повод]` — pompous toast from drunk toastmaster Valery

## Data Architecture (YDB)
- **`users`**: `user_id` (PK), `name`, `is_bot_admin`, `last_activity`, `created_at`
- **`plank_records`**: (`user_id`, `plank_date`) PK, `actual_seconds` (nullable Int32), `created_at`
- **`chat_messages`**: `message_id` (PK), `user_id`, `user_name`, `msg_date`, `text`, `created_at` (TTL: 1 day)
- **`story_turns`**: (`peer_id`, `turn_index`) PK, `role`, `content`, `created_at` (TTL: 1 day)

## Key Design Patterns
- `PlankMarkResult(is_new, was_updated, was_incremented)` — returned by `mark_plank`
- Explicit YDB `SerializableReadWrite` transactions for all writes
- Session pool initialized at module level (survives warm invocations)
- Auth: `ydb.iam.MetadataUrlCredentials()` in cloud; tests use mocks
- `PLANK_TIMEZONE` env var (default `Europe/Moscow`) for day boundaries
- Bot commands are excluded from `chat_messages` storage
- Story mode uses multi-turn `chat.completions.create` (not single-turn `responses.create`)
- Story context trimming keeps first turn (premise) + most recent turns within 80k char budget

## Environment Variables
| Variable | Description | Default |
|---|---|---|
| `VK_GROUP_TOKEN` | VK group API token | required |
| `VK_CONFIRMATION_TOKEN` | VK callback confirmation token | required |
| `VK_SECRET_KEY` | VK Callback API secret key | required |
| `YANDEX_FOLDER_ID` | Yandex Cloud folder ID | required |
| `YANDEX_LLM_API_KEY` | API key for LLM SA | required |
| `YDB_ENDPOINT` | YDB endpoint (grpcs://...) | required |
| `YDB_DATABASE` | YDB database path | required |
| `PLANK_TIMEZONE` | Timezone for day calculation | `Europe/Moscow` |

## Rules

### Change Policy
- **Non-invasive changes**: avoid breaking changes or massive refactorings for small features/fixes
- **Refactoring**: only refactor if explicitly requested or current state blocks the task

### Keeping Docs in Sync
When bot commands change, **all three must be updated together**:
1. This file (`CLAUDE.md`) — command list and data architecture
2. `README.md` — user-facing docs
3. `handle_guide()` in `src/bot.py` — in-bot help text

Also update this file when: data schema changes, new env vars are introduced, or deployment process changes.

### After Each Task
- Provide a git-commitable summary
