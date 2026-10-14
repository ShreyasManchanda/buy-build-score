# Demo script — 2 minutes

**Read the 🗣 SAY lines out loud. Do the 🖱 SHOW steps while you say them.** Each scene says exactly what to click and where to point your cursor.

**Pitch in one line:** *Spend SaaSquatch credits only on owners who'll actually sell.*

---

## Before you record (5 min)

1. **Open three things and leave them open:**
   - Window 1: `cd "C:\Users\Shreyas\Desktop\capre capital\buy-build-score\api"` → `uv run uvicorn app.main:app --port 8000`
   - Window 2: `cd "C:\Users\Shreyas\Desktop\capre capital\buy-build-score\web"` → `pnpm start -p 3000`
   - Browser: `http://localhost:3000` (or your deployed URL).
   - Check `…/api/v1/healthz` shows `"ok":true,"db":true`.
2. **Pre-warm once:** type *dental practices near Columbus, OH*, press **Find targets**, wait until the tab title shows **✓**. This caches the data so the recorded run takes about 30 seconds.
3. Browser window **1440 px wide**, **light theme** (sun/moon icon, top right), one tab, bookmarks bar hidden, zoom 100%. Close everything else (memory is tight on this machine).
4. **If anything breaks mid-recording:** go to `http://localhost:3000/runs/demo`. Same data, loads instantly, needs no keys. Cut and continue from Scene 3.

---

## Scene 1 — The problem (0:00–0:15)

🖱 **SHOW:** the landing page. Hold still. Slowly move the cursor over the big headline *"Spend SaaSquatch credits only on owners who'll actually sell."*

🗣 **SAY:** "If you're searching for a business to buy, SaaSquatch credits cost about 39 cents for every enriched lead. Most of those leads are businesses whose owner will never sell. This tool sits before that step and ranks them first, so you only spend credits where it counts."

---

## Scene 2 — Start a search (0:15–0:30)

🖱 **SHOW:**
1. Click the **"Describe your thesis"** box and type **`dental practices near Columbus, OH`**.
2. **Point at** the *Industry* and *Location* fields below as they fill in by themselves.
3. **Point at** the three cards: *Searcher · SDR · Caprae*. Leave **Searcher** selected.
4. Click the purple **Find targets** button.

🗣 **SAY:** "I type one sentence and it fills in the fields. I'm a searcher, so durability and the chance the owner sells count most. A sales rep would pick SDR and weight digital gaps instead."

---

## Scene 3 — Leads stream in (0:30–0:50)

🖱 **SHOW:**
1. **Point at** the progress chips at the top right (*Discovered → Reading → Done*) and the timer next to them.
2. **Point at** the table as rows appear one by one. Let them fill in.
3. When it's done, **point at** the thin banner under the header: *"4 sites asked crawlers to stay out (robots.txt) — respected and labelled."*
4. **Point at** one amber warning icon in the right-hand *Contact* column.

🗣 **SAY:** "Businesses come from OpenStreetMap, which is free. Then each business's own website is read politely: it follows robots.txt, one request a second per site, four pages at most. Rows appear the moment each one is scored. If a site says no crawlers, we respect it and label it. If a business has no readable website, it's scored from its listing only and marked thin data. We never guess."

---

## Scene 4 — Why is this one ranked here? (0:50–1:25)  ← the key scene

🖱 **SHOW:**
1. Click the first row, **Fixari Family Dental** (tier **B**, score **57**). A panel slides in from the right.
2. **Point at** the owner line: *"Mark and Shayne Fixari — found on /about-us"*.
3. **Point at** the three section headings one after another: *Durability 89 · Succession 41 · Digital upside 41*.
4. In *Durability*, **hover** over **Years in business** and hold for 2 seconds. A box shows the exact sentence from their website.
5. In *Succession*, click the small **↗ arrow** next to **Founder / family-run**. Their real page opens in a new tab. Show it for 2 seconds, then close the tab.
6. **Point at** the greyed rows (*"0"*, like *Not hiring*, *Exit language*).

🗣 **SAY:** "Fixari Family Dental. Founded in 1987, family-owned, run by Mark and Shayne Fixari. Every point has a source. If I hover, this is the exact sentence on their site that earned it. And if I click the arrow, that's their actual page. The greyed rows are things we looked for and didn't find. Nothing is made up."

---

## Scene 5 — Re-weight without re-crawling (1:25–1:40)

🖱 **SHOW:**
1. Press **Esc** to close the panel.
2. In the left sidebar under **Weights**, click **SDR**. **Point at** the **Score** column numbers changing and the **A / B / C** counts at the top of the sidebar.
3. Click **Searcher** again.
4. Drag the **Digital upside** slider to the right slowly and back, still pointing at the Score numbers and the tier counts as they move.

🗣 **SAY:** "I can change what 'good' means. Switch to SDR and the list re-ranks instantly. Nothing is re-crawled, it's all in the browser."

---

## Scene 6 — Take it with you (1:40–1:55)

🖱 **SHOW:**
1. Tick the checkboxes on the **top 4 rows**.
2. **Point at** the bar that appears at the bottom: *"4 selected · Export CSV · Push to HubSpot"*.
3. Click **Export CSV**. A toast appears: *"Exported 4 leads."*

🗣 **SAY:** "I pick the leads worth a credit and export them in SaaSquatch's format, with scores, owner name and the top three pieces of evidence. There's a HubSpot push too."

---

## Scene 7 — Close (1:55–2:00)

🖱 **SHOW:** scroll the landing page to the **"How it scores"** section (click *Scoring model*, top right), then rest on the three cards.

🗣 **SAY:** "Public data only, free tiers all the way through, and every score explains itself. Spend credits only on owners who'll actually sell."

---

## If a judge asks

| Question | Answer |
| --- | --- |
| **Why is there no A-tier in the demo?** | A needs a rare mix: family-run, one named leader, a stale site, not hiring, 25+ years. Modern dental sites rarely look like that, and free data has no review signals. The model is strict on purpose. Top lead here is B. |
| **How do you stop the AI making up owners?** | It's the last resort, only when rules find nothing. A name is kept only if it appears word-for-word in a quote that is itself in the page. Otherwise it's thrown away. Tested with a planted "ignore your instructions" line. |
| **Is the scraping ethical?** | robots.txt, an honest user-agent, one request a second per site, four pages max, no LinkedIn, no logins, no email guessing, no age guessing. |
| **What isn't built?** | Owner-email drafting was cut. HubSpot push is built and tested on mocks but not yet against a live HubSpot account. JavaScript-only sites aren't rendered. |
| **What does it cost?** | $0 to run: Vercel Hobby, Neon Free and free AI tiers. |

## Numbers you can quote

- Demo: **60 found → 7 chains removed → 59 scored.** 21 sites read in full, 4 blocked by robots.txt, 29 listings with no website.
- Speed: **27–57 s** with warm caches. A cold run took 163 s because the free public map servers were busy.
- AI: only **4–5 calls per 60 businesses**; everything else is plain rules.
- Quality: **142 unit + 6 database + 11 frontend tests**, all passing.
- Owners found: **9 of 59**, every one quote-checked.
