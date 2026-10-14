# DECISIONS.md

Ambiguities resolved during the build. One line each: what, why.

## M0 — Scaffold

- **Repo isolation.** The folder sat inside a home-directory git repo with an auto-commit bot; ran `git init` here so the project is its own repo.
- **`evidence.extractor` allows `'osm'`.** SPEC's CHECK list omitted it, but `osm_tags.yaml` emits `start_date` evidence with extractor `osm` and `scoring.yaml` gives `osm` confidence 0.85. Without it those inserts fail.
- **Extra columns.** `runs.plan` (deduped company ids, so a partial run can resume with only unscored companies), `runs.warnings` (upstream banner messages), `runs.mode` (`osm`/`places`/`csv`), `runs.started_at`, `leads.email`, `leads.created_at`. All additive; nothing in SPEC removed.
- **`DATABASE_URL` accepts any Postgres URL.** `config.normalize_db_url` rewrites `postgresql://…?sslmode=require&channel_binding=require` (Neon's default copy-paste) to `postgresql+asyncpg://…` with `ssl=require` in connect args, because asyncpg rejects libpq-only params.
- **Prepared-statement cache off** (`statement_cache_size=0`) so the same engine works through Neon's PgBouncer pooler.
- **Crawler User-Agent** defaults to the repo URL only; a contact email is opt-in via `CRAWL_USER_AGENT` so no personal address is sent to crawled sites by default.
- **`max_results`** is validated against FR-1 (20/40/60, up to 180 with Expand); the `ThesisIn` example's `100` is treated as a typo.
- **Vercel Services config** follows docs.vercel.com/docs/services (checked 2026-10-13): `services.{web,api}` with `root`, FastAPI `entrypoint: "app.main:app"`, `functions["app/main.py"].maxDuration = 300` inside the api service, top-level rewrites `/api/(.*)` → api, `/(.*)` → web. FastAPI keeps the `/api/v1` prefix because Vercel forwards the original path.
- **TanStack Table pinned to v8** (create-time resolved v9, whose API changed); v8 is stable and documented.
- **Next.js 16.4 defaults kept** (`cacheComponents` + `partialPrefetching`); interactive screens are client components.
- **Mini-bars are CSS, not Recharts.** Three 0–100 bars don't need a chart library; saves ~90 KB.
- **`.claude/` and `skills-lock.json` are git-ignored.** They're local agent tooling, not part of the submission.
- **Local dev DB.** `docker-compose.yml` provides Postgres 17, but this machine is memory-constrained; Neon (the production DB) also works for local dev since every key except `DATABASE_URL` is optional.

## M1 — Discovery + dedup

- **Overpass mirror added** (`osm_tags.yaml` `fallback_endpoints`): `maps.mail.ru` first, then `private.coffee`. On 2026-10-13 the main instance returned 504 for trivial queries and private.coffee timed out; mail.ru answered. Per-request timeout 28 s (server-side `[timeout:25]` + transfer).
- **Chains are dropped before dedup** (`discover.drop_chains`): OSM `brand`/`brand:wikidata`, store-locator subdomains (`locations.`, `store.`…), or one domain shared by 3+ locations. Franchises aren't owner-operated, so they're noise for a searcher. The run reports how many were dropped.
- **Name-regex matches with a different category tag are dropped** (an `office=insurance` called "…Auto…", an `amenity=bar` called "…Mechanical"). Rows found by tag rank before name-only rows; rows with a website rank first.
- **Social/directory links aren't websites.** facebook/yelp/linkedin/etc. URLs normalise to no domain, so the business is `no_site` rather than a crawl of Facebook.
- **Fuzzy-name dedup never merges two different known domains**, and ZIP+4 is normalised to ZIP5 before the postcode comparison.
- **tldextract uses its bundled suffix snapshot** (`suffix_list_urls=()`), so serverless cold starts make no network call.
- **OSM coverage is uneven by trade.** Live check, Columbus OH, 40 km: dental 60 found / 30 with sites, auto repair 60 / 23, landscaping 55 / 19, HVAC 15 / 9, plumbing 7 / 4. The demo run should use a well-mapped trade (dental or auto repair) unless a Places key is set.

## M2 — Crawler

- **Robots.txt status handling.** 200 → parse; 404/unreachable → no restrictions published; 401/403/5xx → treat as full disallow (conservative, RFC 9309 says 5xx means "assume complete disallow").
- **Robots user-agent token** is `BuyBuildScoreBot` (product token of the full UA string), so site owners can target us specifically.
- **Bot walls are respected, not bypassed.** A 403 homepage (e.g. Cloudflare) is `unreachable` with the HTTP status as the reason; no retries with a browser UA, no proxies.
- **Bad TLS falls back to plain HTTP** to read the public page, and records `tls_ok=false` for the "No HTTPS / bad cert" upside signal. HTTP is never upgraded silently.
- **Crawl cache stores slimmed HTML** (CSS, inline SVG, comments and base64 blobs stripped; ≤ 400 KB; zlib+base64) so extractors stay pure functions over HTML and a re-run within 7 days makes zero requests. Script tags are kept because fingerprints need them.
- **Page buckets**: about/our-story/history → team/staff/leadership → contact → careers/jobs; one page per bucket, top 3, path matches beat anchor-text matches, shallow paths win.
- **DNS-rebinding window accepted.** The SSRF guard resolves and checks every hop, but httpx resolves again on connect; closing that TOCTOU gap needs a pinned-IP transport, noted as production hardening.
- **JS-rendered sites** are flagged (`js_rendered`) but not re-fetched with Playwright (P2 per SPEC; doesn't fit the free function).

## M3 — Extractors + scoring + LLM

- **Evidence rows only for the 20 scoring signals.** Informational facts (people list, tech stack, services, email, owner title/source) live in `companies.raw` and show in the drawer, so `UNIQUE(company_id, signal)` holds.
- **"Known" vs "missing" (coverage).** Text-absence signals (family, exit, hiring, single leader) and all upside signals are *known* once we've read ≥1 page — "checked and not found" is a fact. `founded_year` and `copyright_year` are known only when found. Places-only signals are excluded from the denominator in OSM/CSV mode (20 → 17).
- **Absent capabilities still get an evidence row** (0 points, e.g. "Online booking: Calendly"), so the drawer shows why a lead did *not* earn upside points.
- **Founding-year precedence:** schema.org `foundingDate` > strong text ("founded/established/est./serving … since") > bare "since" > OSM `start_date` > LLM. "40 years of experience" is never converted to a year (it's often the owner's career, not the business).
- **Exit-language guard** (beyond SPEC's negations): matches followed by "planning/plan/community" are services ("retirement planning", "business succession planning"), not exits. Matches are extended to word end first ("retire" inside "retirement").
- **Negation guard** also treats a preceding "no" as negation ("no job openings").
- **People regex is case-sensitive for names** (only titles ignore case) and never spans block elements; page text keeps one line per block so "A note from Tom" + "Tom Reilly, owner" isn't read as "Tom Tom Reilly".
- **Owner = an owner-type title, or a lone "Dr."** (solo practice). Two doctors and no owner title → owner unknown, never guessed.
- **"Owner surname in business name"** compares against the normalised name tokens ("Petty's Auto Service" → `petty`).
- **Operating, fixed location in OSM/CSV mode** accepts a street address from OSM *or* the site's schema.org `PostalAddress`; evidence links the OSM object or the page.
- **Rounding is half-up everywhere** (`floor(x+0.5)`) so Python and the browser's `Math.round` agree on every composite.
- **LLM grounding is strict:** every non-null field — including each `services` item and `owner_title` — must appear in `evidence_quote`, and the quote must be a substring of the input (whitespace/case-normalised). Page text has `<company` delimiters neutralised before it's sent.
- **Groq model default → `openai/gpt-oss-120b`.** `llama-3.3-70b-versatile` returns 404 (retired); verified with one live call that gpt-oss-120b returns grounded JSON and ignores an injected instruction.
- **LLM circuit breaker.** On 2026-10-13 `gemini-flash-latest` returned 503 and timeouts for this key; a failed provider is skipped for 5 minutes so a run doesn't pay a 40 s timeout per batch. A missing key isn't treated as an outage.
- **LLM cache is per company input** (sha256 of models + prompt + name + text), not per batch, so batch composition doesn't defeat the cache.

## M4 — Run orchestration + API

- **Run lease instead of advisory locks.** Neon's pooler is PgBouncer in transaction mode, where session advisory locks don't hold. A `runs.lease_until` column (migration 0002) is claimed with one conditional `UPDATE … RETURNING`, renewed every 15 s, released in `finally`. A second stream of the same run *follows* (polls the DB and mirrors rows) instead of crawling twice; if the runner dies, the follower emits `resume`.
- **Every discovered company becomes a lead**, including `no_site`, `unreachable` and `blocked_robots` ones (scored from discovery data, thin-data capped) — so the UI can label them instead of silently dropping them.
- **"Crawled within 7 days → reuse"** is implemented by the caches, not a separate path: the crawl cache returns stored pages with zero requests, extraction is pure, the LLM cache is per input. One code path, same results.
- **Status events** fire on phase changes and at most once per second while leads stream, carrying counts (`discovered, deduped, chains_dropped, crawled, scored, ok, partial, no_site, unreachable, blocked_robots, failed, llm_calls`).
- **Overpass hedging.** A live run spent 160 s in discovery trying mirrors in sequence. Now the primary starts first and each mirror joins 3 s later; first success wins and the rest are cancelled; one 10 s retry; 60 s hard cap with a friendly error. A healthy primary means zero mirror traffic.
- **"for sale" must refer to the business** (`X is for sale`, `business for sale`); a live site said "occasionally has vehicles for sale".
- **Gemini timeout 15 s** (flash answers in 2–5 s); with the circuit breaker a slow Gemini costs one batch at most.
- **DB pool 10 + 15 overflow, no pre-ping.** 20 concurrent companies were queueing on 10 connections; `pool_recycle=240` stays under Neon's 5-minute suspend.
- **Integration tests run against a separate `bbs_test` database** (created on the same Neon project) or CI's Postgres container — never the app database. `TEST_DATABASE_URL` unset → skipped.
- **Deploy region.** Neon is `us-east-2` (Ohio); Vercel functions should run in `cle1` (Cleveland) — each lead does ~20 DB round-trips, which is ~0.2 s next door vs ~6 s from far away.
- **MX "couldn't check"** (DNS timeout) is stored as `none`, never `valid_mx`: we don't claim validity we didn't verify. (Schema allows only `valid_mx/no_mx/invalid/none`.)
- **`POST /runs/csv` dedups and inserts companies at upload time** (no network work), so the stream starts crawling immediately.

## M5 — UI

- **Static demo.** "Try the demo run" opens `/runs/demo`, which renders `web/public/demo/run.json` (API-shaped `LeadDetail[]`) straight from the CDN — instant, zero keys, works even if the API is cold. Export from the demo calls `POST /runs/demo` first (idempotent, same lead ids) and falls back to a browser-built CSV with the same columns if the API is down.
- **Rows hold arrival order while streaming**; they rank once the run finishes or the user sorts, moves a slider or presses "Rank now". New rows fade in once (150 ms), not on every virtualised re-mount.
- **SSE goes direct to `:8000` in dev** (`NEXT_PUBLIC_STREAM_ORIGIN`), because the Next dev proxy can buffer streams. In production it's same-origin through Vercel Services.
- **EventSource is closed on `done`/`error`** (otherwise the browser auto-reconnects and replays forever) and reopened on `resume`.
- **Plain-English thesis (FR-17) is rules-only, client-side** ("HVAC companies near Columbus, OH", "within 25 miles"); no LLM call needed for this.
- **Map pin is a Leaflet `CircleMarker`** on OSM tiles: no marker images to bundle, attribution shown.
- **Run page is a server shell + client child under `<Suspense>`**: with Cache Components, `useParams()` outside Suspense blocks prerendering.
- **Visual QA pending.** The machine ran out of memory while the dev servers were up and the Chrome extension wasn't connected, so the screens were verified by typecheck, lint, unit tests and a production `next build`, not by eye. Screenshots for the README are a manual step.

## M6 — Export + validation

- **CSV is de-duplicated by company** and every cell starting with `= + - @` is prefixed with `'` (spreadsheet formula injection).
- **Export re-ranks with the caller's weights**, so the CSV tiers match what the user sees after moving sliders.
- **HubSpot without a token returns 501 problem+json**; the UI disables the button with a tooltip.

## Cut list applied (M7)

Following SPEC's order: HubSpot push was built (it was cheap once export existed). **Cut:** owner opener drafting (FR-16). Plain-English thesis shipped rules-only (above). PageSpeed Insights was added during the audit (it was a ~40-line integration on top of an existing scorer path): only with `PAGESPEED_API_KEY`, run concurrently with the crawl, cached 7 days, TTFB/page-size fallback otherwise. Never cut: evidence links, the demo run, the README.

## Audit fixes (after M6)

- **Mobile drawer was 75% wide, not full-screen.** shadcn's `cn` keeps `data-[side=right]:w-3/4`, which out-specifies a plain `w-full`; overrides now use the same data-variant.
- **CI web job couldn't install pnpm**: `pnpm/action-setup` looks for `packageManager` in the root `package.json`; pointed it at `web/package.json`.
- **Cache/rate-limit rows were never deleted.** Expired rows are now purged whenever a run is created (no cron needed).
- **Rate-limit IP** prefers Vercel's `X-Real-IP`; the first `X-Forwarded-For` hop is client-controlled.
- **Bare-domain websites** (common in CSVs) became relative links; one `website_url()` now returns absolute URLs for the API and CSV.
- **Only a missing location fails a run.** Busy Overpass/Places or an unexpected error leaves the run resumable (scored leads kept) and the UI offers Retry; previously the message said "reopen to resume" while the run was marked failed.
- **robots.txt of the redirect target** now governs subpages when a site redirects to another host.
- **Heartbeats during discovery**: geocoding + Overpass can take a minute; the stream now sends a keep-alive every 15 s there too.
- **Demo feedback** loads the demo server-side first (it 404'd before); the sort arrow is hidden while rows are still in arrival order.
- **Order-dependent test**: the process-wide Overpass throttle leaked between tests; discovery tests now get a fresh one.

## Browser test (Chrome, production build, 2026-10-14)

Tested end to end in Chrome against `next start` + uvicorn + Neon: landing parse, demo run, filters, weights, drawer, keyboard, a live thesis run, a CSV upload, replay, export, light/dark, 375 px / 860 px / 1568 px. Fixed what it found:

- **Demo load race → 500.** Two concurrent `POST /runs/demo` (two Export clicks) both passed the "already loaded?" check and the second crashed on the duplicate run id. Now every insert is a bulk `ON CONFLICT DO NOTHING`; three concurrent loads all return 200.
- **CSV export corrupted phone numbers.** The formula guard turned `+16146180116` into `'+16146180116`. Plain numbers and phone numbers are now left intact; real formulas (`=…`, `+SUM(…)`, `-cmd|…`, `@…`) are still neutralised.
- **Table overflowed sideways at medium widths.** Columns now adapt to the table's measured width: "Why" drops below 980 px, "Founded" below 760 px, reviews below 1080 px.
- **Run header broke on phones** (title truncated to "De…", one word per line). The title owns the first line; stage chips wrap below. The selection bar is compact on phones.
- **Rows froze in background tabs.** Lead batching used `requestAnimationFrame`, which browsers pause in hidden tabs; it now uses a 60 ms timer. The tab title shows live progress ("12/59 Dental · Columbus…", then "✓ …").
- **Company upserts were one session per company** (~5 round-trips each): one prefetch query + one commit per run now.
- Copy: "1 LLM calls" → "1 LLM call"; the demo card no longer stretches next to the CSV preview.
- `API_PROXY_ORIGIN` (build-time, opt-in) lets a production build proxy `/api` to a local API for testing; never set on Vercel.

## Brave test, local DB (2026-10-14)

The network blocked outbound port 5432 (Neon unreachable; port 443 fine), so this pass ran against the docker-compose Postgres. Two more real bugs found by watching live runs:

- **A crawl timeout threw away pages already read.** With 11 sites crawling at once, R & T Yoder HVAC (fine alone in 12 s) hit the 25 s per-site budget mid-subpages and was scored "unreachable" with nothing. The crawler now fills one result object as it goes: if the homepage was read, a timeout returns `partial` with the pages it has. Same HVAC run after the fix: Yoder → B 53, HHR crawled, whole run 18 s.
- **A bare schema.org `Person` became "the owner".** "Gabriel Oscar", marked up on Yoder's *careers* page with no role, was credited as owner and single leader (+13.5) while the about page says the company "was founded in 2004 by Rod and T…". JSON-LD people now count only as an organisation's `founder` or with an owner-type `jobTitle`.
- **Demo regenerated** with both fixes (same thesis, local DB): 0 bare-Person owners; 7 owners, all from the sites' own text. Gemini (503/timeouts) and Groq (free-tier rate limit) were both unavailable, so this demo has no LLM gap-fills — re-run `scripts/export_demo.py` on a fresh run once Groq's limit resets to restore owners like Fixari's.
- **"N LLM calls" counted failed attempts**; it now counts successful answers only (demo counts corrected to 0).

## Production deploy (2026-10-14)

- **Deployed** to https://buy-build-score.vercel.app (Vercel Hobby, Services: `web` Next.js + `api` FastAPI, both in `cle1`, next to Neon `us-east-2`). Secrets (`DATABASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`) are Vercel *sensitive* env vars; `PUBLIC_APP_URL`/`ALLOWED_ORIGINS` set to the production URL.
- **Measured on production, cold** (new city, nothing cached): 60 found → 59 scored in **57 s** server time (target ≤ 90 s ✅). SSE streams through Vercel unbuffered: first lead at ~8 s on a warm run.
- **Found by that run and fixed:** (1) an OSM website tag of `http://<private-use glyph>\nexample.com` made the HTTP client raise a non-`HTTPError`, silently dropping the lead — URLs are cleaned at the source (`dedup.clean_url`) and any unexpected crawl exception now yields an "unreachable" lead; (2) "Provider Relations" (a chain's corporate department) was credited as owner — departmental/role words added to the not-a-name list. Re-run on production: 59/59 scored, the previously dropped practice ranks first.
- **Region:** `"regions": ["cle1"]` in `vercel.json` (accepted in Services mode; build output confirms `[cle1]`).
- **Deploy method:** `vercel deploy --prod` from the repo; Git integration (auto-deploy on push) needs the GitHub repo to be connected in the Vercel dashboard.

## SPEC acceptance criteria — status

| Criterion | Status |
| --- | --- |
| Demo loads with no keys, ≥ 30 ranked leads | ✅ 59 leads, static from the CDN (`/runs/demo`); also loadable via `POST /runs/demo`. Note: 0 A / 5 B / 54 C — OSM dental data is thin (29 listings without a website) and A needs a rare combination of signals; auto repair (also tried) tops out at B 64. Thresholds were not tuned to manufacture an A. |
| Live 60-business run ≤ 90 s, first row ≤ 10 s | ✅ on production (57 s cold, see above). Before that: ⚠️ Partly. From India against Neon (Ohio, ~0.3 s per DB round-trip): cold run 163 s (first row 85 s, dominated by busy public Overpass servers); with Overpass + crawls cached, 59 leads in 27–57 s with the first row at ~13 s. The < 90 s cold target depends on Overpass being responsive; still unmeasured on Vercel `cle1`. |
| Every A-tier lead has ≥ 1 evidence item with a working source link per sub-score | ✅ by construction: every known signal (including 0-point ones) is an evidence row with a source URL (asserted in tests); A requires durability ≥ 30, so durability always has evidence. |
| Slider re-ranks < 100 ms, no network | ✅ pure in-browser re-rank (`lib/score.ts`); vitest re-ranks 500 leads well under 100 ms. |
| SaaSquatch CSV upload maps headers and scores rows | ✅ client preview + server mapping, tested (25-row file, 6 duplicates → 19). |
| CSV export opens in Excel/Sheets, correct columns, no duplicates | ✅ UTF-8 BOM, spec columns, de-duplicated by company, formula-safe (integration-tested). |
| robots.txt-disallowed site not crawled, labelled in UI | ✅ tested (full and partial disallow, 5xx robots, redirect target); amber icon + tooltip + banner. |
| pytest and vitest pass in CI; `/docs` shows OpenAPI | ✅ locally (134 + 6 integration, 11 vitest); CI runs on first push. `/api/v1/docs` served. |
| README covers setup, architecture, scoring, limits, time log | ✅ — screenshot and tier-A precision are placeholders for the owner. |
