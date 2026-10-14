# Demo script — 2 minutes

**One-line pitch:** *Spend SaaSquatch credits only on owners who'll actually sell.*
Everything below uses real data from the bundled demo run (dental practices, Columbus OH, 59 businesses).

## Before you hit record (5 min)

1. **Start the stack** (three windows, leave them open; Claude Code can't reap windows you started):
   ```powershell
   cd "C:\Users\Shreyas\Desktop\capre capital\buy-build-score\api"; uv run uvicorn app.main:app --port 8000
   cd "C:\Users\Shreyas\Desktop\capre capital\buy-build-score\web"; pnpm start -p 3000
   ```
   Open `http://localhost:3000`. Health check: `http://localhost:3000/api/v1/healthz` → `{"ok":true,"db":true,…}`.
   Neon unreachable (port 5432 blocked on some Wi-Fi)? Switch to a hotspot, or `docker compose up -d db` and set `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bbs` for the API.
2. **Warm the caches** so the live run is fast and on-camera-safe: run *"dental practices near Columbus, OH"* once now and let it finish (≈30–60 s). Overpass and the crawls are then cached; the recorded run takes ≈30 s.
3. Browser at **1440 px wide**, light theme, one tab, bookmarks bar hidden, zoom 100%.
4. **Fallback if anything misbehaves live:** open `http://localhost:3000/runs/demo`. Same data, loads instantly, needs no keys, no database for the page itself.

## Script

| Time | On screen | Say |
| --- | --- | --- |
| 0:00 | Landing page | "Searchers and SDRs pay about 39 cents for every enriched lead on SaaSquatch Silver. Most of those leads are businesses whose owner will never sell. Buy & Build Score sits between Discover and Enrich and ranks them first, so credits go only where it counts." |
| 0:15 | Type *dental practices near Columbus, OH* in the thesis box. Fields fill themselves. Point at the three presets. | "One sentence. It fills the fields. I'm a searcher, so durability and succession weigh most; an SDR would weight digital gaps instead." Click **Find targets**. |
| 0:30 | Run screen: skeleton → rows stream in, progress chips, tab title counting up | "Discovery is OpenStreetMap, free, no key. Each business's own website is read politely: robots.txt honoured, one request a second per site, four pages at most. Rows land the moment each one is scored." |
| 0:45 | Yellow banner: *4 sites asked crawlers to stay out* · amber icons | "Sites that say no are respected, not bypassed, and labelled. Businesses with no readable website are scored from listing data only and marked *thin data*. We never guess a signal." |
| 1:00 | Click **Fixari Family Dental** (B, 57) | "Fixari: founded 1987, family-owned, run by Mark and Shayne Fixari. Every point has a source." |
| 1:10 | Drawer: hover *Years in business* → the quoted sentence; click ↗ on *Founder / family-run* (opens their page) | "This is the exact sentence from their site that earned the points. Click through and it's right there. Greyed rows are signals we looked for and didn't find — coverage is honest." |
| 1:30 | Close drawer. Switch preset **Searcher → SDR → Searcher**; drag a weight slider | "Re-weighting never re-crawls. It re-ranks in the browser, instantly, from stored sub-scores." |
| 1:45 | Tick the top few rows → **Export CSV** | "Select the leads worth a credit and export in SaaSquatch's format — scores, owner, top three evidence links. HubSpot push is built too; it lights up with a token." |
| 1:55 | Back to landing, or the scoring section | "Public data only, free tiers end to end, every number explainable. Spend credits only on owners who'll actually sell." |

**Keep it honest on camera:** the best leads in this run are **B tier (57 top)**; no business reached A. Say so if asked: A needs a rare combination (family-run, single named leader, stale site, not hiring, 25+ years) and OSM-only data has no review signals. That's the model being strict, not broken.

## Cheat sheet (numbers you can quote)

- Demo run: 60 found → 7 chains dropped → **59 scored**; 21 sites read fully, 4 blocked by robots.txt, 29 listings without a website. Cold run measured 163 s (busy public Overpass servers); with warm caches **27–57 s**.
- Cost per run: **$0** (Vercel Hobby + Neon Free + free LLM tiers). 4–5 LLM calls per 60 businesses; the rest is deterministic rules.
- Tests: **142 API unit + 6 Postgres integration + 11 frontend**, all passing; 11 hand-written SMB fixtures.
- LLM is last resort and **quote-verified**: a name or year is kept only if it appears verbatim in a quote that is itself a substring of the page. Demo: 9 owner names found, none unverified.
- Scoring: Durability / Succession / Upside, each 0–100 from `scoring.yaml`; tiers A ≥ 70, B 50–69, C < 50; capped at B if durability < 30 or coverage < 40%.

## Likely questions

- **"Why no A-tier in the demo?"** See above. Real, strict, and the A guardrails are visible in the tier tooltip.
- **"How do you stop the LLM inventing owners?"** Verbatim-quote guard + page text treated as untrusted data; ungrounded output is discarded. Tested, including a planted prompt injection.
- **"Is this ethical?"** robots.txt, honest User-Agent, 1 req/s/site, ≤ 4 pages, no LinkedIn, no logins, no email probing, no age estimates. 5xx/403 robots.txt is treated as "don't crawl".
- **"What isn't built?"** Owner opener drafting (cut by plan), headless rendering for JS-only sites, auth/billing. HubSpot push is built and payload-tested but **not yet exercised against a live HubSpot portal** (needs a token). Production deploy to Vercel is documented in the README.
- **"Why OSM, not Google?"** $0 and no card. A Places key is supported and adds ratings/review signals (40 more durability points).
