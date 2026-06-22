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

# unified field -> accepted source column names (matched case-insensitively, so
# both Clay exports and the simple uploaded template work)
FIELDS = {
    "company": ("Name", "companyName", "company"),
    "title": ("title", "Title", "role", "Role"),
    "contact_name": ("fullName", "contact_name", "Contact Name", "contact"),
    "email": ("Work Email", "email", "Email"),
    "website": ("Website", "website", "Domain", "domain", "Website URL", "url"),
    "person_linkedin": ("personLinkedinUrl", "person_linkedin", "linkedin"),
    "company_linkedin": ("companyLinkedinUrl", "company_linkedin"),
    "employee_count": ("Employee Count", "employee_count", "employees"),
    "size": ("Size", "size"), "industry": ("Industry", "industry", "vertical"),
    "description": ("Description", "description", "notes"),
    "founded": ("Founded", "founded"), "annual_revenue": ("Annual Revenue", "annual_revenue"),
    "follower_count": ("Follower Count", "follower_count"),
    "city": ("city", "City", "Locality"), "state": ("state", "State"),
}
OUT_COLS = ["hs_company_id", "company", "domain", "website", "email", "contact_name",
            "title", "city", "state", "practice_type", "source", "person_linkedin",
            "company_linkedin", "employee_count", "size", "industry", "description",
            "founded", "annual_revenue", "follower_count"]


def g(row, field):
    low = {(k or "").strip().lower(): v for k, v in row.items()}
    for c in FIELDS.get(field, ()):
        v = low.get(c.lower())
        if v and v.strip():
            return v.strip()
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
        "email": g(row, "email"), "contact_name": g(row, "contact_name"), "title": g(row, "title"),
        "city": g(row, "city") or l.split(",")[0].strip(),
        "state": g(row, "state") or (l.split(",")[1].strip() if "," in l else ""),
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


def _merge_into(path, new_rows, key_fn, cols):
    """Union new_rows into the CSV at path, deduped by key_fn. Existing rows win
    (preserves backfilled emails). Returns count of genuinely-new rows added."""
    existing = []
    if path.exists():
        existing = list(csv.DictReader(open(path, encoding="utf-8-sig", errors="replace")))
    seen = {key_fn(r) for r in existing}
    added = [r for r in new_rows if key_fn(r) not in seen and key_fn(r)]
    # de-dup the new additions among themselves too
    out, addseen = list(existing), set()
    for r in added:
        k = key_fn(r)
        if k in addseen:
            continue
        addseen.add(k); out.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out)
    return len(addseen)


def main():
    # Additive: process EVERY Clay export in Lists/ (or one passed explicitly), so
    # dropping a new batch in Lists/ adds to the pool rather than replacing it.
    # Dedupe-by-domain below collapses overlaps; seen.json retires worked leads.
    srcs = [sys.argv[1]] if len(sys.argv) > 1 else sorted(glob.glob("Lists/*export*.csv"))
    if not srcs:
        sys.exit("No Clay export found in Lists/ (expected a file matching *export*.csv).")
    rows = []
    for s in srcs:
        these = list(csv.DictReader(open(s, encoding="utf-8-sig", errors="replace")))
        rows += these
        print(f"source: {s}  ({len(these)} rows)")
    print(f"total input rows across {len(srcs)} file(s): {len(rows)}")

    qualifiable, research, drop = [], [], Counter()
    seen_dom, seen_name = set(), set()
    for r in rows:
        name = g(r, "company")
        desc = g(r, "description")[:300]
        dom = domain_from_url(g(r, "website"))
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

    # ADDITIVE: merge into the existing committed output (existing wins on dup, so
    # backfilled emails / prior data are preserved). Lets an uploaded batch ADD
    # leads without needing the original raw export present (e.g. in CI).
    kpath = ROOT / "state" / "keepers_enriched.csv"
    rpath = ROOT / "state" / "research_leads.csv"
    n_new_q = _merge_into(kpath, qualifiable, lambda r: r.get("domain", ""), OUT_COLS)
    rcols = [c for c in OUT_COLS if c not in ("domain", "website", "email", "hs_company_id")]
    n_new_r = _merge_into(rpath, research, lambda r: (r.get("company", "").lower(), r.get("city", "").lower()), rcols)

    print(f"qualifiable (has domain): {n_new_q} new → state/keepers_enriched.csv (merged)")
    print(f"waterfall emails backfilled: {n_bf}")
    print(f"research (no domain, LinkedIn): {n_new_r} new → state/research_leads.csv (merged)")
    print(f"dropped: {dict(drop)}")


if __name__ == "__main__":
    main()
