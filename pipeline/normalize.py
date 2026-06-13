#!/usr/bin/env python3
"""
normalize.py — shared field-cleaning + the canonical practice identity key.

One copy of this logic, used by ingest (to clean rows) and dedupe (to key a
practice across days). Keeping it in one place is load-bearing: a domain parsed
two slightly different ways would key two different practices and slip past the
"never show twice" guard. Keep these pure and side-effect free.
"""
import re
import unicodedata

SOCIAL_HOSTS = ("linkedin.com", "facebook.com", "twitter.com", "x.com",
                "instagram.com", "youtube.com", "tiktok.com", "yelp.com")


def clean_name(s):
    """Strip parentheticals and post-nominal credentials from a person name.
    'Jane Doe, M.D. (she/her)' → 'Jane Doe'."""
    s = (s or "").strip()
    s = re.sub(r"\s*\([^)]*\)", "", s)
    s = re.sub(r",?\s*(ph\.?d\.?|m\.?d\.?|mba|cpa|esq\.?|jd|lcsw|lmft)\b\.?", "", s, flags=re.I)
    return s.strip(" ,")


def domain_from_url(url):
    """'https://www.acme.com/about?x=1' → 'acme.com'. Empty/garbage → ''.

    Rejects social/LinkedIn hosts on a host boundary (not by substring) — we
    want the practice's OWN site, never their social profile, and we must not
    kill a real domain like 'chiropractoramarillotx.com' just because it ends in
    a substring of 'x.com'."""
    u = (url or "").strip().lower()
    if not u or len(u) < 4:
        return ""
    u = re.sub(r"^https?://", "", u)
    u = u.split("/", 1)[0].split("?", 1)[0]
    u = re.sub(r"^www\.", "", u)
    if "." not in u or len(u) < 4:
        return ""
    if any(u == h or u.endswith("." + h) for h in SOCIAL_HOSTS):
        return ""
    return u


def normalize_url(url):
    """Best-effort canonical https URL for fetching. '' if no real domain.
    'acme.com' → 'https://acme.com'; keeps an explicit path if present."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not domain_from_url(raw):
        return ""
    if not re.match(r"^https?://", raw, flags=re.I):
        raw = "https://" + raw.lstrip("/")
    return raw


def slugify(*parts):
    """Stable, lowercase, ascii slug from arbitrary parts. Used to key a
    practice that has no usable domain.
    slugify('Bright Smile Dental', 'Austin') → 'bright-smile-dental-austin'."""
    text = " ".join(str(p or "").strip() for p in parts)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text


def dedupe_key(domain="", *, name="", location=""):
    """The canonical identity of a practice across days. Domain wins; otherwise
    a name+location slug. Returns '' only if there is truly nothing to key on
    (caller drops such a record)."""
    d = domain_from_url(domain) if domain else ""
    if d:
        return d
    s = slugify(name, location)
    return f"name:{s}" if s else ""
