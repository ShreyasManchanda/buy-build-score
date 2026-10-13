# TASKS.md — build order

Work top to bottom. Finish each milestone's checks before starting the next. After every milestone, do all four:

1. Run `uv run pytest -q`, `uv run ruff check .`, and `pnpm typecheck`.
2. Commit.
3. Append a line to `TIMELOG.md`.
4. Tick the boxes here.

Target total: about 5 hours. If you're past 4:30, jump to M8 and apply the SPEC cut list.

## M0 — Scaffold (0:00–0:30)

- [x] Create the repo layout from CLAUDE.md, plus `git init`, `.gitignore`, and `.env.example` (copy from the root file).
- [x] API scaffold:
  - `api/pyproject.toml` with the pinned deps (uv)
  - FastAPI app mounted at `/api/v1`
  - `GET /api/v1/healthz` returns `{ok, db}`
  - `config.py` via pydantic-settings
- [x] Alembic migration with the five tables from SPEC.md "Data model": runs, companies, leads, evidence, cache. Include the `pg_trgm` and `pgcrypto` extensions.
- [x] `docker-compose.yml` with `postgres:17` on port 5432.
- [x] `web/` on Next.js 16 with:
  - App Router, TypeScript strict, Tailwind v4, shadcn/ui init
  - Geist fonts
  - design tokens from SPEC.md as CSS variables, light and dark
  - dev rewrite `/api/:path*` → `http://localhost:8000/api/:path*`
- [x] `vercel.json` defining two Services (web = Next.js, api = FastAPI with entrypoint `api/app/main.py:app`). Check https://vercel.com/docs/services for the exact current schema before writing it.
- [x] `.github/workflows/ci.yml` running two jobs:
  - api: uv, ruff, mypy, pytest against a postgres service
  - web: pnpm, lint, typecheck, vitest
- **Check:** `/api/v1/healthz` returns `{"ok":true,"db":true}` locally, and CI passes on the first push.

## M1 — Discovery + dedup (0:30–1:00)

- [ ] `integrations/nominatim.py`: geocode a location string. Rules:
  - 1 req/s
  - User-Agent from `CRAWL_USER_AGENT`
  - cache 30 days under `geo:`
  - no autocomplete
- [ ] `integrations/osm.py`:
  - build the Overpass query from `osm_tags.yaml`
  - parse into `CompanyIn` (name, website, phone, address, lat/lng, osm_id, start_date)
  - cache 24 h
  - on 429/504: try the fallback endpoint, then wait 30 s once
- [ ] `integrations/places.py` (used only when `GOOGLE_PLACES_API_KEY` is set):
  - Text Search (New), `pageSize` 20, up to 3 pages
  - field mask: `places.id,places.displayName,places.formattedAddress,places.location,places.websiteUri,places.nationalPhoneNumber,places.rating,places.userRatingCount,places.businessStatus,places.reviews`
  - On quota or other errors, fall back to OSM and emit a `warning` event.
- [ ] `pipeline/dedup.py`:
  - normalize domain (tldextract), phone (E.164 via phonenumbers), and name (lowercase, strip LLC/Inc/Co/Corp/&/punctuation)
  - match order: domain → phone → `rapidfuzz.fuzz.token_set_ratio ≥ 90` + same postcode
  - merge keeps the most complete record and records `merged_from`
- [ ] Tests:
  - Overpass response fixture → parsed companies
  - 25-row CSV with 6 planted duplicates → 19 unique

## M2 — Crawler (1:00–1:30)

- [ ] `pipeline/crawl.py`, using httpx.AsyncClient with HTTP/2:
  - global semaphore `CRAWL_CONCURRENCY` (20); per-domain 1 req/s
  - timeouts: connect 5 s, read 10 s, 25 s total per domain
  - 2 retries with backoff on 429/5xx/timeouts; honor `Retry-After`
  - only `text/html`; max body 3 MB
