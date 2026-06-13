#!/usr/bin/env python3
"""
observe.py — ONE grounded, editable observation per qualified site.

The whole pitch hinges on a single specific, TRUE thing about the practice's own
website. This step writes that opening line. Anti-hallucination gate: the model
is shown ONLY the checked findings (never raw HTML) and must cite a signal id
that exists in them; an invalid/missing id falls back to a deterministic
template keyed off the strongest finding. So a hallucinated observation can
never reach the operator — every draft is provably grounded in a checked fact.

Writes onto each record:
    draft_observation         — one editable sentence (verify-before-send)
    observation_cited_signal  — the signal id it's grounded in
    observation_source        — "claude" | "fallback"
    observation_lang          — "en" | "es" (matches the site's language)

Works with or without ANTHROPIC_API_KEY: no key → every observation uses the
deterministic fallback, so the step still runs and stays truthful.
"""
from __future__ import annotations

from .anthropic_client import call_claude_json, have_key
from .signals import CONF_WEIGHT

CITABLE = ("high", "med")   # low-confidence findings are never the observation


def _citable(rec):
    return [f for f in rec.get("evidence", []) if f.get("confidence") in CITABLE]


def _strongest(citable):
    return max(citable, key=lambda f: CONF_WEIGHT.get(f["confidence"], 0))


def _build_prompt(name, practice_type, citable, lang):
    lines = [f'- [{f["id"]}] {f["evidence_str"]}' for f in citable]
    lang_line = ("- Write the sentence in SPANISH (the site is in Spanish).\n"
                 if lang == "es" else
                 "- Write the sentence in English.\n")
    return (
        "You help a one-person web-design studio write the FIRST LINE of a cold "
        "outreach message to a small professional or healthcare practice. The "
        "whole message hinges on ONE specific, TRUE observation about the "
        "practice's own website — that honest observation is the entire reason "
        "they'll reply.\n\n"
        f"Practice: {name} ({(practice_type or 'practice').replace('_',' ')})\n\n"
        "Below are VERIFIED findings about THEIR website. Each is a checked fact.\n"
        + "\n".join(lines) + "\n\n"
        "Write ONE opening sentence, grounded in EXACTLY ONE of these findings.\n"
        "Rules:\n"
        "- Use only ONE finding. Invent nothing that isn't in the list above.\n"
        "- Plain, human, peer-to-peer. No greeting, no flattery, no marketing "
        "adjectives, no pitch or offer — just the honest, specific observation.\n"
        "- One sentence, under 30 words, as if a real person noticed it.\n"
        "- Pick the finding that makes the most natural, least nitpicky opener.\n"
        + lang_line +
        '\nReturn ONLY JSON: {"cited_signal_id":"<one id from the list>",'
        '"observation":"<your sentence>"}'
    )


# Deterministic, always-true fallback openers keyed by signal id. {name} = the
# practice name. Used when the model is unavailable or cites an invalid id.
_FALLBACKS_EN = {
    "no_website": "I went looking for {name}'s website and couldn’t find one — "
                  "anyone searching for you online comes up empty.",
    "no_ssl": "{name}'s site doesn’t load over a secure https connection, so "
              "browsers show visitors a “Not secure” warning.",
    "no_viewport": "{name}'s site isn’t built to adapt to phone screens, so on "
                   "mobile it shows up as a zoomed-out desktop layout.",
    "stale_copyright": "The footer on {name}'s site still shows an old copyright "
                       "year, which usually means it hasn’t been touched in a few years.",
    "old_wordpress": "{name}'s site is running an outdated version of WordPress — "
                     "a security and maintenance risk worth getting off of.",
    "thin_site": "{name}'s homepage is pretty sparse — there’s very little there "
                 "for someone deciding whether to reach out.",
    "no_booking": "There’s no way to book or request an appointment from {name}'s site.",
    "broken_links": "A few links on {name}'s site are dead, which quietly costs "
                    "you visitors who hit a missing page.",
    "builder": "{name}'s site looks like an off-the-shelf template build that "
               "could present the practice a lot better.",
    "no_cta": "{name}'s homepage doesn’t surface an obvious way to get in touch.",
}
_FALLBACKS_ES = {
    "no_website": "Busqué el sitio web de {name} y no encontré ninguno — quien los "
                  "busca en internet no encuentra nada.",
    "no_ssl": "El sitio de {name} no carga con conexión segura https, así que el "
              "navegador muestra a las visitas un aviso de “No seguro”.",
    "no_viewport": "El sitio de {name} no está hecho para adaptarse a pantallas de "
                   "celular, así que en móvil se ve como una versión de escritorio alejada.",
    "stale_copyright": "El pie de página del sitio de {name} todavía muestra un año "
                       "de copyright viejo, señal de que no se ha actualizado en años.",
    "old_wordpress": "El sitio de {name} usa una versión desactualizada de WordPress, "
                     "un riesgo de seguridad y mantenimiento.",
    "thin_site": "La página de inicio de {name} tiene muy poco contenido — casi nada "
                 "para alguien que está decidiendo si contactarlos.",
    "no_booking": "No hay forma de agendar o solicitar una cita desde el sitio de {name}.",
    "broken_links": "Varios enlaces del sitio de {name} están rotos, lo que pierde "
                    "silenciosamente a quienes llegan a una página inexistente.",
    "builder": "El sitio de {name} parece una plantilla genérica que podría presentar "
               "mucho mejor a la práctica.",
    "no_cta": "La página de inicio de {name} no muestra una forma clara de contactarlos.",
}


def _fallback(finding, name, lang):
    table = _FALLBACKS_ES if lang == "es" else _FALLBACKS_EN
    tmpl = table.get(finding["id"])
    if tmpl:
        return tmpl.format(name=name)
    return f"On {name}'s site, I noticed: {finding['evidence_str']}"


def observe_one(rec, *, use_llm):
    citable = _citable(rec)
    if not citable:   # qualified always has >=1 high/med, so this is defensive
        rec.update(draft_observation="", observation_cited_signal="",
                   observation_source="none", observation_lang=rec.get("lang", "en"))
        return rec

    lang = "es" if rec.get("lang") == "es" else "en"
    valid_ids = {f["id"] for f in citable}
    source, cited, text = "fallback", "", ""

    if use_llm:
        out = call_claude_json(
            _build_prompt(rec.get("name", "this practice"),
                          rec.get("practice_type", "practice"), citable, lang),
            max_tokens=300, default=None)
        # GATE: accept only a response that cites an id present in the evidence
        if (isinstance(out, dict) and out.get("cited_signal_id") in valid_ids
                and (out.get("observation") or "").strip()):
            source = "claude"
            cited = out["cited_signal_id"]
            text = out["observation"].strip()

    if source != "claude":
        top = _strongest(citable)
        cited = top["id"]
        text = _fallback(top, rec.get("name", "this practice"), lang)

    rec.update(draft_observation=text, observation_cited_signal=cited,
               observation_source=source, observation_lang=lang)
    return rec


def observe_all(recs):
    """Generate observations for every qualified record in place. Returns
    (n_claude, n_fallback)."""
    use_llm = have_key()
    n_claude = n_fb = 0
    for r in recs:
        if r.get("qualify_status") != "qualified":
            continue
        observe_one(r, use_llm=use_llm)
        if r.get("observation_source") == "claude":
            n_claude += 1
        else:
            n_fb += 1
    return n_claude, n_fb
