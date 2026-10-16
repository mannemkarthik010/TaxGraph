# TaxProof — Return Assurance Twin

> Every number has a proof. Every change has a history. Every filing can be reconstructed.
>
> **AI investigates. Code calculates. Evidence proves. CPAs decide.**
>
> The supplied engine produces the return. TaxProof independently assembles the assurance record around it —
> and answers, at any moment, *why should I trust this return?*

TaxProof is a working prototype of a web-native tax workpaper for the Miraflores case study
("Redesign the Tax Workpaper"), built around the Okafor-Lindqvist 2025 packet. The supplied packet is
treated as immutable pipeline output. Everything people add (notes, reviews, decisions) lives in a
separate workpaper layer that points into the packet with the packet's own reference grammar.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data map, layering and schema, and
[docs/ITERATIONS.md](docs/ITERATIONS.md) for what each iteration delivered.

## Run it locally

Prerequisites: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+, and Docker (for PostgreSQL).

```bash
# 1. Database (PostgreSQL 16 on localhost:5433)
docker compose up -d db

# 2. API (FastAPI on :8000). Runs migrations and seeds from the packet on startup.
cd backend
uv venv .venv --python 3.12 && uv pip install -p .venv -r requirements.txt
cp .env.example .env            # points at the docker Postgres
.venv/bin/uvicorn app.main:app --port 8000

# 3. Web (Next.js on :3000, proxies /api to :8000)
cd ../frontend
npm install
npm run dev
```

Open http://localhost:3000. Use the switcher in the top right to act as a different person. Permissions
are enforced by the API, not the UI.

No Docker? Delete `backend/.env` (or set `TAXPROOF_DATABASE_URL=sqlite:///./taxproof.db`) and the API
runs on SQLite with the same migrations.

### Optional: an AI model

AI features work without a model: TaxProof then writes deterministic, evidence-grounded sentences and labels
them "no AI model". To use Claude, set these in `backend/.env` (never commit the key):

```
TAXPROOF_AI_API_KEY=...
TAXPROOF_AI_MODEL=claude-opus-5-5
```

Only masked context is sent, and every claim is validated against the evidence it cites.

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q          # each test module gets its own fresh SQLite database
```

Frontend unit tests (Vitest + Testing Library):

```bash
cd frontend && npm test
```

The backend suite on PostgreSQL (uses a separate `taxproof_test` database whose schema is rebuilt each run):

```bash
docker compose exec -T db createdb -U taxproof taxproof_test   # once
cd backend && TAXPROOF_TEST_DATABASE_URL=postgresql+psycopg://taxproof:taxproof_local_dev@localhost:5433/taxproof_test .venv/bin/python -m pytest -q
```

## Repository layout

```
okafor_lindqvist_2025_packet.json   supplied packet — never modified (SHA-256 checked at startup)
docker-compose.yml                  PostgreSQL
backend/app/packet/                 loader (deep-freeze + hash), indexes, universal reference resolver
backend/app/security/               role/permission matrix, sensitive-data masking
backend/app/services/               audit hash chain, return read-models, evidence checks, graph, schedules,
                                    assurance engine, adjustments, Time Machine / What-If, Uncertainty Inbox,
                                    judgments, living sign-offs, filing lifecycle, snapshots, Examiner Mode,
                                    grounded AI, risk score, search, firm standards, assurance twin
backend/app/api/                    FastAPI routers
backend/alembic/                    migrations
backend/tests/                      pytest suite
frontend/src/app/                   Overview (Assurance Twin), Evidence, Return, Challenge, Review, Timeline, Filing, Examiner, Search, Firm, Trust
frontend/src/components/tp/         TaxProof components (shell, role switcher, line detail, notes)
docs/                               architecture and iteration notes
```

## Users for the role switcher (from the packet)

| User | Role | Notes |
|---|---|---|
| Priya Raman (st-01) | Preparer | assigned preparer |
| Marcus Bell (st-04) | Preparer | **no sensitive-data clearance**: reveals are denied and logged |
| Daniel Ortiz (st-02) | Reviewer | can raise and clear review notes |
| Helen Strand (st-03) | Partner | can see the audit trail |
| Sam Adeyemi (st-06) | Quality Reviewer | audit trail and access log |
| Jo Kimura (st-05) | Firm Administrator | firm settings and logs; no client data reveals, no notes |
| Ngozi Okafor / Erik Lindqvist | Client | own return and documents; no internal notes, firm or audit pages |
