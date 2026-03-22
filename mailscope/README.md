# MailScope – E-Mail-Sicherheitsanalyse

A Docker-based web application that lets employees upload `.eml` or `.msg` email files for automated security analysis. Extracts headers, links, checks URLs against VirusTotal and urlscan.io, and produces an LLM-powered security assessment.

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start with Docker Compose

```bash
docker compose up --build
```

- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000
- **API docs**: http://localhost:8000/docs

### 3. Upload an email

Open http://localhost:3000 and drag-and-drop a `.eml` or `.msg` file.

## API Endpoints

```bash
# Health check
curl http://localhost:8000/api/health

# Upload email
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test-email.eml"

# Check job status
curl http://localhost:8000/api/jobs/{job_id}

# Get full result
curl http://localhost:8000/api/jobs/{job_id}/result
```

## Architecture

```
mailscope/
├── backend/          # FastAPI + Python 3.12
│   ├── app/
│   │   ├── main.py           # API endpoints
│   │   ├── config.py         # Settings from env
│   │   ├── database.py       # SQLAlchemy + SQLite
│   │   ├── models.py         # DB models
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── prompts/
│   │   │   └── assessment.txt  # LLM prompt template
│   │   └── services/
│   │       ├── parser.py         # .eml/.msg parsing
│   │       ├── link_extractor.py # URL extraction
│   │       ├── url_normalizer.py # SafeLinks, dedup
│   │       ├── header_analyzer.py # Header heuristics
│   │       ├── link_analyzer.py   # Link heuristics
│   │       ├── virustotal.py     # VT client
│   │       ├── urlscan.py        # urlscan client
│   │       ├── llm_client.py     # LLM client
│   │       └── orchestrator.py   # Background pipeline
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/         # Next.js + TypeScript + Tailwind
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx          # Upload page
│   │   │   └── jobs/[id]/page.tsx # Status + Results
│   │   ├── components/
│   │   │   ├── VerdictCard.tsx
│   │   │   ├── HeaderFindings.tsx
│   │   │   ├── LinkTable.tsx
│   │   │   ├── SenderInfo.tsx
│   │   │   └── Accordion.tsx
│   │   └── lib/api.ts
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | (required) |
| `LLM_MODEL` | Model name | `gpt-4o` |
| `VIRUSTOTAL_API_KEY` | VirusTotal API key | (optional) |
| `URLSCAN_API_KEY` | urlscan.io API key | (optional) |
| `URLSCAN_VISIBILITY` | urlscan scan visibility | `private` |
| `MAX_POLL_SECONDS` | Max wait for external scans | `120` |
| `POLL_INTERVAL_SECONDS` | Polling interval | `5` |
| `MAX_UPLOAD_SIZE_MB` | Max upload file size | `25` |

## Security & Privacy

- **Only extracted URLs** are submitted to VirusTotal and urlscan.io
- The email itself is never uploaded to external services
- urlscan visibility defaults to `private`
- Email masking toggle in the UI
- Secrets via environment variables only
- No raw email bodies logged at INFO level

## Known Limitations

- SQLite is used for MVP; not suitable for production concurrency
- Background tasks use FastAPI BackgroundTasks (in-process); a task queue (Celery/arq) would be more robust
- VT/urlscan rate limits may apply depending on API tier
- `.msg` parsing via python-oxmsg may not cover all proprietary fields
- No user authentication

## Suggested Improvements

1. Add Celery/Redis for robust task queue
2. Add PostgreSQL for production database
3. Add user authentication and role-based access
4. Add rate limiting on upload endpoint
5. Support batch upload of multiple emails
6. Add email export / report PDF generation
7. Webhook notifications when analysis completes
8. Store uploaded emails encrypted at rest
