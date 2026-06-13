#!/usr/bin/env python3
"""
hs_prune.py — score HubSpot against Magni's ICP and (optionally) archive off-target.

DEFAULTS TO PREVIEW (read-only). It buckets every contact + company into
keep / review / cut, shows counts + reasons + samples, and writes the full
proposal to state/prune_preview_*.csv so you can eyeball it.

Only with --live does it archive the `cut` bucket — and archive is a SOFT delete
(recoverable in HubSpot for 90 days). `review` is never touched automatically.

  python3 hs_prune.py                 # preview only
  python3 hs_prune.py --live          # archive the cut bucket (after you've seen the preview)
  python3 hs_prune.py --live --yes    # skip the confirm prompt
"""
import argparse
import csv
from collections import Counter
from pathlib import Path

from pipeline.hubspot import HubSpot
from pipeline import icp

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"

COMPANY_PROPS = ["name", "domain", "website", "city", "state"]
CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "company", "city",
                 "state", "hs_linkedin_url"]


def bucket_all(rows, scorer):
    out = {"keep": [], "review": [], "cut": []}
    for r in rows:
        verdict, reason = scorer(r["properties"])
        out[verdict].append((r, reason))
    return out


def _write_csv(path, buckets, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["verdict", "reason", "id"] + fields)
        for verdict in ("cut", "review", "keep"):
            for r, reason in buckets[verdict]:
                p = r["properties"]
                w.writerow([verdict, reason, r["id"]] + [(p.get(f) or "") for f in fields])


def summarize(label, buckets, fields, csv_path):
    total = sum(len(v) for v in buckets.values())
    print(f"\n{'='*60}\n{label}: {total} records\n{'='*60}")
    for v in ("keep", "review", "cut"):
        n = len(buckets[v])
        print(f"  {v:6s}: {n:5d}  ({100*n//total if total else 0}%)")
    print("  cut reasons:", dict(Counter(reason for _, reason in buckets["cut"])))
    print("  keep verticals:",
          dict(Counter(reason.split(' · ')[0] for _, reason in buckets["keep"]).most_common(8)))
    g = lambda p, k: (p.get(k) or "")
    print(f"  sample CUT (first 6):")
    for r, reason in buckets["cut"][:6]:
        p = r["properties"]
        who = (g(p, "company") or g(p, "name") or "—")
        print(f"    ✗ {who[:30]:30s} {g(p,'jobtitle')[:22]:22s} {g(p,'city')[:14]:14s} [{reason[:40]}]")
    print(f"  sample KEEP (first 6):")
    for r, reason in buckets["keep"][:6]:
        p = r["properties"]
        who = (g(p, "company") or g(p, "name") or "—")
        print(f"    ✓ {who[:30]:30s} {g(p,'jobtitle')[:22]:22s} {g(p,'city')[:14]:14s} [{reason[:40]}]")
    _write_csv(csv_path, buckets, fields)
    print(f"  → full proposal written to {csv_path.relative_to(ROOT)}")


def archive_cut(hs, object_type, buckets):
    cut = buckets["cut"]
    print(f"  archiving {len(cut)} {object_type} (soft delete, 90-day recovery)…")
    for i, (r, _) in enumerate(cut, 1):
        hs.archive(object_type, r["id"])
        if i % 50 == 0:
            print(f"    {i}/{len(cut)}")
    print(f"  ✅ archived {len(cut)} {object_type}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="archive the cut bucket")
    ap.add_argument("--yes", action="store_true", help="skip confirm prompt")
    ap.add_argument("--max", type=int, default=5000)
    args = ap.parse_args()

    hs = HubSpot()
    print("connected to HubSpot ✓ (preview = read-only)")

    companies = list(hs.iter_objects("companies", COMPANY_PROPS, max_records=args.max))
    contacts = list(hs.iter_objects("contacts", CONTACT_PROPS, max_records=args.max))
    cb = bucket_all(companies, icp.score_company)
    ub = bucket_all(contacts, icp.score_contact)

    summarize("COMPANIES", cb, COMPANY_PROPS, STATE / "prune_preview_companies.csv")
    summarize("CONTACTS", ub, CONTACT_PROPS, STATE / "prune_preview_contacts.csv")

    if not args.live:
        print("\nPREVIEW ONLY — nothing changed. Review the CSVs, then re-run with --live to archive the cut bucket.")
        return

    n_cut = len(cb["cut"]) + len(ub["cut"])
    if not args.yes:
        print(f"\nAbout to ARCHIVE {n_cut} records (soft delete). 'review' + 'keep' untouched.")
        if input("Type 'archive' to proceed: ").strip().lower() != "archive":
            print("Aborted."); return
    archive_cut(hs, "companies", cb)
    archive_cut(hs, "contacts", ub)
    print("\nDone. Archived records are recoverable in HubSpot for 90 days.")


if __name__ == "__main__":
    main()
