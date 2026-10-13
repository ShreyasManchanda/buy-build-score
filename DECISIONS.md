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
