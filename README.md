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

## Daily workflow (Almendra)

1. Drop the practices you found on LinkedIn into **`inbox.csv`** — one row each.
   Only `company` and `website` are required; add `contact_name`, `role`,
   `email`, `location`, `vertical` when you have them.
2. Run the tool (see below) — or open the page if someone runs it for you.
3. Open the **review page**. For each card: check the observation is true on
   their site, tweak it, hit **Copy**, and send it from your own inbox.
4. Click **Mark sent** / **Skip** as you go.
5. Click **Export sent/skipped** at the end of the day → it downloads
   `dispositions.json`. Drop that file in **`state/`** before the next run so
   the practices you handled never come back.

`Download CSV` gives you the day's list in your CRM's exact columns, ready to
paste into the Magni Digital CRM pipeline.

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

## What it deliberately does NOT do

No auto-sending, no sequences, no CRM writes, no scraping LinkedIn for you, no
dashboards or scoring of job titles. It does the judgment-heavy part —
qualification and one true observation — and hands it to you to send.
