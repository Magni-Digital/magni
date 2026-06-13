/* Magni 2.0 — Daily Review Queue (static, no server).
 *
 * Loads data.json, renders one card per qualified practice with its checked
 * site-weakness evidence and an editable grounded observation, and lets Almendra
 * Copy / Mark sent / Skip. Edits + dispositions persist to localStorage so the
 * page survives a reload. "Export sent/skipped" downloads dispositions.json —
 * drop it in state/ and the next `python3 run.py` retires those practices so
 * they never resurface. NOTHING is ever sent to a prospect from here.
 */
const DATA_URL = './data.json';
const LS_KEY = 'magni2_dispositions';

const EMAIL_LABEL = {
  deliverable: '✓ email verified', mx_ok: '✓ email domain OK', risky: 'email: risky',
  undeliverable: 'email: bad address', no_email: 'no email', unverified: 'email unverified',
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

let QUEUE = [];
let DISPOS = loadDispos();   // { dedupe_key: {status, observation, iso} }
let FILTER = '';

function loadDispos() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
  catch (_) { return {}; }
}
function saveDispos() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(DISPOS)); } catch (_) {}
}

async function boot() {
  let practices = [];
  try {
    const r = await fetch(DATA_URL, { cache: 'no-store' });
    if (r.ok) {
      const data = await r.json();
      practices = Array.isArray(data) ? data : (data.practices || []);
    }
  } catch (_) { /* shown as empty below */ }
  QUEUE = practices;
  $('search').addEventListener('input', (e) => { FILTER = e.target.value.toLowerCase().trim(); applyFilter(); });
  $('export').addEventListener('click', exportDispositions);
  render();
}

function dispoFor(p) { return DISPOS[p.dedupe_key] || null; }

function render() {
  const root = $('queue');
  root.innerHTML = '';
  if (!QUEUE.length) { $('empty').hidden = false; updateCounts(); return; }
  $('empty').hidden = true;
  QUEUE.forEach((p, i) => root.appendChild(card(p, i)));
  updateCounts();
  applyFilter();
}

function matchesFilter(p) {
  if (!FILTER) return true;
  return [p.name, p.practice_type, p.location].join(' ').toLowerCase().includes(FILTER);
}
function applyFilter() {
  document.querySelectorAll('.card').forEach((el) => {
    const p = QUEUE[+el.dataset.i];
    el.classList.toggle('hidden', !matchesFilter(p));
  });
}

