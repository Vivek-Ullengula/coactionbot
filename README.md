# Coaction Bot

Clean codebase with one main flow:

1. Scrape website content.
2. Upload cleaned text to S3.
3. Ingest in Bedrock Knowledge Base from AWS Console.
4. Ask questions in UI/API or AgentCore runtime.

## Current Structure

```text
app/
  api/routes.py
  api/sessions.py
  bedrock_kb_agent.py
  bedrock_kb_indexer.py
  config.py
  html_cleaner.py
  main.py
  models.py
  s3_uploader.py
  session_manager.py
  simple_crawler.py

agentcore_runtime/
  agentcore_entrypoint.py

ui/
  app.py              # Streamlit UI (legacy)
  gradio_app.py       # Gradio UI (current)
  Dockerfile          # Streamlit Dockerfile
  Dockerfile.gradio   # Gradio Dockerfile

.bedrock_agentcore.yaml
docker-compose.yml
Dockerfile
requirements.txt
scrape.py
query.py
README.md
```

## Why Only One Dependency File

This repo now uses only `requirements.txt`.
`pyproject.toml` was removed to avoid duplicate dependency management.

## Required .env

Create `.env` from `.env.example`:

```bash
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=your-crawl-bucket
BEDROCK_KB_ID=your-existing-kb-id
OPENAI_API_KEY=...
OPENAI_CHAT_MODEL=gpt-4o
MAX_CRAWL_DEPTH=2
MAX_PAGES_PER_CRAWL=50
CRAWL_CONCURRENCY=5
LOG_LEVEL=INFO
```

## Local Run

Install:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Run UI (Gradio — recommended):

```bash
python ui/gradio_app.py
```

Or legacy Streamlit UI:

```bash
cd ui
streamlit run app.py
```

## Run UI + API with Docker Compose

Yes, this repo is already dockerized for both services.

Run from project root:

```bash
docker compose up --build
```

Access:
- API: `http://localhost:8000`
- UI (Gradio): `http://localhost:7860`

Stop:

```bash
docker compose down
```

## Scrape + KB Ingestion

Run scraper:

```bash
python scrape.py https://your-site.com
```

After scrape upload completes:

1. Open AWS Bedrock console.
2. Open your Knowledge Base.
3. Run Sync/Ingestion from the KB data source.

## Query Modes

### 1) API/UI local

- UI calls `POST /api/v1/query`.
- Agent retrieves from Bedrock KB using `BEDROCK_KB_ID`.

### 2) AgentCore local

```bash
python agentcore_runtime/agentcore_entrypoint.py
```

### 3) AgentCore deployed runtime

Deploy via AgentCore CLI, then invoke runtime endpoint.

## AgentCore Setup and Deploy (Detailed)

Use this exact order for first-time setup.

### 1) Authenticate AWS CLI

From PowerShell:

```powershell
aws login
```

If prompted, choose region (for your case `us-east-1`).
If `aws login` is not available in your CLI version, use:

```powershell
aws configure
```

Set:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (`us-east-1`)
- Output format (`json`)

Verify identity:

```powershell
aws sts get-caller-identity
```

### 2) Configure AgentCore project

```powershell
agentcore configure
```

This reads `.bedrock_agentcore.yaml` and prepares local AgentCore settings.

### 3) Deploy with required runtime env vars

Use a clean multiline command in PowerShell:

```powershell
$openaiKey = "YOUR_OPENAI_KEY"

agentcore deploy --agent underwriting_agent `
  --env BEDROCK_KB_ID=OVA78JS0CN `
  --env AWS_REGION=us-east-1 `
  --env OPENAI_CHAT_MODEL=gpt-4o `
  --env OPENAI_API_KEY=$openaiKey
```

Notes:
- Keep backtick `` ` `` only for line continuation.
- Do not leave extra text after a line (that can break parsing and cause API key errors).
- If `.env.local` exists, AgentCore may also load `OPENAI_API_KEY` from it during deploy.

### 4) Validate deployment

```powershell
agentcore status
agentcore invoke "{`"prompt`":`"what is class code 10040`"}"
```

Expected:
- Deployment success shows `Agent ARN`, `ECR URI`, and `CodeBuild ID`.
- Invoke response should return `status: "success"` and a grounded answer when KB has matching data.

### 5) Check logs when answers look wrong

```powershell
aws logs tail /aws/bedrock-agentcore/runtimes/<runtime-name>-DEFAULT --log-stream-name-prefix "2026/04/15/[runtime-logs]" --since 1h
```

Replace `<runtime-name>` with your deployed runtime id (example: `underwriting_agent-dXy3Uj6m45`).

### 6) Grant Bedrock KB permissions to AgentCore runtime role (required)

When `execution_role_auto_create: true`, AgentCore creates a runtime role (for example `AmazonBedrockAgentCoreSDKRuntime-...`).
Your local tests can pass with your own AWS credentials, but deployed runtime calls use this role.

If this role does not have Bedrock Knowledge Base retrieve permissions, the deployed agent returns fallback answers even though deploy is successful.

Add an inline policy on the runtime role with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockKnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": [
        "bedrock:Retrieve",
        "bedrock:RetrieveAndGenerate"
      ],
      "Resource": "*"
    }
  ]
}
```

PowerShell example:

```powershell
$roleName = "AmazonBedrockAgentCoreSDKRuntime-us-east-1-<id>"
$policyDoc = @'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockKnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": [
        "bedrock:Retrieve",
        "bedrock:RetrieveAndGenerate"
      ],
      "Resource": "*"
    }
  ]
}
'@

aws iam put-role-policy `
  --role-name $roleName `
  --policy-name BedrockKnowledgeBaseRetrieveInline `
  --policy-document $policyDoc
```

Then re-invoke:

```powershell
agentcore invoke "{`"prompt`":`"tell me about binding authority property manual`"}"
```

## Why fallback answers happen after successful deploy

If you get:
- `Please contact your Coaction underwriter.`
- `I can only answer binding authority related questions.`

then deployment is working, but retrieval returned no useful context. Check:

1. `BEDROCK_KB_ID` is correct in deploy command.
2. KB data source points to the S3 path where scraper uploaded files (`web/...`).
3. Ingestion/sync completed in Bedrock console after scrape upload.
4. Question matches content that exists in ingested documents.
5. Same region is used everywhere (`AWS_REGION`, KB region, AgentCore region).

## AgentCore YAML behavior

Before first deploy, `.bedrock_agentcore.yaml` is partly template/config data.
After deploy, AgentCore populates runtime fields like:
- `bedrock_agentcore.agent_id`
- `bedrock_agentcore.agent_arn`
- active session-related metadata

Auto-create flags currently enabled:
- `execution_role_auto_create: true`
- `ecr_auto_create: true`
- `s3_auto_create: true`

If you already manage IAM/ECR/S3 manually, set them to `false`.

## Notes

- Removed duplicate root `agentcore_entrypoint.py`; only `agentcore_runtime/agentcore_entrypoint.py` remains.
- Removed extra docs/tests/examples and generated zip artifact.
- Removed script-based ingestion helper; ingestion is now expected from AWS Console.
