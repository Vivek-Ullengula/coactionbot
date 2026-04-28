# Coaction Underwriting Assistant

An AI-powered underwriting assistant that helps Coaction Specialty underwriters search General Liability and Property manuals using natural language. Built on AWS Bedrock Knowledge Base with Aurora PostgreSQL (PGVector) for hybrid search.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  Gradio UI      │────▶│  FastAPI Backend  │────▶│  OpenAI GPT-4o (LLM)   │
│  localhost:7860  │     │  localhost:8000   │     │  + Strands Agent        │
└─────────────────┘     └──────────────────┘     └───────────┬─────────────┘
                                                             │
                                                    search_manuals() tool
                                                             │
                                                             ▼
                                                ┌─────────────────────────┐
                                                │  AWS Bedrock KB         │
                                                │  (Retrieve API)         │
                                                │  ┌───────────────────┐  │
                                                │  │ Aurora PostgreSQL │  │
                                                │  │ + PGVector        │  │
                                                │  │ (HNSW + GIN)     │  │
                                                │  └───────────────────┘  │
                                                └─────────────────────────┘
```

**How it works:**
1. User asks a question in the Gradio UI
2. FastAPI streams the request to the Strands Agent (OpenAI GPT-4o)
3. The agent calls `search_manuals()` — a tool that hits the AWS Bedrock Retrieve API
4. Bedrock performs hybrid search (vector + keyword) against Aurora PGVector
5. The agent synthesizes a cited answer from the retrieved manual chunks
6. Response streams back to the UI with status updates, follow-up suggestions, and source links

## Project Structure

```
coactionbot/
├── app/                          # Backend application
│   ├── __init__.py
│   ├── main.py                   # FastAPI app + lifespan (entrypoint)
│   ├── bedrock_kb_agent.py       # Strands Agent with search_manuals tool
│   ├── config.py                 # Pydantic settings (reads .env)
│   ├── models.py                 # Request/response schemas
│   ├── session_manager.py        # In-memory session + TTL cleanup
│   ├── logger.py                 # Structured logging (structlog)
│   ├── add_index.py              # One-time script: GIN + HNSW indexes
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py             # POST /query (SSE streaming)
│   │   └── sessions.py           # Session CRUD endpoints
│   └── crawlers/
│       └── coaction_crawler.py   # Website scraper (Firecrawl/crawl4ai)
│
├── ui/
│   ├── gradio_app.py             # Gradio 6 chat UI (current)
│   ├── app.py                    # Streamlit UI (legacy, not maintained)
│   ├── Dockerfile.gradio         # Docker image for Gradio UI
│   └── Dockerfile                # Docker image for Streamlit UI (legacy)
│
├── agentcore_runtime/
│   ├── agentcore_entrypoint.py   # AWS Bedrock AgentCore entry point
│   └── requirements.txt          # AgentCore-specific dependencies
│
├── .env                          # Environment variables (DO NOT COMMIT)
├── .gitignore
├── .dockerignore
├── Dockerfile                    # Docker image for FastAPI backend
├── docker-compose.yml            # Run API + UI together
├── requirements.txt              # Python dependencies
├── query.py                      # CLI tool to test queries
├── scrape.py                     # CLI tool to crawl + upload to S3
├── global-bundle.pem             # AWS RDS SSL certificate bundle
└── README.md
```

## Prerequisites

- **Python 3.11+**
- **AWS Account** with:
  - Bedrock Knowledge Base configured with Aurora PostgreSQL
  - S3 bucket with ingested manual documents
  - IAM credentials with `bedrock:Retrieve` permission
- **OpenAI API Key** (GPT-4o or GPT-4o-mini)

## Quick Start (First Run)

### 1. Clone and install dependencies

```bash
git clone <repository-url>
cd coactionbot

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# AWS
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
BEDROCK_KB_ID=your-knowledge-base-id

# Aurora PostgreSQL (only needed if running add_index.py)
DB_HOST=your-aurora-cluster.us-east-1.rds.amazonaws.com
DB_NAME=coaction_kb
DB_USER=coaction_admin
DB_PASSWORD=your-password
DB_PORT=5432

# OpenAI
OPENAI_API_KEY=sk-your-openai-key
OPENAI_CHAT_MODEL=gpt-4o-mini

# Crawler (optional)
MAX_CRAWL_DEPTH=2
MAX_PAGES_PER_CRAWL=500
CRAWL_CONCURRENCY=5

