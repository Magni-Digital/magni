/**
 * functions/api/upload.js — Cloudflare Pages Function (route: /api/upload).
 *
 * Lets the operator import a lead CSV from the tool — no terminal. It commits the
 * uploaded file into the repo's Lists/ folder via the GitHub API, then triggers
 * the "Daily review queue" Action, which runs build_enriched.py + run.py and
 * redeploys. New leads appear in the queue a few minutes later.
 *
 * Env (set on the Pages project):
 *   GITHUB_TOKEN  — fine-grained PAT for this repo: Contents read/write + Actions read/write
 *   GITHUB_REPO   — "owner/name", e.g. "Magni-Digital/magni"
 *
 * The endpoint is unauthenticated — keep the URL private, or put Cloudflare
 * Access in front of the project if you want a login gate.
 */
const GH = "https://api.github.com";

export async function onRequestPost({ request, env }) {
  const token = (env.GITHUB_TOKEN || "").trim();
  const repo = (env.GITHUB_REPO || "").trim();
  if (!token || !repo) return json({ ok: false, error: "GITHUB_TOKEN / GITHUB_REPO not set on the Pages project" }, 503);

  let text = "", name = "upload";
  try {
    const ct = request.headers.get("content-type") || "";
    if (ct.includes("form-data")) {
      const form = await request.formData();
      const f = form.get("file");
      if (!f || typeof f.text !== "function") return json({ ok: false, error: "no file" }, 400);
      text = await f.text();
      name = (f.name || "upload").replace(/[^a-zA-Z0-9._-]/g, "_");
    } else {
      text = await request.text();
    }
  } catch (e) {
    return json({ ok: false, error: "could not read upload: " + e }, 400);
  }
  if (!text.trim()) return json({ ok: false, error: "empty file" }, 400);
  const rows = text.split(/\r?\n/).filter((l) => l.trim()).length - 1;

  // path must contain "export" so build_enriched.py picks it up
  const path = `Lists/upload-${Date.now()}-${name.replace(/\.csv$/i, "")}-export.csv`;
  const headers = { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json",
    "User-Agent": "magni-upload", "Content-Type": "application/json" };

  try {
    const put = await fetch(`${GH}/repos/${repo}/contents/${encodeURIComponent(path)}`, {
      method: "PUT", headers,
      body: JSON.stringify({ message: `lead upload: ${name}`, content: b64utf8(text), branch: "main" }) });
    if (!put.ok) return json({ ok: false, error: `commit failed (${put.status}): ${(await put.text()).slice(0, 200)}` }, 502);

    const disp = await fetch(`${GH}/repos/${repo}/actions/workflows/daily.yml/dispatches`, {
      method: "POST", headers, body: JSON.stringify({ ref: "main" }) });
    // a 204 = queued; a non-2xx just means they'll get it on the nightly run
    return json({ ok: true, rows, path, triggered: disp.ok });
  } catch (e) {
    return json({ ok: false, error: String(e) }, 502);
  }
}

function b64utf8(s) {
  const bytes = new TextEncoder().encode(s);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json" } });