- [ ] robots.txt via `urllib.robotparser`, cached 24 h. A fully disallowed site gets `crawl_status = blocked_robots`.
- [ ] Page selection: homepage plus up to 3 internal links matching `about|our-story|history|team|staff|contact|careers|jobs` in the path or anchor text.
- [ ] SSRF guard: resolve the host and reject private/loopback/link-local/metadata IPs. Re-check every redirect hop. Allow only http(s).
- [ ] Cache cleaned pages under `crawl:{domain}` for 7 days. Also record TTFB, total bytes, final URL scheme, and TLS ok.
- [ ] Tests (with respx):
  - robots disallow honored
  - SSRF to 127.0.0.1 and 169.254.169.254 blocked
  - redirect to a private IP blocked
  - page selection picks /about-us and /contact

## M3 — Extractors + scoring (1:30–2:45)

- [ ] One pure function per signal in `extractors/`:
  - `founded_year` (JSON-LD, regex, OSM `start_date`)
  - `copyright_year` (footer region)
  - `family_owned`, `exit_language`, `hiring` (with the negation guard)
  - `people_named` (regex on "Owner|President|Founder|Principal[:,–-] Name")
  - `tech_fingerprints` (from `fingerprints.yaml`)
  - `mobile_viewport`, `https`, `ttfb`/`page_bytes`, `social_links`, `tel_only_cta`, `quote_form`, `table_layout`
- [ ] `pipeline/score.py`:
  - load `scoring.yaml`; compute the three sub-scores with confidence weighting and OSM-mode re-normalization
  - compute coverage; apply guardrails
  - return evidence rows with dimension, signal, value, points, confidence, source_url, snippet, extractor
- [ ] `integrations/llm.py`:
  - batched extraction per `prompts/extract.md`, Gemini then Groq fallback
  - run the quote guard; cache results
  - call it only for companies still missing `owner_name` or `founded_year` after rules
- [ ] Fixtures: at least 10 realistic SMB homepages in `api/tests/fixtures/`, each with a `.expected.json` listing the expected evidence signals. Cover:
  - stale copyright (2018)
  - "family owned since 1979"
  - "owner is retiring" (and one "not for sale" negation)
  - Calendly
  - Tidio chat
  - GA4 present
  - no viewport
  - http-only
  - jQuery 1.12
  - phone-only CTA
- [ ] Tests:
  - every fixture's expected signals are found
  - scoring math: caps, durability floor, thin-data cap, OSM re-normalization, preset weights
  - the LLM guard rejects an ungrounded quote and a hallucinated owner

## M4 — Run orchestration + API (2:45–3:15)

- [ ] `POST /api/v1/runs` (thesis) and `POST /api/v1/runs/csv` (multipart, ≤ 2 MB, ≤ 500 rows, header aliases from SPEC.md) create a run row and return `{run_id, stream_url}`.
- [ ] `GET /api/v1/runs/{id}/stream` executes the run as SSE. Requirements:
  - **events:**
    - `status` `{status, counts}`
    - `lead` `LeadOut`
    - `warning` `{company, reason}`
    - `resume` `{remaining}`
    - `done` `{counts, duration_ms}`
    - `error` `{message}`
    - plus a heartbeat comment every 15 s
  - **pipeline:** discover → dedup → per company (cache check → crawl → extract → score → upsert → emit `lead`)
  - **concurrency:** run per-company tasks with `asyncio.as_completed` so rows stream as they finish
  - **time guard:** at 280 s, stop launching work, emit `resume`, and close
  - **re-opening:** a finished run replays stored leads; a partial run resumes with only unscored companies
- [ ] `POST /api/v1/runs/demo` loads `data/demo_run.json` into the DB (idempotent) and returns its run_id.
- [ ] `GET /api/v1/runs/{id}` returns status and counts.
- [ ] `GET /api/v1/runs/{id}/leads` takes these query params: `wd`, `ws`, `wu`, `tier`, `min_d`, `min_s`, `min_u`, `q`, `sort`, `page`, `page_size≤100`. The composite is computed in SQL from the weights.
- [ ] `GET /api/v1/leads/{id}` returns `LeadDetail` with full evidence.
- [ ] Errors use RFC 7807 problem+json. Rate limit is 10 runs/hour/IP plus 60 req/min/IP, backed by Postgres. The SSRF guard covers all fetches.
- [ ] Integration test: with respx-mocked Overpass and 5 sites plus real Postgres, the event order is `status → lead×5 → done`, and the DB holds 5 leads with evidence.

