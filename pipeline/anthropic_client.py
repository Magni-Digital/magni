#!/usr/bin/env python3
"""
anthropic_client.py — tiny Claude HTTP client for the observation step.

Used by observe.py to draft ONE grounded sentence per site. Optional: if
ANTHROPIC_API_KEY is unset, observe.py falls back to deterministic templates, so
the whole tool still runs without a key. Stdlib urllib only — no SDK dependency,
so the daily run stays light.

Uses Haiku: plenty for a single grounded sentence, and far more rate-limit
headroom than Sonnet for a batch.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ANTH_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ANTH_VERSION = "2023-06-01"
UA = "magni-2.0 (web-studio outreach helper)"


def have_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def call_claude(prompt, *, system=None, model=None, max_tokens=400,
                temperature=0, max_retries=4, timeout=60):
    """Send one user message, return the assistant text (stripped). Retries on
    429 with exponential backoff. On any other error returns '' so a single bad
    call can never crash the daily run — the caller falls back deterministically."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return ""
    payload = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    body = json.dumps(payload).encode()

    def _request():
        return urllib.request.Request(
            ANTH_URL, data=body, method="POST",
            headers={"User-Agent": UA, "x-api-key": key,
                     "anthropic-version": ANTH_VERSION,
                     "content-type": "application/json"})

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(_request(), timeout=timeout) as r:
                d = json.loads(r.read().decode())
            return (d.get("content") or [{}])[0].get("text", "").strip()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 4 * (2 ** attempt)
                print(f"  Claude 429 — backing off {wait}s "
                      f"(attempt {attempt+1}/{max_retries})", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  Claude HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
            return ""
        except Exception as e:  # noqa: BLE001 — never let one call kill the batch
            print(f"  Claude error: {e}", file=sys.stderr)
            return ""
    return ""


def _strip_fences(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def call_claude_json(prompt, *, default=None, **kwargs):
    """call_claude + tolerant JSON parse. Returns `default` on empty/parse fail."""
    text = call_claude(prompt, **kwargs)
    if not text:
        return default
    try:
        return json.loads(_strip_fences(text))
    except (ValueError, TypeError):
        return default
