/* Project Brain WebUI — app.js */
/* Extracted from server.py f-string */

/* ════════════════════════════════════════════════
   Project Brain Web UI — 純 JS 實作（無外部依賴）
   Force simulation: Verlet + spring + repulsion
   ════════════════════════════════════════════════ */

const KIND_COLOR = {
  Pitfall:'#f87171', Decision:'#34d399', Rule:'#60a5fa',
  ADR:'#c084fc', Component:'#94a3b8', Architecture:'#fb923c', Note:'#fbbf24'
};
const KIND_LABEL = {
  Pitfall:'踩坑', Decision:'決策', Rule:'規則',
  ADR:'ADR', Component:'組件', Architecture:'架構', Note:'筆記'
};

// ── State ─────────────────────────────────────
let allNodes = [], allLinks = [], nodeMap = {};
let currentFilter = 'all';
let selectedId = null;
let currentNodeData = null;
let searchHits = null;   // Set of matching ids, or null
let alpha = 0;

// ── SVG transform ──────────────────────────────
let tx = 0, ty = 0, sk = 1;
const svg    = document.getElementById('canvas');
const NS     = 'http://www.w3.org/2000/svg';
let gLinks, gNodes, gLabels, rootG;

function initSVG() {
  svg.innerHTML = '';
  rootG  = document.createElementNS(NS,'g'); svg.appendChild(rootG);
  gLinks = document.createElementNS(NS,'g'); rootG.appendChild(gLinks);
  gNodes = document.createElementNS(NS,'g'); rootG.appendChild(gNodes);
  gLabels= document.createElementNS(NS,'g'); rootG.appendChild(gLabels);
  applyTx();
}

function applyTx() {
  rootG.setAttribute('transform', `translate(${tx},${ty}) scale(${sk})`);
}

function zoom(factor) {
  const W = svg.clientWidth, H = svg.clientHeight;
  tx = W/2 + (tx - W/2) * factor;
  ty = H/2 + (ty - H/2) * factor;
  sk *= factor;
  applyTx();
}

function resetView() {
  tx = 0; ty = 0; sk = 1; applyTx();
  clearSelection();
}

// ── Wheel zoom ─────────────────────────────────
svg.addEventListener('wheel', e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  const r  = svg.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  tx = mx + (tx - mx) * factor;
  ty = my + (ty - my) * factor;
  sk *= factor; applyTx();
}, {passive: false});

// ── Pan (drag on background) ───────────────────
let panning = false, panX0, panY0, tx0, ty0;
svg.addEventListener('mousedown', e => {
  if (e.target === svg || e.target === rootG || e.target === gLinks) {
    panning = true; panX0 = e.clientX; panY0 = e.clientY; tx0 = tx; ty0 = ty;
    e.preventDefault();
  }
});
window.addEventListener('mousemove', e => {
  if (!panning) return;
  tx = tx0 + e.clientX - panX0;
  ty = ty0 + e.clientY - panY0;
  applyTx();
});
window.addEventListener('mouseup', () => { panning = false; });

// ── Force simulation ────────────────────────────
const REPULSION = 4000, LINK_DIST = 90, SPRING_K = 0.06, DAMPING = 0.72, CENTER_K = 0.004;

function initPositions() {
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  allNodes.forEach(n => {
    if (!n.x || !n.y) {
      const angle = Math.random() * Math.PI * 2;
      const r     = Math.random() * 200 + 50;
      n.x = W/2 + Math.cos(angle)*r;
      n.y = H/2 + Math.sin(angle)*r;
    }
    n.vx = 0; n.vy = 0;
  });
  allLinks.forEach(l => {
    l._src = nodeMap[l.source]; l._tgt = nodeMap[l.target];
  });
}

function simStep() {
  if (alpha < 0.003) return;
  alpha *= 0.976;
  const W = svg.clientWidth || 800, H = svg.clientHeight || 600;
  const cx = W/2, cy = H/2;
  const n  = allNodes.length;

  // Dampen velocities
  for (const nd of allNodes) {
    if (nd.fixed) continue;
    nd.vx = (nd.vx||0) * DAMPING;
    nd.vy = (nd.vy||0) * DAMPING;
  }

  // Repulsion (O(n²), fine for n < 500)
  for (let i = 0; i < n; i++) {
    const a = allNodes[i];
    for (let j = i+1; j < n; j++) {
      const b  = allNodes[j];
      let dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx*dx + dy*dy || 0.01;
      const d  = Math.sqrt(d2);
      const f  = REPULSION * alpha / d2;
      const fx = dx/d * f, fy = dy/d * f;
      if (!a.fixed) { a.vx -= fx; a.vy -= fy; }
      if (!b.fixed) { b.vx += fx; b.vy += fy; }
    }
  }

  // Spring along links
  for (const l of allLinks) {
    const a = l._src, b = l._tgt;
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const d  = Math.sqrt(dx*dx + dy*dy) || 1;
    const f  = (d - LINK_DIST) * SPRING_K * alpha;
    const fx = dx/d*f, fy = dy/d*f;
    if (!a.fixed) { a.vx += fx; a.vy += fy; }
    if (!b.fixed) { b.vx -= fx; b.vy -= fy; }
  }

  // Centering + position update
  for (const nd of allNodes) {
    if (nd.fixed) continue;
    nd.vx += (cx - nd.x) * CENTER_K * alpha;
    nd.vy += (cy - nd.y) * CENTER_K * alpha;
    nd.x  += nd.vx; nd.y += nd.vy;
  }

  updateSVGPositions();
  requestAnimationFrame(simStep);
}

