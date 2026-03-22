# MailScope – E-Mail-Sicherheitsanalyse

A Docker-based web application that lets employees upload `.eml` or `.msg` email files for automated security analysis. Extracts headers, links, checks URLs against VirusTotal and urlscan.io, computes deterministic pre-scores, and produces an LLM-powered security assessment.

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
# Health check (no token required)
curl http://localhost:8000/api/health

# Upload email
curl -X POST http://localhost:8000/api/upload \
  -H "X-App-Token: my-secret-test-token" \
  -F "file=@test-email.eml"

# Check job status
curl http://localhost:8000/api/jobs/{job_id} \
  -H "X-App-Token: my-secret-test-token"

# Get full result
curl http://localhost:8000/api/jobs/{job_id}/result \
  -H "X-App-Token: my-secret-test-token"

# Export structured JSON
curl http://localhost:8000/api/jobs/{job_id}/export \
  -H "X-App-Token: my-secret-test-token"
```

> **Note:** The `X-App-Token` header is only required if `APP_ACCESS_TOKEN` is set in the environment. If unset, the API is open.

## Architecture

```
mailscope/
├── backend/          # FastAPI + Python 3.12
│   ├── app/
│   │   ├── main.py              # API endpoints (upload, status, result, export)
│   │   ├── config.py            # Settings + service toggles from env
│   │   ├── database.py          # SQLAlchemy + SQLite
│   │   ├── models.py            # DB models (job, links, checks, assessment)
│   │   ├── schemas.py           # Pydantic schemas (incl. pre-scores, export)
│   │   ├── prompts/
│   │   │   └── assessment.txt   # German LLM prompt with guardrails
│   │   └── services/
│   │       ├── parser.py           # .eml/.msg parsing
│   │       ├── link_extractor.py   # URL extraction from text + HTML
│   │       ├── url_normalizer.py   # SafeLinks, Google redirect, dedup
│   │       ├── header_analyzer.py  # Header heuristics (SPF/DKIM/DMARC etc.)
│   │       ├── link_analyzer.py    # Link heuristics (TLD, punycode, etc.)
│   │       ├── pre_scorer.py       # Deterministic pre-scoring + fallback
│   │       ├── virustotal.py       # VT client
│   │       ├── urlscan.py          # urlscan client
│   │       ├── llm_client.py       # LLM client with retry + validation
│   │       └── orchestrator.py     # Background pipeline with partial failure
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/         # Next.js + TypeScript + Tailwind
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx              # Upload page with privacy notice
│   │   │   └── jobs/[id]/page.tsx    # Status + Results + Export
│   │   ├── components/
│   │   │   ├── VerdictCard.tsx       # Classification + risk + action
│   │   │   ├── PreScoreBar.tsx       # Deterministic pre-scores
│   │   │   ├── ServiceBadges.tsx     # VT/urlscan/LLM status
│   │   │   ├── HeaderFindings.tsx    # Header analysis findings
│   │   │   ├── LinkTable.tsx         # Per-link flags + check results
│   │   │   ├── SenderInfo.tsx        # Sender metadata
│   │   │   └── Accordion.tsx         # Expandable sections
│   │   └── lib/api.ts               # Typed API client
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | (required for LLM) |
| `LLM_MODEL` | Model name | `gpt-4o` |
| `VIRUSTOTAL_API_KEY` | VirusTotal API key | (optional) |
| `URLSCAN_API_KEY` | urlscan.io API key | (optional) |
| `URLSCAN_VISIBILITY` | urlscan scan visibility | `private` |
| `ENABLE_VIRUSTOTAL` | Enable VirusTotal checks | `true` |
| `ENABLE_URLSCAN` | Enable urlscan.io checks | `true` |
| `ENABLE_LLM` | Enable LLM assessment | `true` |
| `APP_ACCESS_TOKEN` | Optional access token for test deployments | (unset = open) |
| `MAX_POLL_SECONDS` | Max wait for external scans | `120` |
| `POLL_INTERVAL_SECONDS` | Polling interval | `5` |
| `MAX_UPLOAD_SIZE_MB` | Max upload file size | `25` |

## Security & Privacy

