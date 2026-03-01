# PlankaBot

A VK group chat bot that tracks daily plank exercise completions.  
Deployed as a **Yandex Cloud Function** with an **API Gateway** serving as the VK Callback API endpoint.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [YC CLI Setup](#yc-cli-setup)
3. [Bootstrap: One-time Yandex Cloud Setup](#bootstrap-one-time-yandex-cloud-setup)
4. [Local Deployment](#local-deployment)
5. [GitHub Actions Deployment](#github-actions-deployment)
6. [Post-deploy Checklist: LLM API Key Setup](#post-deploy-checklist-llm-api-key-setup)
7. [Environment Variables Reference](#environment-variables-reference)
8. [Running Tests](#running-tests)
9. [Configuring VK Callback URL](#configuring-vk-callback-url)

---

## Prerequisites

- [Yandex Cloud CLI (`yc`)](https://cloud.yandex.ru/docs/cli/quickstart)
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.6
- Python 3.12 + pip
- `~/.aws/credentials` configured with Object Storage static keys (see below)

### Install `yc` CLI

```bash
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
# Restart shell or source profile, then verify:
yc version
```

---

## YC CLI Setup

> You do **not** need to log in with a personal account. Configure `yc` directly
> with the deployer service account key — this is the recommended approach for
> both local development and CI.
>
> ✅ The deployer SA authorized key JSON (`~/.yc/deployer-key-dev.json`) has already
> been created. Start from Step 1 below.

### Step 1 — Create named `yc` profiles

```bash
# Dev profile
yc config profile create dev
yc config set service-account-key ~/.yc/deployer-key-dev.json
yc config set folder-id <dev-folder-id>
yc config set cloud-id <cloud-id>

# Prod profile
yc config profile create prod
yc config set service-account-key ~/.yc/deployer-key-prod.json
yc config set folder-id <prod-folder-id>
yc config set cloud-id <cloud-id>
```

### Step 2 — Activate a profile

```bash
yc config profile activate dev
# Verify
yc config list
```

### Step 3 — Configure `~/.aws/credentials` for Terraform S3 backend

Terraform uses the Object Storage S3 API for remote state. It requires
**static access keys** (HMAC), not the IAM authorized key used by `yc`.

> ✅ The static keys have already been created and will be shared with you directly.
> Add them to `~/.aws/credentials` under named profiles:

```ini
# ~/.aws/credentials

[plankabot-dev]
aws_access_key_id     = <dev-access-key-id>
aws_secret_access_key = <dev-secret-key>

[plankabot-prod]
aws_access_key_id     = <prod-access-key-id>
aws_secret_access_key = <prod-secret-key>
```

---

## Bootstrap: One-time Yandex Cloud Setup

> ✅ **Already done.** The Object Storage state buckets and deployer SA static keys
> have been created. Skip to [Local Deployment](#local-deployment).

For reference, the buckets created are:
- `plankabot-tfstate-dev` (dev folder)
- `plankabot-tfstate-prod` (prod folder)

Credentials are stored in `~/.aws/credentials` under `[plankabot-dev]` and `[plankabot-prod]` profiles.

---

## Local Deployment

All Terraform commands are run from the `terraform/` directory.

### 1. Create your `.tfvars` from the example

`.tfvars` files are **git-ignored** (they contain secrets). Example files are
provided as templates:

```bash
cp terraform/environments/dev.tfvars.example terraform/environments/dev.tfvars
cp terraform/environments/prod.tfvars.example terraform/environments/prod.tfvars
```

Edit the copied file and replace all `REPLACE_WITH_*` placeholders with real values.

> Alternatively, skip the `.tfvars` file entirely and pass secrets as
> `TF_VAR_*` environment variables
> (see [Environment Variables Reference](#environment-variables-reference)).

### 2. Initialize Terraform (dev example)

```bash
cd terraform

AWS_PROFILE=plankabot-dev terraform init \
  -backend-config="bucket=plankabot-tfstate-dev" \
  -backend-config="key=terraform.tfstate" \
  -backend-config="region=ru-central1" \
  -backend-config="skip_region_validation=true" \
  -backend-config="skip_credentials_validation=true" \
  -backend-config="skip_metadata_api_check=true" \
  -backend-config="skip_requesting_account_id=true" \
  -backend-config="force_path_style=true"
```

For prod, replace `plankabot-dev` → `plankabot-prod` and `dev` → `prod`.

### 3. Plan & Apply

```bash
AWS_PROFILE=plankabot-dev terraform apply \
  -var-file="environments/dev.tfvars"
```

Terraform will print the API Gateway URL on success:

```
Outputs:
api_gateway_url = "https://<id>.apigw.yandexcloud.net/"
```

### Switching environments

```bash
# Re-init to switch state backend to prod
AWS_PROFILE=plankabot-prod terraform init \
  -backend-config="bucket=plankabot-tfstate-prod" \
  -backend-config="key=terraform.tfstate" \
  -backend-config="region=ru-central1" \
  -backend-config="skip_region_validation=true" \
  -backend-config="skip_credentials_validation=true" \
  -backend-config="skip_metadata_api_check=true" \
  -backend-config="skip_requesting_account_id=true" \
  -backend-config="force_path_style=true" \
  -reconfigure

AWS_PROFILE=plankabot-prod terraform apply \
  -var-file="environments/prod.tfvars"
```

---

## GitHub Actions Deployment

A single workflow (`deploy-dev.yml`) handles deployment. It triggers on:
- Any push to any branch
- Manual `workflow_dispatch`

### Required GitHub Secrets

Add these in **Settings → Secrets and variables → Actions**:

| Secret name                 | Description                                                                    |
|-----------------------------|--------------------------------------------------------------------------------|
| `YC_CLOUD_ID`               | Yandex Cloud cloud ID                                                          |
| `YC_FOLDER_ID_DEV`          | Dev folder ID                                                                  |
| `YC_SA_KEY_JSON_DEV`        | Full JSON content of deployer SA authorized key (dev)                          |
| `YC_S3_ACCESS_KEY_DEV`      | Static access key ID for S3 backend (dev)                                      |
| `YC_S3_SECRET_KEY_DEV`      | Static secret key for S3 backend (dev)                                         |
| `VK_GROUP_TOKEN_DEV`        | VK group API token                                                             |
| `VK_CONFIRMATION_TOKEN_DEV` | VK callback confirmation token                                                 |
| `VK_SECRET_KEY_DEV`         | VK Callback API secret key (set in VK group settings → Callback API → Secret key) |
| `YANDEX_LLM_API_KEY_DEV`    | API key for `plankabot-llm-dev` SA (created manually — see post-deploy steps)  |

> **Prod note:** when a prod workflow is added, mirror the above with `_PROD` suffixes and `YANDEX_LLM_API_KEY_PROD`.

---

## Post-deploy Checklist: LLM API Key Setup

> ⚠️ **Do this after every first `terraform apply` in a new environment** (or whenever the SA is recreated).
> The `plankabot-llm-<env>` service account is created by Terraform, but its API key must be created manually.

### Dev

1. In the [YC Console](https://console.yandex.cloud/), navigate to the dev folder.
2. Go to **Identity and Access Management → Service accounts**.
3. Find `plankabot-llm-dev` and click on it.
4. Click **Create new key → Create API key**.
5. Description: `plankabot-dev LLM key`.
6. Scope: select **`yc.ai.languageModels.execute`**.
7. Click **Create**. Copy the **secret key** (shown only once).
8. In the GitHub repo, go to **Settings → Secrets and variables → Actions**.
9. Create or update secret `YANDEX_LLM_API_KEY_DEV` with the copied value.
10. Re-run the GitHub Actions deployment so the function picks up the new key.

### Prod *(when prod workflow is set up)*

Repeat the same steps for `plankabot-llm-prod` and secret `YANDEX_LLM_API_KEY_PROD`.

---

## Environment Variables Reference

These environment variables are set on the deployed Yandex Cloud Function:

| Variable               | Description                                      | Required |
|------------------------|--------------------------------------------------|----------|
| `VK_GROUP_TOKEN`       | VK group API token (for sending messages)        | Yes      |
| `VK_CONFIRMATION_TOKEN`| VK confirmation string for callback verification | Yes      |
| `VK_SECRET_KEY`        | VK Callback API secret key; requests with a non-matching `secret` field are rejected with 403. Set in VK group settings → Callback API → Secret key (up to 50 alphanumeric chars). | Yes |
| `YANDEX_FOLDER_ID`     | Yandex Cloud folder ID (injected from `folder_id` tfvar) | Yes |
| `YANDEX_LLM_API_KEY`   | API key for the LLM service account             | Yes      |
| `YDB_ENDPOINT`         | YDB API endpoint (`grpcs://...`) — auto-wired from Terraform | Yes |
| `YDB_DATABASE`         | YDB database path (`/ru-central1/...`) — auto-wired from Terraform | Yes |
| `PLANK_TIMEZONE`       | IANA timezone for day boundary calculation (default: `Europe/Moscow`) | No |

For local Terraform runs, secrets can also be passed as `TF_VAR_*` variables
to avoid writing them to `.tfvars` files:

```bash
export TF_VAR_vk_group_token="your_token"
export TF_VAR_vk_confirmation_token="your_confirmation"
export TF_VAR_vk_secret_key="your_secret_key"
```

---

## Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v
```

---

## Configuring VK Callback URL

1. After deployment, get the API Gateway URL:
   ```bash
   cd terraform
   AWS_PROFILE=plankabot-dev terraform output api_gateway_url
   ```
2. In the VK group settings → **API** → **Callback API**:
   - Set the **server URL** to the output URL (e.g. `https://<id>.apigw.yandexcloud.net/`)
   - Click **Confirm** — VK will send a `confirmation` event; the function will respond with `VK_CONFIRMATION_TOKEN`
3. Enable the `message_new` event type in the same section.
4. Set a **Secret key** in the same section (up to 50 alphanumeric characters). Copy the value and set it as `VK_SECRET_KEY_DEV` in GitHub Secrets (or `TF_VAR_vk_secret_key` for local deploys). The function will reject any request where the `secret` field doesn't match.

---

## Bot Commands

| Command | Description |
|---|---|
| `планка` | Record today's plank (no duration) |
| `планка X` | Record plank with X seconds; updates if already recorded today |
| `стата` | Show today's plank stats: who did it, who hasn't |
| `гайд` | Show command help |
| `ебать гусей [context]` | Generate a goose-wisdom story via LLM |
| `кто сегодня [question]` | Analyze today's chat and pick a winner. E.g. `кто сегодня больше всех похож на Цоя?` |

All commands work in VK group chats only.

---

## Project Structure

```
PlankaBot/
├── src/
│   ├── handler.py          # Yandex Cloud Function entry point
│   ├── bot.py              # VK bot logic (message routing, responses)
│   ├── db.py               # YDB driver, session pool, all DB operations
│   ├── config.py           # Configuration from environment variables
│   └── prompts/
│       ├── geese_story_prompt.txt      # System prompt for the LLM geese story
│       └── who_is_today_prompt.txt     # System prompt for кто сегодня
├── tests/
│   ├── test_handler.py     # Handler unit tests
│   ├── test_bot.py         # Bot logic unit tests
│   └── test_db.py          # YDB layer unit tests (mocked)
├── terraform/
│   ├── main.tf             # Provider + S3 backend config
│   ├── variables.tf        # Input variables
│   ├── function.tf         # Yandex Cloud Function resource
│   ├── iam.tf              # Service accounts + IAM role bindings
│   ├── ydb.tf              # YDB serverless DB + users/plank_records/chat_messages tables
│   ├── api_gateway.tf      # Yandex API Gateway resource
│   ├── outputs.tf          # Output values
│   └── environments/
│       ├── dev.tfvars.example   # Dev variables template (copy → dev.tfvars, git-ignored)
│       └── prod.tfvars.example  # Prod variables template (copy → prod.tfvars, git-ignored)
├── .github/
│   └── workflows/
│       └── deploy-dev.yml  # CI/CD — triggers on push to any branch
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test/dev dependencies
└── README.md