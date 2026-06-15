#!/usr/bin/env python3
"""
dedupe.py — the persistent seen-set, so a practice never appears twice.

The operator's rule: never work the same practice two days running. This module
keys each practice (domain, else name+location) and remembers every one ever
surfaced or sent in state/seen.json. A practice surfaced or sent before is
excluded forever; a skipped one cools down and can resurface after 30 days.

seen.json schema:
  { "<key>": {first_seen_iso, surfaced_count, last_surfaced_iso, disposition} }
  disposition ∈ {surfaced, sent, skipped}

Dispositions come from the review page (state/dispositions.json, exported by the
operator) and are folded in at the start of each run so a practice she sent
yesterday never comes back today.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .normalize import dedupe_key

SKIP_COOLDOWN_DAYS = 30


def key_for(rec):
    return dedupe_key(rec.get("domain", ""), name=rec.get("name", ""),
                      location=rec.get("location", ""))


def load_seen(path):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            return {}
    return {}


def save_seen(path, seen):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(seen, indent=2, ensure_ascii=False))


def _days_since(iso, now):
    try:
        then = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return 1e9
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 86400.0


def apply_dispositions(seen, dispositions, now_iso):
    """Fold the review page's Send/Skip records into the seen-set BEFORE
    selecting, so a just-sent practice retires and a skipped one cools down.
    Each disposition: {key, status in (sent, skipped), iso?}. Returns count."""
    applied = 0
    for d in dispositions or []:
        key = (d.get("key") or "").strip()
        status = d.get("status")
        if not key or status not in ("sent", "skipped"):
            continue
        entry = seen.get(key) or {"first_seen_iso": now_iso, "surfaced_count": 0}
        entry["disposition"] = status
        entry["last_surfaced_iso"] = d.get("iso") or entry.get("last_surfaced_iso", now_iso)
        seen[key] = entry
        applied += 1
    return applied


def excluded(rec, seen, now):
    """(is_excluded, reason). Sent/surfaced → never resurface; skipped →
    excluded only within the cooldown window."""
    key = key_for(rec)
    if not key or key not in seen:
        return False, "new"
    entry = seen[key]
    disp = entry.get("disposition", "surfaced")
    if disp == "sent":
        return True, "already_sent"
    if disp == "skipped":
        if _days_since(entry.get("last_surfaced_iso", ""), now) < SKIP_COOLDOWN_DAYS:
            return True, "skipped_cooldown"
        return False, "skip_cooldown_elapsed"
    # surfaced-but-not-acted-on: do NOT retire — the queue is a rolling working set,
    # so an unworked lead stays eligible and re-appears (re-ranked) until she
    # sends or skips it. Only sent/skipped (above) leave the queue.
    return False, "surfaced_unworked"


def annotate(recs, seen, now):
    for rec in recs:
        rec["dedupe_key"] = key_for(rec)
        ex, reason = excluded(rec, seen, now)
        rec["seen_excluded"] = ex
        rec["seen_reason"] = reason
    return recs


def mark_surfaced(seen, recs, now_iso):
    """Record every queued practice as surfaced, so it never appears again."""
    for rec in recs:
        key = key_for(rec)
        if not key:
            continue
        entry = seen.get(key) or {"first_seen_iso": now_iso, "surfaced_count": 0,
                                  "disposition": "surfaced"}
        entry["surfaced_count"] = entry.get("surfaced_count", 0) + 1
        entry["last_surfaced_iso"] = now_iso
        entry["disposition"] = "surfaced"
        seen[key] = entry
    return seen
