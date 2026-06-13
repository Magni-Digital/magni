#!/usr/bin/env python3
"""
icp.py — score a HubSpot record against Magni's real ICP.

Magni sells websites to the OWNER / decision-maker of a small (5-50) practice in
professional services or health & wellness (+ education, real estate, nonprofit),
in a set of US + MX target cities. The old Atlas seeded HubSpot against a
DIFFERENT ICP (marketing leaders), so this module is how we separate the two.

verdict ∈ {keep, cut, review}
  keep   — clearly on-target (right vertical + decision-maker role + plausible geo)
  cut    — clearly off-target (marketing/agency buyer, or wrong vertical AND geo)
  review — ambiguous; never auto-archived, surfaced for a human glance

Fields are sparse (industry/employees empty in the seed), so vertical is inferred
from the company name. We bias toward NOT cutting when unsure.
"""
from __future__ import annotations

from .ingest import classify

# US target states (full + abbrev) and MX geo hints, from the Target Markets sheet.
TARGET_CITIES = {
    "austin", "dallas", "denver", "nashville", "phoenix", "portland", "seattle",
    "mexico city", "ciudad de méxico", "cdmx", "guadalajara", "monterrey",
    "querétaro", "queretaro", "mérida", "merida", "puebla", "cancún", "cancun",
    "playa del carmen",
}
TARGET_STATES = {"tx", "texas", "co", "colorado", "tn", "tennessee", "az",
                 "arizona", "or", "oregon", "wa", "washington"}
MX_HINTS = {"mexico", "méxico", "cdmx", "guadalajara", "monterrey", "queretaro",
            "querétaro", "merida", "mérida", "puebla", "cancun", "cancún",
            "playa del carmen", "jalisco", "nuevo león", "nuevo leon"}

# Wrong buyer for a web-design pitch: marketing/agency decision-makers (the old
# Atlas's ICP). A small practice owner does not carry these titles.
MARKETING_ROLE = ("market", "cmo", "brand", "growth", "demand gen", "communications",
                  "content", "social media", " seo", "advertis", "paid media",
                  "mercadotecnia", "mercadeo")
# Right buyer: the owner / operator / principal of the practice.
DECISION_ROLE = ("owner", "founder", "co-founder", "cofounder", "ceo", "president",
                 "principal", "partner", "managing", "practice manager",
                 "office manager", "director of operations", "operations manager",
                 "executive director", "administrator", "proprietor", "doctor",
                 "dr.", "dueñ", "duen", "director general", "socio", "fundador")


def geo_bucket(props):
    city = (props.get("city") or "").lower()
    state = (props.get("state") or "").lower()
    if any(t in city for t in TARGET_CITIES):
        return "in"
    if state in TARGET_STATES:
        return "in"
    if any(h in city or h in state for h in MX_HINTS):
        return "in"
    if city or state:
        return "out"
    return "unknown"


def role_bucket(title):
    t = (title or "").lower()
    if any(k in t for k in MARKETING_ROLE):
        return "marketing"
    if any(k in t for k in DECISION_ROLE):
        return "decision"
    return "other"


def score_contact(props):
    vert = classify(props.get("company") or "")
    geo = geo_bucket(props)
    role = role_bucket(props.get("jobtitle"))

    if role == "marketing":
        return "cut", "marketing/agency title — wrong buyer for web sales"
    if not vert and geo == "out":
        return "cut", "non-target vertical + outside target geo"
    if vert and role == "decision" and geo in ("in", "unknown"):
        return "keep", f"{vert} · decision-maker · geo:{geo}"
    return "review", f"vert:{vert or '?'} role:{role} geo:{geo}"


def score_company(props):
    vert = classify(props.get("name") or "")
    geo = geo_bucket(props)
    if not vert and geo == "out":
        return "cut", "non-target vertical + outside target geo"
    if vert and geo in ("in", "unknown"):
        return "keep", f"{vert} · geo:{geo}"
    return "review", f"vert:{vert or '?'} geo:{geo}"
