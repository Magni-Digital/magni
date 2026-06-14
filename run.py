#!/usr/bin/env python3
"""
run.py — Magni 2.0, the whole tool in one command.

  python3 run.py

Reads practices from inbox.csv + the CRM xlsx, then for each:
  fetch the homepage → detect objective weaknesses (each individually true)
  → keep only sites with >=1 real weakness → draft ONE grounded observation
  → verify the contact email → dedupe against every practice ever surfaced
  → write the day's 20-30 best to public/data.json (+ public/daily-list.csv).

Nothing is ever sent. Almendra opens the review page, checks each observation is
true, rewrites it in her voice, and sends it herself.

Options:
  --target N      max practices to surface today (default 30)
  --min N         warn if fewer than N qualify (default 20)
  --limit N       qualify only the first N candidates (testing)
  --no-broken-links   skip the per-site dead-link probe (faster)
  --dry-run       qualify + print, but don't write data.json or touch seen.json
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from pipeline import dedupe as D
from pipeline import signals as S
from pipeline import verify_email as V
from pipeline.fetch import fetch_site, harvest_email
from pipeline.ingest import load_candidates
from pipeline.observe import observe_all
from pipeline.score import compute, rank_key

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "inbox.csv"
CRM = ROOT / "Magni_Digital_CRM.xlsx"
STATE = ROOT / "state"
SEEN_PATH = STATE / "seen.json"
EMAIL_CACHE = STATE / "email_cache.json"
DISPOS_PATH = STATE / "dispositions.json"   # exported from the review page
PUBLIC = ROOT / "public"
DATA_PATH = PUBLIC / "data.json"
CSV_PATH = PUBLIC / "daily-list.csv"

EMAIL_VERIFIED_LABEL = {
    "deliverable": "Verified", "mx_ok": "Verified", "risky": "Risky",
    "undeliverable": "Bad", "unverified": "Unverified", "no_email": "No email",
}


_HEAD_UA = "Mozilla/5.0 (compatible; magni-2.0 link checker)"


def _head(url, timeout=6):
    try:
        r = requests.head(url, headers={"User-Agent": _HEAD_UA}, timeout=timeout,
                          allow_redirects=True)
        return r.status_code
    except requests.RequestException:
        return None


def qualify_one(cand, *, current_year, do_broken):
    """Fetch + run detectors + score. Mutates cand with evidence/qualify fields.
    Holds (does not fabricate findings for) sites that are unreachable, blocked,
    or empty JS shells — absence of HTML is not evidence of a weak site."""
    if cand.get("website_status") == "none":
        nf = S._finding("no_website", "No website at all", S.HIGH,
                        f"{cand.get('name','This practice')} has no website at all — "
                        f"anyone searching for them online finds nothing.")
        return _attach(cand, [nf], {"final_url": "", "secure": None}, "qualified", "en")

    if not cand.get("domain"):
        return _attach(cand, [], {}, "needs_domain", "en")

    ctx = fetch_site(cand["domain"])
    lang = "es" if ctx.get("lang") == "es" else "en"
    if not ctx.get("reachable"):
        return _attach(cand, [], _meta(ctx), "unreachable", lang)
    status = ctx.get("status")
    if isinstance(status, int) and status >= 400:
        return _attach(cand, [], _meta(ctx), "blocked", lang)
    if ctx.get("near_empty"):
        return _attach(cand, [], _meta(ctx), "needs_render", lang)

    # free email harvest from the site (only if we don't already have one) — fills
    # the gap so Clay's paid waterfall is needed only where the site shows nothing
    if not (cand.get("email") or "").strip():
        em = harvest_email(ctx, fetch_contact=do_broken)  # reuse the broken-links flag to gate the extra /contact GET
        if em:
            cand["email"] = em
            cand["email_source"] = "site"

    findings = [
        S.detect_no_ssl(ctx, cand),
        S.detect_no_viewport(ctx, cand),
        S.detect_stale_copyright(ctx, cand, current_year),
        S.detect_no_booking(ctx, cand),
        S.detect_builder(ctx, cand),
        S.detect_thin_site(ctx, cand),
        S.detect_no_cta(ctx, cand),
    ]
    if do_broken:
        findings.append(S.detect_broken_links(ctx, cand, fetcher=_head))
    present = [f for f in findings if f]
    verdict = compute(present)
    return _attach(cand, present, _meta(ctx),
                   "qualified" if verdict["qualified"] else "not_qualified", lang, verdict)


def _meta(ctx):
    return {"final_url": ctx.get("final_url", ""), "secure": ctx.get("secure"),
            "status": ctx.get("status"), "elapsed_ms": ctx.get("elapsed_ms")}


def _attach(cand, present, meta, qualify_status, lang, verdict=None):
    verdict = verdict or compute(present)
    cand.update({
        "evidence": present,
        "weakness_score": verdict["weakness_score"],
        "qualified": qualify_status == "qualified",
        "qualify_status": qualify_status,
        "site_high_count": verdict["high_count"],
        "site_med_count": verdict["med_count"],
        "site_meta": meta,
        "lang": lang,
    })
    return cand


HS_CANDIDATES = STATE / "hubspot_candidates.json"
ENRICHED_KEEPERS = STATE / "keepers_enriched.csv"


def _load_enriched_keepers():
    """Keeper practices after bulk enrichment (Apollo/Clay/ZoomInfo export).
    Drop the file at state/keepers_enriched.csv with flexible headers — any of:
      hs_company_id, company|name, domain|website, email, contact_name,
      city, state, practice_type
    Each becomes a candidate (re-qualified fresh), carrying hs_company_id so a
    later confirmation can write back to the right HubSpot record."""
    import csv
    if not ENRICHED_KEEPERS.exists():
        return []
    out = []
    with open(ENRICHED_KEEPERS, encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.DictReader(fh):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            site = r.get("domain") or r.get("website") or ""
            from pipeline.normalize import domain_from_url
            dom = domain_from_url(site)
            if not dom:
                continue   # no website → can't qualify a site; skip (it's a no-site lead to confirm)
            out.append({
                "name": r.get("company") or r.get("name") or "",
                "domain": dom, "website_raw": site if site.startswith("http") else "https://" + dom,
                "website_status": "unknown",
                "practice_type": r.get("practice_type", ""),
                "location": (r.get("city", "") + " " + r.get("state", "")).strip(),
                "contact_name": r.get("contact_name", ""), "role": r.get("role", ""),
                "email": r.get("email", ""), "source": "HubSpot+enriched",
                "hs_company_id": r.get("hs_company_id", ""),
                "domain_provisional": False,
            })
    return out


def _load_hubspot_candidates():
    """HubSpot keeper practices whose domain was resolved by enrichment. Loaded
    as raw candidates (re-qualified fresh each run). Carries the provisional flag
    + hs_company_id so the review page can flag 'confirm domain' and a later
    operator confirmation can write back to the right HubSpot record."""
    if not HS_CANDIDATES.exists():
        return []
    try:
        rows = json.loads(HS_CANDIDATES.read_text())
    except ValueError:
        return []
    out = []
    for r in rows:
        if not r.get("domain"):
            continue
        out.append({
            "name": r.get("name", ""), "domain": r["domain"],
            "website_raw": r.get("website_raw") or "https://" + r["domain"],
            "website_status": "unknown",
            "practice_type": r.get("practice_type", ""),
            "location": r.get("location", ""),
            "contact_name": r.get("contact_name", ""), "role": r.get("role", ""),
            "email": r.get("email", ""), "source": "HubSpot",
            "hs_company_id": r.get("hs_company_id", ""),
            "domain_provisional": bool(r.get("domain_provisional")),
        })
    return out


def _load_dispositions():
    if DISPOS_PATH.exists():
        try:
            data = json.loads(DISPOS_PATH.read_text())
            return data if isinstance(data, list) else data.get("dispositions", [])
        except (ValueError, AttributeError):
            return []
    return []


def to_entry(rec, queue_date):
    return {
        "name": rec.get("name", ""),
        "practice_type": rec.get("practice_type", "") or "practice",
        "domain": rec.get("domain", ""),
        "website_raw": rec.get("website_raw", "") or ("https://" + rec["domain"] if rec.get("domain") else ""),
        "location": rec.get("location", ""),
        "contact": {"name": rec.get("contact_name", ""), "role": rec.get("role", ""),
                    "email": rec.get("email", "")},
        "weakness_score": rec.get("weakness_score", 0),
        "site_high_count": rec.get("site_high_count", 0),
        "evidence": rec.get("evidence", []),
        "draft_observation": rec.get("draft_observation", ""),
        "observation_cited_signal": rec.get("observation_cited_signal", ""),
        "observation_source": rec.get("observation_source", ""),
        "observation_lang": rec.get("observation_lang", "en"),
        "email_verified": rec.get("email_verified", "no_email"),
        "verified_email": rec.get("verified_email", ""),
        "source": rec.get("source", ""),
        "domain_provisional": bool(rec.get("domain_provisional")),
        "hs_company_id": rec.get("hs_company_id", ""),
        "dedupe_key": rec.get("dedupe_key") or D.key_for(rec),
        "queue_date": queue_date,
    }


def write_csv(entries):
    import csv
    cols = ["Company", "Contact Name", "Role", "Website URL",
            "Site Observation (1 line)", "Email", "Email Verified?", "Source",
            "Status", "Next Action"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for e in entries:
            w.writerow([
                e["name"], e["contact"]["name"], e["contact"]["role"], e["website_raw"],
                e["draft_observation"], e["contact"]["email"] or e["verified_email"],
                EMAIL_VERIFIED_LABEL.get(e["email_verified"], e["email_verified"]),
                e["source"], "Not Contacted",
                "Verify email + send 1st" if e["email_verified"] in ("no_email", "unverified", "undeliverable")
                else "Send 1st email",
            ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=30)
    ap.add_argument("--min", type=int, default=20)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-broken-links", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    queue_date = now.date().isoformat()
    current_year = now.year

    # 1) ingest — inbox.csv + CRM xlsx + any HubSpot-resolved candidates
    cands, prior = load_candidates(INBOX, CRM)
    hs_cands = _load_hubspot_candidates() + _load_enriched_keepers()
    cands += hs_cands
    if args.limit:
        cands = cands[:args.limit]
    print(f"▸ ingested {len(cands)} candidates to qualify "
          f"({len(hs_cands)} from HubSpot, "
          f"{len(prior)} already-contacted CRM rows folded into seen-set)")

    # 2) qualify
    for i, c in enumerate(cands, 1):
        qualify_one(c, current_year=current_year, do_broken=not args.no_broken_links)
        flag = "✓" if c["qualified"] else " "
        print(f"  [{i:3d}/{len(cands)}] {flag} {c['qualify_status']:13s} "
              f"score={c['weakness_score']:3d} hi={c['site_high_count']} {c['name'][:34]}")
    qst = Counter(c["qualify_status"] for c in cands)
    print(f"▸ qualify status: {dict(qst)}")

    # 3) observe (one grounded sentence per qualified site)
    n_claude, n_fb = observe_all(cands)
    bad = [c for c in cands if c.get("qualify_status") == "qualified"
           and c.get("observation_cited_signal") not in {f["id"] for f in c.get("evidence", [])}]
    print(f"▸ observations: claude={n_claude} fallback={n_fb}  "
          f"grounding gate: {'✅ all cite a checked finding' if not bad else f'❌ {len(bad)} ungrounded'}")

    # 4) verify emails
    dist = V.verify_all(cands, EMAIL_CACHE)
    print(f"▸ email verification: {dist}")

    # 5) dedupe — fold dispositions, then select qualified & not-yet-seen
    seen = D.load_seen(SEEN_PATH)
    dispositions = prior + _load_dispositions()
    applied = D.apply_dispositions(seen, dispositions, now_iso)
    D.annotate(cands, seen, now)
    eligible = [c for c in cands if c.get("qualify_status") == "qualified"
                and not c.get("seen_excluded") and c.get("dedupe_key")]
    eligible.sort(key=rank_key)
    queued = eligible[:args.target]
    print(f"▸ dedupe: {len(seen)} known keys, {applied} dispositions folded → "
          f"qualified={sum(1 for c in cands if c['qualified'])} "
          f"eligible={len(eligible)} surfacing={len(queued)}")
    if len(queued) < args.min:
        print(f"  ⚠ only {len(queued)} today (< target {args.min}) — surfacing fewer "
              f"rather than padding with weak findings.")

    entries = [to_entry(c, queue_date) for c in queued]

    if args.dry_run:
        print("▸ --dry-run: not writing data.json / seen.json.")
        for e in entries[:10]:
            print(f"    · {e['name'][:32]:32s} hi={e['site_high_count']} "
                  f"score={e['weakness_score']}  “{e['draft_observation'][:60]}”")
        return

    # 6) persist: mark surfaced, write outputs
    D.mark_surfaced(seen, queued, now_iso)
    D.save_seen(SEEN_PATH, seen)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({"generated": now_iso, "queue_date": queue_date,
                                     "count": len(entries), "practices": entries},
                                    indent=2, ensure_ascii=False))
    write_csv(entries)
    print(f"✅ wrote {DATA_PATH.relative_to(ROOT)} ({len(entries)} practices)")
    print(f"✅ wrote {CSV_PATH.relative_to(ROOT)}")
    print(f"✅ updated {SEEN_PATH.relative_to(ROOT)} ({len(seen)} known keys)")


if __name__ == "__main__":
    main()
