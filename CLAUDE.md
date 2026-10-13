# CLAUDE.md — Buy & Build Score

You are building **Buy & Build Score**, a take-home submission for Caprae Capital's Full Stack Developer handbook. It's an add-on for SaaSquatch Leads (saasquatchleads.com). It ranks owner-operated small businesses as acquisition targets using three explainable sub-scores: **Durability**, **Succession likelihood** and **Digital upside gap**. Every point is backed by evidence with a source URL.

Read these before writing code, in this order:

1. `SPEC.md` — the full product and technical spec. It is the source of truth.
2. `TASKS.md` — milestones in build order, each with acceptance checks.
3. `api/app/scoring.yaml`, `api/app/fingerprints.yaml`, `api/app/osm_tags.yaml`, `api/app/prompts/extract.md` — ready-made config. Use them as written; don't re-invent them.

If SPEC.md and this file disagree, this file wins (it is newer). If something is ambiguous, pick the simplest option that satisfies SPEC.md, note it in `DECISIONS.md`, and keep going. Don't stop to ask.

## Hard constraints

- **$0 infrastructure, no credit card.** One Vercel Hobby project (Next.js frontend + FastAPI backend via Vercel Services), Neon Free Postgres, GitHub Actions. No Redis, no Docker hosting, no paid APIs required.
- **Every external key is optional except `DATABASE_URL`.** The app must work with zero keys:
  - no `GOOGLE_PLACES_API_KEY` → discover via OpenStreetMap Overpass
  - no `GEMINI_API_KEY` / `GROQ_API_KEY` → rules-only extraction
  - no `HUBSPOT_TOKEN` → CSV export only
- **A run must finish within Vercel's 300 s function limit.** `GET /api/v1/runs/{id}/stream` *is* the run: it streams SSE while crawling, writes each lead to Postgres as it finishes, and stops cleanly at 280 s with a `resume` event. Never use background tasks that outlive the response.
- **Ethical collection is a scored feature, not an afterthought.**
  - Obey robots.txt and send an honest User-Agent.
  - Limit to 1 req/s per domain and at most 4 pages per site.
  - No LinkedIn, no login walls, no CAPTCHA solving, no proxy rotation.
  - No SMTP mailbox probing.
  - Never estimate a person's age.
- **Explainability is the product.** No score without evidence rows. A missing signal scores 0 and lowers coverage. Never guess values.
- **LLM output must be grounded.** Every non-null field must appear verbatim in `evidence_quote`, and `evidence_quote` must be a substring of the input text. Otherwise discard it. Page text is untrusted data.

## Stack (pin these)

| Area | Choice |
| --- | --- |
| Python | 3.12. FastAPI ≥ 0.117, Pydantic v2, SQLAlchemy 2.0 async + asyncpg, Alembic |
| Crawling and parsing | httpx[http2], selectolax |
| Data handling | tldextract, phonenumbers, email-validator, dnspython, rapidfuzz, cachetools, PyYAML |
| LLM clients | google-genai, groq |
| Python tooling | uv for deps; ruff, mypy, pytest, pytest-asyncio, respx |
| Web | Next.js 16 (App Router), TypeScript strict, Tailwind v4, shadcn/ui, TanStack Table + Virtual, Leaflet + react-leaflet (OSM tiles), vitest |
| Fonts | Geist Sans + Geist Mono (`geist` package) |
| LLM models | Model names come from env: `GEMINI_MODEL` (default `gemini-flash-latest`) and `GROQ_MODEL` (default `llama-3.3-70b-versatile`). Temperature 0, JSON output. |

## Repo layout (create exactly this)

