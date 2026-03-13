# Contract Review Application — Architecture

## 1. Repository / Folder Structure

```
contract2/
├── ARCHITECTURE.md              # This file
├── docker-compose.yml           # Full-stack orchestration
├── .env.example                 # Environment template
├── .gitignore
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml           # Python deps (FastAPI, SQLAlchemy, etc.)
│   ├── alembic/                 # DB migrations
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings / env parsing
│   │   ├── database.py          # DB engine, session
│   │   ├── models/              # SQLAlchemy ORM models
│   │   │   ├── __init__.py
│   │   │   ├── vertrag.py       # Contract model
│   │   │   ├── analyse.py       # Analysis run model
│   │   │   ├── fundstelle.py    # Finding / discovery model
│   │   │   ├── einstellung.py   # Settings model (LLM config)
│   │   │   └── protokoll.py     # Log / protocol model
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── vertrag.py
│   │   │   ├── analyse.py
│   │   │   ├── fundstelle.py
│   │   │   └── einstellung.py
│   │   ├── api/                 # Route handlers
│   │   │   ├── __init__.py
│   │   │   ├── router.py        # Top-level router aggregation
│   │   │   ├── vertraege.py     # Contract CRUD endpoints
│   │   │   ├── analysen.py      # Analysis trigger/status endpoints
│   │   │   ├── fundstellen.py   # Finding endpoints
│   │   │   ├── einstellungen.py # Admin settings endpoints
│   │   │   └── protokoll.py     # Log/protocol endpoints
│   │   ├── services/            # Business logic layer
│   │   │   ├── __init__.py
│   │   │   ├── upload.py        # Upload + text extraction
│   │   │   ├── extraktion.py    # Text extraction / normalization
│   │   │   └── review.py        # Human review workflow logic
│   │   ├── discovery/           # *** Core: multi-pass analysis engine ***
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py  # Runs the full discovery pipeline
│   │   │   ├── chunking.py      # Overlapping segment builder
│   │   │   ├── passes/          # Individual discovery passes
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py      # Abstract pass interface
│   │   │   │   ├── breit.py     # Pass 1: broad issue scan
│   │   │   │   ├── perspektive.py # Pass 2: domain-specific perspectives
│   │   │   │   ├── implizit.py  # Pass 3: hidden obligations scan
│   │   │   │   └── querverweis.py # Pass 4: cross-reference scan
│   │   │   ├── consolidation.py # Dedup + merge + confidence scoring
│   │   │   └── llm_client.py    # LLM abstraction (OpenAI-compatible)
│   │   └── worker.py            # Background task runner (async)
│   └── tests/
│       ├── conftest.py
│       ├── test_api/
│       ├── test_discovery/
│       └── test_services/
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── router.ts
│       ├── api/                 # API client layer
│       │   └── client.ts
│       ├── stores/              # Pinia stores
│       │   ├── vertraege.ts
│       │   ├── analysen.ts
│       │   ├── fundstellen.ts
│       │   └── einstellungen.ts
│       ├── views/               # Page-level components (German naming)
│       │   ├── VertragUebersicht.vue    # Contract list
│       │   ├── VertragDetail.vue        # Single contract detail
│       │   ├── AnalyseStatus.vue        # Analysis run status + log
│       │   ├── FundstellenListe.vue     # Findings list
│       │   ├── FundstelleDetail.vue     # Single finding detail
│       │   ├── PruefungAnsicht.vue      # Human review view
│       │   └── Einstellungen.vue        # Admin settings
│       ├── components/          # Reusable UI components
│       │   ├── Navigation.vue
│       │   ├── StatusBadge.vue
│       │   ├── ProtokollAnzeige.vue     # Log viewer component
│       │   └── DokumentVorschau.vue     # Document preview
│       └── types/
│           └── index.ts
│
└── docs/
    └── terminologie.md          # German terminology reference
```

---

## 2. Backend Architecture

### Tech Stack

| Layer          | Technology                        |
|----------------|-----------------------------------|
| Web framework  | FastAPI (Python 3.12+)            |
| ORM            | SQLAlchemy 2.x (async)            |
| Database       | PostgreSQL 16                     |
| Migrations     | Alembic                           |
| Task queue     | Built-in asyncio tasks (MVP), upgrade to Celery/ARQ later |
| LLM client     | OpenAI-compatible SDK (litellm)   |
| Text extraction| pdfplumber, python-docx, pandoc   |
| File storage   | Local filesystem (Docker volume)  |

