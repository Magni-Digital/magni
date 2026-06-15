#!/usr/bin/env python3
"""
hubspot_setup.py — one-time HubSpot schema setup for Magni-as-hub.

Creates a queryable company property `magni_status` so the pipeline can bulk-read
which companies have been sent/skipped (instead of scanning notes per company),
and a `magni_observation` text property to mirror the last observation sent.

Idempotent: skips properties that already exist.

  python3 hubspot_setup.py
"""
from pipeline.hubspot import HubSpot, HubSpotError

PROPS = [
    {"name": "magni_status", "label": "Magni Status", "type": "enumeration",
     "fieldType": "select", "groupName": "companyinformation",
     "options": [{"label": "In queue", "value": "queued", "displayOrder": 0},
                 {"label": "Sent", "value": "sent", "displayOrder": 1},
                 {"label": "Skipped", "value": "skipped", "displayOrder": 2}]},
    {"name": "magni_observation", "label": "Magni Observation (last sent)",
     "type": "string", "fieldType": "textarea", "groupName": "companyinformation"},
]


def main():
    hs = HubSpot()
    print("connected to HubSpot ✓")
    existing = {p["name"] for p in hs.list_properties("companies")}
    for p in PROPS:
        if p["name"] in existing:
            print(f"  · {p['name']} already exists — skipping")
            continue
        try:
            hs._req("POST", "/crm/v3/properties/companies", json=p)
            print(f"  ✅ created {p['name']}")
        except HubSpotError as e:
            print(f"  ⚠ {p['name']}: {e}")


if __name__ == "__main__":
    main()