## M5 — UI (3:15–4:15)

- [ ] `/` (thesis screen):
  - industry and location fields, radius, max results (20/40/60) with an "Expand" toggle
  - preset segmented control (Searcher, SDR, Caprae)
  - CSV drag-and-drop with a header-mapping preview
  - "Try the demo run" button
  - a "Find targets" primary button, disabled until industry and location are set
- [ ] `/runs/[id]` (run screen):
  - **header:** progress header with stage labels and elapsed time
  - **left rail:**
    - tier chips with counts
    - sub-score range sliders
    - toggles: has owner, valid email, hide thin data
    - weight sliders with a preset reset
  - **table:** virtualized TanStack table with these columns: checkbox · tier badge (letter plus color) · company (name + domain) · composite (Geist Mono) · D/S/U mini-bars · founded · reviews (Places mode only) · top 2 evidence chips · contact icons
  - **streaming:** rows stream in with a 150 ms fade. Don't re-sort until the user interacts.
  - **sticky action bar:** Export CSV / Push to HubSpot / N selected
- [ ] Lead drawer (480 px):
  - header: name, tier, composite, address, Leaflet map pin, website, phone, owner with "found on /about" link
  - three collapsible dimension sections listing evidence rows: label · value · +points · confidence dot · ↗ source, with the snippet on hover
  - missing signals shown greyed as "not found"
  - keyboard: ↑/↓ moves between leads, E exports, Esc closes
- [ ] `lib/score.ts`: client-side re-weighting matches the API composite to within ±1. Write a vitest for it.
- [ ] States:
  - empty
  - partial (amber icon with tooltip)
  - upstream warning banner
  - thin-data badge
  - "durability (site-only)" label in OSM mode
  - mobile (< 768 px): cards plus a full-screen drawer
- [ ] Footer attribution: "© OpenStreetMap contributors". Add Google attribution when Places data is shown.

## M6 — Export + validation (4:15–4:35)

- [ ] Validation:
  - website status/HTTPS/TLS
  - company email (from `mailto:` or the contact page) via syntax plus an MX check (dnspython, 2 s timeout, cached 7 days)
  - phone via `phonenumbers` validity
  - **no SMTP probing**
- [ ] `POST /api/v1/export/csv` with the columns from SPEC.md "Integrations", as UTF-8 with BOM.
- [ ] P1 `POST /api/v1/export/hubspot` (only if `HUBSPOT_TOKEN` is set):
  - ensure the property group and `bbs_*` properties exist
  - batch upsert on `domain` in batches of 100
  - on a "non-unique property domain" error, search by domain and update the oldest record by ID
  - return `{created, updated, failed[]}`

## M7 — P1 extras (only if time remains)

- [ ] `POST /api/v1/leads/{id}/opener`: an owner email of at most 120 words plus a 2-line call opener, grounded only in stored evidence. Return the `evidence_ids` used.
- [ ] `POST /api/v1/parse-thesis`: plain English → thesis fields (LLM, with a rules fallback).
- [ ] PageSpeed Insights mobile score (if `PAGESPEED_API_KEY` is set).

## M8 — Demo, docs, deploy (4:35–5:00)

- [ ] Generate `data/demo_run.json` by running one real thesis locally (e.g. "HVAC, Columbus OH", 60 results), then exporting run + companies + leads + evidence. Commit it.
- [ ] README.md:
  - pitch
  - screenshot or GIF
  - mermaid architecture
  - scoring table (from scoring.yaml)
  - setup (local + Vercel + Neon)
  - free-tier notes
  - ethics and limits
  - tier-A precision from a 30-lead manual review (leave a placeholder for Shreyas to fill)
  - `TIMELOG.md` summary
- [ ] Deploy: create the Neon project, set env vars in Vercel, push `main`, and run `alembic upgrade head` against Neon.
- [ ] Smoke test on prod:
  - the demo run loads
  - one live 20-result run completes
  - `/api/v1/docs` renders
- [ ] Final pass over SPEC.md's "Acceptance criteria". Every box ticked, or explained in DECISIONS.md.