// ── SVG rendering ───────────────────────────────
function render() {
  initSVG();
  // Links
  allLinks.forEach(l => {
    const line = document.createElementNS(NS,'line');
    line.setAttribute('stroke', getComputedStyle(document.documentElement).getPropertyValue('--border2').trim());
    line.setAttribute('stroke-width','1.2');
    line.setAttribute('stroke-linecap','round');
    l._el = line;
    gLinks.appendChild(line);
  });
  // Nodes (outer ring = confidence, inner = kind color)
  allNodes.forEach(nd => {
    const g = document.createElementNS(NS,'g');
    g.style.cursor = 'pointer';
    // Confidence ring
    const ring = document.createElementNS(NS,'circle');
    ring.setAttribute('r', nd.size + 3.5);
    ring.setAttribute('fill','none');
    ring.setAttribute('stroke', nd.conf_color);
    ring.setAttribute('stroke-width','2');
    ring.setAttribute('opacity','0.7');
    nd._ring = ring; g.appendChild(ring);
    // Kind fill
    const circ = document.createElementNS(NS,'circle');
    circ.setAttribute('r', nd.size);
    circ.setAttribute('fill', nd.color);
    circ.setAttribute('fill-opacity','0.88');
    circ.setAttribute('stroke', nd.color);
    circ.setAttribute('stroke-opacity','0.35');
    circ.setAttribute('stroke-width','2.5');
    circ.style.filter = `drop-shadow(0 0 4px ${nd.color}66)`;
    nd._circ = circ; g.appendChild(circ);
    // Events
    g.addEventListener('mouseenter', e => onNodeHover(e, nd));
    g.addEventListener('mouseleave', () => onNodeLeave(nd));
    g.addEventListener('click',      e => { e.stopPropagation(); onNodeClick(nd); });
    // Drag
    let dragging = false, dx0, dy0, nx0, ny0;
    g.addEventListener('mousedown', e => {
      e.stopPropagation(); dragging = true;
      dx0 = e.clientX; dy0 = e.clientY; nx0 = nd.x; ny0 = nd.y;
    });
    window.addEventListener('mousemove', e => {
      if (!dragging) return;
      nd.x = nx0 + (e.clientX - dx0) / sk;
      nd.y = ny0 + (e.clientY - dy0) / sk;
      nd.fixed = true;
      updateSVGPositions();
    });
    window.addEventListener('mouseup', () => {
      if (dragging) { dragging = false; nd.fixed = false; alpha = Math.max(alpha, 0.1); requestAnimationFrame(simStep); }
    });
    nd._g = g;
    gNodes.appendChild(g);
  });
  // Labels
  allNodes.forEach(nd => {
    const t = document.createElementNS(NS,'text');
    t.textContent = nd.title.length > 12 ? nd.title.slice(0,12)+'…' : nd.title;
    t.setAttribute('font-size','8.5');
    t.setAttribute('fill', getComputedStyle(document.documentElement).getPropertyValue('--text3').trim());
    t.setAttribute('text-anchor','middle');
    t.style.pointerEvents = 'none';
    t.style.userSelect    = 'none';
    nd._lbl = t;
    gLabels.appendChild(t);
  });
  // Click canvas to deselect
  svg.addEventListener('click', clearSelection);
  updateSVGPositions();
  applyOpacity();
}

function updateSVGPositions() {
  allLinks.forEach(l => {
    if (!l._el || !l._src || !l._tgt) return;
    l._el.setAttribute('x1', l._src.x); l._el.setAttribute('y1', l._src.y);
    l._el.setAttribute('x2', l._tgt.x); l._el.setAttribute('y2', l._tgt.y);
  });
  allNodes.forEach(nd => {
    if (nd._circ) {
      nd._ring.setAttribute('cx', nd.x); nd._ring.setAttribute('cy', nd.y);
      nd._circ.setAttribute('cx', nd.x); nd._circ.setAttribute('cy', nd.y);
    }
    if (nd._lbl) {
      nd._lbl.setAttribute('x', nd.x);
      nd._lbl.setAttribute('y', nd.y + nd.size + 11);
    }
  });
}

// ── Hover / click ───────────────────────────────
const tip   = document.getElementById('tooltip');
const ttKind= document.getElementById('tt-kind');
const ttTitl= document.getElementById('tt-title');
const ttConf= document.getElementById('tt-conf');

function onNodeHover(e, nd) {
  if (panning) return;
  tip.style.display = 'block';
  ttKind.textContent  = KIND_LABEL[nd.kind] || nd.kind;
  ttKind.style.color  = nd.color;
  ttTitl.textContent  = nd.title;
  ttConf.textContent  = nd.conf_label + '  ' + (nd.confidence*100|0) + '%';
  ttConf.style.color  = nd.conf_color;
  moveTip(e);
  nd._circ.setAttribute('r', nd.size * 1.25);
  nd._circ.style.filter = `drop-shadow(0 0 9px ${nd.color})`;
}

svg.addEventListener('mousemove', e => { if (tip.style.display==='block') moveTip(e); });

function moveTip(e) {
  tip.style.left = (e.clientX + 14) + 'px';
  tip.style.top  = (e.clientY - 10) + 'px';
}

function onNodeLeave(nd) {
  tip.style.display = 'none';
  if (nd.id !== selectedId) {
    nd._circ.setAttribute('r', nd.size);
    nd._circ.style.filter = `drop-shadow(0 0 4px ${nd.color}66)`;
  }
}

function onNodeClick(nd) {
  selectedId = nd.id;
  applyOpacity();
  nd._circ.setAttribute('r', nd.size * 1.3);
  nd._circ.style.filter = `drop-shadow(0 0 12px ${nd.color})`;
  showNodePanel(nd);
}

function clearSelection() {
  selectedId = null; currentNodeData = null;
  document.getElementById('node-panel').classList.remove('visible');
  applyOpacity();
}

// ── Confidence / pinned filters ──────────────────
let confFilter   = null;   // 'hi'|'med'|'low'|'vlow'|null
let pinnedFilter = false;

const CONF_RANGE = {
  hi:   nd => nd.confidence >= 0.80,
  med:  nd => nd.confidence >= 0.60 && nd.confidence < 0.80,
  low:  nd => nd.confidence >= 0.30 && nd.confidence < 0.60,
  vlow: nd => nd.confidence  < 0.30,
};

function filterConf(key) {
  confFilter   = (confFilter === key) ? null : key;
  pinnedFilter = false;
  const pin = document.getElementById('card-pin');
  if (pin) pin.classList.remove('filter-active');
  ['hi','med','low','vlow'].forEach(k => {
    const el = document.getElementById('conf-row-' + k);
    if (el) el.classList.toggle('filter-active', k === confFilter);
  });
  applyOpacity();
  _syncHash();
}

function filterPinned() {
  pinnedFilter = !pinnedFilter;
  confFilter   = null;
  ['hi','med','low','vlow'].forEach(k => {
    const el = document.getElementById('conf-row-' + k);
    if (el) el.classList.remove('filter-active');
  });
  const pin = document.getElementById('card-pin');
  if (pin) pin.classList.toggle('filter-active', pinnedFilter);
  applyOpacity();
  _syncHash();
}

// ── URL hash 篩選持久化（UX-01）────────────────
function _syncHash() {
  const parts = [];
  if (currentFilter && currentFilter !== 'all') parts.push('kind=' + currentFilter);
  if (confFilter)   parts.push('conf=' + confFilter);
  if (pinnedFilter) parts.push('pin=1');
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : location.pathname + location.search);
}

function _restoreHash() {
  const h = location.hash.slice(1);
  if (!h) return;
  const params = Object.fromEntries(
    h.split('&').map(s => { const i = s.indexOf('='); return [s.slice(0,i), s.slice(i+1)]; })
  );
  if (params.kind) {
    currentFilter = params.kind;
    document.querySelectorAll('.pill').forEach(p =>
      p.classList.toggle('active', p.dataset.kind === currentFilter));
  }
  if (params.conf && CONF_RANGE[params.conf]) {
    confFilter = params.conf;
    ['hi','med','low','vlow'].forEach(k => {
      const el = document.getElementById('conf-row-' + k);
      if (el) el.classList.toggle('filter-active', k === confFilter);
    });
  }
  if (params.pin) {
    pinnedFilter = true;
    const pin = document.getElementById('card-pin');
    if (pin) pin.classList.add('filter-active');
  }
}

