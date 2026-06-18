# innhance-ai — Python AI Service

FastAPI service providing AI capabilities for the Innhance hotel bot.

## What this service does

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Uptime check (pinged by UptimeRobot every 10min) |
| `/detect-language` | POST | Detect EN / HI / Hinglish from guest message |
| `/classify` | POST | Claude Haiku tool_use → intent + booking slots |
| `/retrieve` | POST | pgvector cosine search → top-K hotel knowledge chunks |
| `/ingest` | POST | PDF / URL → chunk → embed → store in Supabase |
| `/ingest/status` | GET | Poll ingestion progress |
| `/verify-payment` | POST | GPT-4o vision → UPI screenshot verification |

## Local setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/innhance/innhance-ai
cd innhance-ai

# 2. Create venv
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy env and fill in your keys
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY, OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY

# 5. Set up Supabase tables (run ONCE)
# Open Supabase dashboard → SQL editor → paste supabase/migration.sql → Run

# 6. Start the server
uvicorn app.main:app --reload --port 8000
# Docs available at: http://localhost:8000/docs
```

## Running tests

```bash
pytest tests/ -v
```

## Deployment (Railway)

1. Push to GitHub
2. Connect repo to Railway
3. Add all `.env` variables in Railway → Variables tab
4. Railway auto-deploys on push to `main`
5. Set up UptimeRobot to ping `https://your-service.railway.app/health` every 10 minutes

## Project structure

```
innhance-ai/
├── app/
│   ├── main.py              # FastAPI app, middleware, router registration
│   ├── core/
│   │   ├── config.py        # Pydantic settings (loads .env)
│   │   ├── llm.py           # Anthropic + OpenAI clients, dual-provider fallback
│   │   └── database.py      # Supabase client singleton
│   ├── models/
│   │   └── schemas.py       # All request/response Pydantic models (API contract)
│   ├── services/
│   │   ├── language.py      # Language detection (Ridhimaa owns this)
│   │   ├── classifier.py    # Intent classification via Claude tool_use
│   │   ├── rag.py           # Document ingestion + chunk retrieval
│   │   └── payment.py       # Payment screenshot verification
│   └── routers/
│       ├── health.py
│       ├── language.py
│       ├── classify.py
│       ├── rag.py
│       └── payment.py
├── tests/
│   └── test_language.py     # Language detection tests (Ridhimaa owns this)
├── supabase/
│   └── migration.sql        # Run once in Supabase SQL editor
├── .env.example
├── requirements.txt
├── Dockerfile
└── pytest.ini
```

## Team ownership

| File / folder | Owner |
|---|---|
| `app/services/language.py` | Ridhimaa (co-lead reviews PRs) |
| `tests/test_language.py` | Ridhimaa |
| `app/services/classifier.py` | You |
| `app/services/rag.py` | You |
| `app/services/payment.py` | Co-lead |
| `app/core/llm.py` | You |
| `app/models/schemas.py` | You + Co-lead (API contract) |
