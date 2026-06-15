/**
 * functions/api/hubspot.js — Cloudflare Pages Function (route: /api/hubspot).
 *
 * The review page calls this from Almendra's actions. Because she only acts after
 * reviewing, these are operator-gated writes, not the agent writing inferred data.
 *
 * Actions (POST body { action, ... }):
 *   sent         — find/create company, write confirmed domain, set magni_status=sent,
 *                  log a note (with the #magni2sent marker the pipeline searches for)
 *   skip         — set magni_status=skipped + a #magni2skip note
 *   note         — append a free note to the company (lives with the record)
 *   set_website  — write a website/domain she found for a no-site lead
 *
 * Token from Pages env var HUBSPOT_TOKEN (never in the browser). magni_status is a
 * custom property — set best-effort (separate PATCH) so a missing property never
 * fails the whole call. Best-effort throughout: a failure returns ok:false but the
 * dashboard keeps the local copy, so her work is never lost.
 */
const HS = "https://api.hubapi.com";

export async function onRequestPost({ request, env }) {
  const token = (env.HUBSPOT_TOKEN || "").trim();
  if (!token) return json({ ok: false, error: "HUBSPOT_TOKEN not set on the Pages project" }, 503);
  let b;
  try { b = await request.json(); } catch { return json({ ok: false, error: "bad json" }, 400); }

  const action = clean(b.action) || "sent";
  const domain = clean(b.domain);
  const companyName = clean(b.companyName);
  const email = clean(b.email).toLowerCase();
  const observation = clean(b.observation);
  const note = clean(b.note);
  let companyId = clean(b.hsCompanyId);

  const hs = (path, method = "GET", body) =>
    fetch(HS + path, { method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined });

  try {
    // resolve company: id → domain search → (for actions that may add) create
    if (!companyId && domain) {
      const r = await hs("/crm/v3/objects/companies/search", "POST", {
        filterGroups: [{ filters: [{ propertyName: "domain", operator: "EQ", value: domain }] }],
        properties: ["domain"], limit: 1 });
      const d = await r.json();
      if (d.results && d.results[0]) companyId = d.results[0].id;
    }
    if (!companyId && (companyName || domain)) {
      const r = await hs("/crm/v3/objects/companies", "POST", { properties: { name: companyName || domain, domain } });
      companyId = (await r.json()).id;
    }
    if (!companyId) return json({ ok: false, error: "could not resolve company" }, 422);

    // write the operator-confirmed / manually-found domain
    if (domain && (action === "sent" || action === "set_website")) {
      await hs(`/crm/v3/objects/companies/${companyId}`, "PATCH",
        { properties: { domain, website: "https://" + domain } });
    }
    // status (custom property) — best-effort, separate call so a missing prop can't 400 the rest
    if (action === "sent" || action === "skip") {
      const status = action === "sent" ? "sent" : "skipped";
      await hs(`/crm/v3/objects/companies/${companyId}`, "PATCH", { properties: { magni_status: status } })
        .catch(() => {});
    }

    // note (sent/skip carry a searchable marker; note/set_website carry her text)
    let body = "";
    if (action === "sent") body = `#magni2sent\nObservation sent: ${observation || "(none)"}`;
    else if (action === "skip") body = `#magni2skip ${note || ""}`.trim();
    else if (action === "set_website") body = `Magni: website added — ${domain}`;
    else body = note;   // action === 'note'
    let noteId = "";
    if (body) {
      let contactId = "";
      if (email) {
        const r = await hs("/crm/v3/objects/contacts/search", "POST", {
          filterGroups: [{ filters: [{ propertyName: "email", operator: "EQ", value: email }] }],
          properties: ["email"], limit: 1 });
        const d = await r.json();
        if (d.results && d.results[0]) contactId = d.results[0].id;
      }
      const assoc = [a(companyId, 190)];
      if (contactId) assoc.push(a(contactId, 202));
      const nr = await hs("/crm/v3/objects/notes", "POST", {
        properties: { hs_note_body: body, hs_timestamp: Date.now() }, associations: assoc });
      noteId = (await nr.json()).id || "";
    }
    return json({ ok: true, companyId, noteId, action });
  } catch (e) {
    return json({ ok: false, error: String(e) }, 502);
  }
}

const clean = (s) => (s == null ? "" : String(s)).trim();
const a = (id, typeId) => ({ to: { id }, types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: typeId }] });
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json" } });
