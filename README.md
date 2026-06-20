# Magni 2.0 — the "one true thing" tool

A simple tool for the part of outreach that's actually hard: **picking practices
with weak websites and noticing the one specific, true thing wrong with each
one.** You do the sending.

It does four things, and nothing else:

1. **Qualify** — fetches each practice's homepage and runs objective checks (no
   HTTPS, not mobile-ready, stale copyright, thin/placeholder page, no online
   booking, dead links, outdated CMS…). A practice only makes the list if it has
   at least one *real, checked* weakness.
2. **Observe** — drafts **one** opening line per site, grounded in a checked
   finding. A draft can never claim something the checks didn't actually find
   (the grounding gate), so you're never handed a plausible-but-false opener.
3. **Verify email** — runs each contact email through syntax → MX → optional
   deliverability API, and labels it (verified / risky / bad / no email).
4. **Dedupe** — remembers every practice ever surfaced or sent, so the same one
   never lands on your list twice.

The output is a **review page** you open in a browser: the day's 20–30 qualified
practices, each with its evidence and an editable observation. You confirm it's
true, rewrite it in your voice, and send it yourself. **Nothing is ever sent
automatically.**

---

## Daily use (Almendra) — just open the page

Go to the review URL (**atlas-magni.pages.dev**). A fresh set of practices is
waiting each morning. You don't run anything — the list refreshes itself.

**Two tabs at the top:**
- **Today's queue** — practices that qualified on a real, checked website weakness,
  each with one drafted observation. This is your daily work.
- **Research · no site** — practices the enrichment couldn't find a website for.
  Open their LinkedIn, check for a site, and write your own line (no site at all
  is a strong opener).

**Filters** (the bar under the tabs): filter by name, **vertical**, **city**, or
**email status** (has email / needs email). Use these to batch similar outreach.

**Working a card:**
1. Read the **Checked findings** — the true things wrong with their site.
2. Read the **draft observation**. **Open their site (and LinkedIn) and confirm
   it's actually true**, then rewrite it in your own voice in the box.
3. **Copy** the observation (and **Copy email** if shown), paste into your own
   email, and send it. *The tool never sends anything.*
4. Click **Mark sent** (or **Skip**); it won't appear again.
5. Hit **Download CSV** — the day's work (your edited observations, notes, sent
   status) exports in the spreadsheet's exact columns. Paste into the Magni
   Digital CRM sheet. **That sheet is the CRM.**

Badges to know: **✓ email verified** (good to use), **no email** (you'll need to
find it / it's on the Research tab), **⚠ confirm site** (the website was
auto-matched — double-check it's really theirs before sending).

**More on each card:**
- **Notes** — a box for your own notes; saved in the tool and included in Download CSV.
- **More info ▾** — expands employees, industry, founded, annual revenue, LinkedIn
  followers, full description.
- **(Research tab) Add their website** — found their site via LinkedIn? Paste it;
  it's saved and included in your CSV (add it to `inbox.csv` to have it qualified).

**The queue is a rolling working set:** you won't lose leads you don't get to.
Sent ones retire; skipped ones return in 30 days; anything you don't touch stays
and comes back next time. There are hundreds queued behind today's view.

**Adding leads:** drop new finds into `inbox.csv` (or a fresh Clay batch via
`build_enriched.py`) and the next run qualifies them.

---

## Running the pipeline

```bash
pip install -r requirements.txt        # one time
python3 run.py                         # qualify → observe → verify → dedupe
```

Writes `public/data.json` (the review page reads it) and `public/daily-list.csv`.

Useful flags:

| flag | effect |
|------|--------|
| `--target 30` | max practices to surface today (default 30) |
| `--min 20` | warn if fewer than N qualify (default 20) |
| `--limit 10` | qualify only the first N candidates (testing) |
| `--no-broken-links` | skip the per-site dead-link probe (faster) |
| `--dry-run` | qualify + print, write nothing |

**Optional, better observations.** Set `ANTHROPIC_API_KEY` and the observation
becomes a one-line, human draft written by Claude (still grounded in the checked
fact — same gate). Without a key it uses a true template sentence, so the tool
runs fine either way. Spanish-language sites get a Spanish observation
automatically.

**Optional, better email verification.** Set `EMAIL_VERIFY_API_URL` +
`EMAIL_VERIFY_API_KEY` (any ZeroBounce-style endpoint) for true deliverability.
Without it, MX lookup still catches dead domains. `pip install dnspython` makes
MX lookups reliable.

---

## Hosting (so Almendra can just open a URL)

The review page is **static** — the whole `public/` folder is the site. Any
static host works:

- **Cloudflare Pages** (replaces the old atlas) — connect this repo, build
  command: *none*, output directory: `public`. Or `wrangler pages deploy public`.
- **Netlify** — drag the `public/` folder onto app.netlify.com/drop.
- **GitHub Pages** — serve `public/` from the repo.

To refresh the list, run `python3 run.py` and redeploy `public/` (the page is
just files). If you want it hands-off, run `run.py` on a daily schedule (cron, a
GitHub Action with `ANTHROPIC_API_KEY` as a secret, etc.) and commit the updated
`public/data.json`.

---

## Files

```
inbox.csv                 ← you add LinkedIn finds here
Magni_Digital_CRM.xlsx    ← your CRM; uncontacted "Pipeline" rows are also pulled in
run.py                    ← the whole pipeline, one command
pipeline/                 ← ingest · fetch · signals · score · observe · verify_email · dedupe
state/
  seen.json               ← every practice ever surfaced (the never-twice memory)
  dispositions.json       ← drop your exported sent/skipped here before a run
  email_cache.json        ← cached email checks (machine-local)
public/                   ← the review page (static site) + data.json + daily-list.csv
```

## Bringing in a new batch (Clay enrichment)

The CRM is the spreadsheet. There's no other system to maintain. New leads come
from a Sales Navigator scrape, enriched in Clay for **website + email**:

1. Scrape Sales Nav (see the target-market searches you've been using).
2. Enrich in **Clay** — company **domain/website** + **work email**. *(Don't
   bother with site-quality checks; Magni does that.)*
3. Drop the export in `Lists/`, run **`python3 build_enriched.py`** — it filters to
   ICP, dedupes, and writes `state/keepers_enriched.csv` (+ a `research_leads.csv`
   for no-website practices).
4. `python3 run.py` — qualifies, observes, verifies, dedupes → the daily queue.

For one-off finds, just add a row to `inbox.csv` (only `company` + `website`
required) and run.

## What it deliberately does NOT do

No auto-sending, no sequences, no external CRM, no scraping LinkedIn for you, no
dashboards or scoring of job titles. It does the judgment-heavy part —
qualification and one true observation — hands it to you to send, and exports the
day's work to your spreadsheet.