// ── Opacity (filter + search) ───────────────────
function applyOpacity() {
  allNodes.forEach(nd => {
    let vis = true;
    if (searchHits  !== null) vis = searchHits.has(nd.id);
    if (vis && confFilter)    vis = CONF_RANGE[confFilter]?.(nd) ?? true;
    if (vis && pinnedFilter)  vis = !!nd.is_pinned;
    nd._g.setAttribute('opacity', vis ? (nd.id===selectedId ? 1 : 0.88) : 0.08);
    nd._lbl.setAttribute('opacity', vis ? 0.42 : 0.04);
  });
  allLinks.forEach(l => {
    const src = l._src, tgt = l._tgt;
    let vis = searchHits === null || (src && tgt && searchHits.has(src.id) && searchHits.has(tgt.id));
    if (vis && confFilter)   vis = (CONF_RANGE[confFilter]?.(src) ?? true) || (CONF_RANGE[confFilter]?.(tgt) ?? true);
    if (vis && pinnedFilter) vis = !!(src?.is_pinned || tgt?.is_pinned);
    l._el.setAttribute('opacity', vis ? (selectedId && (src?.id===selectedId||tgt?.id===selectedId) ? 1 : 0.5) : 0.04);
  });
}

// ── Node panel ──────────────────────────────────
function showNodePanel(nd) {
  currentNodeData = nd;
  const p = document.getElementById('node-panel');
  p.classList.add('visible');
  const badge = document.getElementById('node-kind-badge');
  badge.textContent  = KIND_LABEL[nd.kind] || nd.kind;
  badge.style.background = nd.color + '22';
  badge.style.color      = nd.color;
  badge.style.border     = `1px solid ${nd.color}55`;
  document.getElementById('node-title').textContent = nd.title;
  // Confidence bar
  document.getElementById('conf-label-text').textContent = nd.conf_label;
  document.getElementById('conf-val-text').textContent   = (nd.confidence*100|0) + '%';
  const fill = document.getElementById('conf-bar-fill');
  fill.style.width      = (nd.confidence * 100) + '%';
  fill.style.background = nd.conf_color;
  document.getElementById('node-content').textContent = nd.excerpt || '（無內容）';
  document.getElementById('node-meta').textContent =
    (nd.created_at ? '📅 '+nd.created_at.slice(0,10)+'  ' : '') +
    (nd.scope && nd.scope!=='global' ? '🗂 '+nd.scope : '');
  const tags = (nd.tags||'').split(',').filter(t=>t.trim());
  document.getElementById('node-tags').innerHTML =
    tags.map(t=>`<span class="tag-chip">${t.trim()}</span>`).join('');
  // Pin btn
  const pinBtn = document.getElementById('pin-btn');
  pinBtn.textContent = nd.is_pinned ? '📌 已釘選' : '📌 釘選';
  pinBtn.className   = 'node-btn' + (nd.is_pinned ? ' pinned' : '');
  // Load full content + neighbors
  fetch('/api/node/' + nd.id).then(r=>r.json()).then(n => {
    document.getElementById('node-content').textContent = n.content || '（無內容）';
    const nl = document.getElementById('neighbor-list');
    if (n.neighbors && n.neighbors.length) {
      nl.innerHTML = '<div class="nbr-hdr">關聯節點</div>' +
        n.neighbors.map(nb => `
          <div class="nbr-item" onclick="flyTo('${nb.id}')">
            <div class="nbr-dot" style="background:${nb.color||KIND_COLOR[nb.kind]||'#94a3b8'}"></div>
            <span class="nbr-title">${nb.title.slice(0,26)}</span>
            <span class="nbr-rel">${nb.relation||''}</span>
          </div>`).join('');
    } else { nl.innerHTML = ''; }
  });
}

function flyTo(id) {
  const nd = nodeMap[id];
  if (!nd) return;
  const W = svg.clientWidth, H = svg.clientHeight;
  tx = W/2 - nd.x * sk; ty = H/2 - nd.y * sk;
  applyTx();
  onNodeClick(nd);
}

// ── Pin ─────────────────────────────────────────
async function togglePin() {
  if (!currentNodeData) return;
  const nd = currentNodeData;
  const pin = !nd.is_pinned;
  const res = await fetch(`/api/node/${nd.id}/pin`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({pinned: pin})
  });
  if (res.ok) {
    nd.is_pinned = pin;
    const btn = document.getElementById('pin-btn');
    btn.textContent = pin ? '📌 已釘選' : '📌 釘選';
    btn.className   = 'node-btn' + (pin ? ' pinned' : '');
    await loadStats();
  }
}

// ── Copy content ─────────────────────────────────
function copyContent() {
  const txt = document.getElementById('node-content').textContent;
  if (!txt || txt==='（無內容）') return;
  navigator.clipboard?.writeText(txt).then(() => {
    const btn = document.querySelector('.node-btn[onclick="copyContent()"]');
    const orig = btn.textContent;
    btn.textContent = '✓ 已複製';
    setTimeout(()=>{ btn.textContent = orig; }, 1200);
  });
}

// ── Filter pills ─────────────────────────────────
function filterKind(kind) {
  currentFilter = kind;
  document.querySelectorAll('.pill').forEach(p =>
    p.classList.toggle('active', p.dataset.kind === kind));
  _syncHash();
  loadGraph();
}
document.querySelectorAll('.pill').forEach(p =>
  p.addEventListener('click', () => filterKind(p.dataset.kind)));

// ── Search ───────────────────────────────────────
const searchInput = document.getElementById('search-input');
const searchClear = document.getElementById('search-clear');
const srPanel     = document.getElementById('search-results');
const srList      = document.getElementById('sr-list');
let searchTimer;

searchInput.addEventListener('input', e => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchClear.style.display = q ? 'block' : 'none';
  if (!q) {
    searchHits = null;
    srPanel.classList.remove('visible');
    applyOpacity();
    document.getElementById('node-panel').classList.remove('visible');
    return;
  }
  searchTimer = setTimeout(async () => {
    const data = await fetch('/api/search?q='+encodeURIComponent(q)).then(r=>r.json());
    searchHits  = new Set(data.results.map(r=>r.id));
    applyOpacity();
    // Show result list
    if (data.results.length) {
      srPanel.classList.add('visible');
      srList.innerHTML = data.results.map(r => `
        <div class="sr-item" onclick="flyTo('${r.id}')">
          <div class="sr-dot" style="background:${r.color||KIND_COLOR[r.kind]||'#94a3b8'}"></div>
          <div class="sr-body">
            <div class="sr-title">${r.title}</div>
            <div class="sr-ex">${r.excerpt}</div>
          </div>
        </div>`).join('');
    } else {
      srPanel.classList.add('visible');
      srList.innerHTML = '<div style="font-size:11px;color:var(--text3);padding:4px 0">無符合結果</div>';
    }
  }, 260);
});

