#!/usr/bin/env python3
"""
build_enriched.py — turn a Clay company-enrichment export into Magni inputs.

Writes TWO files (carrying LinkedIn URLs + all enriched firmographics):
  state/keepers_enriched.csv  — rows WITH a domain → qualified by Magni (site check)
  state/research_leads.csv    — rows with NO domain → browsable "Research" list
                                (LinkedIn-first, for manual lookup; never auto-claimed)

Shared filters: company size <= 50, drop SaaS/app companies, dedupe.

  python3 build_enriched.py "Lists/<clay export>.csv"
  python3 build_enriched.py            # newest Lists/*export*.csv
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
SAAS_TLDS = (".io", ".app", ".ai", ".dev", ".tech", ".so", ".xyz", ".health")
SAAS_RE = re.compile(r"\b(app|saas|platform|software|fintech|healthtech|medtech|"
                     r"startup|api|mobile app|web app|marketplace|ai-powered|ai powered)\b", re.I)

# unified field -> Clay/source column
FIELDS = {
    "company": ("Name", "companyName"), "title": ("title",), "contact_name": ("fullName",),
    "person_linkedin": ("personLinkedinUrl",), "company_linkedin": ("companyLinkedinUrl",),
    "website": ("Website",), "employee_count": ("Employee Count",), "size": ("Size",),
    "industry": ("Industry",), "description": ("Description",), "founded": ("Founded",),
    "annual_revenue": ("Annual Revenue",), "follower_count": ("Follower Count",),
}
OUT_COLS = ["hs_company_id", "company", "domain", "website", "email", "contact_name",
            "title", "city", "state", "practice_type", "source", "person_linkedin",
            "company_linkedin", "employee_count", "size", "industry", "description",
            "founded", "annual_revenue", "follower_count"]


def g(row, field):
    for c in FIELDS.get(field, ()):
        if (row.get(c) or "").strip():
            return row[c].strip()
    return ""


def is_saas(name, domain, desc):
    return domain.endswith(SAAS_TLDS) or bool(SAAS_RE.search(f"{name} {desc}"))


def emp_ok(row):
    if (row.get("Size") or "").strip() in BIG_SIZES:
        return False
    try:
        return int(float(row.get("Employee Count") or 0)) <= 50
    except (ValueError, TypeError):
        return True


def loc(row):
    return (row.get("Locality") or row.get("location") or "").replace(", États-Unis", "").strip()


def rec(row, domain):
    l = loc(row)
    name = g(row, "company")
    return {
        "hs_company_id": "", "company": name, "domain": domain,
        "website": g(row, "website") or ("https://" + domain if domain else ""),
        "email": "", "contact_name": g(row, "contact_name"), "title": g(row, "title"),
        "city": l.split(",")[0].strip(), "state": (l.split(",")[1].strip() if "," in l else ""),
        "practice_type": classify(f"{name} {g(row,'industry')} {g(row,'description')[:200]}"),
        "source": "SalesNav/Clay", "person_linkedin": g(row, "person_linkedin"),
        "company_linkedin": g(row, "company_linkedin"), "employee_count": g(row, "employee_count"),
        "size": g(row, "size"), "industry": g(row, "industry"),
        "description": g(row, "description")[:280], "founded": g(row, "founded"),
        "annual_revenue": g(row, "annual_revenue"), "follower_count": g(row, "follower_count"),
    }


def _backfill_emails(qualifiable):
    """Fold Work Email from a waterfall-enriched export (Lists/*waterfall-enriched*.csv)
    into rows that had none, matched by domain."""
    wf = glob.glob("Lists/*waterfall-enriched*.csv")
    if not wf:
        return 0
    m = {}
    for r in csv.DictReader(open(wf[0], encoding="utf-8-sig", errors="replace")):
        dom = domain_from_url(r.get("domain") or r.get("Domain") or "")
        em = (r.get("Work Email") or r.get("email") or r.get("Email") or "").strip()
        if dom and em:
            m[dom] = em
    n = 0
    for rec_ in qualifiable:
        if not rec_["email"] and rec_["domain"] in m:
            rec_["email"] = m[rec_["domain"]]; n += 1
    return n


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else max(
        glob.glob("Lists/*export*.csv"), key=lambda p: Path(p).stat().st_mtime)
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig", errors="replace")))
    print(f"source: {src}  ({len(rows)} rows)")

    qualifiable, research, drop = [], [], Counter()
    seen_dom, seen_name = set(), set()
    for r in rows:
        name = g(r, "company")
        desc = g(r, "description")[:300]
        dom = domain_from_url(r.get("Domain") or r.get("Website") or "")
        if dom and is_saas(name, dom, desc):
            drop["saas/app"] += 1; continue
        if not emp_ok(r):
            drop[">50 employees"] += 1; continue
        if dom:
            if dom in seen_dom:
                drop["dup domain"] += 1; continue
            seen_dom.add(dom)
            qualifiable.append(rec(r, dom))
        else:
            key = (name.lower(), loc(r).lower())
            if key in seen_name or not name:
                drop["dup/blank no-domain"] += 1; continue
            seen_name.add(key)
            research.append(rec(r, ""))

    n_bf = _backfill_emails(qualifiable)

    (ROOT / "state").mkdir(exist_ok=True)
    with open(ROOT / "state" / "keepers_enriched.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLS); w.writeheader(); w.writerows(qualifiable)
    rcols = [c for c in OUT_COLS if c not in ("domain", "website", "email", "hs_company_id")]
    with open(ROOT / "state" / "research_leads.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rcols, extrasaction="ignore"); w.writeheader(); w.writerows(research)

    print(f"qualifiable (has domain): {len(qualifiable)}  → state/keepers_enriched.csv")
    print(f"waterfall emails backfilled: {n_bf}")
    print(f"research (no domain, LinkedIn): {len(research)}  → state/research_leads.csv")
    print(f"dropped: {dict(drop)}")


if __name__ == "__main__":
    main()