### Key Design Decisions

- **No auth in MVP**: Single-user / trusted-network assumption initially. Add auth later.
- **Async background tasks**: Analysis runs as async background tasks with real-time status updates via polling (SSE later).
- **LLM abstraction via litellm**: Supports OpenAI, Azure OpenAI, Anthropic, local models — configurable by admin at runtime.
- **All business logic in `services/` and `discovery/`**: API routes are thin — validate, delegate, return.

---

## 3. Discovery Architecture — High Recall Design

### The Problem with Naive Approaches

A single-pass pipeline ("chunk → prompt → findings") systematically misses:
- Obligations hidden in definitions or preamble
- Implicit responsibilities from vague language
- Cross-reference traps ("as defined in section X" where X contains the trap)
- Clauses that are individually benign but collectively overreaching
- Risks buried under harmless headings

### Multi-Pass Discovery Pipeline

The pipeline runs **sequentially per contract**, with each pass operating on the **full text** (or overlapping segments), not on pre-classified sections.

```
┌─────────────────────────────────────────────────────────┐
│                    EINGABE (Input)                       │
│  Volltext des Vertrags, normalisiert, mit Absatz-IDs    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          PASS 1: Breite Ersterfassung                   │
│  "Breit-Pass"                                           │
│                                                         │
│  Goal: Cast the widest possible net.                    │
│  Prompt: "Identify EVERY clause, sentence, or phrase    │
│  that could create an obligation, risk, liability,      │
│  restriction, or commitment for the Auftragnehmer.      │
│  When in doubt, INCLUDE it."                            │
│                                                         │
│  Input: Overlapping segments (e.g., 2000 tokens,        │
│         500 token overlap)                               │
│  Output: List of candidate text spans + rough category  │
│  Temperature: 0.3 (slightly creative for recall)        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          PASS 2: Perspektivische Vertiefung             │
│  "Perspektive-Passes" (multiple sub-passes)             │
│                                                         │
│  Goal: Apply domain-expert lenses that Pass 1 may miss. │
│  Each sub-pass re-reads relevant segments with a        │
│  specialized perspective:                               │
│                                                         │
│  2a. Informationssicherheit & Datenschutz               │
│      (InfoSec, data handling, breach notification,      │
│       encryption requirements, access controls)         │
│                                                         │
│  2b. Compliance & Regulatorik                           │
│      (Regulatory pass-through, audit rights,            │
│       certification requirements, reporting)            │
│                                                         │
│  2c. Betrieb & Verfügbarkeit                            │
│      (SLAs, uptime commitments, BCM, disaster recovery, │
│       response times, penalty triggers)                 │
│                                                         │
│  2d. Haftung & Gewährleistung                           │
│      (Liability caps, indemnification, warranty scope,  │
│       limitation of liability carve-outs)               │
│                                                         │
│  2e. Vertragsmanagement                                 │
│      (Termination traps, auto-renewal, change control,  │
│       subcontracting restrictions, IP transfer)         │
│                                                         │
│  Input: Full text (or large overlapping segments)       │
│  Output: Additional candidates not yet found            │
│  Temperature: 0.2                                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          PASS 3: Implizite Pflichten                    │
│  "Implizit-Pass"                                        │
│                                                         │
│  Goal: Find what is NOT explicitly stated but implied.  │
│  Prompt: "Read this contract and identify obligations   │
│  that are NOT explicitly listed but are IMPLICITLY      │
│  created through:                                       │
│  - Vague scope definitions that could expand            │
│  - 'Reasonable efforts' / 'best efforts' language       │
│  - Definitions that smuggle in commitments              │
│  - Catch-all clauses ('including but not limited to')   │
│  - References to external standards/frameworks          │
│  - Obligations that arise from combinations of clauses" │
│                                                         │
│  Input: Full text                                       │
│  Output: Implicit obligation candidates                 │
│  Temperature: 0.4 (more creative)                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          PASS 4: Querverweise & Wechselwirkungen        │
│  "Querverweis-Pass"                                     │
│                                                         │
│  Goal: Find cross-reference traps and clause combos.    │
│  Prompt: "Examine cross-references, definitions, and    │
│  annexes. Identify cases where:                         │
│  - A reference to another section creates hidden scope  │
│  - Annex terms override main body protections           │
│  - Definitions expand plain-language meaning            │
│  - Multiple clauses combine to create obligations       │
│    beyond what any single clause states"                │
│                                                         │
│  Input: Full text (must see complete document)          │
│  Output: Cross-reference and interaction findings       │
│  Temperature: 0.2                                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│          KONSOLIDIERUNG (Consolidation)                  │
│                                                         │
│  Goal: Merge, deduplicate, and score all candidates.    │
│                                                         │
│  Steps:                                                 │
│  1. Collect all candidates from passes 1-4              │
│  2. Cluster by text span overlap (fuzzy matching)       │
│  3. Merge duplicates, keep richest description          │
│  4. LLM-assisted consolidation pass:                    │
│     "Given these candidate findings, consolidate into   │
│      a final list. Remove true duplicates. Assign:      │
│      - Risikostufe (Hoch/Mittel/Niedrig/Hinweis)       │
│      - Kategorie (from domain taxonomy)                 │
│      - Betroffener Vertragsabschnitt                    │
│      - Kurzbeschreibung                                 │
│      - Empfehlung für Auftragnehmer"                    │
│  5. Store as Fundstellen in DB                          │
│                                                         │
│  Output: Final deduplicated findings                    │
└─────────────────────────────────────────────────────────┘
```

