#!/usr/bin/env python3
"""
signals.py — objective site-weakness detectors.

Each detector inspects a fetched page and returns a finding or None. A finding:
    {id, label, confidence: high|med|low, evidence_str}
`evidence_str` is a verbatim, defensible statement of fact. It is shown to the
operator AND is the ONLY material the observation generator may cite — so every
detector carries an explicit false-positive guard and says nothing it can't back
up. This is the heart of "one specific TRUE thing per site."

Magni's ICP is broad (professional services, health & wellness, education, real
estate, nonprofit), so the universal detectors fire for any vertical; the
booking detector is gated to health/wellness practices where missing online
scheduling is a real, expected gap.
"""
from __future__ import annotations

import re

HIGH, MED, LOW = "high", "med", "low"
CONF_WEIGHT = {HIGH: 3, MED: 2, LOW: 1}


def _finding(sid, label, confidence, evidence):
    return {"id": sid, "label": label, "confidence": confidence,
            "evidence_str": evidence}


BOOKING_FINGERPRINTS = (
    "calendly.com", "acuityscheduling", "squareup.com/appointments", "schedulicity",
    "simplybook", "nexhealth", "zocdoc", "vagaro.com", "setmore", "mindbodyonline",
    "janeapp", "healthgrades.com/appointment", "solutionreach", "intakeq", "simplepractice",
    "book now", "book online", "request appointment", "schedule online",
    "schedule an appointment", "book an appointment", "agendar cita", "reservar cita",
)
BUILDERS = [
    ("Wix", ("wix.com", "_wix", "wixstatic.com")),
    ("Weebly", ("weebly.com", "weeblycloud")),
    ("Squarespace", ("squarespace.com", "static1.squarespace")),
    ("GoDaddy Website Builder", ("godaddy.com/websites", "img1.wsimg.com")),
    ("WordPress", ("wp-content", "wp-includes")),
]
# verticals where missing online booking is a real, expected gap
HEALTH_TYPES = {
    "dental", "mental_health", "therapy", "counseling", "addiction_recovery",
    "medical_clinic", "specialty_clinic", "integrative_health", "physical_therapy",
    "chiropractic", "dermatology", "med_spa", "wellness", "optometry", "veterinary",
}


def detect_no_ssl(ctx, cand):
    if not ctx.get("reachable"):
        return None
    if ctx.get("secure") is True:
        return None
    return _finding(
        "no_ssl", "No HTTPS / insecure", HIGH,
        "The site does not load over a valid HTTPS connection, so browsers flag "
        "it as “Not secure” in the address bar.")


def detect_no_viewport(ctx, cand):
    html = ctx.get("html") or ""
    if not html:
        return None
    if re.search(r'<meta[^>]+name=["\']?viewport', html, re.I):
        return None
    return _finding(
        "no_viewport", "No mobile viewport tag", HIGH,
        "The homepage has no mobile viewport tag, so it isn’t built to adapt "
        "to phone screens — mobile visitors get a zoomed-out desktop layout.")


def detect_stale_copyright(ctx, cand, current_year):
    """Flag a copyright year >=2 years old. Scans ALL years near each ©/copyright
    mention and takes the NEWEST, so a range like “© 2010-2026” reads as
    current. Stores the literal footer text containing the newest year."""
    html = ctx.get("html") or ""
    newest, literal = 0, ""
    for m in re.finditer(r"©|&copy;|copyright|derechos reservados", html, re.I):
        window = html[m.start(): m.start() + 56]
        for ym in re.finditer(r"(?:19|20)\d{2}", window):
            y = int(ym.group())
            if 1990 <= y <= current_year + 1 and y > newest:
                newest = y
                literal = re.sub(r"\s+", " ", window.split("<")[0]).strip()[:46]
    if not newest or newest > current_year - 2:
        return None
    return _finding(
        "stale_copyright", "Stale copyright year", MED,
        f"The footer still reads “{literal}” — {current_year - newest} "
        f"years out of date, a sign the site hasn’t been touched since then.")


def detect_no_booking(ctx, cand):
    if cand.get("practice_type") not in HEALTH_TYPES:
        return None
    html = (ctx.get("html") or "").lower()
    if not html:
        return None
    if any(fp in html for fp in BOOKING_FINGERPRINTS):
        return None
    if "<form" in html:
        return None  # contactable via a form — don't overclaim
    return _finding(
        "no_booking", "No online booking", MED,
        "There’s no way to book or request an appointment online — no "
        "scheduling tool and no contact form on the homepage.")


def detect_builder(ctx, cand):
    html = (ctx.get("html") or "").lower()
    if not html:
        return None
    mver = re.search(r'name=["\']generator["\'][^>]*content=["\']wordpress\s*([0-9.]+)',
                     html, re.I)
    if mver:
        ver = mver.group(1)
        try:
            major = int(ver.split(".")[0])
        except ValueError:
            major = 99
        if major and major < 6:
            return _finding(
                "old_wordpress", "Outdated WordPress", MED,
                f"The site runs WordPress {ver} (current is 6.x) — an "
                f"out-of-date, unmaintained CMS with known security holes.")
    for label, fps in BUILDERS:
        if any(fp in html for fp in fps):
            return _finding(
                "builder", f"Built on {label}", LOW,
                f"The site is built on {label}.")
    return None


def detect_thin_site(ctx, cand):
    text = ctx.get("text") or ""
    if not text:
        return None
    words = len(text.split())
    links = len(re.findall(r"<a\s", ctx.get("html") or "", re.I))
    if words < 130 and links < 12:
        return _finding(
            "thin_site", "Very thin homepage", MED,
            f"The homepage has only ~{words} words of content and {links} links "
            f"— barely more than a placeholder.")
    return None


def detect_no_cta(ctx, cand):
    html = (ctx.get("html") or "").lower()
    if not html:
        return None
    if ("tel:" in html or "mailto:" in html or "<form" in html
            or any(fp in html for fp in BOOKING_FINGERPRINTS)):
        return None  # some contact path exists — not a standalone weakness
    # LOW: a JS-rendered contact widget wouldn't show in source, so this never
    # qualifies a site alone and is never citable as the observation.
    return _finding(
        "no_cta", "No clear call-to-action", LOW,
        "The homepage has no clickable phone number, booking link, contact form, "
        "or email visible in the page source.")


def detect_broken_links(ctx, cand, fetcher=None, cap=10):
    """Sample internal links, HEAD them, flag if >=2 are dead. Network-heavy;
    `fetcher(url)->status_or_None` is injected so the orchestrator controls it."""
    if fetcher is None:
        return None
    html = ctx.get("html") or ""
    base = ctx.get("final_domain") or ctx.get("domain") or ""
    if not html or not base:
        return None
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
    internal, seen = [], set()
    for h in hrefs:
        if h.startswith("#") or h.startswith("mailto:") or h.startswith("tel:"):
            continue
        if h.startswith("/"):
            url = "https://" + base + h
        elif base in h:
            url = h
        else:
            continue
        if url not in seen:
            seen.add(url)
            internal.append(url)
        if len(internal) >= cap:
            break
    dead = []
    for url in internal:
        status = fetcher(url)
        if status is not None and status >= 400:
            dead.append((url, status))
        if len(dead) >= 3:
            break
    if len(dead) < 2:
        return None
    sample = ", ".join(f"{u.split(base, 1)[-1] or '/'} ({s})" for u, s in dead[:2])
    return _finding(
        "broken_links", "Broken links", MED,
        f"At least {len(dead)} links on the site are dead — e.g. {sample}.")
