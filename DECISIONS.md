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