### Chunking Strategy

**Do NOT chunk by sections/headings.** This was the old mistake.

Instead:
- **Overlapping sliding window**: Fixed token-size segments with ~25% overlap.
- **Paragraph-aware boundaries**: Split at paragraph boundaries within the token window, never mid-sentence.
- **Each segment gets a stable ID**: `seg-{start_para}-{end_para}` — so findings can reference exact locations.
- **Full-text passes**: Passes 3 and 4 attempt to use the full document. If the document exceeds context limits, use large overlapping segments (e.g., 80% of context window with 30% overlap).

### Why This Works Better

| Old approach | New approach |
|---|---|
| Chunk by heading → miss misplaced clauses | Overlapping windows → every sentence seen multiple times |
| Single prompt → single perspective | 4+ passes with different lenses |
| Precision-oriented → low recall | Recall-oriented → cast wide net, consolidate later |
| Heading-dependent → blind to structure tricks | Full-text + cross-reference pass → catches interactions |
| One-shot → miss implicit obligations | Dedicated implicit-obligation pass |

---

## 4. Data Model Overview

### Vertrag (Contract)

| Field             | Type         | Description                          |
|-------------------|--------------|--------------------------------------|
| id                | UUID         | Primary key                          |
| dateiname         | String       | Original filename                    |
| dateipfad         | String       | Storage path                         |
| volltext          | Text         | Extracted + normalized full text     |
| absaetze          | JSONB        | Array of `{id, text, position}`      |
| status            | Enum         | Hochgeladen / Extrahiert / In Analyse / Analysiert / Archiviert |
| erstellt_am       | Timestamp    | Created at                           |
| aktualisiert_am   | Timestamp    | Updated at                           |

### Analyse (Analysis Run)

| Field             | Type         | Description                          |
|-------------------|--------------|--------------------------------------|
| id                | UUID         | Primary key                          |
| vertrag_id        | UUID FK      | Link to contract                     |
| status            | Enum         | Gestartet / Pass 1 läuft / Pass 2 läuft / Pass 3 läuft / Pass 4 läuft / Konsolidierung / Abgeschlossen / Fehlgeschlagen |
| aktueller_pass    | String       | Current pass name                    |
| fortschritt       | Integer      | Progress 0-100                       |
| konfig_snapshot   | JSONB        | LLM settings at time of run          |
| gestartet_am      | Timestamp    | Start time                           |
| beendet_am        | Timestamp    | End time                             |
| fehler            | Text         | Error message if failed              |

### Fundstelle (Finding)

| Field             | Type         | Description                          |
|-------------------|--------------|--------------------------------------|
| id                | UUID         | Primary key                          |
| analyse_id        | UUID FK      | Link to analysis run                 |
| vertrag_id        | UUID FK      | Link to contract                     |
| textstelle        | Text         | Exact quoted text from contract      |
| absatz_ids        | JSONB        | Which paragraph(s) this relates to   |
| kategorie         | String       | Domain category                      |
| risikostufe       | Enum         | Hoch / Mittel / Niedrig / Hinweis    |
| kurzbeschreibung  | Text         | Short description of the issue       |
| erklaerung        | Text         | Detailed explanation                 |
| empfehlung        | Text         | Recommended action for Auftragnehmer |
| quelle_pass       | String       | Which pass discovered this           |
| pruef_status      | Enum         | Offen / Bestaetigt / Abgelehnt / Zurueckgestellt |
| pruef_kommentar   | Text         | Reviewer comment                     |
| erstellt_am       | Timestamp    | Created at                           |

