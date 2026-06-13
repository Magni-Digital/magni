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
