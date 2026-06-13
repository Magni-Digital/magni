#!/usr/bin/env python3
"""
score.py — roll findings into a weakness score + a qualify verdict.

Qualification is deliberately NOT "high score" — it's "has at least one HIGH- or
MED-confidence, concretely-evidenced weakness," because the pitch is a single
TRUE observation. A pile of low-confidence heuristics never qualifies a site on
its own; it only colors the ranking. The operator applies final judgment, so
volume is fine as long as every surfaced finding is literally true.
"""
from __future__ import annotations

from .signals import CONF_WEIGHT, HIGH, MED

_FULL = 9   # sum-of-weights (3 high-confidence signals) that maps to score 100


def compute(findings):
    present = [f for f in findings if f]
    high = [f for f in present if f["confidence"] == HIGH]
    med = [f for f in present if f["confidence"] == MED]
    weight = sum(CONF_WEIGHT.get(f["confidence"], 0) for f in present)
    return {
        "weakness_score": min(100, round(weight * 100 / _FULL)),
        "qualified": len(high) >= 1 or len(med) >= 1,
        "high_count": len(high),
        "med_count": len(med),
        "n": len(present),
    }


def rank_key(rec):
    """Sort key for the daily list: most-defensible findings first (high count,
    then med count, then score) — the strongest, safest pitches rise to the top."""
    return (-rec.get("site_high_count", 0),
            -rec.get("site_med_count", 0),
            -rec.get("weakness_score", 0))