### Einstellung (Setting)

| Field             | Type         | Description                          |
|-------------------|--------------|--------------------------------------|
| id                | UUID         | Primary key                          |
| schluessel        | String       | Setting key (e.g., `llm_provider`)   |
| wert              | Text         | Encrypted value for secrets          |
| beschreibung      | Text         | Human description                    |
| aktualisiert_am   | Timestamp    | Updated at                           |

### Protokoll (Log Entry)

| Field             | Type         | Description                          |
|-------------------|--------------|--------------------------------------|
| id                | UUID         | Primary key                          |
| analyse_id        | UUID FK      | Link to analysis (nullable)          |
| vertrag_id        | UUID FK      | Link to contract (nullable)          |
| ebene             | Enum         | Info / Warnung / Fehler              |
| nachricht         | Text         | Log message (German for UI display)  |
| details           | JSONB        | Structured metadata                  |
| erstellt_am       | Timestamp    | Created at                           |

---

## 5. Frontend Module Overview (German UI)

### Navigation / Hauptmenü

| Route             | German Label           | Description                    |
|-------------------|------------------------|--------------------------------|
| `/`               | Vertragsübersicht      | Contract list / dashboard      |
| `/vertrag/:id`    | Vertragsdetail         | Single contract + its analyses |
| `/vertrag/:id/analyse/:aid` | Analysestatus | Live analysis progress + log   |
| `/pruefung`       | Prüfung                | Human review queue             |
| `/pruefung/:id`   | Fundstellendetail      | Single finding review          |
| `/einstellungen`  | Einstellungen          | Admin: LLM config              |

### Screen Descriptions

**Vertragsübersicht** — Main landing page. Table of all contracts with status, upload date, finding count. Upload button. Delete action.

**Vertragsdetail** — Shows contract metadata, extracted text preview, list of analysis runs, and aggregated findings. Button to trigger new analysis.

**Analysestatus** — Real-time view of an ongoing or completed analysis. Shows which pass is currently running, progress bar, and a scrolling protocol/log view (ProtokollAnzeige component).

**Prüfung** — Review queue. Lists all findings with status "Offen". Filterable by contract, risk level, category. Bulk actions for "Bestätigt" / "Abgelehnt".

**Fundstellendetail** — Single finding with the quoted text span, contract context (surrounding paragraphs), AI explanation, recommendation. Reviewer can set status and add comment.

**Einstellungen** — Admin page. Configure LLM provider (OpenAI / Azure / Anthropic / Custom), model name, API key (masked), temperature defaults, max tokens. Test connection button.

---

## 6. German Terminology & Statuses

### Core Entities

| German Term        | Meaning                       | Used For                        |
|--------------------|-------------------------------|---------------------------------|
| Vertrag            | Contract                      | Uploaded document               |
| Analyse            | Analysis                      | One analysis run                |
| Fundstelle         | Finding / discovered location | A single discovered issue       |
| Prüfung            | Review / examination          | Human review process            |
| Einstellung        | Setting                       | System configuration            |
| Protokoll          | Log / protocol                | System log entries              |

### Contract Statuses (Vertragsstatus)

| German              | Meaning                    |
|---------------------|----------------------------|
| Hochgeladen         | Uploaded                   |
| Extrahiert          | Text extracted             |
| In Analyse          | Analysis running           |
| Analysiert          | Analysis complete          |
| Archiviert          | Archived                   |

### Analysis Statuses (Analysestatus)

| German              | Meaning                    |
|---------------------|----------------------------|
| Gestartet           | Started                    |
| Pass 1 läuft        | Pass 1 running             |
| Pass 2 läuft        | Pass 2 running             |
| Pass 3 läuft        | Pass 3 running             |
| Pass 4 läuft        | Pass 4 running             |
| Konsolidierung      | Consolidation running      |
| Abgeschlossen       | Completed                  |
| Fehlgeschlagen      | Failed                     |

### Finding Risk Levels (Risikostufe)

| German              | Meaning                    |
|---------------------|----------------------------|
| Hoch                | High risk                  |
| Mittel              | Medium risk                |
| Niedrig             | Low risk                   |
| Hinweis             | Informational note         |

### Finding Review Statuses (Prüfstatus)

