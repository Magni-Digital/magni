#!/usr/bin/env python3
"""
build_enriched.py — turn a Clay company-enrichment export into the Magni-ready
state/keepers_enriched.csv (and a needs_domain_or_waterfall.csv side-list).

Filters applied:
  - must have a resolvable domain (else → side-list, can't qualify a site)
  - company size <= 50 employees (drops 51-200+)
  - drop obvious SaaS / app / startup companies (not website-buying practices)
  - dedupe by domain (keep first)
  - infer practice_type from name + industry + description

  python3 build_enriched.py "Lists/<clay export>.csv"
  python3 build_enriched.py            # auto-picks the newest Lists/*export*.csv
"""
import csv
import glob
import re
import sys
from collections import Counter
from pathlib import Path

from pipeline.normalize import domain_from_url
from pipeline.ingest import classify

ROOT = Path(__file__).resolve().parent
csv.field_size_limit(100_000_000)

BIG_SIZES = {"51-200 employees", "201-500 employees", "501-1,000 employees",
             "1,001-5,000 employees", "5,001-10,000 employees", "10,001+ employees"}
# app-y TLDs that signal a software product, not a local practice
SAAS_TLDS = (".io", ".app", ".ai", ".dev", ".tech", ".so", ".xyz", ".health")
# SaaS/startup language in name or description (word-ish boundaries)
SAAS_RE = re.compile(
    r"\b(app|saas|platform|software|fintech|healthtech|medtech|startup|api|"
    r"mobile app|web app|marketplace|ai-powered|ai powered|b2b software)\b", re.I)


def is_saas(name, domain, desc):
    if domain.endswith(SAAS_TLDS):
        return True
    blob = f"{name} {desc}"
    # 'app' alone is noisy; require it as a standalone product word
    return bool(SAAS_RE.search(blob))


def emp_ok(row):
    if (row.get("Size") or "").strip() in BIG_SIZES:
        return False
    try:
        if int(float(row.get("Employee Count") or 0)) > 50:
            return False
    except (ValueError, TypeError):
        pass
    return True


def locality(row):
    return (row.get("Locality") or row.get("location") or "").replace(", États-Unis", "").strip()


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else max(glob.glob("Lists/*export*.csv"), key=lambda p: Path(p).stat().st_mtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig", errors="replace")))
    print(f"source: {src}  ({len(rows)} rows)")

    ready, nodomain, drop = [], [], Counter()
    seen = set()
    for r in rows:
        name = r.get("Name") or r.get("companyName", "")
        desc = (r.get("Description") or "")[:300]
        dom = domain_from_url(r.get("Domain") or r.get("Website") or "")
        if not dom:
            nodomain.append(r); continue
        if is_saas(name, dom, desc):
            drop["saas/app"] += 1; continue
        if not emp_ok(r):
            drop[">50 employees"] += 1; continue
        if dom in seen:
            drop["dup domain"] += 1; continue
        seen.add(dom)
        loc = locality(r)
        ready.append({
            "hs_company_id": "", "company": name, "domain": dom, "email": "",
            "contact_name": r.get("fullName", ""), "title": r.get("title", ""),
            "city": loc.split(",")[0].strip(),
            "state": (loc.split(",")[1].strip() if "," in loc else ""),
            "practice_type": classify(f"{name} {r.get('Industry','')} {desc}"),
            "source": "SalesNav/Clay",
        })

    cols = ["hs_company_id", "company", "domain", "email", "contact_name", "title",
            "city", "state", "practice_type", "source"]
    (ROOT / "state").mkdir(exist_ok=True)
    with open(ROOT / "state" / "keepers_enriched.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(ready)
    with open(ROOT / "Lists" / "needs_domain_or_waterfall.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["companyName", "title", "fullName", "location", "industry_fr"])
        for r in nodomain:
            w.writerow([r.get("companyName", ""), r.get("title", ""), r.get("fullName", ""),
                        r.get("location", ""), r.get("industry_fr", "")])

    print(f"READY for Magni: {len(ready)}  → state/keepers_enriched.csv")
    print(f"no domain (manual/waterfall): {len(nodomain)}  → Lists/needs_domain_or_waterfall.csv")
    print(f"dropped: {dict(drop)}")
    print(f"practice_type mix: {dict(Counter(r['practice_type'] or 'unclassified' for r in ready).most_common(12))}")


if __name__ == "__main__":
    main()
