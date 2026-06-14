#!/usr/bin/env python3
"""
fetch.py — fetch a practice homepage so the detectors can inspect it.

Plain HTTPS GET (default). Distinguishes a genuine TLS/SSL failure (→ the no_ssl
signal) from an unreachable host (→ can't qualify, don't invent weaknesses).
Flags near-empty bodies (JS-rendered SPAs) so we hold them rather than fabricate
findings from an empty DOM. Detects page language so the observation can be
written in the site's own language (the ICP includes Mexico / Spanish sites).
Never raises — every failure is captured in fields.
"""
from __future__ import annotations

import re
import time

import requests
from requests.exceptions import SSLError, ConnectionError as ReqConnErr, Timeout

from .normalize import domain_from_url

UA = "Mozilla/5.0 (compatible; magni-2.0 site checker; +mailto:hello@magnidigital)"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
MAX_BYTES = 600_000
NEAR_EMPTY_TEXT = 220   # visible-text chars below which we suspect a JS SPA

_TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_ANYTAG_RE = re.compile(r"<[^>]+>")
_LANG_RE = re.compile(r"<html[^>]*\blang=[\"']?([a-zA-Z-]{2,5})", re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# generic local-parts are fine (a way in) but a person-looking one is better
_GENERIC_LOCAL = ("info", "contact", "hello", "office", "admin", "frontdesk",
                  "front.desk", "reception", "appointments", "scheduling", "team",
                  "support", "help", "inquiries", "hola", "citas", "recepcion")
# never treat these as contact emails (asset hashes, vendors, placeholders)
_EMAIL_JUNK_DOMAIN = ("example.com", "sentry.io", "wixpress.com", "wix.com",
                      "godaddy.com", "squarespace.com", "w3.org", "schema.org",
                      "sentry-next.wixpress.com", "fontawesome.com", "googleapis.com")
_EMAIL_JUNK_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def visible_text(html):
    """Rough visible-text extraction (drop script/style, strip tags)."""
    if not html:
        return ""
    t = _TAG_RE.sub(" ", html)
    t = _ANYTAG_RE.sub(" ", t)
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def detect_lang(html):
    """Best-effort 2-letter language from <html lang=…>. '' if absent.
    Used only to pick the observation's language; never a weakness signal."""
    m = _LANG_RE.search(html or "")
    return m.group(1).split("-")[0].lower() if m else ""


def extract_emails(html, site_domain=""):
    """Pull contact emails out of page HTML (mailto: + visible text). Returns a
    ranked list, best first: same-domain person address > same-domain generic >
    other person address > other generic. Junk (asset hashes, vendor domains) is
    dropped. Never invents — only what's literally on the page."""
    if not html:
        return []
    found = set()
    for m in re.finditer(r'mailto:([^"\'?>\s]+)', html, re.I):
        found.add(m.group(1).strip().lower())
    for m in _EMAIL_RE.finditer(html):
        found.add(m.group(0).strip().lower())

    sd = (site_domain or "").lower().lstrip("www.")
    ranked = []
    for e in found:
        try:
            local, dom = e.split("@", 1)
        except ValueError:
            continue
        if dom in _EMAIL_JUNK_DOMAIN or any(e.endswith(x) for x in _EMAIL_JUNK_EXT):
            continue
        if len(local) < 2 or "." not in dom:
            continue
        same = bool(sd) and (dom == sd or dom.endswith("." + sd) or sd.endswith("." + dom))
        generic = any(local.startswith(g) for g in _GENERIC_LOCAL)
        # rank: lower = better
        rank = (0 if same else 2) + (1 if generic else 0)
        ranked.append((rank, e))
    ranked.sort()
    return [e for _, e in ranked]


def harvest_email(ctx, *, fetch_contact=True, timeout=8):
    """Best contact email for a fetched site: homepage first, then a /contact
    page if the homepage had none. '' if the site publishes no email (common —
    many practices only have a form; those become Clay-waterfall candidates)."""
    domain = ctx.get("final_domain") or ctx.get("domain") or ""
    emails = extract_emails(ctx.get("html", ""), domain)
    if emails:
        return emails[0]
    if not fetch_contact or not domain:
        return ""
    for path in ("/contact", "/contact-us", "/contacto"):
        try:
            r = _get("https://" + domain + path, timeout, verify=True)
            if r.status_code < 400:
                got = extract_emails(_read(r), domain)
                r.close()
                if got:
                    return got[0]
            else:
                r.close()
        except requests.RequestException:
            continue
    return ""


def _get(url, timeout, verify):
    return requests.get(url, headers=HEADERS, timeout=timeout,
                        allow_redirects=True, verify=verify, stream=True)


def _read(resp):
    raw = resp.raw.read(MAX_BYTES, decode_content=True) or b""
    return raw.decode(resp.encoding or "utf-8", "ignore")


def fetch_site(domain, timeout=10):
    """Fetch https://domain (falling back to http). Returns a context dict the
    signal detectors consume. Never raises."""
    ctx = {
        "domain": domain, "final_url": "", "final_domain": "", "status": None,
        "html": "", "text": "", "lang": "",
        "reachable": False, "secure": None, "ssl_error": False,
        "error": "", "near_empty": False, "elapsed_ms": None,
    }
    if not domain:
        ctx["error"] = "no domain"
        return ctx

    t0 = time.time()
    resp = None
    try:
        resp = _get("https://" + domain, timeout, verify=True)
        ctx["secure"] = True
        ctx["reachable"] = True
    except SSLError:
        # Real TLS problem — try again unverified to still grab content, and try
        # plain http; either way this is the no_ssl signal.
        ctx["ssl_error"] = True
        ctx["secure"] = False
        for url, vf in (("https://" + domain, False), ("http://" + domain, True)):
            try:
                resp = _get(url, timeout, verify=vf)
                ctx["reachable"] = True
                break
            except (SSLError, ReqConnErr, Timeout, requests.RequestException):
                continue
    except (ReqConnErr, Timeout):
        try:
            resp = _get("http://" + domain, timeout, verify=True)
            ctx["secure"] = False
            ctx["reachable"] = True
        except requests.RequestException as e:
            ctx["error"] = f"unreachable: {type(e).__name__}"
    except requests.RequestException as e:
        ctx["error"] = f"error: {type(e).__name__}"

    ctx["elapsed_ms"] = int((time.time() - t0) * 1000)

    if resp is not None:
        try:
            ctx["status"] = resp.status_code
            ctx["final_url"] = resp.url
            ctx["final_domain"] = domain_from_url(resp.url) or domain
            ctx["secure"] = bool(ctx["final_url"].lower().startswith("https://")) and not ctx["ssl_error"]
            ctx["html"] = _read(resp)
            ctx["text"] = visible_text(ctx["html"])
            ctx["lang"] = detect_lang(ctx["html"])
            ctx["near_empty"] = (len(ctx["text"]) < NEAR_EMPTY_TEXT
                                 and "<script" in ctx["html"].lower())
        except requests.RequestException as e:
            ctx["error"] = f"read error: {type(e).__name__}"
        finally:
            resp.close()
    return ctx