searchClear.addEventListener('click', () => {
  searchInput.value = '';
  searchClear.style.display = 'none';
  searchHits = null;
  srPanel.classList.remove('visible');
  applyOpacity();
});

// ── Keyboard shortcuts ───────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement !== searchInput) {
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
  }
  if (e.key === 'Escape') {
    if (document.activeElement === searchInput) {
      searchInput.blur();
    } else {
      clearSelection();
      searchInput.value = '';
      searchClear.style.display = 'none';
      searchHits = null;
      srPanel.classList.remove('visible');
      applyOpacity();
    }
  }
});

// ── Data loading ─────────────────────────────────
async function loadStats() {
  const d = await fetch('/api/stats').then(r=>r.json());
  document.getElementById('s-nodes').textContent = d.total_nodes;
  document.getElementById('s-edges').textContent = d.total_edges;
  document.getElementById('s-low').textContent   = d.low_confidence;
  document.getElementById('s-pin').textContent   = d.pinned;
  // Kind list with count + avg confidence
  const kl = document.getElementById('kind-list');
  kl.innerHTML = (d.by_kind||[]).map(k => `
    <div class="kind-row" onclick="filterKind('${k.kind}')">
      <div class="kind-dot" style="background:${KIND_COLOR[k.kind]||'#94a3b8'}"></div>
      <span class="kind-name">${KIND_LABEL[k.kind]||k.kind}</span>
      <span class="kind-conf">${(k.avg_confidence*100|0)}%</span>
      <span class="kind-count">${k.count}</span>
    </div>`).join('');
  // Confidence distribution
  const cd = d.conf_dist || {};
  const cdTotal = (cd.hi||0) + (cd.med||0) + (cd.low||0) + (cd.vlow||0) || 1;
  const cdItems = [
    { key: 'hi',   label: '✓✓ 權威', count: cd.hi||0,   color: '#34d399', pct: ((cd.hi||0)/cdTotal*100).toFixed(0) },
    { key: 'med',  label: '✓ 已驗證', count: cd.med||0,  color: '#86efac', pct: ((cd.med||0)/cdTotal*100).toFixed(0) },
    { key: 'low',  label: '~ 推斷',   count: cd.low||0,  color: '#fbbf24', pct: ((cd.low||0)/cdTotal*100).toFixed(0) },
    { key: 'vlow', label: '⚠ 推測',  count: cd.vlow||0, color: '#f87171', pct: ((cd.vlow||0)/cdTotal*100).toFixed(0) },
  ];
  document.getElementById('conf-dist-list').innerHTML = cdItems.map(c => `
    <div class="conf-row" id="conf-row-${c.key}" onclick="filterConf('${c.key}')" style="margin-bottom:6px" title="點擊篩選">
      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:2px">
        <span style="color:${c.color}">${c.label}</span>
        <span style="color:var(--text2)">${c.count} 筆</span>
      </div>
      <div style="background:var(--border);border-radius:3px;height:5px">
        <div style="background:${c.color};width:${c.pct}%;height:100%;border-radius:3px;transition:width .4s"></div>
      </div>
    </div>`).join('');
  // Update pill counts
  const countMap = {};
  let total = 0;
  (d.by_kind||[]).forEach(k => { countMap[k.kind] = k.count; total += k.count; });
  document.querySelectorAll('.pill').forEach(p => {
    const k = p.dataset.kind;
    const cnt = k === 'all' ? total : (countMap[k] || 0);
    const existing = p.querySelector('.pill-cnt');
    if (existing) existing.remove();
    if (cnt > 0) {
      const s = document.createElement('span');
      s.className = 'pill-cnt'; s.textContent = cnt;
      p.appendChild(s);
    }
  });
}

async function loadGraph() {
  document.getElementById('loading').style.display = 'flex';
  document.getElementById('empty-state').style.display = 'none';
  const lim = document.getElementById('graph-limit')?.value || 100;
  const url = `/api/graph?limit=${lim}${currentFilter!=='all'?'&kind='+currentFilter:''}`;
  const data = await fetch(url).then(r=>r.json());
  allNodes = data.nodes || [];
  allLinks = data.links || [];
  nodeMap  = {};
  allNodes.forEach(n => nodeMap[n.id] = n);
  document.getElementById('loading').style.display = 'none';
  if (!allNodes.length) {
    document.getElementById('empty-state').style.display = 'flex'; return;
  }
  initPositions();
  render();
  alpha = 1.0;
  requestAnimationFrame(simStep);
}

async function refreshAll() {
  selectedId = null; searchHits = null;
  searchInput.value = '';
  searchClear.style.display = 'none';
  srPanel.classList.remove('visible');
  document.getElementById('node-panel').classList.remove('visible');
  await Promise.all([loadStats(), loadGraph()]);
}

// ── Inline edit ──────────────────────────────
function startEdit() {
  if (!currentNodeData) return;
  const nd = currentNodeData;
  document.getElementById('ef-title').value = nd.title || '';
  document.getElementById('ef-kind').value = nd.kind || 'Note';
  const ci = document.getElementById('ef-confidence');
  ci.value = nd.confidence || 0.7;
  document.getElementById('ef-conf-val').textContent = parseFloat(ci.value).toFixed(2);
  fetch('/api/node/' + nd.id).then(r => r.json()).then(n => {
    document.getElementById('ef-content').value = n.content || '';
  });
  document.getElementById('edit-form').classList.add('visible');
}

function cancelEdit() {
  document.getElementById('edit-form').classList.remove('visible');
}

async function saveEdit() {
  if (!currentNodeData) return;
  const nd = currentNodeData;
  const body = {
    title:      document.getElementById('ef-title').value.trim(),
    kind:       document.getElementById('ef-kind').value,
    confidence: parseFloat(document.getElementById('ef-confidence').value),
    content:    document.getElementById('ef-content').value,
  };
  const res = await fetch('/api/node/' + nd.id, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(()=>({}));
    alert('儲存失敗：' + (err.error || res.status));
    return;
  }
  Object.assign(nd, body);
  nd.color = KIND_COLOR[nd.kind] || '#94a3b8';
  if (nd._circ) nd._circ.setAttribute('fill', nd.color);
  if (nd._lbl)  nd._lbl.textContent = nd.title.length > 12 ? nd.title.slice(0,12)+'…' : nd.title;
  document.getElementById('edit-form').classList.remove('visible');
  showNodePanel(nd);
  loadStats();
}

async function deleteNode() {
  if (!currentNodeData) return;
  const nd = currentNodeData;
  if (!confirm('確定刪除「' + nd.title + '」？此操作無法復原。')) return;
  const res = await fetch('/api/node/' + nd.id, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(()=>({}));
    alert('刪除失敗：' + (err.error || res.status));
    return;
  }
  if (nd._g)   nd._g.remove();
  if (nd._lbl) nd._lbl.remove();
  allLinks.filter(l => l._src === nd || l._tgt === nd).forEach(l => { if (l._el) l._el.remove(); });
  allLinks = allLinks.filter(l => l._src !== nd && l._tgt !== nd);
  allNodes = allNodes.filter(n => n !== nd);
  delete nodeMap[nd.id];
  clearSelection();
  loadStats();
}

