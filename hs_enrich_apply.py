#!/usr/bin/env python3
"""
hs_enrich_apply.py — take resolved domains for HubSpot keeper companies, qualify
their sites, and write CONFIRMED domains back to HubSpot.

Input: state/resolved_batch.json  — [{id, name, city, state, practice_type, domain, provisional}]
  (domains resolved by web search; `provisional` = not confidently theirs)

For each:
  - fetch + qualify the site, draft one grounded observation (existing pipeline)
  - write the domain back to the HubSpot company  ONLY if not provisional
    (never seed a guessed domain into the CRM)
  - emit the qualified ones to state/hubspot_candidates.json for the daily queue

Safe to re-run. Writes to HubSpot only for confirmed, qualified domains.

  python3 hs_enrich_apply.py            # qualify + write confirmed domains
  python3 hs_enrich_apply.py --no-write # qualify only, touch nothing in HubSpot
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.hubspot import HubSpot
from pipeline.observe import observe_one
from pipeline.verify_email import verify_all
import run as R   # reuse qualify_one + to_entry

ROOT = Path(__file__).resolve().parent
BATCH = ROOT / "state" / "resolved_batch.json"
OUT = ROOT / "state" / "hubspot_candidates.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true", help="don't write to HubSpot")
    args = ap.parse_args()

    batch = json.loads(BATCH.read_text())
    hs = None if args.no_write else HubSpot()
    year = datetime.now(timezone.utc).year

    qualified = []
    for b in batch:
        cand = {
            "name": b["name"], "domain": b["domain"],
            "website_raw": "https://" + b["domain"],
            "website_status": "unknown", "practice_type": b.get("practice_type", ""),
            "location": f'{b.get("city","")} {b.get("state","")}'.strip(),
            "contact_name": "", "role": "", "email": "", "source": "HubSpot",
            "hs_company_id": b["id"], "domain_provisional": b.get("provisional", False),
        }
        R.qualify_one(cand, current_year=year, do_broken=False)
        flag = "✓" if cand["qualified"] else " "
        prov = " ⚠prov" if cand["domain_provisional"] else ""
        print(f"  {flag} {cand['qualify_status']:13s} score={cand['weakness_score']:3d} "
              f"{cand['name'][:34]:34s} {cand['domain']}{prov}")

        # write confirmed domain back to HubSpot (never a provisional guess)
        if cand["qualified"] and not cand["domain_provisional"] and hs is not None:
            hs.update("companies", b["id"], {"domain": b["domain"], "website": cand["website_raw"]})
            print(f"      ↳ wrote domain to HubSpot company {b['id']}")

        if cand["qualified"]:
            observe_one(cand, use_llm=False)   # set use_llm via env handled in observe
            qualified.append(cand)

    verify_all(qualified, ROOT / "state" / "email_cache.json")
    OUT.write_text(json.dumps(qualified, indent=2, ensure_ascii=False))
    print(f"\n  qualified {len(qualified)}/{len(batch)} → wrote {OUT.relative_to(ROOT)}")
    for c in qualified:
        print(f"    “{c['draft_observation']}”")


if __name__ == "__main__":
    main()
