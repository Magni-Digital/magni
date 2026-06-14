/* Magni 2.0 — review queue (static, no server).
 *
 * Two views: "queue" (qualified weak-site leads from data.json) and "research"
 * (no-site leads from research.json — LinkedIn-first, for manual lookup). Each
 * card carries LinkedIn + firmographics. Dispositions + edits persist to
 * localStorage; on "Mark sent" the queue posts to /api/hubspot (best-effort).
 * Nothing is ever sent to a prospect from here.
 */
const LS_KEY = 'magni2_dispositions';
const EMAIL_LABEL = {
  deliverable: '✓ email verified', mx_ok: '✓ email domain OK', risky: 'email: risky',
  undeliverable: 'email: bad address', no_email: 'no email', unverified: 'email unverified',
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

let DATA = { queue: [], research: [] };
let VIEW = 'queue';
let FILTERS = { text: '', vertical: '', city: '', email: '' };
let DISPOS = loadDispos();

function loadDispos() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; } }
function saveDispos() { try { localStorage.setItem(LS_KEY, JSON.stringify(DISPOS)); } catch {} }

async function boot() {
  const [q, r] = await Promise.all([fetchJson('./data.json'), fetchJson('./research.json')]);
  DATA.queue = (q && (q.practices || q)) || [];
  DATA.research = (r && (r.leads || r)) || [];
  $('n-queue').textContent = DATA.queue.length;
  $('n-research').textContent = DATA.research.length;
  populateFilters();
  wire();
  render();
}
async function fetchJson(u) { try { const r = await fetch(u, { cache: 'no-store' }); return r.ok ? await r.json() : null; } catch { return null; } }

function wire() {
  document.querySelectorAll('.tab').forEach((t) => t.onclick = () => {
    VIEW = t.dataset.view;
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
    $('lede-queue').hidden = VIEW !== 'queue';
    $('lede-research').hidden = VIEW !== 'research';
    render();
  });
  $('search').oninput = (e) => { FILTERS.text = e.target.value.toLowerCase().trim(); render(); };
  $('f-vertical').onchange = (e) => { FILTERS.vertical = e.target.value; render(); };
  $('f-city').onchange = (e) => { FILTERS.city = e.target.value; render(); };
  $('f-email').onchange = (e) => { FILTERS.email = e.target.value; render(); };
  $('f-clear').onclick = () => {
    FILTERS = { text: '', vertical: '', city: '', email: '' };
    $('search').value = ''; $('f-vertical').value = ''; $('f-city').value = ''; $('f-email').value = '';
    render();
  };
  $('export').onclick = exportDispositions;
}

function populateFilters() {
  const all = [...DATA.queue, ...DATA.research];
  const verts = [...new Set(all.map((p) => (p.practice_type || '').replace(/_/g, ' ')).filter(Boolean))].sort();
  const cities = [...new Set(all.map((p) => p.city).filter(Boolean))].sort();
  for (const v of verts) $('f-vertical').add(new Option(v, v));
  for (const c of cities) $('f-city').add(new Option(c, c));
}

function emailOf(p) { return (p.contact && p.contact.email) || p.verified_email || ''; }
function matches(p) {
  if (FILTERS.text && !(p.name || '').toLowerCase().includes(FILTERS.text)) return false;
  if (FILTERS.vertical && (p.practice_type || '').replace(/_/g, ' ') !== FILTERS.vertical) return false;
  if (FILTERS.city && p.city !== FILTERS.city) return false;
  if (FILTERS.email === 'has' && !emailOf(p)) return false;
  if (FILTERS.email === 'needs' && emailOf(p)) return false;
  return true;
}

function render() {
  const root = $('queue'); root.innerHTML = '';
  const list = DATA[VIEW].filter(matches);
  if (!list.length) { $('empty').hidden = false; updateCounts(); return; }
  $('empty').hidden = true;
  list.forEach((p) => root.appendChild(VIEW === 'queue' ? queueCard(p) : researchCard(p)));
  updateCounts();
}

function dispoFor(p) { return DISPOS[p.dedupe_key] || null; }

