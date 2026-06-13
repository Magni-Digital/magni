/**
 * functions/api/hubspot.js — Cloudflare Pages Function (route: /api/hubspot).
 *
 * The review page calls this when Almendra marks a lead SENT. Because she only
 * sends after reviewing the site + observation, "sent" IS her confirmation — so
 * this is operator-gated write-back, not the agent writing inferred data.
 *
 * It persists to HubSpot (the backend):
 *   - finds the company by hs_company_id, else by domain, else creates it
 *   - writes the confirmed domain back to the company
 *   - logs a Note with the observation she sent (associated to company + contact)
 *
 * The HubSpot token is read from the Pages env var HUBSPOT_TOKEN — it never
 * touches the browser. Set it in: Cloudflare Pages → the project → Settings →
 * Environment variables → Production → HUBSPOT_TOKEN = <pat-na1-…>.
 *
 * Best-effort: any failure returns ok:false but the dashboard keeps the local
 * disposition, so the operator's work is never lost.
 */

const HS = "https://api.hubapi.com";

export async function onRequestPost({ request, env }) {
  const token = (env.HUBSPOT_TOKEN || "").trim();
  if (!token) return json({ ok: false, error: "HUBSPOT_TOKEN not set on the Pages project" }, 503);

  let b;
  try { b = await request.json(); } catch { return json({ ok: false, error: "bad json" }, 400); }

  const domain = clean(b.domain);
  const companyName = clean(b.companyName);
  const email = clean(b.email).toLowerCase();
  const observation = clean(b.observation);
  const status = clean(b.status) || "sent";
  let companyId = clean(b.hsCompanyId);

  const hs = (path, method = "GET", body) =>
    fetch(HS + path, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });

  try {
    // 1) resolve the company: id → domain search → create
    if (!companyId && domain) {
      const r = await hs("/crm/v3/objects/companies/search", "POST", {
        filterGroups: [{ filters: [{ propertyName: "domain", operator: "EQ", value: domain }] }],
        properties: ["domain"], limit: 1,
      });
      const d = await r.json();
      if (d.results && d.results[0]) companyId = d.results[0].id;
    }
    if (!companyId && (companyName || domain)) {
      const r = await hs("/crm/v3/objects/companies", "POST", {
        properties: { name: companyName || domain, domain },
      });
      const d = await r.json();
      companyId = d.id;
    }
    // 2) write the operator-confirmed domain back
    if (companyId && domain) {
      await hs(`/crm/v3/objects/companies/${companyId}`, "PATCH", {
        properties: { domain, website: "https://" + domain },
      });
    }
    // 3) find the contact by email (to associate the note)
    let contactId = "";
    if (email) {
      const r = await hs("/crm/v3/objects/contacts/search", "POST", {
        filterGroups: [{ filters: [{ propertyName: "email", operator: "EQ", value: email }] }],
        properties: ["email"], limit: 1,
      });
      const d = await r.json();
      if (d.results && d.results[0]) contactId = d.results[0].id;
    }
    // 4) log the note (the observation she sent), associated to company + contact
    const assoc = [];
    if (companyId) assoc.push(a(companyId, 190));   // note → company
    if (contactId) assoc.push(a(contactId, 202));   // note → contact
    const noteBody = `Magni: marked ${status}. Observation sent:\n${observation || "(none)"}`;
    const nr = await hs("/crm/v3/objects/notes", "POST", {
      properties: { hs_note_body: noteBody, hs_timestamp: Date.now() },
      associations: assoc,
    });
    const nd = await nr.json();

    return json({ ok: nr.ok, companyId, contactId, noteId: nd.id || "" });
  } catch (e) {
    return json({ ok: false, error: String(e) }, 502);
  }
}

const clean = (s) => (s == null ? "" : String(s)).trim();
const a = (id, typeId) => ({
  to: { id },
  types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: typeId }],
});
const json = (obj, statusCode = 200) =>
  new Response(JSON.stringify(obj), { status: statusCode, headers: { "Content-Type": "application/json" } });