function card(p, i) {
  const el = document.createElement('article');
  el.className = 'card';
  el.dataset.i = i;
  if (dispoFor(p)) el.classList.add('done');

  const cited = p.observation_cited_signal;
  const evid = (p.evidence || []).map((f) => `
    <li class="${f.id === cited ? 'cited' : ''}">
      <span class="dot ${esc(f.confidence)}"></span>
      <span class="conf">${esc(f.confidence)}</span>
      <span>${esc(f.evidence_str)}</span>
    </li>`).join('');

  const site = p.domain
    ? `<a class="sitelink" href="${esc(p.website_raw || 'https://' + p.domain)}" target="_blank" rel="noopener">${esc(p.domain)} ↗</a>`
    : '<span class="muted">no website found — confirm before claiming</span>';
  const ev = p.email_verified || 'no_email';
  const emailBadge = `<span class="badge email-${esc(ev)}">${esc(EMAIL_LABEL[ev] || ev)}</span>`;
  const langBadge = p.observation_lang === 'es' ? '<span class="badge lang">ES</span>' : '';
  const provBadge = p.domain_provisional
    ? '<span class="badge prov" title="This website was auto-matched from a web search — confirm it really is their site before sending.">⚠ confirm site is theirs</span>'
    : '';

  const c = p.contact || {};
  const contactLine = (c.name || c.role || c.email) ? `
    <div class="contact">Contact: ${esc(c.name || '—')}${c.role ? ' · ' + esc(c.role) : ''}
      ${c.email ? ` · <a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : ''}</div>` : '';

  const d = dispoFor(p);
  const obsText = (d && d.observation != null) ? d.observation : (p.draft_observation || '');
  const obsSrc = p.observation_source === 'claude'
    ? 'drafted by AI from the checked fact above'
    : 'template grounded in the checked fact above';

  el.innerHTML = `
    <div class="card-head">
      <div class="card-titlerow">
        <div>
          <div class="pname">${esc(p.name)}</div>
          <div class="pmeta">
            <span class="tag">${esc((p.practice_type || 'practice').replace(/_/g, ' '))}</span>
            ${p.location ? `<span>${esc(p.location)}</span>` : ''}
            ${p.source ? `<span>${esc(p.source)}</span>` : ''}
          </div>
        </div>
        <div class="score-chip"><div class="n">${p.weakness_score || 0}</div><div class="l">weak</div></div>
      </div>
      <div class="linkrow">${site} ${emailBadge} ${langBadge} ${provBadge}</div>
      ${contactLine}
    </div>
    <div class="card-body">
      <p class="evid-label">Checked findings (the truth the pitch rests on)</p>
      <ul class="evidence">${evid}</ul>

      <p class="obs-label">Draft observation</p>
      <p class="obs-help">Confirm it's true on their site, then rewrite it in your own voice. You send it — this tool never does.</p>
      <textarea class="obs">${esc(obsText)}</textarea>
      <div class="obs-src">${esc(obsSrc)}${cited ? ` · cites: ${esc(cited)}` : ''}</div>

      <div class="actions" data-actions></div>
    </div>`;

  const ta = el.querySelector('textarea.obs');
  ta.addEventListener('input', () => {
    const cur = DISPOS[p.dedupe_key];
    if (cur) { cur.observation = ta.value; saveDispos(); }
  });
  renderActions(el.querySelector('[data-actions]'), p, ta, el);
  return el;
}

function renderActions(host, p, ta, cardEl) {
  const d = dispoFor(p);
  if (d) {
    host.innerHTML = `<span class="status-pill ${esc(d.status)}">${d.status === 'sent' ? 'Marked sent' : 'Skipped'}</span>
      <span class="spacer"></span>
      <button class="ghost" data-undo>Undo</button>`;
    host.querySelector('[data-undo]').onclick = () => undo(p, cardEl);
    return;
  }
  host.innerHTML = `
    <button class="primary" data-sent>Mark sent</button>
    <button data-skip>Skip</button>
    <span class="spacer"></span>
    <button class="ghost" data-copyobs>Copy observation</button>
    ${(p.contact && p.contact.email) ? '<button class="ghost" data-copyemail>Copy email</button>' : ''}`;
  host.querySelector('[data-sent]').onclick = () => disposition(p, 'sent', ta.value, cardEl);
  host.querySelector('[data-skip]').onclick = () => disposition(p, 'skipped', ta.value, cardEl);
  host.querySelector('[data-copyobs]').onclick = () => copy(ta.value, 'Observation copied');
  const ce = host.querySelector('[data-copyemail]');
  if (ce) ce.onclick = () => copy(p.contact.email, 'Email copied');
}

function disposition(p, status, observation, cardEl) {
  DISPOS[p.dedupe_key] = { status, observation, iso: new Date().toISOString() };
  saveDispos();
  cardEl.classList.add('done');
  renderActions(cardEl.querySelector('[data-actions]'), p, cardEl.querySelector('textarea.obs'), cardEl);
  updateCounts();
  toast(status === 'sent' ? 'Marked sent ✓' : 'Skipped');
}

function undo(p, cardEl) {
  delete DISPOS[p.dedupe_key];
  saveDispos();
  cardEl.classList.remove('done');
  renderActions(cardEl.querySelector('[data-actions]'), p, cardEl.querySelector('textarea.obs'), cardEl);
  updateCounts();
}

function updateCounts() {
  let sent = 0, skip = 0;
  QUEUE.forEach((p) => {
    const d = dispoFor(p);
    if (d && d.status === 'sent') sent++;
    else if (d && d.status === 'skipped') skip++;
  });
  $('c-pending').textContent = QUEUE.length - sent - skip;
  $('c-sent').textContent = sent;
  $('c-skip').textContent = skip;
}

function exportDispositions() {
  const out = Object.entries(DISPOS).map(([key, d]) => ({ key, status: d.status, iso: d.iso }));
  if (!out.length) { toast('Nothing sent or skipped yet'); return; }
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'dispositions.json';
  a.click();
  URL.revokeObjectURL(a.href);
  toast(`Exported ${out.length} — drop in state/ before the next run`);
}

function copy(text, msg) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
    .then(() => toast(msg)).catch(() => toast('Copy failed'));
}

let toastTimer;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}

boot();
