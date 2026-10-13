# Kickoff prompt — paste this into Claude Code

Open a terminal in this folder (`buy-build-score/`), run `claude`, and paste everything between the lines.

---

Build the project described in this folder end to end.

1. Read `CLAUDE.md`, then `SPEC.md`, then `TASKS.md`, then the config files in `api/app/` (`scoring.yaml`, `fingerprints.yaml`, `osm_tags.yaml`, `prompts/extract.md`). Don't modify those config files except to fix a real bug, and log any change in `DECISIONS.md`.
2. Execute `TASKS.md` milestone by milestone, M0 through M8. For each milestone:
   - implement it
   - write and run its tests
   - run `ruff`, `mypy` and `pytest` for the API, and `lint`, `typecheck` and `vitest` for the web app
   - fix everything until green
   - commit with a clear message
   - tick the boxes in `TASKS.md`
   - append the milestone and elapsed time to `TIMELOG.md`
3. Don't ask me questions. When something is ambiguous, choose the simplest option that satisfies SPEC.md, write one line in `DECISIONS.md`, and continue.
4. Hard rules from CLAUDE.md are non-negotiable:
   - $0 stack, every key optional except `DATABASE_URL`
   - the run happens inside the SSE stream, with a 280 s guard
   - robots.txt, rate limits, SSRF guard, no SMTP probing
   - grounded LLM output only
   - every score backed by evidence rows with source URLs
5. Before writing `vercel.json`, check the current Vercel Services and FastAPI docs (https://vercel.com/docs/services, https://vercel.com/docs/frameworks/backend/fastapi) and follow them exactly.
6. The UI carries half the grade. Follow the UI spec, states and design tokens in SPEC.md precisely, and make it look polished in both light and dark.
7. When M8 is done:
   - print a short report: what's built, test counts, anything cut (and why), and the exact commands I need to run to deploy (Neon project, Vercel env vars, first migration)
   - list anything I must do by hand: the API keys, the 30-lead manual precision review, and recording the 2-minute video

Start with M0 now.

---

## Before you start (5 minutes, all free, no card)

1. Make a GitHub repo `buy-build-score` (public, so Actions minutes are free) and push this folder to it.
2. Create a Neon project (Free plan) → copy the **pooled** connection string → put it in `.env` as `DATABASE_URL` (use the `postgresql+asyncpg://` scheme).
3. Optional:
   - Gemini key from Google AI Studio and/or a Groq key
   - HubSpot free account → Settings → Integrations → Private Apps → token with company read/write and schema write scopes
4. Install `uv`, `pnpm`, and Docker (for the local Postgres).

## After it's done

- Import the repo into Vercel (Hobby). Add the env vars from `.env.example`. Deploy.
- Run `alembic upgrade head` against Neon (CI does this on `main` if `DATABASE_URL` is set as a repo secret).
- Do the 30-lead manual review and put the tier-A precision in the README.
- Record the 2-minute video using the script in the research doc.
- Keep `TIMELOG.md` honest. The handbook caps the build at 5 hours, and reviewers may ask how you used AI tools.