// ── KRB Staging ──────────────────────────────
let stagingData = [];

async function loadStaging() {
  let data;
  try { data = await fetch('/api/staging').then(r => r.json()); }
  catch(e) { return; }
  stagingData = data.staging || [];
  const panel = document.getElementById('staging-panel');
  const badge = document.getElementById('stg-badge');
  const list  = document.getElementById('stg-list');
  if (!stagingData.length) { panel.classList.remove('visible'); return; }
  badge.textContent = stagingData.length;
  panel.classList.add('visible');
  list.innerHTML = stagingData.map(s => `
    <div class="stg-item" id="stg-${s.id}">
      <div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">
        <div style="width:6px;height:6px;border-radius:50%;background:${s.color};flex-shrink:0"></div>
        <span class="stg-title" title="${s.title}">${s.title}</span>
      </div>
      <div class="stg-meta">${s.kind} · ${s.source} · ${s.created_at.slice(0,10)}</div>
      <div style="font-size:10px;color:var(--text3);margin-bottom:5px;line-height:1.4">${(s.content||'').slice(0,120)}${(s.content||'').length>120?'…':''}</div>
      <div class="stg-actions">
        <button class="stg-btn approve" onclick="stagingAction('${s.id}','approve')">✓ 核准</button>
        <button class="stg-btn reject"  onclick="stagingAction('${s.id}','reject')">✕ 拒絕</button>
      </div>
    </div>`).join('');
}

async function stagingAction(sid, action) {
  const res = await fetch('/api/staging/' + sid + '/' + action, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
  });
  if (!res.ok) {
    const err = await res.json().catch(()=>({}));
    alert(action + ' 失敗：' + (err.error || res.status));
    return;
  }
  const el = document.getElementById('stg-' + sid);
  if (el) el.remove();
  stagingData = stagingData.filter(s => s.id !== sid);
  document.getElementById('stg-badge').textContent = stagingData.length;
  if (!stagingData.length) document.getElementById('staging-panel').classList.remove('visible');
  if (action === 'approve') refreshAll();
}

// ═══════════════════════════════════════════════════
//  View switching + Table Management Panel
// ═══════════════════════════════════════════════════

let currentView = 'graph';
let tvPage = 1;
let tvTotalPages = 1;
let tvSearchTimer = null;

function switchView(view) {
  currentView = view;
  document.querySelectorAll('.view-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });
  const gv = document.getElementById('graph-view');
  const tv = document.getElementById('table-view');
  const allAdminViews = ['dashboard-view','audit-view','settings-view','add-view','review-view'];
  // Hide all admin views
  allAdminViews.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  if (view === 'graph') {
    gv.classList.remove('hidden'); tv.classList.remove('active');
  } else if (view === 'table') {
    gv.classList.add('hidden'); tv.classList.remove('active'); tv.classList.add('active');
    tvLoadPage(1);
  } else {
    gv.classList.add('hidden'); tv.classList.remove('active');
    const viewEl = document.getElementById(view + '-view');
    if (viewEl) viewEl.classList.add('active');
    if (view === 'dashboard') loadDashboard();
    else if (view === 'audit') loadAudit();
    else if (view === 'settings') loadSettings();
    else if (view === 'review') loadReview();
  }
}

function tvDebounceSearch() {
  clearTimeout(tvSearchTimer);
  tvSearchTimer = setTimeout(() => tvLoadPage(1), 300);
}

async function tvLoadPage(page) {
  tvPage = page;
  const q     = document.getElementById('tv-q')?.value || '';
  const kind  = document.getElementById('tv-kind')?.value || '';
  const sort  = document.getElementById('tv-sort')?.value || 'confidence';
  const order = (sort === 'title') ? 'asc' : 'desc';
  const params = new URLSearchParams({page, page_size: 20, sort, order});
  if (q) params.set('q', q);
  if (kind) params.set('kind', kind);
  try {
    const data = await fetch('/api/nodes?' + params).then(r => r.json());
    tvTotalPages = data.total_pages || 1;
    document.getElementById('tv-info').textContent =
      `${data.total} 筆${q ? '（搜尋: '+q+'）' : ''}`;
    _tvRenderRows(data.nodes || []);
    _tvUpdatePager(data.page, data.total_pages);
  } catch(e) {
    document.getElementById('tv-info').textContent = '載入失敗';
  }
}

function _tvRenderRows(nodes) {
  const tbody = document.getElementById('tv-body');
  if (!nodes.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text3)">無結果</td></tr>';
    return;
  }
  const kindColors = {'Pitfall':'#f87171','Decision':'#34d399','Rule':'#60a5fa','ADR':'#c084fc','Component':'#94a3b8','Architecture':'#fb923c','Note':'#fbbf24'};
  tbody.innerHTML = nodes.map(n => {
    const kc = kindColors[n.kind] || '#94a3b8';
    const conf = (n.confidence * 100).toFixed(0);
    const pin = n.is_pinned ? '<span class="tv-pinned">📌</span> ' : '';
    const date = n.created_at ? n.created_at.slice(0, 10) : '—';
    return `<tr>
      <td><span class="tv-kind" style="background:${kc}20;color:${kc}">${n.kind}</span></td>
      <td class="tv-title" title="${_esc(n.title)}">${pin}${_esc(n.title)}</td>
      <td class="tv-excerpt" title="${_esc(n.excerpt)}">${_esc(n.excerpt)}</td>
      <td class="tv-conf" style="color:${conf>=80?'var(--green)':conf>=50?'var(--yellow)':'var(--red)'}">${conf}%</td>
      <td style="font-size:11px;color:var(--text2)">${n.access_count}</td>
      <td style="font-size:11px;color:var(--text2)">${date}</td>
      <td class="tv-actions">
        <button class="tv-btn" onclick="tvShowNode('${n.id}')" title="查看詳情">🔍</button>
        <button class="tv-btn useful" onclick="tvFeedback('${n.id}',true)" title="有用">👍</button>
        <button class="tv-btn outdated" onclick="tvFeedback('${n.id}',false)" title="過時">👎</button>
      </td>
    </tr>`;
  }).join('');
}

function _esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _tvUpdatePager(page, total) {
  document.getElementById('tv-prev').disabled = page <= 1;
  document.getElementById('tv-next').disabled = page >= total;
  document.getElementById('tv-page-info').innerHTML =
    `<span class="current">${page}</span> / ${total}`;
}

function tvPrev() { if (tvPage > 1) tvLoadPage(tvPage - 1); }
function tvNext() { if (tvPage < tvTotalPages) tvLoadPage(tvPage + 1); }

function tvShowNode(id) {
  // Switch to graph view and select node, or open detail panel
  switchView('graph');
  const n = nodeMap[id];
  if (n) onNodeClick(n);
}

