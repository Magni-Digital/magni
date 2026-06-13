#!/usr/bin/env python3
"""
verify_email.py — contact-email verification (the "this genuinely helps" part).

A graceful ladder that NEVER blocks a strong site-weakness lead — email is
enrichment, not a gate:

  syntax → MX (does the domain accept mail?) → optional deliverability API

email_verified ∈ {deliverable, risky, mx_ok, undeliverable, no_email, unverified}
Results cache per-email in state/email_cache.json to save quota/time.

MX lookup degrades gracefully: dnspython if installed → `nslookup` subprocess →
A-record proxy via socket → "unverified". A catch-all/deliverability API
(ZeroBounce-style) runs only if EMAIL_VERIFY_API_URL + EMAIL_VERIFY_API_KEY are
set in the environment.
"""
import json
import os
import re
import socket
import subprocess
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")
_mx_cache = {}   # domain -> bool|None (per-process)

GOOD = ("deliverable", "risky", "mx_ok")   # statuses worth surfacing the address


def syntax_ok(email):
    return bool(EMAIL_RE.match((email or "").strip()))


def _mx_via_dnspython(domain):
    try:
        import dns.resolver
    except Exception:
        return None
    try:
        return len(dns.resolver.resolve(domain, "MX")) > 0
    except Exception:
        return False


def _mx_via_nslookup(domain):
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain],
                             capture_output=True, text=True, timeout=8)
        return None if out.returncode != 0 else ("mail exchanger" in out.stdout.lower())
    except (OSError, subprocess.SubprocessError):
        return None


def _a_record_proxy(domain):
    """Weak proxy: if the domain resolves at all it *might* take mail. Reported
    as 'unverified', never 'mx_ok'."""
    try:
        socket.gethostbyname(domain)
        return True
    except OSError:
        return False


def has_mx(domain):
    if domain in _mx_cache:
        return _mx_cache[domain]
    res = _mx_via_dnspython(domain)
    if res is None:
        res = _mx_via_nslookup(domain)
    _mx_cache[domain] = res
    return res


def _deliverability_api(email):
    url = (os.environ.get("EMAIL_VERIFY_API_URL") or "").strip()
    key = (os.environ.get("EMAIL_VERIFY_API_KEY") or "").strip()
    if not url or not key:
        return None
    import urllib.parse
    import urllib.request
    q = urllib.parse.urlencode({"email": email, "api_key": key})
    try:
        with urllib.request.urlopen(f"{url}?{q}", timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    status = str(data.get("status") or data.get("result") or "").lower()
    if status in ("valid", "deliverable"):
        return "deliverable"
    if status in ("catch-all", "catch_all", "unknown", "risky", "accept_all"):
        return "risky"
    if status in ("invalid", "undeliverable"):
        return "undeliverable"
    return None


def verify(email, cache):
    e = (email or "").strip().lower()
    if not e:
        return "no_email"
    if e in cache:
        return cache[e]
    if not syntax_ok(e):
        cache[e] = "undeliverable"
        return cache[e]
    domain = EMAIL_RE.match(e).group(1)

    api = _deliverability_api(e)
    if api:
        cache[e] = api
        return api

    mx = has_mx(domain)
    if mx is True:
        status = "mx_ok"
    elif mx is False:
        status = "undeliverable"
    else:   # no MX method available — A-record is only a weak proxy
        status = "unverified" if _a_record_proxy(domain) else "undeliverable"
    cache[e] = status
    return status


def load_cache(path):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return {}
    return {}


def save_cache(path, cache):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def verify_all(recs, cache_path):
    """Annotate each record with email_verified + verified_email. Returns a
    {status: count} distribution. Never drops a record."""
    from collections import Counter
    cache = load_cache(cache_path)
    dist = Counter()
    for rec in recs:
        email = (rec.get("email") or "").strip()
        status = verify(email, cache)
        rec["email_verified"] = status
        rec["verified_email"] = email if status in GOOD else ""
        dist[status] += 1
    save_cache(cache_path, cache)
    return dict(dist)
