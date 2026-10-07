/* Disk Cleanup dashboard — vanilla JS, no dependencies. */
(() => {
  const TOKEN = document.querySelector('meta[name=token]').content;
  const $ = (s, r = document) => r.querySelector(s);
  const GB = 1024 ** 3;

  const TIERS = {
    safe: { name: 'Safe to reclaim', desc: 'Caches and build output the owning tool regenerates on its own. Preselected.', color: 'var(--safe)' },
    care: { name: 'Needs a decision', desc: 'Reclaimable, but it loses some state, can’t go through the Trash, or needs an app quit first.', color: 'var(--care)' },
    personal: { name: 'Your files — not touched', desc: 'Looks like content you made. Shown so you can judge for yourself; it can’t be selected here.', color: 'var(--personal)' },
    inuse: { name: 'App data — not touched', desc: 'Real application data, not junk. Listed so you know it was seen and skipped.', color: 'var(--inuse)' },
  };
  // Fixed category → categorical slot. Never cycled; unlisted categories fall to neutral.
  const CAT_COLOR = {
    'Xcode builds': 'var(--c1)', 'Simulators': 'var(--c2)', 'App caches': 'var(--c3)', 'Package managers': 'var(--c4)',
    'Editors & AI tools': 'var(--c5)', 'Claude scratch': 'var(--c6)', 'Installers': 'var(--c7)', 'Test fixture': 'var(--c8)',
  };
  const NEUTRAL = 'var(--surface-3)';

  const state = { scan: null, disk: null, running: [], settings: null, schedule: null, history: [], runs: [],
    selected: new Set(), expanded: new Set(), treemapMode: 'findings', lastScanKey: null };

  // ---------- helpers ----------
  const fmt = (n) => {
    if (n == null) return '—';
    if (n < 1024) return `${n} B`;
    const u = ['KB', 'MB', 'GB', 'TB']; let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${u[i]}`;
  };
  const gb = (n) => (n / GB).toFixed(n / GB < 10 ? 1 : 0);
  const ago = (t) => {
    if (!t) return '';
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  };
  const when = (t) => new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };

  async function api(path, body) {
    const opts = body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN }, body: JSON.stringify(body) } : {};
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  }
  let toastTimer;
  function toast(msg) {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    const t = el(`<div class="toast">${esc(msg)}</div>`); document.body.appendChild(t);
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.remove(), 3200);
  }

  // ---------- theme ----------
  const themeBtn = $('#themeBtn');
  const saved = localStorage.getItem('theme');
  if (saved) document.documentElement.dataset.theme = saved;
  themeBtn.onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next; localStorage.setItem('theme', next);
  };

  // ---------- derived ----------
  const findings = () => (state.scan?.findings) || [];
  const byTier = (t) => findings().filter((f) => f.tier === t);
  const sum = (arr) => arr.reduce((a, f) => a + (f.bytes || 0), 0);
  const selectedItems = () => findings().filter((f) => state.selected.has(f.id));

  // ---------- hero ----------
  function renderHero() {
    const d = state.disk; if (!d) return;
    const usedFrac = d.used / d.total;
    const safeBytes = sum(byTier('safe'));
    const L = 314.16;
    $('#gaugeFill').setAttribute('stroke-dasharray', `${usedFrac * L} ${L}`);
    const reclaimLen = Math.min(usedFrac * L, (safeBytes / d.total) * L);
    const rec = $('#gaugeReclaim');
    rec.setAttribute('stroke-dasharray', `${reclaimLen} ${L}`);
    rec.setAttribute('stroke-dashoffset', `${-(usedFrac * L - reclaimLen)}`);
    $('#freeNum').textContent = `${gb(d.free)} GB`;
    $('#freeSub').textContent = `free of ${gb(d.total)} GB · ${Math.round(usedFrac * 100)}% used`;
    $('#tSafe').textContent = fmt(safeBytes);
    $('#tSafeHint').textContent = `${byTier('safe').length} items · would leave ${gb(d.free + safeBytes)} GB free`;
    const care = byTier('care');
    $('#tCare').textContent = fmt(sum(care));
    const blocked = care.filter((f) => f.blocked_by.length).length;
    $('#tCareHint').textContent = `${care.length} items` + (blocked ? ` · ${blocked} waiting on an app to quit` : '');
    const freed = state.runs.reduce((a, r) => a + (r.freed || 0), 0);
    $('#tFreed').textContent = fmt(freed);
    $('#tFreedHint').textContent = state.runs.length ? `${state.runs.length} cleanups · last ${ago(state.runs.at(-1).t)}` : 'no cleanups yet';
    const chips = $('#runningChips'); chips.innerHTML = '';
    const relevant = ['Xcode', 'Simulator', 'Cursor', 'Claude', 'Codex', 'Visual Studio Code', 'LM Studio', 'Google Chrome'];
    relevant.forEach((app) => {
      const on = state.running.includes(app);
      chips.appendChild(el(`<span class="chip ${on ? 'on' : ''}"><i class="dot" style="background:${on ? 'var(--care)' : 'var(--surface-3)'}"></i>${esc(app)}</span>`));
    });
    const blockedApps = [...new Set(findings().flatMap((f) => f.blocked_by))];
    $('#runningHint').textContent = blockedApps.length ? `Quit ${blockedApps.join(', ')} to unlock ${findings().filter((f) => f.blocked_by.length).length} more items, then rescan.` : 'Nothing is blocking a cleanup.';
    $('#scanmeta').textContent = !state.scan ? 'Not scanned yet' : !state.scan.finishedAt ? 'Scanning…' : `Scanned ${ago(state.scan.finishedAt)}${state.scan.deep ? ' · deep' : ''}`;
  }

  // ---------- treemap ----------
  function squarify(items, x, y, w, h, out) {
    // items: [{v, ...}] sorted desc; classic squarified treemap.
    if (!items.length) return out;
    const total = items.reduce((a, i) => a + i.v, 0);
    const scale = (w * h) / total;
    let row = [], rest = items.slice();
    const worst = (row, side) => {
      const s = row.reduce((a, i) => a + i.v * scale, 0);
      let mx = 0;
      for (const i of row) { const a = i.v * scale; mx = Math.max(mx, Math.max((side * side * a) / (s * s), (s * s) / (side * side * a))); }
      return mx;
    };
    while (rest.length) {
      const side = Math.min(w, h);
      const next = rest[0];
      if (!row.length || worst([...row, next], side) <= worst(row, side)) { row.push(next); rest.shift(); continue; }
      ({ x, y, w, h } = layoutRow(row, x, y, w, h, scale, out)); row = [];
    }
    if (row.length) layoutRow(row, x, y, w, h, scale, out);
    return out;
  }
  function layoutRow(row, x, y, w, h, scale, out) {
    const s = row.reduce((a, i) => a + i.v * scale, 0);
    if (w >= h) { // vertical strip on the left
      const sw = s / h; let cy = y;
      for (const i of row) { const ih = (i.v * scale) / sw; out.push({ ...i, x, y: cy, w: sw, h: ih }); cy += ih; }
      return { x: x + sw, y, w: w - sw, h };
    }
    const sh = s / w; let cx = x;
    for (const i of row) { const iw = (i.v * scale) / sh; out.push({ ...i, x: cx, y, w: iw, h: sh }); cx += iw; }
    return { x, y: y + sh, w, h: h - sh };
  }
  function renderTreemap() {
    const box = $('#treemap'); const legend = $('#treemapLegend');
    const W = box.clientWidth || 600, H = box.clientHeight || 220;
    box.innerHTML = ''; legend.innerHTML = '';
    const overview = state.scan?.overview || [];
    const mode = state.treemapMode === 'disk' && overview.length ? 'disk' : 'findings';
    let items;
    if (mode === 'disk') {
      items = overview.slice(0, 22).map((o) => ({ v: o.bytes, label: o.display.split('/').pop() || o.display, sub: o.display, color: 'var(--c1)', dim: false }));
      $('#treemapTitle').textContent = 'Where the disk space goes';
    } else {
      items = findings().filter((f) => f.bytes > 0).slice(0, 26).map((f) => ({
        v: f.bytes, label: f.title, sub: f.display, color: CAT_COLOR[f.category] || NEUTRAL,
        dim: !(f.tier === 'safe' || f.tier === 'care'), id: f.id }));
      $('#treemapTitle').textContent = "What's taking the space";
    }
    const total = items.reduce((a, i) => a + i.v, 0);
    $('#treemapSub').innerHTML = overview.length
      ? `<a href="#" data-mode="findings" style="color:${mode === 'findings' ? 'var(--text)' : 'var(--text-3)'};text-decoration:none">Findings</a> · <a href="#" data-mode="disk" style="color:${mode === 'disk' ? 'var(--text)' : 'var(--text-3)'};text-decoration:none">Whole disk</a>`
      : (total ? `${fmt(total)} across ${items.length} largest items` : '');
    $('#treemapSub').querySelectorAll('a').forEach((a) => a.onclick = (e) => { e.preventDefault(); state.treemapMode = a.dataset.mode; renderTreemap(); });
    if (!items.length) { box.appendChild(el('<div class="empty" style="position:absolute;inset:0;display:grid;place-items:center;border:none">Run a scan to see the map</div>')); return; }
    const rects = squarify(items.sort((a, b) => b.v - a.v), 0, 0, W, H, []);
    for (const r of rects) {
      const c = el(`<div class="cell ${r.dim ? 'dim' : ''}" title="${esc(r.label)} — ${fmt(r.v)}\n${esc(r.sub)}"></div>`);
      Object.assign(c.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px`, background: r.color });
      if (r.w > 54 && r.h > 30) c.innerHTML = `<div class="t">${esc(r.label)}</div>${r.h > 44 ? `<div class="s">${fmt(r.v)}</div>` : ''}`;
      if (r.id) { c.style.cursor = 'pointer'; c.onclick = () => { const row = document.getElementById('item-' + r.id); if (row) { row.scrollIntoView({ behavior: 'smooth', block: 'center' }); row.animate([{ boxShadow: '0 0 0 3px var(--accent)' }, { boxShadow: 'none' }], 1400); } }; }
      box.appendChild(c);
    }
    if (mode === 'findings') {
      const cats = [...new Set(items.map((i) => i.sub && findings().find((f) => f.id === i.id)?.category).filter(Boolean))];
      cats.forEach((cat) => legend.appendChild(el(`<span><i class="sw" style="background:${CAT_COLOR[cat] || NEUTRAL}"></i>${esc(cat)}</span>`)));
      if (items.some((i) => i.dim)) legend.appendChild(el(`<span><i class="sw" style="background:${NEUTRAL}"></i>Not actionable</span>`));
    }
  }

  // ---------- donut + trend ----------
  function renderDonut() {
    const svg = $('#donut'); const leg = $('#donutLegend'); svg.innerHTML = ''; leg.innerHTML = '';
    const parts = Object.keys(TIERS).map((t) => ({ t, v: sum(byTier(t)), n: byTier(t).length })).filter((p) => p.v > 0);
    const total = parts.reduce((a, p) => a + p.v, 0);
    $('#donutSub').textContent = total ? `${fmt(total)} examined` : '';
    if (!total) { svg.innerHTML = '<circle cx="75" cy="75" r="56" stroke="var(--surface-3)"/>'; leg.appendChild(el('<span class="faint">No data yet</span>')); return; }
    const C = 2 * Math.PI * 56; let off = 0;
    for (const p of parts) {
      const len = (p.v / total) * C - 2; // 2px surface gap between segments
      svg.appendChild(el(`<circle cx="75" cy="75" r="56" stroke="${TIERS[p.t].color}" stroke-dasharray="${Math.max(0, len)} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 75 75)"><title>${esc(TIERS[p.t].name)}: ${fmt(p.v)}</title></circle>`));
      off += (p.v / total) * C;
      leg.appendChild(el(`<div class="row"><span><i class="dot" style="background:${TIERS[p.t].color}"></i>${esc(TIERS[p.t].name)} <span class="faint">· ${p.n}</span></span><b>${fmt(p.v)}</b></div>`));
    }
    svg.appendChild(el(`<text x="75" y="71" text-anchor="middle" font-size="18" font-weight="700" fill="var(--text)">${esc(fmt(total).split(' ')[0])}</text>`));
    svg.appendChild(el(`<text x="75" y="88" text-anchor="middle" font-size="11" fill="var(--text-3)">${esc(fmt(total).split(' ')[1])} found</text>`));
  }
  function renderTrend() {
    const svg = $('#trend'); svg.innerHTML = '';
    const pts = state.history.slice(-30);
    if (pts.length < 2) { $('#trendSub').textContent = 'Appears after your second scan'; return; }
    const W = 400, H = 64, pad = 6;
    const vals = pts.map((p) => p.free / GB);
    const min = Math.min(...vals) * 0.9, max = Math.max(...vals) * 1.05 || 1;
    const X = (i) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
    const Y = (v) => H - pad - ((v - min) / (max - min)) * (H - 2 * pad);
    const d = vals.map((v, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ');
    svg.appendChild(el(`<path class="area" d="${d} L${X(pts.length - 1)} ${H} L${X(0)} ${H} Z"/>`));
    svg.appendChild(el(`<path class="line" d="${d}"/>`));
    svg.appendChild(el(`<circle class="pt" cx="${X(pts.length - 1)}" cy="${Y(vals.at(-1))}" r="3.5"/>`));
    const delta = vals.at(-1) - vals[0];
    $('#trendSub').textContent = `${gb(pts[0].free)} → ${gb(pts.at(-1).free)} GB free · ${delta >= 0 ? '+' : ''}${delta.toFixed(0)} GB over ${pts.length} scans`;
  }

  // ---------- tiers & items ----------
  function tagsFor(f) {
    const tags = [];
    if (f.blocked_by?.length) tags.push(`<span class="tag warn">Quit ${esc(f.blocked_by.join(', '))} first</span>`);
    else if (f.requires_quit?.length && f.tier === 'care') tags.push(`<span class="tag">${esc(f.requires_quit.join(', '))} is closed ✓</span>`);
    if (f.action?.permanent && f.action.type !== 'none') tags.push('<span class="tag danger">Skips Trash</span>');
    if (f.meta?.stale) tags.push('<span class="tag">Unused 45+ days</span>');
    if (f.meta?.alive && f.meta?.recent) tags.push('<span class="tag warn">Session active</span>');
    tags.push(`<span class="tag cat">${esc(f.category)}</span>`);
    return tags.join('');
  }
  function renderTiers() {
    const root = $('#tiers'); root.innerHTML = '';
    if (!state.scan) { root.appendChild(el('<div class="empty">Press <b>Scan</b> to look for reclaimable space. Nothing is deleted without you choosing it.</div>')); return; }
    for (const [tier, meta] of Object.entries(TIERS)) {
      const list = byTier(tier); if (!list.length) continue;
      const max = Math.max(...list.map((f) => f.bytes), 1);
      const sel = list.filter((f) => f.selectable);
      const sec = el(`<section class="tier" data-tier="${tier}">
        <div class="tier-head"><span class="badge"></span><h2>${esc(meta.name)}</h2><span class="count">${list.length} items</span>
          ${sel.length ? `<span class="actions"><button class="btn sm ghost" data-act="all">Select all</button><button class="btn sm ghost" data-act="none">None</button></span>` : ''}
          <span class="total num">${fmt(sum(list))}</span></div>
        <div class="tier-desc">${esc(meta.desc)}</div><div class="items"></div></section>`);
      sec.querySelectorAll('[data-act]').forEach((b) => b.onclick = () => { sel.forEach((f) => b.dataset.act === 'all' ? state.selected.add(f.id) : state.selected.delete(f.id)); renderTiers(); renderActionBar(); });
      const items = $('.items', sec);
      for (const f of list) items.appendChild(renderItem(f, max));
      root.appendChild(sec);
    }
  }
  function renderItem(f, max) {
    const checked = state.selected.has(f.id);
    const canSel = f.selectable;
    const row = el(`<div class="item ${checked ? 'selected' : ''} ${f.blocked_by.length ? 'blocked' : ''}" id="item-${f.id}">
      <input type="checkbox" ${checked ? 'checked' : ''} ${canSel ? '' : 'disabled'} aria-label="Select ${esc(f.title)}">
      <div class="main">
        <div class="title">${esc(f.title)} ${tagsFor(f)}</div>
        <div class="path"><code title="${esc(f.path)}">${esc(f.display)}</code>
          ${f.path.startsWith('pid:') ? '' : `<button class="btn sm ghost reveal" title="Reveal in Finder">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="13" height="13"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></button>`}
          ${f.mtime ? `<span class="faint" style="font-size:11.5px;white-space:nowrap">· ${ago(f.mtime)}</span>` : ''}</div>
        <div class="reason">${esc(f.reason)}</div>
      </div>
      <div class="side"><span class="size num">${f.bytes ? fmt(f.bytes) : '—'}</span><span class="bar"><i style="width:${Math.max(3, (f.bytes / max) * 100)}%"></i></span>
        ${f.children?.length ? `<button class="btn sm ghost expand">${state.expanded.has(f.id) ? 'Hide' : 'Details'}</button>` : ''}</div>
      ${f.children?.length && state.expanded.has(f.id) ? `<div class="children">${f.children.map((c) => `<span>${esc(c.name)} <b>${fmt(c.bytes)}</b></span>`).join('')}</div>` : ''}
    </div>`);
    const cb = $('input', row);
    cb.onchange = () => { cb.checked ? state.selected.add(f.id) : state.selected.delete(f.id); row.classList.toggle('selected', cb.checked); renderActionBar(); };
    row.onclick = (e) => { if (canSel && e.target === row) { cb.checked = !cb.checked; cb.onchange(); } };
    $('.reveal', row)?.addEventListener('click', async () => { try { await api('/api/reveal', { id: f.id }); } catch (e) { toast(e.message); } });
    $('.expand', row)?.addEventListener('click', () => { state.expanded.has(f.id) ? state.expanded.delete(f.id) : state.expanded.add(f.id); row.replaceWith(renderItem(f, max)); });
    return row;
  }

  // ---------- action bar ----------
  function renderActionBar() {
    const items = selectedItems(); const bar = $('#actionbar');
    bar.classList.toggle('show', items.length > 0);
    const perm = items.filter((i) => i.action.permanent).length;
    $('#selSum').innerHTML = `${items.length} item${items.length === 1 ? '' : 's'} · ${fmt(sum(items))}` + (perm ? `<small>${perm} skip the Trash</small>` : '');
    $('#trashBtn').textContent = perm === items.length && perm ? 'Clean selected' : 'Move to Trash';
  }
  $('#selClear').onclick = () => { state.selected.clear(); renderTiers(); renderActionBar(); };
  $('#trashBtn').onclick = () => confirmClean('trash');
  $('#deleteBtn').onclick = () => confirmClean('delete');

  // ---------- modals ----------
  const modalRoot = $('#modalRoot');
  function openModal(html) { modalRoot.innerHTML = `<div class="modal-bg"><div class="modal" role="dialog" aria-modal="true">${html}</div></div>`; return $('.modal', modalRoot); }
  function closeModal() { modalRoot.innerHTML = ''; }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('.modal .status.working')) closeModal(); });

  function confirmClean(mode) {
    const items = selectedItems(); if (!items.length) return;
    const perm = items.filter((i) => i.action.permanent);
    const title = mode === 'delete' ? `Permanently delete ${items.length} item${items.length > 1 ? 's' : ''}?` : `Move ${items.length} item${items.length > 1 ? 's' : ''} to the Trash?`;
    const m = openModal(`<h2>${title}</h2>
      <p>${fmt(sum(items))} in total. ${mode === 'delete' ? 'This skips the Trash and cannot be undone.' : 'You can restore anything from the Trash until you empty it.'}</p>
      ${perm.length && mode !== 'delete' ? `<div class="callout">${perm.length} item${perm.length > 1 ? 's' : ''} can’t go through the Trash and will be removed directly: ${esc(perm.map((p) => p.title).join(', '))}.</div>` : ''}
      <div class="list">${items.map((i) => `<div class="row"><span class="n">${esc(i.title)}</span><span class="b">${fmt(i.bytes)}</span></div>`).join('')}</div>
      ${mode === 'delete' ? '<p>Type <b>delete</b> to confirm.</p><input type="text" id="confirmText" autocomplete="off" spellcheck="false">' : ''}
      <div class="foot"><button class="btn" id="mCancel">Cancel</button><button class="btn ${mode === 'delete' ? 'danger solid' : 'primary'}" id="mGo" ${mode === 'delete' ? 'disabled' : ''}>${mode === 'delete' ? 'Delete permanently' : 'Move to Trash'}</button></div>`);
    $('#mCancel', m).onclick = closeModal;
    $('#confirmText', m)?.addEventListener('input', (e) => { $('#mGo', m).disabled = e.target.value.trim().toLowerCase() !== 'delete'; });
    $('#mGo', m).onclick = () => startClean(items.map((i) => i.id), mode);
  }

  async function startClean(ids, mode) {
    let res;
    try { res = await api('/api/clean', { ids, mode }); } catch (e) { toast(e.message); return; }
    if (res.error) { toast(res.error); return; }
    if (res.rejected?.length) toast(`${res.rejected.length} skipped: ${res.rejected[0].error}`);
    const m = openModal(`<h2 id="cTitle">${mode === 'delete' ? 'Deleting…' : 'Moving to Trash…'}</h2><p class="big num" id="cFreed">0 B</p><div class="list" id="cList"></div><div id="cFoot"></div>`);
    const poll = async () => {
      const s = await api('/api/clean/status');
      $('#cFreed', m).textContent = fmt(s.freed || 0);
      $('#cList', m).innerHTML = (s.items || []).map((i) => `<div class="row"><span class="status ${i.status}">${i.status === 'done' ? '✓' : i.status === 'failed' ? '!' : ''}</span><span class="n" title="${esc(i.error || i.note || '')}">${esc(i.title)}${i.error ? ` <span class="faint">— ${esc(i.error)}</span>` : ''}</span><span class="b">${fmt(i.bytes)}</span></div>`).join('');
      if (s.running) { setTimeout(poll, 600); return; }
      const failed = (s.items || []).filter((i) => i.status === 'failed').length;
      $('#cTitle', m).textContent = mode === 'delete' ? `Freed ${fmt(s.freed)}` : `Moved ${fmt(s.freed)} to the Trash`;
      $('#cFoot', m).innerHTML = `${mode === 'trash' && s.freed ? '<div class="callout">Disk space is reclaimed when you empty the Trash. Finder → Trash → Empty, or use the Trash item in the list below.</div>' : ''}
        ${failed ? `<p class="muted">${failed} item${failed > 1 ? 's' : ''} failed — hover for the reason.</p>` : ''}
        <div class="foot">${mode === 'trash' && s.freed ? '<button class="btn" id="openTrash">Open Trash in Finder</button>' : ''}<button class="btn primary" id="cDone">Done</button></div>`;
      $('#openTrash', m)?.addEventListener('click', () => api('/api/open-trash', {}));
      $('#cDone', m).onclick = async () => { closeModal(); state.selected.clear(); await loadState(); };
    };
    poll();
  }

  // ---------- scanning ----------
  async function startScan(deep) {
    const r = await api('/api/scan', { deep });
    if (!r.started) { toast('A scan is already running'); }
    state.selected.clear(); renderActionBar();
    pollScan();
  }
  async function pollScan() {
    const s = await api('/api/scan/status');
    const p = $('#progress'); p.hidden = !s.running;
    $('#scanBtn').disabled = s.running; $('#deepBtn').disabled = s.running;
    if (s.running) {
      const frac = s.total ? s.done / s.total : 0;
      p.classList.toggle('indet', s.done === 0);
      $('#progressFill').style.width = `${Math.max(4, frac * 100)}%`;
      $('#progressText').textContent = `Scanning · ${s.current}`;
      $('#progressCount').textContent = `${s.done}/${s.total} · ${s.findings?.length || 0} found`;
      // progressive reveal
      state.scan = { ...(state.scan || {}), findings: (s.findings || []).sort((a, b) => b.bytes - a.bytes), finishedAt: null, overview: state.scan?.overview || [] };
      renderTiers(); renderTreemap(); renderDonut(); renderHero();
      setTimeout(pollScan, 700); return;
    }
    if (s.error) toast(`Scan failed: ${s.error}`);
    await loadState();
  }
  $('#scanBtn').onclick = () => startScan(false);
  $('#deepBtn').onclick = () => startScan(true);

  // ---------- auto cleanup panel ----------
  const hourSel = $('#hour');
  for (let h = 0; h < 24; h++) hourSel.appendChild(el(`<option value="${h}">${h === 0 ? '12 am' : h < 12 ? `${h} am` : h === 12 ? '12 pm' : `${h - 12} pm`}</option>`));
  const AUTO_CATS = ['Xcode builds', 'Simulators', 'App caches', 'Package managers', 'Editors & AI tools', 'Claude scratch', 'Installers'];
  function renderAuto() {
    const a = state.settings?.autoclean; if (!a) return;
    $('#autoSwitch').setAttribute('aria-checked', String(!!a.enabled));
    $('#freq').value = a.frequency; $('#weekday').value = String(a.weekday); hourSel.value = String(a.hour); $('#notify').value = a.notify ? '1' : '0';
    $('#weekdayField').style.display = a.frequency === 'weekly' ? '' : 'none';
    const sched = state.schedule || {};
    $('#scheduleTag').textContent = a.enabled ? (sched.installed ? `Scheduled · ${a.frequency === 'weekly' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][a.weekday] + ' ' : 'daily '}${hourSel.options[a.hour].text}` : 'Enabled, but not installed — toggle again') : 'Off';
    $('#scheduleTag').className = 'tag ' + (a.enabled && sched.installed ? '' : a.enabled ? 'warn' : '');
    const cats = $('#autoCats'); cats.innerHTML = '';
    AUTO_CATS.forEach((c) => {
      const on = a.categories.includes(c);
      const l = el(`<label><input type="checkbox" ${on ? 'checked' : ''}> <i class="sw" style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${CAT_COLOR[c]}"></i>${esc(c)}</label>`);
      $('input', l).onchange = (e) => { const next = e.target.checked ? [...a.categories, c] : a.categories.filter((x) => x !== c); saveSettings({ autoclean: { categories: next } }); };
      cats.appendChild(l);
    });
    const would = findings().filter((f) => f.tier === 'safe' && f.selectable && !f.action.permanent && a.categories.includes(f.category));
    $('#autoPreview').innerHTML = state.scan ? `Based on the last scan, the next run would move <b>${fmt(sum(would))}</b> across ${would.length} items to the Trash.` + (would.length ? `<ul>${would.slice(0, 6).map((f) => `<li>${esc(f.title)} <span class="faint">· ${fmt(f.bytes)}</span></li>`).join('')}${would.length > 6 ? `<li class="faint">…and ${would.length - 6} more</li>` : ''}</ul>` : '') : '';
    const runs = $('#runs'); runs.innerHTML = state.runs.length ? '<div class="faint" style="font-size:12px;margin-top:4px">Recent cleanups</div>' : '';
    [...state.runs].reverse().slice(0, 8).forEach((r) => runs.appendChild(el(`<div class="run"><span class="when">${when(r.t)}</span><span>${r.kind === 'auto' ? 'Auto' : 'Manual'} · ${r.mode === 'delete' ? 'deleted' : 'to Trash'} <b>${fmt(r.freed)}</b> across ${r.count} item${r.count === 1 ? '' : 's'}${r.dryRun ? ' (dry run)' : ''}</span></div>`)));
  }
  async function saveSettings(patch) { state.settings = await api('/api/settings', patch); renderAuto(); }
  $('#autoSwitch').onclick = async () => {
    const on = $('#autoSwitch').getAttribute('aria-checked') !== 'true';
    const r = await api('/api/schedule', { enabled: on });
    if (r.error) toast(r.error); else toast(on ? 'Auto cleanup scheduled' : 'Auto cleanup turned off');
    await loadState();
  };
  $('#freq').onchange = (e) => saveSettings({ autoclean: { frequency: e.target.value } });
  $('#weekday').onchange = (e) => saveSettings({ autoclean: { weekday: +e.target.value } });
  hourSel.onchange = (e) => saveSettings({ autoclean: { hour: +e.target.value } });
  $('#notify').onchange = (e) => saveSettings({ autoclean: { notify: e.target.value === '1' } });
  $('#saveExcludes').onclick = async () => { await saveSettings({ excludes: $('#excludes').value.split('\n').map((s) => s.trim()).filter(Boolean) }); toast('Saved — rescan to apply'); };

  // ---------- load ----------
  async function loadState() {
    const s = await api('/api/state');
    Object.assign(state, { scan: s.scan, disk: s.disk, running: s.running, settings: s.settings, schedule: s.schedule, history: s.history, runs: s.runs });
    const key = s.scan?.finishedAt;
    if (key && key !== state.lastScanKey) { // new scan: preselect the safe tier
      state.lastScanKey = key; state.selected = new Set(byTier('safe').filter((f) => f.selectable).map((f) => f.id));
    } else { state.selected = new Set([...state.selected].filter((id) => findings().some((f) => f.id === id && f.selectable))); }
    $('#excludes').value = (s.settings.excludes || []).join('\n');
    renderHero(); renderTreemap(); renderDonut(); renderTrend(); renderTiers(); renderActionBar(); renderAuto();
    if (s.scanning?.running) pollScan();
  }
  addEventListener('resize', () => renderTreemap());
  setInterval(() => fetch('/api/ping').catch(() => {}), 60_000); // keeps an idle-exit server alive while the tab is open
  loadState().then(() => { if (!state.scan) startScan(false); }).catch((e) => toast(e.message));
})();