async function tvFeedback(nodeId, useful) {
  try {
    const body = useful
      ? {confidence: null}  // mark as useful — no change needed, just record
      : {confidence: null};
    // Optimistic feedback via PATCH (toggle visual feedback)
    const btn = event.target;
    btn.textContent = useful ? '✓' : '✗';
    btn.disabled = true;
    // If MCP is available, the real feedback goes through report_knowledge_outcome
    // For now, just record the user intent visually
    setTimeout(() => {
      btn.textContent = useful ? '👍' : '👎';
      btn.disabled = false;
    }, 2000);
  } catch(e) {}
}

// ═══════════════════════════════════════════════════
//  E-06: Dashboard / Audit / Settings / Add Knowledge
// ═══════════════════════════════════════════════════

async function loadDashboard() {
  try {
    const d = await fetch('/api/admin/dashboard').then(r => r.json());
    const cards = document.getElementById('dash-cards');
    const hs = d.health || {};
    cards.innerHTML = [
      {icon:'📚',val:d.total_nodes,  label:'知識總量',cls:''},
      {icon:'🔗',val:d.total_edges,  label:'關係數',cls:''},
      {icon:'⚠' ,val:d.low_confidence_count, label:'低信心（< 0.3）', cls:d.low_confidence_count>0?'warn':''},
      {icon:'⚡',val:d.conflicts,    label:'衝突',cls:d.conflicts>0?'warn':''},
      {icon:'📋',val:d.krb_pending,  label:'KRB 待審',cls:''},
      {icon:'📡',val:d.signal_pending,label:'Signal 佇列',cls:''},
    ].map(c => `<div class="dash-card ${c.cls}">
      <span class="dc-icon">${c.icon}</span>
      <div class="dc-val">${c.val}</div>
      <div class="dc-label">${c.label}</div>
      <div class="dc-bar" style="${c.cls==='warn'?'background:var(--red)':''}""></div>
    </div>`).join('');

    // Kind distribution — horizontal bar chart
    const kinds = d.kind_distribution || {};
    const kindColors = {'Pitfall':'#f87171','Decision':'#34d399','Rule':'#60a5fa','ADR':'#c084fc','Component':'#94a3b8','Architecture':'#fb923c','Note':'#fbbf24'};
    const maxCnt = Math.max(...Object.values(kinds), 1);
    document.getElementById('dash-kinds').innerHTML = Object.entries(kinds)
      .sort((a,b) => b[1]-a[1])
      .map(([k,v]) => {
        const pct = (v / maxCnt * 100).toFixed(1);
        const c = kindColors[k] || 'var(--accent)';
        return `<div class="dash-kind-row">
          <div class="dkr-dot" style="background:${c}"></div>
          <span class="dkr-name">${k}</span>
          <div class="dkr-bar-wrap"><div class="dkr-bar" style="width:${pct}%;background:${c};opacity:0.7"></div></div>
          <span class="dkr-cnt">${v}</span>
        </div>`;
      }).join('');

    // Activity — three cards
    const a = d.activity || {};
    document.getElementById('dash-activity').innerHTML = `<div class="activity-grid">
      <div class="activity-card"><div class="ac-val">+${a.today||0}</div><div class="ac-label">今天</div></div>
      <div class="activity-card"><div class="ac-val">+${a.week||0}</div><div class="ac-label">本週</div></div>
      <div class="activity-card"><div class="ac-val">+${a.month||0}</div><div class="ac-label">本月</div></div>
    </div>`;

    // Health — status items
    const items = [];
    if (hs.status === 'ok') items.push({cls:'ok',icon:'✅',text:'系統正常，所有檢查通過'});
    else items.push({cls:'warn',icon:'⚠',text:'系統有 '+(hs.warnings||0)+' 個警告'});
    if (d.low_confidence_count > 0) items.push({cls:'warn',icon:'📉',text:d.low_confidence_count+' 筆知識信心度 < 0.3（建議複查或更新）'});
    if (d.conflicts > 0) items.push({cls:'warn',icon:'⚡',text:d.conflicts+' 個知識衝突待解決'});
    if (d.low_confidence_count === 0 && d.conflicts === 0 && hs.status === 'ok')
      items.push({cls:'ok',icon:'🎯',text:'無低信心知識、無衝突'});
    document.getElementById('dash-health').innerHTML = '<div class="health-items">' +
      items.map(i => `<div class="health-item ${i.cls}"><span class="hi-icon">${i.icon}</span><span class="hi-text">${i.text}</span></div>`).join('') + '</div>';
  } catch(e) { document.getElementById('dash-cards').innerHTML = '<div style="color:var(--red);padding:20px">載入失敗，請檢查伺服器連線</div>'; }
}

