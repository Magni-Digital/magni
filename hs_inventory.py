#!/usr/bin/env python3
"""
hs_inventory.py — read-only snapshot of what's in HubSpot.

Run BEFORE pruning anything. Reports counts, which fields are populated (does a
record even have a website to qualify?), and how far the data drifts from
Magni's ICP — by city, employee band, industry, and (for contacts) job title.
Writes nothing to HubSpot.

  python3 hs_inventory.py
  python3 hs_inventory.py --max 3000     # cap records scanned per object
"""
import argparse
from collections import Counter

from pipeline.hubspot import HubSpot

COMPANY_PROPS = ["name", "domain", "website", "city", "state", "country",
                 "numberofemployees", "industry", "lifecyclestage",
                 "hs_object_source_label", "createdate"]
CONTACT_PROPS = ["email", "firstname", "lastname", "jobtitle", "company",
                 "city", "state", "hs_linkedin_url", "lifecyclestage",
                 "hs_object_source_label", "createdate"]

# Magni ICP target cities (lowercased), for a quick in/out tally.
ICP_CITIES = {"austin", "dallas", "denver", "nashville", "phoenix", "portland",
              "seattle", "ciudad de méxico", "mexico city", "cdmx", "guadalajara",
              "monterrey", "querétaro", "queretaro", "mérida", "merida", "puebla",
              "cancún", "cancun", "playa del carmen"}


def _fill(rows, prop):
    n = sum(1 for r in rows if (r["properties"].get(prop) or "").strip())
    return n, (100 * n // len(rows) if rows else 0)


def _top(rows, prop, k=12):
    c = Counter((r["properties"].get(prop) or "—").strip().lower() for r in rows)
    return c.most_common(k)


def _emp_band(v):
    try:
        n = int(float(v))
    except (ValueError, TypeError):
        return "unknown"
    if n <= 4:
        return "1-4 (below ICP)"
    if n <= 50:
        return "5-50 (ICP)"
    if n <= 200:
        return "51-200"
    return "200+"


def report(label, rows, props):
    print(f"\n{'='*64}\n{label}: {len(rows)} records scanned\n{'='*64}")
    print("  field fill rates:")
    for p in props:
        n, pct = _fill(rows, p)
        print(f"    {p:26s} {pct:3d}%  ({n})")

    cities = [(r["properties"].get("city") or "").strip().lower() for r in rows]
    in_icp = sum(1 for c in cities if c in ICP_CITIES)
    print(f"  in an ICP target city: {in_icp}/{len(rows)} "
          f"({100*in_icp//len(rows) if rows else 0}%)")

    print("  top cities:")
    for v, n in _top(rows, "city"):
        print(f"    {n:5d}  {v}")

    if "numberofemployees" in props:
        bands = Counter(_emp_band(r["properties"].get("numberofemployees")) for r in rows)
        print("  employee bands:", dict(bands))
        print("  top industries:")
        for v, n in _top(rows, "industry"):
            print(f"    {n:5d}  {v}")
    if "jobtitle" in props:
        print("  top job titles:")
        for v, n in _top(rows, "jobtitle"):
            print(f"    {n:5d}  {v}")

    # how many are actually qualifiable (have a website/domain)?
    if "domain" in props or "website" in props:
        has_site = sum(1 for r in rows
                       if (r["properties"].get("domain") or r["properties"].get("website") or "").strip())
        print(f"  have a website/domain (qualifiable): {has_site}/{len(rows)} "
              f"({100*has_site//len(rows) if rows else 0}%)")

    created = sorted((r["properties"].get("createdate") or "")[:10] for r in rows if r["properties"].get("createdate"))
    if created:
        print(f"  created span: {created[0]} → {created[-1]}")
        print("  created by day (top):")
        for v, n in Counter(created).most_common(6):
            print(f"    {n:5d}  {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5000)
    args = ap.parse_args()

    hs = HubSpot()
    print("connected to HubSpot ✓")
    print(f"  contacts total:  {hs.count('contacts')}")
    print(f"  companies total: {hs.count('companies')}")

    companies = list(hs.iter_objects("companies", COMPANY_PROPS, max_records=args.max))
    report("COMPANIES", companies, COMPANY_PROPS)

    contacts = list(hs.iter_objects("contacts", CONTACT_PROPS, max_records=args.max))
    report("CONTACTS", contacts, CONTACT_PROPS)

    print("\n(read-only — nothing was changed in HubSpot)")


if __name__ == "__main__":
    main()