| German              | Meaning                    |
|---------------------|----------------------------|
| Offen               | Open / unreviewed          |
| Bestätigt           | Confirmed                  |
| Abgelehnt           | Rejected (false positive)  |
| Zurückgestellt      | Deferred                   |

### Finding Categories (Kategorie)

| German                              | Scope                                    |
|-------------------------------------|------------------------------------------|
| Informationssicherheit              | InfoSec, encryption, access, breaches    |
| Datenschutz                         | Data protection, GDPR                    |
| Compliance & Regulatorik            | Regulatory pass-through, certifications  |
| Verfügbarkeit & Betrieb             | SLA, uptime, BCM, DR                     |
| Haftung & Gewährleistung            | Liability, warranty, indemnification     |
| Audit & Berichtswesen               | Audit rights, reporting obligations      |
| Vertragsmanagement                  | Termination, renewal, change control     |
| Leistungsumfang & Abgrenzung        | Scope creep, vague deliverables          |
| Personalanforderungen               | Staffing obligations, key personnel      |
| Geistiges Eigentum                  | IP transfer, licensing                   |
| Implizite Pflichten                 | Hidden / implied obligations             |

### Log Levels (Protokollebene)

| German              | Meaning                    |
|---------------------|----------------------------|
| Info                | Informational              |
| Warnung             | Warning                    |
| Fehler              | Error                      |

### UI Button / Action Labels

| German              | Action                     |
|---------------------|----------------------------|
| Hochladen           | Upload                     |
| Analyse starten     | Start analysis             |
| Löschen             | Delete                     |
| Bestätigen          | Confirm                    |
| Ablehnen            | Reject                     |
| Zurückstellen       | Defer                      |
| Speichern           | Save                       |
| Verbindung testen   | Test connection            |
| Exportieren         | Export                     |

---

## 7. Docker / Deployment

### docker-compose.yml Services

| Service    | Image / Build          | Port  | Purpose              |
|------------|------------------------|-------|----------------------|
| db         | postgres:16-alpine     | 5432  | PostgreSQL database  |
| backend    | ./backend (Dockerfile) | 8000  | FastAPI API server   |
| frontend   | ./frontend (Dockerfile)| 3000  | Vue.js dev / nginx   |

### Volumes

- `pgdata`: Persistent PostgreSQL data
- `uploads`: Contract file storage

### Environment Variables (.env)

```
POSTGRES_USER=contract_review
POSTGRES_PASSWORD=<secret>
POSTGRES_DB=contract_review
DATABASE_URL=postgresql+asyncpg://...
UPLOAD_DIR=/data/uploads
SECRET_KEY=<for encrypting API keys at rest>
```

---

## 8. Step-by-Step Implementation Plan

### Phase 1: Foundation (Week 1-2)
1. Set up repository structure (folders, configs, Dockerfiles)
2. Initialize FastAPI app with health endpoint
3. Set up PostgreSQL + Alembic migrations
4. Create all ORM models (Vertrag, Analyse, Fundstelle, Einstellung, Protokoll)
5. Implement Vertrag CRUD API (upload, list, detail, delete)
6. Implement text extraction service (PDF → plain text)
7. Initialize Vue.js frontend with router and basic layout
8. Build Vertragsübersicht and Vertragsdetail views
9. Docker Compose for full stack

### Phase 2: Discovery Engine (Week 3-4)
1. Build LLM client abstraction (litellm wrapper)
2. Build Einstellungen API + UI for LLM configuration
3. Implement overlapping chunking strategy
4. Implement Pass 1: Breite Ersterfassung
5. Implement Pass 2: Perspektivische Vertiefung (start with 2-3 sub-passes)
6. Implement Pass 3: Implizite Pflichten
7. Implement Pass 4: Querverweise & Wechselwirkungen
8. Implement consolidation logic
9. Build orchestrator to run passes sequentially
10. Protokoll logging throughout pipeline

### Phase 3: Review & UI (Week 5-6)
1. Build Analysestatus view with live progress + log
2. Build Prüfung (review queue) view
3. Build Fundstellendetail view with context display
4. Implement review workflow (status transitions + comments)
5. Add filtering and sorting across all list views
6. Status badges and risk-level color coding

### Phase 4: Hardening (Week 7-8)
1. Add remaining Pass 2 sub-passes
2. Prompt tuning based on real contract tests
3. Export functionality (findings → PDF/Excel)
4. Error handling and retry logic for LLM calls
5. Basic rate limiting and input validation
6. Documentation for deployment