// ── Audit Log ──
let auditPage = 1, auditTotalPages = 1, auditTimer = null;
function auditDebounce() { clearTimeout(auditTimer); auditTimer = setTimeout(() => loadAudit(), 300); }
async function loadAudit(page) {
  if (page) auditPage = page; else auditPage = 1;
  const days = document.getElementById('audit-days')?.value || 30;
  const author = document.getElementById('audit-author')?.value || '';
  const action = document.getElementById('audit-action')?.value || '';
  const params = new URLSearchParams({days, page: auditPage, page_size: 50});
  if (author) params.set('author', author);
  if (action) params.set('action', action);
  try {
    const d = await fetch('/api/admin/audit-log?' + params).then(r => r.json());
    auditTotalPages = d.total_pages || 1;
    document.getElementById('audit-info').textContent = d.total + ' 筆紀錄';
    const tbody = document.getElementById('audit-body');
    if (!d.entries || !d.entries.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="audit-empty">
        <div class="ae-icon">📋</div>
        <div class="ae-text">此時間範圍內無變更紀錄</div>
      </div></td></tr>`;
    } else {
      const actionLabels = {update:'修改',submit:'提交',approve:'核准',reject:'拒絕',delete:'刪除'};
      tbody.innerHTML = d.entries.map(e => `<tr>
        <td style="font-size:11px;color:var(--text2);white-space:nowrap">${(e.time||'').replace('T',' ').slice(0,16)}</td>
        <td style="font-size:11px;color:var(--text);font-weight:500">${_esc(e.actor||'—')}</td>
        <td><span class="audit-action ${e.action}">${actionLabels[e.action]||e.action}</span></td>
        <td style="font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(e.title)}">${_esc(e.title)}</td>
        <td style="font-size:11px;color:var(--text3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(e.detail)}">${_esc((e.detail||'').slice(0,80))}</td>
      </tr>`).join('');
    }
    document.getElementById('audit-prev').disabled = auditPage <= 1;
    document.getElementById('audit-next').disabled = auditPage >= auditTotalPages;
    document.getElementById('audit-page-info').innerHTML = `<span class="current">${auditPage}</span> / ${auditTotalPages}`;
  } catch(e) { document.getElementById('audit-info').textContent = '載入失敗'; }
}
function auditPrev() { if (auditPage > 1) loadAudit(auditPage - 1); }
function auditNext() { if (auditPage < auditTotalPages) loadAudit(auditPage + 1); }

// ── Settings ──
let _settingsData = null;
async function loadSettings() {
  const grid = document.getElementById('settings-grid');
  let d;
  try {
    const res = await fetch('/api/admin/settings');
    d = await res.json();
  } catch(e) {
    console.error('loadSettings fetch failed:', e);
    grid.innerHTML = '<div class="settings-card"><div style="color:var(--red);padding:12px">\u7db2\u8def\u932f\u8aa4\uff0c\u7121\u6cd5\u8f09\u5165\u8a2d\u5b9a</div></div>';
    return;
  }
  _settingsData = d;
  const svcs = d.services || [];
  const st = d.storage || {};
  const c = d.config || {};
  const storageLabels = {brain_db:'\u8cc7\u6599\u5eab\u5927\u5c0f',backups:'\u5099\u4efd'};

  // Build HTML pieces safely (no template literal nesting that can silently fail)
  let svcsHtml = '';
  for (const s of svcs) {
    const cls = s.status === 'ok' ? 'ok' : (s.status === 'warn' ? 'warn' : 'err');
    svcsHtml += '<div class="svc-item"><div class="svc-dot '+cls+'"></div><span class="svc-name">'+(s.name||'')+'</span><span class="svc-detail">'+(s.detail||'')+'</span></div>';
  }
  if (!svcsHtml) svcsHtml = '<div style="color:var(--text3);font-size:12px;padding:8px 0">\u7121\u670d\u52d9\u8cc7\u8a0a</div>';

  let storageHtml = '';
  for (const [k,v] of Object.entries(st)) {
    storageHtml += '<div class="settings-row"><span class="sr-label">'+(storageLabels[k]||k)+'</span><span class="sr-value">'+(v||'')+'</span></div>';
  }
  if (!storageHtml) storageHtml = '<div style="color:var(--text3);font-size:12px;padding:8px 0">\u7121\u5132\u5b58\u8cc7\u8a0a</div>';

  grid.innerHTML =
    '<div class="settings-card">'
    + '<div class="sc-title">\u7cfb\u7d71\u8cc7\u8a0a</div>'
    + '<div class="settings-row"><span class="sr-label">\u904b\u884c\u6a21\u5f0f</span><span class="sr-value">'+(d.mode||'standalone')+'</span></div>'
    + '<div class="settings-row"><span class="sr-label">Embedding</span><span class="sr-value">'+(d.embedding||'LocalTFIDF')+'</span></div>'
    + '<div class="settings-row"><span class="sr-label">LLM</span><span class="sr-value">'+(d.llm||'\u672a\u8a2d\u5b9a')+'</span></div>'
    + '<div class="settings-row"><span class="sr-label">Schema</span><span class="sr-value">v'+(d.schema_version||0)+'</span></div>'
    + '</div>'
    + '<div class="settings-card">'
    + '<div class="sc-title">\u670d\u52d9\u72c0\u614b</div>'
    + svcsHtml
    + '</div>'
    + '<div class="settings-card">'
    + '<div class="sc-title">\u5132\u5b58\u7a7a\u9593</div>'
    + storageHtml
    + '</div>'
    + '<div class="settings-card" style="grid-column:1/-1">'
    + '<div class="sc-title">\u77e5\u8b58\u5f15\u64ce\u8a2d\u5b9a</div>'
    + _cfgRow('\u6700\u5927\u4e0a\u4e0b\u6587 Token',   'brain_max_context_tokens',  c.brain_max_context_tokens  ?? 6000, 'number', '\u63a8\u85a6 4000\u301c8000')
    + _cfgRow('\u904e\u6642\u8b66\u544a\u5929\u6578',     'brain_freshness_warn_days', c.brain_freshness_warn_days ?? 30,   'number', '\u8d85\u904e\u6b64\u5929\u6578\u7684\u77e5\u8b58\u6a19\u8a18\u70ba\u904e\u6642')
    + _cfgRow('\u53bb\u91cd\u95be\u503c',           'brain_dedup_threshold',     c.brain_dedup_threshold     ?? 0.85, 'number', '0.0\u301c1.0\uff0c\u8d8a\u9ad8\u8d8a\u56b4\u683c')
    + '</div>'
    + '<div class="settings-card">'
    + '<div class="sc-title">\u77e5\u8b58\u8870\u6e1b</div>'
    + _cfgToggle('\u555f\u7528\u8870\u6e1b', 'decay_enabled', c.decay_enabled ?? true)
    + _cfgRow('\u57f7\u884c\u9593\u9694\uff08\u5c0f\u6642\uff09', 'decay_interval_hours', c.decay_interval_hours ?? 24, 'number', '\u591a\u4e45\u57f7\u884c\u4e00\u6b21\u8870\u6e1b\u8a08\u7b97')
    + '</div>'
    + '<div class="settings-card">'
    + '<div class="sc-title">Pipeline \u81ea\u52d5\u5316</div>'
    + _cfgToggle('\u555f\u7528 Pipeline', 'pipeline_enabled', c.pipeline_enabled ?? true)
    + _cfgRow('Worker \u9593\u9694\uff08\u79d2\uff09', 'pipeline_worker_interval', c.pipeline_worker_interval ?? 60, 'number', '\u6700\u5c0f 10 \u79d2')
    + _cfgRow('\u81ea\u52d5\u4fe1\u5fc3\u5ea6\u4e0a\u9650', 'pipeline_max_auto_confidence', c.pipeline_max_auto_confidence ?? 0.85, 'number', '0.0\u301c1.0')
    + '</div>'
    + '<div class="settings-card">'
    + '<div class="sc-title">\u77e5\u8b58\u5be9\u6838 (KRB)</div>'
    + _cfgRow('\u81ea\u52d5\u6838\u51c6\u95be\u503c', 'review_auto_approve_threshold', c.review_auto_approve_threshold ?? 0.8, 'number', '\u4fe1\u5fc3\u5ea6\u8d85\u904e\u6b64\u503c\u81ea\u52d5\u901a\u904e')
    + _cfgRow('\u5f85\u5be9\u4fdd\u7559\u5929\u6578', 'review_staging_ttl_days', c.review_staging_ttl_days ?? 30, 'number', '\u8d85\u904e\u5929\u6578\u81ea\u52d5\u6e05\u9664')
    + '</div>';

  document.getElementById('cfg-save-wrap').style.display = 'flex';
}
function _cfgRow(label, key, val, type, hint) {
  const step = type === 'number' && String(val).includes('.') ? '0.01' : '1';
  return '<div class="settings-row"><span class="sr-label">'+label+'</span>'
    +'<input class="cfg-input" data-key="'+key+'" type="'+type+'" value="'+val+'" step="'+step+'">'
    +'<span class="cfg-hint">'+hint+'</span></div>';
}
function _cfgToggle(label, key, val) {
  return '<div class="settings-row"><span class="sr-label">'+label+'</span>'
    +'<label class="cfg-toggle"><input type="checkbox" data-key="'+key+'" '+(val?'checked':'')+'>'
    +'<span class="cfg-slider"></span></label></div>';
}
async function saveSettings() {
  const cfg = {};
  document.querySelectorAll('.cfg-input').forEach(el => {
    const k = el.dataset.key;
    const raw = el.value;
    if (raw === '' || raw == null) return;  // skip empty fields
    const num = el.step === '0.01' ? parseFloat(raw) : parseInt(raw, 10);
    if (isNaN(num)) return;  // skip invalid numbers
    cfg[k] = num;
  });
  document.querySelectorAll('.cfg-toggle input[type=checkbox]').forEach(el => {
    cfg[el.dataset.key] = el.checked;
  });
  if (Object.keys(cfg).length === 0) return;
  const btn = document.getElementById('cfg-save-btn');
  btn.disabled = true; btn.textContent = '\u5132\u5b58\u4e2d\u2026';
  try {
    const res = await fetch('/api/admin/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({config: cfg})
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      btn.textContent = '\u2713 \u5df2\u5132\u5b58';
      setTimeout(() => { btn.textContent = '\u5132\u5b58\u8a2d\u5b9a'; btn.disabled = false; }, 2000);
      // Reload settings to reflect the saved state
      await loadSettings();
    } else {
      btn.textContent = data.error || '\u5132\u5b58\u5931\u6557';
      setTimeout(() => { btn.textContent = '\u5132\u5b58\u8a2d\u5b9a'; btn.disabled = false; }, 3000);
    }
  } catch(e) {
    btn.textContent = '\u7db2\u8def\u932f\u8aa4'; btn.disabled = false;
  }
}

// ── Add Knowledge ──
function _addMsg(text, type) {
  const msg = document.getElementById('add-msg');
  msg.className = 'add-msg ' + type;
  msg.textContent = text;
  if (type === 'success') setTimeout(() => { msg.className = 'add-msg'; }, 5000);
}
async function submitAddNode() {
  const title = document.getElementById('add-title').value.trim();
  const content = document.getElementById('add-content').value.trim();
  const kind = document.getElementById('add-kind').value;
  const confidence = parseFloat(document.getElementById('add-confidence').value);
  if (!title) { _addMsg('請輸入知識標題','error'); return; }
  if (!content) { _addMsg('請輸入知識內容','error'); return; }
  const btn = document.getElementById('add-submit-btn');
  btn.disabled = true; btn.textContent = '新增中…';
  try {
    const res = await fetch('/api/node', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, content, kind, confidence})
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      _addMsg('新增成功！知識已加入知識庫。','success');
      document.getElementById('add-title').value = '';
      document.getElementById('add-content').value = '';
      document.getElementById('add-confidence').value = '0.7';
      document.getElementById('add-conf-val').textContent = '0.70';
    } else {
      _addMsg(data.error || '新增失敗，請稍後再試','error');
    }
  } catch(e) {
    _addMsg('網路錯誤，無法連線至伺服器','error');
  } finally {
    btn.disabled = false; btn.textContent = '新增知識';
  }
}

// ── Theme toggle ──────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('brain-theme', next);
  document.getElementById('theme-toggle').textContent = next === 'dark' ? '☀' : '☾';
}
(function initTheme() {
  const saved = localStorage.getItem('brain-theme');
  if (saved === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.getElementById('theme-toggle').textContent = '☾';
  }
})();

// ═══════════════════════════════════════════════════
//  I-03: KRB Review Queue
// ═══════════════════════════════════════════════════

async function loadReview() {
  const sort = document.getElementById('review-sort')?.value || 'created_at';
  const kind = document.getElementById('review-kind-filter')?.value || '';
  let url = `/api/review/queue?sort=${sort}`;
  if (kind) url += `&kind=${encodeURIComponent(kind)}`;
  let data;
  try { data = await fetch(url).then(r => r.json()); }
  catch(e) { return; }
  const items = data.items || [];
  const countEl = document.getElementById('review-count');
  const bodyEl = document.getElementById('review-body');
  const emptyEl = document.getElementById('review-empty');
  if (countEl) countEl.textContent = items.length ? `${items.length} 筆待審` : '佇列為空';
  if (!items.length) {
    if (bodyEl) bodyEl.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  if (bodyEl) bodyEl.innerHTML = items.map(s => {
    const confPct = Math.round((s.confidence || 0) * 100);
    const confCls = confPct >= 80 ? 'conf-high' : confPct >= 50 ? 'conf-mid' : 'conf-low';
    return `<tr id="rv-${s.id}">
      <td><span class="kind-badge" style="background:${s.color}">${s.kind}</span></td>
      <td class="rv-title" title="${(s.content||'').replace(/"/g,'&quot;')}">${s.title}</td>
      <td style="font-size:11px;color:var(--text3)">${(s.content||'').slice(0,80)}${(s.content||'').length>80?'…':''}</td>
      <td><span class="${confCls}">${confPct}%</span></td>
      <td style="font-size:11px">${s.source || '—'}</td>
      <td style="font-size:11px">${(s.created_at||'').slice(0,10)}</td>
      <td>
        <button class="rv-btn approve" onclick="reviewAction('${s.id}','approve')">✓ 核准</button>
        <button class="rv-btn reject" onclick="reviewAction('${s.id}','reject')">✕ 拒絕</button>
      </td>
    </tr>`;
  }).join('');
}

async function reviewAction(sid, action) {
  const res = await fetch('/api/staging/' + sid + '/' + action, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
  });
  if (!res.ok) {
    const err = await res.json().catch(()=>({}));
    alert(action + ' 失敗：' + (err.error || res.status));
    return;
  }
  const el = document.getElementById('rv-' + sid);
  if (el) el.remove();
  // Update count
  const countEl = document.getElementById('review-count');
  const remaining = document.querySelectorAll('#review-body tr').length;
  if (countEl) countEl.textContent = remaining ? `${remaining} 筆待審` : '佇列為空';
  if (!remaining) {
    const emptyEl = document.getElementById('review-empty');
    if (emptyEl) emptyEl.style.display = '';
  }
  // Refresh sidebar staging panel too
  loadStaging();
  if (action === 'approve') loadStats();
}

async function reviewBatchApprove() {
  const threshold = parseFloat(document.getElementById('review-batch-threshold')?.value || '0.85');
  if (!confirm(`批次核准信心度 ≥ ${(threshold*100).toFixed(0)}% 的所有待審知識？`)) return;
  const res = await fetch('/api/review/batch-approve', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({threshold}),
  });
  const data = await res.json();
  if (!res.ok || data.error) {
    alert('批次核准失敗：' + (data.error || res.status));
    return;
  }
  alert(`已核准 ${data.approved} 筆知識`);
  loadReview();
  loadStaging();
  loadStats();
}

// ── Boot ─────────────────────────────────────────
_restoreHash();   // UX-01: apply filter state from URL hash before first load
loadStats();
loadGraph();
loadStaging();