function firmo(p) {
  const bits = [];
  if (p.employee_count) bits.push(esc(p.employee_count) + ' emp');
  else if (p.company_size) bits.push(esc(p.company_size));
  if (p.industry) bits.push(esc(p.industry));
  return bits.length ? `<div class="firmo">${bits.join(' · ')}</div>` : '';
}
function linkedinRow(p) {
  const out = [];
  if (p.person_linkedin) out.push(`<a class="li" href="${esc(p.person_linkedin)}" target="_blank" rel="noopener">in/ contact ↗</a>`);
  if (p.company_linkedin) out.push(`<a class="li" href="${esc(p.company_linkedin)}" target="_blank" rel="noopener">in/ company ↗</a>`);
  return out.join(' ');
}
function header(p, rightChip) {
  const c = p.contact || {};
  const contact = (c.name || c.role || c.email) ? `<div class="contact">Contact: ${esc(c.name || '—')}${c.role ? ' · ' + esc(c.role) : ''}${c.email ? ` · <a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : ''}</div>` : '';
  return `
    <div class="card-titlerow">
      <div>
        <div class="pname">${esc(p.name)}</div>
        <div class="pmeta">
          <span class="tag">${esc((p.practice_type || 'practice').replace(/_/g, ' '))}</span>
          ${p.city ? `<span>${esc(p.city)}${p.state ? ', ' + esc(p.state) : ''}</span>` : ''}
          ${p.source ? `<span>${esc(p.source)}</span>` : ''}
        </div>
      </div>
      ${rightChip}
    </div>
    ${firmo(p)}
    ${contact}`;
}

function queueCard(p) {
  const el = document.createElement('article'); el.className = 'card';
  if (dispoFor(p)) el.classList.add('done');
  const cited = p.observation_cited_signal;
  const evid = (p.evidence || []).map((f) => `
    <li class="${f.id === cited ? 'cited' : ''}"><span class="dot ${esc(f.confidence)}"></span>
      <span class="conf">${esc(f.confidence)}</span><span>${esc(f.evidence_str)}</span></li>`).join('');
  const site = p.domain ? `<a class="sitelink" href="${esc(p.website_raw || 'https://' + p.domain)}" target="_blank" rel="noopener">${esc(p.domain)} ↗</a>` : '<span class="muted">no website</span>';
  const ev = p.email_verified || 'no_email';
  const prov = p.domain_provisional ? '<span class="badge prov" title="auto-matched site — confirm it is theirs">⚠ confirm site</span>' : '';
  const chip = `<div class="score-chip"><div class="n">${p.weakness_score || 0}</div><div class="l">weak</div></div>`;
  const d = dispoFor(p);
  const obsText = (d && d.observation != null) ? d.observation : (p.draft_observation || '');
  el.innerHTML = `
    <div class="card-head">${header(p, chip)}
      <div class="linkrow">${site} <span class="badge email-${esc(ev)}">${esc(EMAIL_LABEL[ev] || ev)}</span> ${prov} ${linkedinRow(p)}</div>
    </div>
    <div class="card-body">
      <p class="evid-label">Checked findings</p>
      <ul class="evidence">${evid}</ul>
      <p class="obs-label">Draft observation</p>
      <textarea class="obs">${esc(obsText)}</textarea>
      <div class="obs-src">${p.observation_source === 'claude' ? 'AI-drafted' : 'template'} from the checked fact${cited ? ` · cites: ${esc(cited)}` : ''}</div>
      <div class="actions" data-actions></div>
    </div>`;
  const ta = el.querySelector('textarea.obs');
  ta.oninput = () => { const cur = DISPOS[p.dedupe_key]; if (cur) { cur.observation = ta.value; saveDispos(); } };
  renderActions(el.querySelector('[data-actions]'), p, ta, el, true);
  return el;
}

function researchCard(p) {
  const el = document.createElement('article'); el.className = 'card';
  if (dispoFor(p)) el.classList.add('done');
  const d = dispoFor(p);
  const noteText = (d && d.observation != null) ? d.observation : '';
  el.innerHTML = `
    <div class="card-head">${header(p, '<span class="score-chip nosite"><div class="l">no site<br>found</div></span>')}
      <div class="linkrow">${linkedinRow(p) || '<span class="muted">no LinkedIn</span>'}</div>
    </div>
    <div class="card-body">
      ${p.description ? `<p class="desc">${esc(p.description)}</p>` : ''}
      <p class="obs-help">Enrichment found no website. Open their LinkedIn, check for a site, then write your observation (no site at all is a strong opener).</p>
      <textarea class="obs" placeholder="Your observation once you've looked them up…">${esc(noteText)}</textarea>
      <div class="actions" data-actions></div>
    </div>`;
  const ta = el.querySelector('textarea.obs');
  ta.oninput = () => { const cur = DISPOS[p.dedupe_key]; if (cur) { cur.observation = ta.value; saveDispos(); } };
  renderActions(el.querySelector('[data-actions]'), p, ta, el, false);
  return el;
}

function renderActions(host, p, ta, cardEl, isQueue) {
  const d = dispoFor(p);
  if (d) {
    host.innerHTML = `<span class="status-pill ${esc(d.status)}">${d.status === 'sent' ? 'Marked sent' : 'Skipped'}</span><span class="spacer"></span><button class="ghost" data-undo>Undo</button>`;
    host.querySelector('[data-undo]').onclick = () => undo(p, cardEl);
    return;
  }
  host.innerHTML = `<button class="primary" data-sent>Mark sent</button><button data-skip>Skip</button><span class="spacer"></span>
    <button class="ghost" data-copyobs>Copy</button>${(p.contact && p.contact.email) ? '<button class="ghost" data-copyemail>Copy email</button>' : ''}`;
  host.querySelector('[data-sent]').onclick = () => disposition(p, 'sent', ta.value, cardEl, isQueue);
  host.querySelector('[data-skip]').onclick = () => disposition(p, 'skipped', ta.value, cardEl, isQueue);
  host.querySelector('[data-copyobs]').onclick = () => copy(ta.value, 'Copied');
  const ce = host.querySelector('[data-copyemail]');
  if (ce) ce.onclick = () => copy(p.contact.email, 'Email copied');
}

function disposition(p, status, observation, cardEl, isQueue) {
  DISPOS[p.dedupe_key] = { status, observation, iso: new Date().toISOString() };
  saveDispos();
  cardEl.classList.add('done');
  renderActions(cardEl.querySelector('[data-actions]'), p, cardEl.querySelector('textarea.obs'), cardEl, isQueue);
  updateCounts();
  toast(status === 'sent' ? 'Marked sent ✓' : 'Skipped');
  if (status === 'sent' && isQueue) {
    saveToHubSpot({ hsCompanyId: p.hs_company_id || '', domain: p.domain || '', companyName: p.name || '',
      email: emailOf(p), observation, status });
  }
}
async function saveToHubSpot(payload) {
  try {
    const r = await fetch('/api/hubspot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const d = await r.json().catch(() => ({ ok: r.ok }));
    toast(d.ok ? 'Saved to HubSpot ✓' : 'Sent saved locally (HubSpot: ' + (d.error || 'unavailable') + ')');
  } catch { toast('Sent saved locally (HubSpot offline)'); }
}
function undo(p, cardEl) {
  delete DISPOS[p.dedupe_key]; saveDispos(); cardEl.classList.remove('done');
  renderActions(cardEl.querySelector('[data-actions]'), p, cardEl.querySelector('textarea.obs'), cardEl, VIEW === 'queue');
  updateCounts();
}
function updateCounts() {
  const list = DATA[VIEW];
  let sent = 0, skip = 0;
  list.forEach((p) => { const d = dispoFor(p); if (d && d.status === 'sent') sent++; else if (d && d.status === 'skipped') skip++; });
  $('c-pending').textContent = list.length - sent - skip; $('c-sent').textContent = sent; $('c-skip').textContent = skip;
}
function exportDispositions() {
  const out = Object.entries(DISPOS).map(([key, d]) => ({ key, status: d.status, iso: d.iso }));
  if (!out.length) { toast('Nothing sent or skipped yet'); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }));
  a.download = 'dispositions.json'; a.click(); URL.revokeObjectURL(a.href);
  toast(`Exported ${out.length} — drop in state/ before the next run`);
}
function copy(text, msg) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast(msg)).catch(() => toast('Copy failed'));
}
let toastTimer;
function toast(msg) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2200); }

boot();
