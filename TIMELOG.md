# TIMELOG.md

Wall-clock build time, AI-assisted (Claude Code). Design/research/spec writing and video are excluded.

| Milestone | Finished at (local) | Notes |
| --- | --- | --- |
| M0 — Scaffold | 2026-10-13 20:16 | API + Alembic (5 tables, Neon + local), Next.js 16 + shadcn + tokens, vercel.json, CI. Lost ~10 min to an out-of-memory machine (pnpm crashes) — stopped Docker to recover. |
| M1 — Discovery + dedup | 2026-10-13 20:35 | Nominatim, Overpass (+mirrors, chain filter), Places, CSV import, dedup. 27 tests. Live-checked against Overpass. |
| M2 — Crawler | 2026-10-13 21:05 | robots, 1 req/s/host, SSRF per hop, retries, 3 MB cap, TLS fallback, 7-day cache. 54 tests. Live crawl of 6 Columbus sites in 7.8 s. |
| M3 — Extractors + scoring + LLM | 2026-10-13 22:05 | 14 extractors, scorer, Gemini→Groq with quote guard + circuit breaker. 11 hand-written fixtures. 115 tests. |
| M4 — Run orchestration + API | 2026-10-13 23:20 | SSE run with lease/follow/resume/replay, runs + leads + demo routes, rate limits, problem+json. 121 unit + 5 integration tests (real Postgres). Live 20-lead auto-repair run: done in 140 s from India→Neon. |