- **Only extracted URLs** are submitted to VirusTotal and urlscan.io
- The email itself and attachments are **never** uploaded to external services
- Email body sent to the LLM is sanitized (HTML/script stripped), limited to 1500 chars, and wrapped in an `<UNTRUSTED_EMAIL_CONTENT>` delimiter with explicit prompt instructions to treat it as evidence only
- urlscan visibility defaults to `private`
- External services can be disabled entirely via env flags
- Email masking toggle in the UI
- Secrets via environment variables only
- No raw email bodies logged at INFO level
- Sensitive internal emails should not be analyzed without prior approval
- Job IDs are random UUIDs; there is no endpoint to list all jobs

### Access protection for test deployments

Set `APP_ACCESS_TOKEN` in `.env` to require an `X-App-Token` header on all API calls (except `/api/health`). The frontend provides a token input field (stored in localStorage).

```bash
# .env
APP_ACCESS_TOKEN=my-secret-test-token
```

> **This is NOT production-grade authentication.** It is a simple shared-secret gate for internal test deployments. For production use, add proper user authentication (OAuth, SSO, etc.).

## Testing Modes

### Offline mode (no external services)

```bash
# Set in .env:
ENABLE_VIRUSTOTAL=false
ENABLE_URLSCAN=false
ENABLE_LLM=false
```

The system will still parse the email, extract links, run header/link heuristics, and compute deterministic pre-scores. The assessment will be based on deterministic analysis only.

### Single-service mode

```bash
# VT only (no urlscan, no LLM):
ENABLE_VIRUSTOTAL=true
ENABLE_URLSCAN=false
ENABLE_LLM=false

# LLM only (no external URL checks):
ENABLE_VIRUSTOTAL=false
ENABLE_URLSCAN=false
ENABLE_LLM=true
```

### Testing without API keys

Leave `VIRUSTOTAL_API_KEY` and `URLSCAN_API_KEY` empty. Even with `ENABLE_VIRUSTOTAL=true`, missing keys will cause those checks to be skipped with warnings.

### Privacy implications

| Service | What is sent | Visibility |
|---|---|---|
| VirusTotal | Extracted URLs only | Public API |
| urlscan.io | Extracted URLs only | Configurable (default: private) |
| OpenAI | Structured findings, header analysis, sanitized text excerpt (max 1500 chars) | Per API terms |

No email body HTML, no attachments, no raw headers are sent to external services.

## Job Lifecycle

Jobs progress through these states:
1. `queued` → `parsing` → `extracting_links` → `checking_reputation` → `llm_assessment` → `completed`
2. If scan or LLM issues occur: → `completed_with_warnings`
3. On fatal error: → `failed`

Partial failures (VT timeout, urlscan error) do **not** fail the entire analysis. The pipeline continues with available evidence and records warnings.

## Deterministic Pre-Scoring

Before the LLM assessment, a weighted pre-score is computed:
- **Phishing score** (0-100): SPF/DKIM/DMARC failures, domain mismatches, suspicious links, VT/urlscan flags
- **Advertising score** (0-100): Bulk headers, marketing indicators, tracking links
- **Legitimacy score** (0-100): Authentication passes

The LLM prompt includes these scores and is instructed to consider (not ignore) them.

If the LLM fails or is disabled, a deterministic fallback assessment is generated from these scores.

## Known Limitations

- SQLite is used for MVP; not suitable for production concurrency
- Background tasks use FastAPI BackgroundTasks (in-process); a task queue would be more robust
- VT/urlscan rate limits may apply depending on API tier
- `.msg` parsing via python-oxmsg may not cover all proprietary fields (e.g. some custom Exchange headers, embedded OLE objects, or non-standard attachment encoding)
- No production-grade user authentication (APP_ACCESS_TOKEN is a simple test gate only)
- LLM retry is limited to one repair attempt before fallback

## Suggested Improvements

1. Add Celery/Redis for robust task queue
2. Add PostgreSQL for production database
3. Add user authentication and role-based access
4. Add rate limiting on upload endpoint
5. Support batch upload of multiple emails
6. Add email export / report PDF generation
7. Webhook notifications when analysis completes
8. Store uploaded emails encrypted at rest
9. Add YARA rule scanning for attachments
10. Add configurable LLM provider (Anthropic, Azure OpenAI)
