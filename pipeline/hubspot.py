#!/usr/bin/env python3
"""
hubspot.py — thin HubSpot CRM client for Magni 2.0.

HubSpot is the backend: the lead store we pull from, and where notes + status
updates persist. This module is the one place that talks to the HubSpot API, so
auth, paging, and backoff live here once.

Token resolution (first hit wins), so the value never has to be pasted in chat:
    1. env HUBSPOT_TOKEN
    2. state/hubspot_token.local   (gitignored)

Stdlib + requests only. Read helpers are safe to run anytime; write helpers
(notes, archive, property updates) are used by the prune/notes steps and are
always reversible-first (archive, not hard-delete).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

HS_BASE = "https://api.hubapi.com"
ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "state" / "hubspot_token.local"


class HubSpotError(RuntimeError):
    pass


def load_token():
    tok = (os.environ.get("HUBSPOT_TOKEN") or "").strip()
    if not tok and TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text().strip()
    if not tok:
        raise HubSpotError(
            "No HUBSPOT_TOKEN. Set the env var or write the token to "
            f"{TOKEN_FILE.relative_to(ROOT)} (gitignored).")
    # latin-1 guard: a stray non-ASCII char (e.g. a pasted Unicode ellipsis in a
    # placeholder) throws cryptic header errors deep in a run. Fail fast here.
    try:
        tok.encode("ascii")
    except UnicodeEncodeError:
        raise HubSpotError("HUBSPOT_TOKEN contains a non-ASCII character — "
                           "re-copy it (you may have pasted a placeholder).")
    return tok


class HubSpot:
    def __init__(self, token=None, *, timeout=30):
        self.token = token or load_token()
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {self.token}",
                               "Content-Type": "application/json"})

    def _req(self, method, path, *, params=None, json=None, max_retries=5):
        url = path if path.startswith("http") else HS_BASE + path
        for attempt in range(max_retries):
            r = self.s.request(method, url, params=params, json=json, timeout=self.timeout)
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(2 ** attempt, 16)
                time.sleep(wait)
                continue
            if r.status_code == 401:
                raise HubSpotError("HubSpot 401 — token invalid or missing scopes.")
            if r.status_code >= 400:
                raise HubSpotError(f"HubSpot {r.status_code} {method} {path}: {r.text[:300]}")
            return r.json() if r.text else {}
        raise HubSpotError(f"HubSpot retries exhausted: {method} {path}")

    # ── reads ────────────────────────────────────────────────────────────────
    def count(self, object_type):
        """Total records of an object type (uses search with a 1-row page)."""
        d = self._req("POST", f"/crm/v3/objects/{object_type}/search",
                      json={"limit": 1, "properties": ["hs_object_id"]})
        return d.get("total", 0)

    def iter_objects(self, object_type, properties, *, page_limit=100, max_records=None):
        """Yield every record (dict with 'id' + 'properties'), paging via 'after'."""
        after, fetched = None, 0
        while True:
            params = {"limit": page_limit, "properties": ",".join(properties),
                      "archived": "false"}
            if after:
                params["after"] = after
            d = self._req("GET", f"/crm/v3/objects/{object_type}", params=params)
            for row in d.get("results", []):
                yield row
                fetched += 1
                if max_records and fetched >= max_records:
                    return
            after = (d.get("paging", {}).get("next", {}) or {}).get("after")
            if not after:
                return

    def list_properties(self, object_type):
        d = self._req("GET", f"/crm/v3/properties/{object_type}", params={"archived": "false"})
        return d.get("results", [])

    # ── writes (used by prune + notes steps; reversible-first) ────────────────
    def update(self, object_type, object_id, properties):
        return self._req("PATCH", f"/crm/v3/objects/{object_type}/{object_id}",
                         json={"properties": properties})

    def archive(self, object_type, object_id):
        """Soft delete (recoverable for 90 days). Never hard-deletes."""
        return self._req("DELETE", f"/crm/v3/objects/{object_type}/{object_id}")

    def add_note(self, body, *, contact_id=None, company_id=None):
        """Create a Note engagement, optionally associated to a contact/company."""
        props = {"hs_note_body": body, "hs_timestamp": int(time.time() * 1000)}
        payload = {"properties": props, "associations": []}
        # association typeIds: note→contact 202, note→company 190
        if contact_id:
            payload["associations"].append({
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 202}]})
        if company_id:
            payload["associations"].append({
                "to": {"id": company_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 190}]})
        return self._req("POST", "/crm/v3/objects/notes", json=payload)