# Logging
LOG_LEVEL=INFO
```

### 3. Start the FastAPI backend

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
{"event": "ready", "agent_type": "bedrock_kb"}
```

### 4. Start the Gradio UI

In a **separate terminal** (with the same virtual environment activated):

```bash
python ui/gradio_app.py
```

Open your browser to **http://localhost:7860** and start chatting.

### 5. (Optional) Test from the command line

```bash
python query.py "What is class code 10040?"
```

## Docker Deployment

### Run with Docker Compose (recommended)

```bash
# Build and start both services
docker compose up --build

# Access:
# - API:  http://localhost:8000
# - UI:   http://localhost:7860
```

The `.env` file is automatically read by Docker Compose.

### Run containers individually

**API:**
```bash
docker build -t coactionbot-api .
docker run -p 8000:8000 --env-file .env coactionbot-api
```

**UI:**
```bash
docker build -t coactionbot-ui -f ui/Dockerfile.gradio ui/
docker run -p 7860:7860 -e API_BASE_URL=http://host.docker.internal:8000/api/v1 coactionbot-ui
```

## AWS Bedrock Knowledge Base Setup

### Data Ingestion Pipeline

1. **Crawl website content:**
   ```bash
   python scrape.py https://bindingauthority.coactionspecialty.com
   ```
   This crawls the site and uploads cleaned text to the S3 bucket.

2. **Sync Knowledge Base:**
   - Open the [AWS Bedrock Console](https://console.aws.amazon.com/bedrock)
   - Navigate to **Knowledge Bases** → select your KB
   - Click **Sync** on the data source

3. **Verify:** Ask a question in the UI to confirm retrieval works.

### Database Indexes (one-time setup)

If setting up Aurora for the first time, run the index creation script:

```bash
python -c "from app.utils.add_index import *"
```

This creates the required GIN (full-text) and HNSW (vector similarity) indexes.

## API Reference

### Health Check
```
GET /health
→ {"status": "ok"}
```

### Query (Streaming SSE)
```
POST /api/v1/query
Content-Type: application/json

{
  "query": "What is class code 10040?",
  "session_id": "optional-uuid",
  "top_k": 5
}

→ Stream of Server-Sent Events:
data: {"type": "status", "message": "🔍 Searching Coaction manuals..."}
data: {"type": "final", "answer": "...", "sources": [...], "follow_up_questions": [...], "session_id": "..."}
```

### Sessions
```
POST /api/v1/session/create  → {"session_id": "uuid"}
GET  /api/v1/session/{id}    → session details
```

## AgentCore Deployment (AWS Managed Runtime)

For deploying as an AWS Bedrock AgentCore runtime:

```powershell
# 1. Authenticate
aws configure

# 2. Configure AgentCore
agentcore configure

# 3. Deploy
agentcore deploy --agent underwriting_agent `
  --env BEDROCK_KB_ID=JATZNTWHAV `
  --env AWS_REGION=us-east-1 `
  --env OPENAI_CHAT_MODEL=gpt-4o `
  --env OPENAI_API_KEY=your-key

# 4. Test
agentcore invoke "{\"prompt\":\"What is class code 10040?\"}"
```

> **Important:** After deployment, add an inline IAM policy to the AgentCore runtime role granting `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` permissions. Without this, the deployed agent will return fallback answers.

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | Yes | — | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | — | IAM secret key |
| `BEDROCK_KB_ID` | Yes | — | Bedrock Knowledge Base ID |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_CHAT_MODEL` | No | `gpt-4o` | OpenAI model to use |
| `DB_HOST` | No | — | Aurora cluster endpoint |
| `DB_NAME` | No | `postgres` | Database name |
| `DB_USER` | No | `postgres` | Database user |
| `DB_PASSWORD` | No | — | Database password |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Session not found" | Backend restarted | Sessions auto-create now; just retry |
| Fallback answers after deploy | Missing IAM permissions | Add `bedrock:Retrieve` to runtime role |
| No sources in response | KB not synced | Run Sync in Bedrock Console |
| Import errors on startup | Stale `.pyc` cache | Delete `__pycache__/` dirs and restart |
| "API Offline" in UI | Backend not running | Start FastAPI first, then Gradio |

## Notes

- `scrape.py` imports a legacy `bedrock_kb_indexer` module — update the import if you need to re-crawl
- `ui/app.py` (Streamlit) is kept for reference but is **not maintained**
- The `global-bundle.pem` file is the AWS RDS SSL certificate bundle for secure Aurora connections
- `app/add_index.py` is a one-time database setup script and can be archived after initial configuration
