# TIMELOG.md

Wall-clock build time, AI-assisted (Claude Code). Design/research/spec writing and video are excluded.

| Milestone | Finished at (local) | Notes |
| --- | --- | --- |
| M0 — Scaffold | 2026-10-13 20:16 | API + Alembic (5 tables, Neon + local), Next.js 16 + shadcn + tokens, vercel.json, CI. Lost ~10 min to an out-of-memory machine (pnpm crashes) — stopped Docker to recover. |
| M1 — Discovery + dedup | 2026-10-13 20:35 | Nominatim, Overpass (+mirrors, chain filter), Places, CSV import, dedup. 27 tests. Live-checked against Overpass. |
