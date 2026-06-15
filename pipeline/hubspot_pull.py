#!/usr/bin/env python3
"""
hubspot_pull.py — read side of HubSpot-as-hub.

  status_domains(hs)            → ({sent_domains}, {skipped_domains}) from the
                                  magni_status company property (set by the review
                                  page via /api/hubspot). Drives retirement so the
                                  working-set queue never re-shows a sent lead.
  pull_new(hs, known_domains)   → candidate dicts for in-ICP HubSpot companies that
                                  have a domain and aren't already in the pipeline —
                                  i.e. ones Almendra (or anyone) added in HubSpot.

Both degrade gracefully: if the property/scope isn't there yet, or the network
fails, they return empty so a run never breaks.
"""
from __future__ import annotations

from . import icp
from .normalize import domain_from_url

COMPANY_PROPS = ["name", "domain", "website", "city", "state", "industry",
                 "numberofemployees", "magni_status", "description"]


def status_domains(hs):
    sent, skipped = set(), set()
    for status, bucket in (("sent", sent), ("skipped", skipped)):
        try:
            after = None
            while True:
                body = {"filterGroups": [{"filters": [
                    {"propertyName": "magni_status", "operator": "EQ", "value": status}]}],
                    "properties": ["domain"], "limit": 100}
                if after:
                    body["after"] = after
                d = hs._req("POST", "/crm/v3/objects/companies/search", json=body)
                for r in d.get("results", []):
                    dom = domain_from_url(r["properties"].get("domain") or "")
                    if dom:
                        bucket.add(dom)
                after = (d.get("paging", {}).get("next", {}) or {}).get("after")
                if not after:
                    break
        except Exception:
            pass   # property/scope not ready → no retirements from HubSpot yet
    return sent, skipped


def pull_new(hs, known_domains, max_records=4000):
    """In-ICP HubSpot companies with a domain not already in the pipeline."""
    out = []
    try:
        for r in hs.iter_objects("companies", COMPANY_PROPS, max_records=max_records):
            p = r["properties"]
            dom = domain_from_url(p.get("domain") or p.get("website") or "")
            if not dom or dom in known_domains:
                continue
            verdict, _ = icp.score_company(p)
            if verdict == "cut":
                continue
            loc = (p.get("city") or "", p.get("state") or "")
            from .ingest import classify
            out.append({
                "name": p.get("name", ""), "domain": dom,
                "website_raw": p.get("website") or "https://" + dom,
                "website_status": "unknown",
                "practice_type": classify(f"{p.get('name','')} {p.get('industry','')} {p.get('description','')[:200]}"),
                "location": " ".join(loc).strip(), "city": loc[0], "state": loc[1],
                "contact_name": "", "role": "", "email": "", "source": "HubSpot",
                "hs_company_id": r["id"], "domain_provisional": False,
                "employee_count": p.get("numberofemployees", ""), "industry": p.get("industry", ""),
                "description": (p.get("description") or "")[:280],
            })
    except Exception:
        pass
    return out