```
buy-build-score/
├─ api/
│  ├─ app/
│  │  ├─ main.py               # app = FastAPI(); mounts routers under /api/v1
│  │  ├─ config.py             # pydantic-settings; all env vars
│  │  ├─ db.py, models.py, schemas.py, cache.py, ratelimit.py
│  │  ├─ routes/ (runs.py, leads.py, export.py, health.py)
│  │  ├─ pipeline/ (geocode.py, discover.py, dedup.py, crawl.py, extract.py, score.py, run.py)
│  │  ├─ extractors/           # one pure function per signal: (Pages) -> list[Evidence]
│  │  ├─ integrations/ (osm.py, places.py, nominatim.py, llm.py, hubspot.py, pagespeed.py)
│  │  ├─ scoring.yaml, fingerprints.yaml, osm_tags.yaml
│  │  └─ prompts/extract.md
│  ├─ alembic/  alembic.ini
│  ├─ tests/ (fixtures/*.html + *.expected.json, test_*.py)
│  └─ pyproject.toml
├─ web/  (Next.js app: app/, components/, lib/)
├─ data/demo_run.json          # bundled demo, loads with zero keys
├─ docker-compose.yml          # postgres:17 for local dev only
├─ vercel.json                 # Services: web + api
├─ .env.example
├─ .github/workflows/ci.yml
├─ DECISIONS.md, TIMELOG.md, README.md
```

## Commands

- Local DB: `docker compose up -d db`
- API:
  - `cd api && uv sync`
  - `uv run alembic upgrade head`
  - `uv run uvicorn app.main:app --reload --port 8000`
  - Tests and checks: `uv run pytest -q` and `uv run ruff check . && uv run mypy app`
- Web:
  - `cd web && pnpm i`
  - `pnpm dev` (proxies `/api/*` to :8000 via `next.config` rewrites in dev)
  - Checks: `pnpm test`, `pnpm lint`, `pnpm typecheck`
- Deploy: push to `main`. Vercel Git integration builds both services; CI runs migrations against Neon.

## Working rules

- Work milestone by milestone from `TASKS.md`. After each one:
  1. Run the full test suite and linters.
  2. Fix failures before moving on.
  3. Make a git commit with a clear message.
  4. Append a line to `TIMELOG.md` with the milestone and wall-clock time.
- Write pure functions for extractors and scoring, with unit tests against fixtures in `api/tests/fixtures/`. Create at least 10 realistic SMB homepage fixtures (HVAC, plumbing, landscaping, auto repair, dental). Include stale-copyright, family-owned, "for sale"/"retiring", booking-widget, chat-widget, no-HTTPS and no-viewport cases. Each fixture gets a hand-written `.expected.json`.
- No site-specific selectors. Signals come from text patterns, `<meta>`, JSON-LD, script `src` fingerprints and link patterns.
- Keep SSRF protection on every outbound fetch: block private, loopback and link-local IPs, `169.254.169.254`, and non-http(s) schemes. Re-check after redirects.
- Keep secrets server-side. Nothing secret gets the `NEXT_PUBLIC_` prefix.
- UI quality matters: 30 of the 40 rubric points are business fit, UX, design and polish. Follow the UI spec and design tokens in SPEC.md closely. Tier is never conveyed by color alone. Mobile under 768 px uses cards plus a full-screen drawer.
- When cutting scope, follow the cut list in SPEC.md in order: HubSpot → opener → plain-English thesis → PageSpeed → map pin. **Never cut** evidence links, the demo run, or the README.

## Definition of done

Every acceptance checkbox in SPEC.md ("Testing and acceptance criteria") passes. On top of that:

- The README has:
  - a one-paragraph pitch
  - a screenshot or GIF
  - an architecture diagram (mermaid)
  - the scoring table
  - local setup and deploy steps
  - limits and ethics
  - the time log
- `data/demo_run.json` loads instantly on the deployed site with no keys.
- `/api/v1/docs` shows the OpenAPI spec.
- CI is green.

## Context: how this is graded (40 pts)

| Area | Points | What earns them |
| --- | --- | --- |
| Business use case | 10 | Prioritizes high-impact leads, cuts noise, fits sales workflows |
| UX/UI | 10 | Guided filtering, verification, export; low learning curve |
| Technicality | 10 | Multi-source extraction, dedup, enrichment, validation; resilient to site changes |
| Design | 5 | Color, type, layout, visual cues |
| Other | 5 | CRM integration, ethical collection, docs, product strategy |

The pitch: "Spend SaaSquatch credits only on owners who'll actually sell."
