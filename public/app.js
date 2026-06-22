/* Magni 2.0 — review queue (static, no server).
 *
 * Two views: "queue" (qualified weak-site leads from data.json) and "research"
 * (no-site leads from research.json — LinkedIn-first, for manual lookup). Each
 * card carries LinkedIn + firmographics. Dispositions + edits persist to
 * localStorage, and Download CSV exports the day's work (with her edits + notes)
 * into the spreadsheet's columns. No external systems. Nothing is ever sent to a
 * prospect from here.
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
let NOTES = loadNotes();

function loadDispos() { try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch { return {}; } }
function saveDispos() { try { localStorage.setItem(LS_KEY, JSON.stringify(DISPOS)); } catch {} }
function loadNotes() { try { return JSON.parse(localStorage.getItem('magni2_notes')) || {}; } catch { return {}; } }
function saveNotes() { try { localStorage.setItem('magni2_notes', JSON.stringify(NOTES)); } catch {} }
let SITES = (() => { try { return JSON.parse(localStorage.getItem('magni2_sites')) || {}; } catch { return {}; } })();
function saveSites() { try { localStorage.setItem('magni2_sites', JSON.stringify(SITES)); } catch {} }

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
  $('download').onclick = downloadCsv;
  $('template').onclick = downloadTemplate;
  const how = $('how');
  $('how-open').onclick = () => { how.hidden = false; };
  $('how-close').onclick = () => { how.hidden = true; };
  how.onclick = (e) => { if (e.target === how) how.hidden = true; };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') how.hidden = true; });
}

// Blank import template with the exact headers (company + website required).
function downloadTemplate() {
  const headers = ['company', 'website', 'email', 'contact_name', 'title', 'city', 'state'];
  const example = ['Bright Smile Dental', 'https://brightsmiledental.com', 'owner@brightsmiledental.com', 'Dr. Lena Ruiz', 'Owner', 'Austin', 'TX'];
  const csv = [headers, example].map((r) => r.map((c) => '"' + c + '"').join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'magni-import-template.csv'; a.click(); URL.revokeObjectURL(a.href);
  toast('Headers downloaded — put these as row 1 of your import Google Sheet');
}

// Build the day's list as CSV — in the CRM's columns, carrying her edited
// observation, notes, status, and any website she found. The sheet IS the CRM now.
function downloadCsv() {
  const list = DATA[VIEW].filter(matches);
  const cols = ['Company', 'Contact Name', 'Role', 'Website URL', 'Site Observation (1 line)',
    'Email', 'Email Verified?', 'Source', 'Status', 'Notes'];
  const EVL = { deliverable: 'Verified', mx_ok: 'Verified', risky: 'Risky', undeliverable: 'Bad', unverified: 'Unverified', no_email: 'No email' };
  const rows = [cols];
  list.forEach((p) => {
    const d = dispoFor(p);
    const obs = (d && d.observation != null) ? d.observation : (p.draft_observation || '');
    const site = p.website_raw || (p.domain ? 'https://' + p.domain : (SITES[p.dedupe_key] ? 'https://' + SITES[p.dedupe_key] : ''));
    rows.push([p.name || '', (p.contact && p.contact.name) || '', (p.contact && p.contact.role) || '', site, obs,
      emailOf(p), EVL[p.email_verified] || p.email_verified || '', p.source || '',
      d ? (d.status === 'sent' ? '1st Sent' : 'Skipped') : 'Not Contacted', NOTES[p.dedupe_key] || '']);
  });
  const csv = rows.map((r) => r.map((c) => '"' + String(c == null ? '' : c).replace(/"/g, '""') + '"').join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'magni-' + VIEW + '.csv'; a.click(); URL.revokeObjectURL(a.href);
  toast('CSV downloaded (' + (list.length) + ' rows)');
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
function detailRows(p, includeDesc = true) {
  const rows = [
    ['Website', p.website_raw || (p.domain ? 'https://' + p.domain : '')],
    ['Employees', p.employee_count || p.company_size],
    ['Industry', p.industry],
    ['Founded', p.founded],
    ['Annual revenue', p.annual_revenue],
    ['LinkedIn followers', p.follower_count],
    ['Location', [p.city, p.state].filter(Boolean).join(', ')],
    ['Source', p.source],
  ].filter((r) => r[1]);
  const desc = (includeDesc && p.description) ? `<p class="desc">${esc(p.description)}</p>` : '';
  return `<button class="moreinfo" data-more>More info ▾</button>
    <div class="details" hidden>${desc}<dl class="detgrid">${rows.map((r) => `<dt>${esc(r[0])}</dt><dd>${esc(r[1])}</dd>`).join('')}</dl></div>`;
}

function wireMore(el) {
  const btn = el.querySelector('[data-more]');
  if (!btn) return;
  btn.onclick = () => {
    const d = el.querySelector('.details');
    const open = d.hasAttribute('hidden') ? (d.removeAttribute('hidden'), true) : (d.setAttribute('hidden', ''), false);
    btn.textContent = open ? 'Less info ▴' : 'More info ▾';
  };
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
      ${notesBlock(p)}
      ${detailRows(p, true)}
      <div class="actions" data-actions></div>
    </div>`;
  const ta = el.querySelector('textarea.obs');
  ta.oninput = () => { const cur = DISPOS[p.dedupe_key]; if (cur) { cur.observation = ta.value; saveDispos(); } };
  renderActions(el.querySelector('[data-actions]'), p, ta, el, true);
  wireMore(el); wireExtras(el, p);
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
      ${siteBlock(p)}
      ${notesBlock(p)}
      ${detailRows(p, false)}
      <div class="actions" data-actions></div>
    </div>`;
  const ta = el.querySelector('textarea.obs');
  ta.oninput = () => { const cur = DISPOS[p.dedupe_key]; if (cur) { cur.observation = ta.value; saveDispos(); } };
  renderActions(el.querySelector('[data-actions]'), p, ta, el, false);
  wireMore(el); wireExtras(el, p);
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
}

function notesBlock(p) {
  return `<div class="notes-wrap">
    <p class="obs-label">Your notes</p>
    <textarea class="note" placeholder="Notes that stay with this record (saved to HubSpot)…">${esc(NOTES[p.dedupe_key] || '')}</textarea>
    <button class="ghost small" data-savenote>Save note</button></div>`;
}
function siteBlock(p) {
  return `<div class="site-wrap">
    <p class="obs-label">Found their website? Add it</p>
    <input class="siteinput" type="url" placeholder="https://theirpractice.com" />
    <button class="ghost small" data-savesite>Save site</button>
    <p class="obs-help">Saves to HubSpot; the next run qualifies it and it moves to Today's queue.</p></div>`;
}
function wireExtras(el, p) {
  const nb = el.querySelector('[data-savenote]');
  if (nb) nb.onclick = () => {
    NOTES[p.dedupe_key] = el.querySelector('textarea.note').value; saveNotes();
    toast('Note saved ✓ (included in Download CSV)');
  };
  const sb = el.querySelector('[data-savesite]');
  if (sb) sb.onclick = () => {
    const url = el.querySelector('.siteinput').value.trim();
    if (!url) { toast('Enter a website first'); return; }
    SITES[p.dedupe_key] = url.replace(/^https?:\/\//, '').replace(/\/.*$/, ''); saveSites();
    toast('Website saved ✓ — it\'s in your CSV; add to inbox.csv to qualify it');
  };
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
