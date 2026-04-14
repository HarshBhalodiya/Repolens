/* ═══════════════════════════════════════════════════════
   RepoLens v2 — SPA Application Logic
   Features: D3 upgrades, SSE chat, code smells, timeline,
             cluster-by-folder, complexity bars, cached analysis
   ═══════════════════════════════════════════════════════ */
const API = window.location.origin + '/api';

// ── State ──────────────────────────────────────────────
let repoData = null,
    repoKey = '',
    selectedFile = null;
let chatHistory = [],
    readmeRaw = '',
    complexityData = [],
    graphData = null;
let smellsData = [],
    timelineData = null,
    currentRepoUrl = '';
let sseStreamingChat = false; // Track if we're streaming

// ═══════════════════════════════════════════════════════
// HERO CANVAS — Animated D3 Force-Directed Background
// ═══════════════════════════════════════════════════════
(function initHeroCanvas() {
    const canvas = document.getElementById('hero-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let width, height, nodes = [],
        links = [];
    const NODE_COUNT = 50;
    const COLORS = ['#FF6044', '#FF7A62', '#58A6FF', '#3FB950', '#F0883E', '#F85149'];

    function resize() {
        width = canvas.parentElement.clientWidth;
        height = canvas.parentElement.clientHeight;
        canvas.width = width * devicePixelRatio;
        canvas.height = height * devicePixelRatio;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        ctx.scale(devicePixelRatio, devicePixelRatio);
    }

    function init() {
        resize();
        nodes = Array.from({ length: NODE_COUNT }, (_, i) => ({
            x: Math.random() * width,
            y: Math.random() * height,
            vx: (Math.random() - 0.5) * 0.4,
            vy: (Math.random() - 0.5) * 0.4,
            r: 2 + Math.random() * 3,
            color: COLORS[Math.floor(Math.random() * COLORS.length)],
        }));
        // Create random connections
        links = [];
        for (let i = 0; i < NODE_COUNT * 0.6; i++) {
            const a = Math.floor(Math.random() * NODE_COUNT);
            const b = Math.floor(Math.random() * NODE_COUNT);
            if (a !== b) links.push([a, b]);
        }
    }

    function animate() {
        ctx.clearRect(0, 0, width, height);
        // Draw links
        ctx.strokeStyle = 'rgba(255, 96, 68, 0.12)';
        ctx.lineWidth = 0.5;
        for (const [a, b] of links) {
            const na = nodes[a],
                nb = nodes[b];
            const dist = Math.hypot(na.x - nb.x, na.y - nb.y);
            if (dist < 200) {
                ctx.beginPath();
                ctx.moveTo(na.x, na.y);
                ctx.lineTo(nb.x, nb.y);
                ctx.stroke();
            }
        }
        // Draw and update nodes
        for (const n of nodes) {
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
            ctx.fillStyle = n.color;
            ctx.globalAlpha = 0.4;
            ctx.fill();
            ctx.globalAlpha = 1;
            n.x += n.vx;
            n.y += n.vy;
            if (n.x < 0 || n.x > width) n.vx *= -1;
            if (n.y < 0 || n.y > height) n.vy *= -1;
        }
        requestAnimationFrame(animate);
    }

    init();
    animate();
    window.addEventListener('resize', () => { resize(); });
})();

// ═══════════════════════════════════════════════════════
// TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════
function toast(msg, type = 'info', duration = 4000) {
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    const icons = { success: 'check_circle', error: 'error', info: 'info' };
    el.innerHTML = `<span class="material-symbols-outlined fill" style="font-size:18px">${icons[type] || 'info'}</span><span>${msg}</span>`;
    c.appendChild(el);
    setTimeout(() => {
        el.classList.add('removing');
        setTimeout(() => el.remove(), 300);
    }, duration);
}

// ═══════════════════════════════════════════════════════
// VIEW ROUTER
// ═══════════════════════════════════════════════════════
function showView(name) {
    document.getElementById('view-landing').classList.add('hidden');
    document.getElementById('view-landing').style.display = '';
    document.getElementById('view-dashboard').classList.add('hidden');
    document.getElementById('view-dashboard').style.display = '';
    document.getElementById('view-health').classList.add('hidden');
    document.getElementById('view-health').style.display = '';

    const el = document.getElementById('view-' + name);
    el.classList.remove('hidden');
    if (name === 'dashboard') { el.style.display = 'flex'; }
    if (name === 'health') runHealthCheck();
    if (name === 'landing') renderHistory();
}

// ═══════════════════════════════════════════════════════
// REPO HISTORY (localStorage)
// ═══════════════════════════════════════════════════════
function saveToHistory(url, name) {
    let h = JSON.parse(localStorage.getItem('repolens-history') || '[]');
    h = h.filter(x => x.url !== url);
    h.unshift({ url, name, ts: Date.now() });
    if (h.length > 8) h = h.slice(0, 8);
    localStorage.setItem('repolens-history', JSON.stringify(h));
}

function renderHistory() {
    const h = JSON.parse(localStorage.getItem('repolens-history') || '[]');
    const sec = document.getElementById('history-section');
    const list = document.getElementById('history-list');
    if (!h.length) { sec.classList.add('hidden'); return; }
    sec.classList.remove('hidden');
    list.innerHTML = h.map(r => `
    <button onclick="fillExample('${r.url}')" class="w-full text-left flex items-center justify-between p-3 rounded-lg bg-surface border border-border hover:border-primary/30 transition-all group">
      <div class="flex items-center gap-3"><span class="material-symbols-outlined text-primary-light" style="font-size:16px">folder</span><span class="text-sm font-mono font-medium">${r.name}</span></div>
      <span class="text-[10px] text-text-muted">${new Date(r.ts).toLocaleDateString()}</span>
    </button>`).join('');
}

function fillExample(url) { document.getElementById('repo-url').value = url; }

// ═══════════════════════════════════════════════════════
// ANALYZE LOADING MODAL (overlay + light card + SSE progress)
// ═══════════════════════════════════════════════════════
function repoDisplayNameFromUrl(url) {
    try {
        const u = new URL(url);
        const segs = u.pathname.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean);
        if (segs.length >= 2) return `${segs[0]}/${segs[1]}`;
        if (segs.length === 1) return segs[0];
    } catch (_) {}
    return 'Repository';
}

function showLoadingScreen() {
    const screen = document.getElementById('loading-screen');
    const url = currentRepoUrl || document.getElementById('repo-url').value.trim();
    document.getElementById('loading-repo-title').textContent = repoDisplayNameFromUrl(url);
    document.getElementById('loading-status').textContent = 'Preparing analysis…';
    document.getElementById('loading-bar').style.width = '0%';
    document.getElementById('loading-pct').textContent = '0 %';
    screen.classList.remove('hidden');
}

function hideLoadingScreen() {
    document.getElementById('loading-screen').classList.add('hidden');
}

function updateLoadingStep(pct, stepLabel) {
    const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    document.getElementById('loading-bar').style.width = clamped + '%';
    document.getElementById('loading-pct').textContent = `${Math.round(clamped)} %`;
    if (stepLabel) document.getElementById('loading-status').textContent = stepLabel;
}

// ═══════════════════════════════════════════════════════
// ANALYSIS (with SSE progress + loading screen)
// ═══════════════════════════════════════════════════════
async function startAnalysis(force = false) {
    const url = document.getElementById('repo-url').value.trim();
    if (!url) {
        document.getElementById('input-wrapper').classList.add('border-danger');
        setTimeout(() => document.getElementById('input-wrapper').classList.remove('border-danger'), 1500);
        return;
    }
    if (!url.includes('github.com')) { toast('Please enter a valid GitHub URL', 'error'); return; }

    currentRepoUrl = url;
    const btn = document.getElementById('analyze-btn');
    btn.disabled = true;
    document.getElementById('btn-text').textContent = 'Analyzing…';
    showLoadingScreen();

    const analysisId = 'a' + Date.now();

    // Start SSE listener
    let evtSource;
    try {
        evtSource = new EventSource(`${API}/progress/${analysisId}`);
        evtSource.onmessage = (e) => {
            try {
                const d = JSON.parse(e.data);
                if (d.pct >= 0) updateLoadingStep(d.pct, d.step);
                if (d.pct >= 100 || d.pct < 0) evtSource.close();
            } catch (_) {}
        };
        evtSource.onerror = () => evtSource.close();
    } catch (_) {}

    try {
        const resp = await fetch(`${API}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo_url: url, analysis_id: analysisId, force }),
        });
        if (evtSource) evtSource.close();
        const data = await resp.json();
        if (!resp.ok) {
            toast(data.error || 'Analysis failed', 'error');
            resetBtn();
            hideLoadingScreen();
            return;
        }

        updateLoadingStep(100, 'Analysis complete!');
        repoData = data;
        repoKey = data.repo_key || data.meta?.full_name || '';
        saveToHistory(url, repoKey);

        if (data.cached) toast('Loaded from cache — no changes detected', 'info');

        setTimeout(() => {
            resetBtn();
            hideLoadingScreen();
            loadDashboard();
        }, 600);
    } catch (err) {
        if (evtSource) evtSource.close();
        toast('Cannot connect to backend. Run: python run.py', 'error');
        resetBtn();
        hideLoadingScreen();
    }
}

function forceReanalyze() {
    if (!currentRepoUrl) { toast('No repo URL to re-analyze', 'info'); return; }
    document.getElementById('repo-url').value = currentRepoUrl;
    showView('landing');
    startAnalysis(true);
}

function resetBtn() {
    document.getElementById('analyze-btn').disabled = false;
    document.getElementById('btn-text').textContent = 'Analyze';
}

// ═══════════════════════════════════════════════════════
// LOAD DASHBOARD
// ═══════════════════════════════════════════════════════
async function loadDashboard() {
    if (!repoData) return;
    complexityData = repoData.complexity || [];
    graphData = repoData.graph || null;

    showView('dashboard');
    document.querySelectorAll('.tab-content').forEach((el, i) => {
        el.style.display = i === 0 ? 'flex' : 'none';
        el.style.flex = '1';
        el.style.overflow = 'hidden';
    });
    document.getElementById('tab-summary').style.overflow = 'auto';

    populateHeader();
    populateSummary();
    renderFileTree(repoData.file_tree || []);
    renderHeatTable();
    renderGraphInsights();
    renderComplexityCards();
    initChat();

    // Load smells, timeline, and insights asynchronously
    loadSmells();
    loadTimeline();
    loadInsights();
}

// ═══════════════════════════════════════════════════════
// HEADER & SUMMARY
// ═══════════════════════════════════════════════════════
function populateHeader() {
    const m = repoData.meta;
    document.getElementById('header-repo').textContent = m.full_name;
    document.getElementById('pill-files').textContent = repoData.stats?.total_files + ' files';
    document.getElementById('pill-lines').textContent = fmtNum(repoData.stats?.total_lines) + ' lines';
    document.getElementById('pill-lang').textContent = m.language || '?';
    document.title = m.full_name + ' — RepoLens';
}

function populateSummary() {
    const m = repoData.meta,
        s = repoData.stats;
    document.getElementById('sum-name').textContent = m.full_name;
    document.getElementById('sum-desc').textContent = m.description || '';
    document.getElementById('s-files').textContent = s?.total_files ?? '–';
    document.getElementById('s-lines').textContent = fmtNum(s?.total_lines);
    document.getElementById('s-funcs').textContent = fmtNum(s?.total_functions);
    document.getElementById('s-cmplx').textContent = s?.avg_complexity ?? '–';
    document.getElementById('sum-topics').innerHTML = (m.topics || []).map(t => `<span class="px-2.5 py-0.5 bg-primary-dim text-primary-light text-[10px] font-semibold rounded-full">${t}</span>`).join('');
}

function renderGraphInsights() {
    const g = graphData?.metrics;
    if (!g) return;
    document.getElementById('graph-insights').innerHTML = `
    <div class="p-4 rounded-xl bg-surface border border-border"><div class="flex items-center gap-2 mb-3"><span class="material-symbols-outlined text-info" style="font-size:18px">hub</span><span class="text-xs font-bold">Dependency Graph</span></div>
      <div class="grid grid-cols-2 gap-2 text-xs"><div class="text-text-secondary">Nodes</div><div class="font-mono font-bold">${g.total_nodes}</div><div class="text-text-secondary">Edges</div><div class="font-mono font-bold">${g.total_edges}</div><div class="text-text-secondary">Circular deps</div><div class="font-mono font-bold ${g.cycles_detected > 0 ? 'text-danger' : 'text-success'}">${g.cycles_detected}</div><div class="text-text-secondary">Isolated</div><div class="font-mono font-bold">${g.isolated_files?.length || 0}</div></div></div>
    <div class="p-4 rounded-xl bg-surface border border-border"><div class="flex items-center gap-2 mb-3"><span class="material-symbols-outlined text-warning" style="font-size:18px">star</span><span class="text-xs font-bold">Most Imported</span></div>
      <ul class="space-y-1.5">${(g.most_imported || []).slice(0, 4).map(([n, c]) => `<li class="flex items-center justify-between"><span class="text-xs font-mono text-text-primary truncate max-w-[150px]">${n}</span><span class="text-[10px] font-bold text-primary-light bg-primary-dim px-2 py-0.5 rounded-full">${c}</span></li>`).join('')}</ul></div>`;
}

function renderHeatTable() {
  const sorted = [...complexityData].sort((a, b) => b.complexity - a.complexity).slice(0, 8);
  document.getElementById('heat-table').innerHTML = sorted.map(f => {
    const g = gradeStyle(f.grade);
    return `<tr class="hover:bg-surface-high transition-colors cursor-pointer" onclick="selectFileByPath('${f.path||f.file}')"><td class="px-4 py-2.5 font-mono truncate max-w-[180px]">${f.path || f.file}</td><td class="px-4 py-2.5 font-bold">${f.complexity}</td><td class="px-4 py-2.5"><span class="inline-flex px-2 py-0.5 rounded text-[10px] font-bold ${g.bg} ${g.text}">${f.grade_label}</span></td><td class="px-4 py-2.5 text-right font-mono text-text-secondary">${fmtNum(f.lines)}</td></tr>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════
// COMPLEXITY CARDS — with horizontal bars + most complex callout
// ═══════════════════════════════════════════════════════
function renderComplexityCards() {
  const sortKey = document.getElementById('sort-select')?.value || 'score';
  const sorted = [...complexityData].sort((a, b) => (b[sortKey] || b.complexity) - (a[sortKey] || a.complexity));
  const max_c = Math.max(...sorted.map(f => f.complexity), 10);
  const avg = sorted.length > 0 ? sorted.reduce((s, f) => s + f.complexity, 0) / sorted.length : 0;

  // Most complex file callout
  const callout = document.getElementById('most-complex-callout');
  if (sorted.length > 0) {
    const worst = sorted[0];
    const wg = gradeStyle(worst.grade);
    callout.classList.remove('hidden');
    callout.innerHTML = `
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-danger" style="font-size:22px">warning</span>
          <div>
            <div class="text-xs font-bold text-danger mb-0.5">Most Complex File</div>
            <div class="text-sm font-mono font-bold cursor-pointer hover:text-info transition-colors" onclick="selectFileByPath('${worst.path||worst.file}')">${worst.path || worst.file}</div>
          </div>
        </div>
        <div class="text-right">
          <div class="text-2xl font-black text-danger">${worst.complexity}</div>
          <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold ${wg.bg} ${wg.text}">${worst.grade_label}</span>
        </div>
      </div>`;
  }

  document.getElementById('complexity-cards').innerHTML = sorted.map(f => {
    const g = gradeStyle(f.grade);
    const pct = Math.min(100, Math.round(f.complexity / max_c * 100));
    const barColor = complexityColor(f.complexity);
    const topFns = (f.top_functions || []).slice(0, 3);
    // Trend vs average
    const diff = f.complexity - avg;
    const trendClass = diff > 2 ? 'trend-up' : diff < -2 ? 'trend-down' : 'trend-same';
    const trendIcon = diff > 2 ? 'trending_up' : diff < -2 ? 'trending_down' : 'trending_flat';

    return `<div class="p-4 rounded-xl bg-surface border border-border hover:border-border-strong transition-all cursor-pointer" onclick="selectFileByPath('${f.path||f.file}')">
      <div class="flex items-start justify-between mb-2">
        <div class="min-w-0">
          <div class="text-xs font-mono font-semibold truncate">${f.path||f.file}</div>
          <div class="text-[10px] text-text-secondary mt-0.5">${fmtNum(f.lines)} lines · ${f.functions||'?'} fn · ${f.lang}</div>
        </div>
        <div class="text-right ml-3 shrink-0 flex items-center gap-2">
          <span class="material-symbols-outlined ${trendClass}" style="font-size:16px">${trendIcon}</span>
          <div>
            <div class="text-xl font-black">${f.complexity}</div>
            <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold ${g.bg} ${g.text}">${f.grade_label}</span>
          </div>
        </div>
      </div>
      <div class="w-full h-1.5 bg-surface-highest rounded-full overflow-hidden mb-2">
        <div class="complexity-bar" style="width:${pct}%;background:${barColor}"></div>
      </div>
      ${topFns.length ? '<div class="mt-2 space-y-1">' + topFns.map(fn => `<div class="flex items-center justify-between"><span class="text-[10px] font-mono text-text-secondary truncate">${fn.name}()</span><span class="text-[10px] font-bold ${fn.complexity > 10 ? 'text-warning' : 'text-text-secondary'}">${fn.complexity}</span></div>`).join('') + '</div>' : ''}
      ${f.maintainability_index ? `<div class="mt-2 text-[10px] text-text-secondary">MI: <strong class="${f.maintainability_index < 20 ? 'text-danger' : f.maintainability_index < 65 ? 'text-warning' : 'text-success'}">${f.maintainability_index}</strong>/100</div>` : ''}
    </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════
// FILE TREE
// ═══════════════════════════════════════════════════════
function renderFileTree(items, container, depth = 0) {
  if (!container) container = document.getElementById('file-tree');
  if (depth === 0) container.innerHTML = '';
  for (const item of items) {
    if (item.type === 'folder') {
      const wrap = document.createElement('div');
      const header = document.createElement('div');
      header.className = 'file-row flex items-center gap-2 py-1.5 rounded-lg cursor-pointer select-none';
      header.style.paddingLeft = (12 + depth * 10) + 'px';
      const uid = btoa(unescape(encodeURIComponent(item.name + depth))).replace(/[^a-zA-Z0-9]/g, '_');
      header.innerHTML = `<span class="material-symbols-outlined fill text-text-muted" style="font-size:14px" id="fi-${uid}">folder_open</span><span class="text-xs font-medium">${item.name}/</span>`;
      const kids = document.createElement('div'); kids.id = 'fc-' + uid;
      header.onclick = () => { const open = kids.style.display !== 'none'; kids.style.display = open ? 'none' : 'block'; document.getElementById('fi-' + uid).textContent = open ? 'folder' : 'folder_open'; };
      if (item.children?.length) renderFileTree(item.children, kids, depth + 1);
      wrap.append(header, kids); container.appendChild(wrap);
    } else {
      const div = document.createElement('div');
      div.className = 'file-row flex items-center gap-2 py-1.5 rounded-lg cursor-pointer';
      div.style.paddingLeft = (12 + depth * 10) + 'px';
      div.setAttribute('data-path', item.path || item.name);
      div.innerHTML = `<span class="${langColor(item.lang)} material-symbols-outlined" style="font-size:13px">${langIcon(item.lang)}</span><span class="text-xs truncate">${item.name}</span>`;
      div.onclick = () => selectFile(item, div);
      container.appendChild(div);
    }
  }
}

function filterTree() {
  const q = document.getElementById('file-search').value.toLowerCase();
  document.querySelectorAll('[data-path]').forEach(el => { el.style.display = el.getAttribute('data-path').toLowerCase().includes(q) ? '' : 'none'; });
}
function toggleFolders() {
  const all = document.querySelectorAll('[id^="fc-"]');
  const anyOpen = [...all].some(el => el.style.display !== 'none');
  all.forEach(el => el.style.display = anyOpen ? 'none' : 'block');
}

function selectFile(item, el) {
  selectedFile = item;
  document.querySelectorAll('[data-path]').forEach(e => e.classList.remove('selected'));
  el.classList.add('selected');
  loadFileViewer(item.path || item.name);
}

function selectFileByPath(path) {
  const el = document.querySelector(`[data-path="${path}"]`);
  if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); el.click(); }
}

// ═══════════════════════════════════════════════════════
// SIDEBAR TOGGLE
// ═══════════════════════════════════════════════════════
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebar-toggle');
  sidebar.classList.toggle('collapsed');
  if (sidebar.classList.contains('collapsed')) {
    toggle.classList.remove('hidden');
    const icon = toggle.querySelector('.material-symbols-outlined');
    icon.textContent = 'chevron_right';
  } else {
    toggle.classList.add('hidden');
  }
}

// ═══════════════════════════════════════════════════════
// FILE CONTENT VIEWER (with syntax highlighting + smell badges)
// ═══════════════════════════════════════════════════════
async function loadFileViewer(path) {
  switchTab('chat', document.getElementById('chat-tab-btn'));
  document.getElementById('viewer-filename').textContent = path;
  document.getElementById('viewer-content').innerHTML = '<div class="flex items-center justify-center h-full text-text-secondary text-sm"><span class="material-symbols-outlined spin mr-2" style="font-size:18px">cycle</span>Loading…</div>';

  try {
    const resp = await fetch(`${API}/file-content?repo=${encodeURIComponent(repoKey)}&path=${encodeURIComponent(path)}`);
    const data = await resp.json();
    if (!resp.ok) { document.getElementById('viewer-content').innerHTML = `<div class="p-6 text-danger">${data.error}</div>`; return; }

    document.getElementById('viewer-stats').textContent = `${data.lines} lines · ${data.functions} fn · complexity ${data.complexity} · ${data.lang}`;
    const langMap = { python: 'python', javascript: 'javascript', typescript: 'typescript', java: 'java', go: 'go', rust: 'rust', ruby: 'ruby', php: 'php', html: 'xml', css: 'css', yaml: 'yaml', bash: 'bash', cpp: 'cpp', c: 'c', csharp: 'csharp' };
    const hljsLang = langMap[data.lang] || 'plaintext';

    let highlighted;
    try { highlighted = hljs.highlight(data.content, { language: hljsLang }).value; } catch (_) { highlighted = esc(data.content); }
    const hLines = highlighted.split('\n');

    // Check for smells on this file
    const fileSmells = smellsData.filter(s => s.file === path || s.file === data.name);
    const smellLines = {};
    for (const s of fileSmells) {
      if (s.line) smellLines[s.line] = s;
    }

    document.getElementById('viewer-content').innerHTML = `<div class="code-viewer font-mono p-0" style="overflow:auto;height:100%"><div class="p-4">${hLines.map((line, i) => {
      const lineNum = i + 1;
      const smell = smellLines[lineNum];
      const badge = smell ? `<span class="smell-badge ${smell.severity}"><span class="material-symbols-outlined" style="font-size:10px">${smell.severity === 'critical' ? 'error' : 'warning'}</span>${smell.description.slice(0, 40)}</span>` : '';
      return `<div class="line"><span class="line-num">${lineNum}</span><span class="line-content">${line || ' '}${badge}</span></div>`;
    }).join('')}</div></div>`;
  } catch (e) { toast('Failed to load file', 'error'); }
}

// ═══════════════════════════════════════════════════════
// TABS
// ═══════════════════════════════════════════════════════
function switchTab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  if (btn) btn.classList.add('active');
  const el = document.getElementById('tab-' + name);
  if (!el) return;
  el.classList.add('active'); el.style.display = 'flex'; el.style.flex = '1';
  el.style.overflow = (name === 'graph' || name === 'chat') ? 'hidden' : 'auto';
  if (name === 'graph') setTimeout(renderGraph, 80);
  if (name === 'timeline' && !timelineData) loadTimeline();
}

// ═══════════════════════════════════════════════════════
// CHAT — SSE streaming + syntax highlighting + copy + sources
// ═══════════════════════════════════════════════════════
function initChat() {
  chatHistory = [];
  const msgs = document.getElementById('chat-messages');
  msgs.innerHTML = '';
  addMsg('ai', `Hello! I've analyzed <code>${repoData.meta.full_name}</code>. Found ${repoData.stats?.total_files} files, ${fmtNum(repoData.stats?.total_lines)} lines of ${repoData.meta.language}. Ask me anything!`);
}

function addMsg(role, html, isNew = false) {
  const wrap = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `flex flex-col gap-1 ${role === 'user' ? 'items-end ml-4' : 'mr-4'} ${isNew ? 'fade-in' : ''}`;
  const bubble = document.createElement('div');
  bubble.className = role === 'user' ? 'chat-user p-3 text-xs' : 'chat-ai p-3 text-xs';
  bubble.innerHTML = html;
  div.append(bubble);
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  // Add copy buttons to code blocks
  bubble.querySelectorAll('pre').forEach(pre => {
    const btn = document.createElement('button');
    btn.className = 'code-copy-btn';
    btn.textContent = 'Copy';
    btn.onclick = () => {
      navigator.clipboard.writeText(pre.textContent).then(() => {
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy', 1500);
      });
    };
    pre.style.position = 'relative';
    pre.appendChild(btn);
  });
  return bubble;
}

function addSourcesPanel(sources) {
  if (!sources?.length) return;
  const wrap = document.getElementById('chat-messages');
  const panel = document.createElement('div');
  panel.className = 'mr-4 fade-in';
  panel.innerHTML = `<details class="sources-panel">
    <summary>📎 Sources used (${sources.length} chunks)</summary>
    ${sources.map(s => `<div class="source-item" onclick="selectFileByPath('${s.path}')">
      <span class="material-symbols-outlined" style="font-size:12px">description</span>
      <span class="font-mono">${s.file}</span>
      <span class="text-text-muted ml-auto">${Math.round(s.relevance * 100)}%</span>
    </div>`).join('')}
  </details>`;
  wrap.appendChild(panel);
  wrap.scrollTop = wrap.scrollHeight;
}

function showTyping() {
  const wrap = document.getElementById('chat-messages');
  const div = document.createElement('div'); div.id = 'typing'; div.className = 'flex items-center gap-2 px-1 mr-4';
  div.innerHTML = `<div class="flex gap-1"><div class="w-1.5 h-1.5 bg-primary-light rounded-full b1"></div><div class="w-1.5 h-1.5 bg-primary-light rounded-full b2"></div><div class="w-1.5 h-1.5 bg-primary-light rounded-full b3"></div></div><span class="text-[10px] font-medium text-primary-light italic">Analyzing code…</span>`;
  wrap.append(div); wrap.scrollTop = wrap.scrollHeight;
}
function hideTyping() { document.getElementById('typing')?.remove(); }
function onChatKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }
function sendQuick(t) { document.getElementById('chat-input').value = t; sendChat(); switchTab('chat', document.getElementById('chat-tab-btn')); }

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim(); if (!msg) return;
  input.value = '';
  addMsg('user', esc(msg), true);
  showTyping();
  // Hide starter questions after first message
  document.getElementById('starter-questions')?.classList.add('hidden');

  try {
    // Try SSE streaming first
    const resp = await fetch(`${API}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_key: repoKey, message: msg, history: chatHistory.slice(-12) }),
    });

    if (resp.ok && resp.headers.get('content-type')?.includes('text/event-stream')) {
      hideTyping();
      let fullReply = '';
      const bubble = addMsg('ai', '<span class="text-text-muted">…</span>', true);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();  // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) {
                fullReply += data.token;
                bubble.innerHTML = fmtReply(fullReply);
                document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;
              } else if (Array.isArray(data)) {
                addSourcesPanel(data);
              }
            } catch (_) {}
          }
        }
      }

      chatHistory.push({ role: 'user', content: msg }, { role: 'assistant', content: fullReply });
      // Add copy buttons to any code blocks
      bubble.querySelectorAll('pre').forEach(pre => {
        if (!pre.querySelector('.code-copy-btn')) {
          const btn = document.createElement('button');
          btn.className = 'code-copy-btn';
          btn.textContent = 'Copy';
          btn.onclick = () => {
            navigator.clipboard.writeText(pre.textContent).then(() => {
              btn.textContent = 'Copied!';
              setTimeout(() => btn.textContent = 'Copy', 1500);
            });
          };
          pre.style.position = 'relative';
          pre.appendChild(btn);
        }
      });
    } else {
      // Fallback to non-streaming
      const data = await resp.json();
      hideTyping();
      if (!resp.ok) { toast(data.error || 'Chat error', 'error'); addMsg('ai', `<span class="text-danger">${esc(data.error || 'Error')}</span>`, true); return; }
      chatHistory.push({ role: 'user', content: msg }, { role: 'assistant', content: data.reply });
      addMsg('ai', fmtReply(data.reply), true);
      if (data.sources) addSourcesPanel(data.sources);
    }
  } catch (e) {
    hideTyping();
    // Try non-streaming endpoint as ultimate fallback
    try {
      const resp = await fetch(`${API}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_key: repoKey, message: msg, history: chatHistory.slice(-12) }) });
      const data = await resp.json();
      if (!resp.ok) { toast(data.error || 'Chat error', 'error'); return; }
      chatHistory.push({ role: 'user', content: msg }, { role: 'assistant', content: data.reply });
      addMsg('ai', fmtReply(data.reply), true);
      if (data.sources) addSourcesPanel(data.sources);
    } catch (err) { toast('Cannot reach backend', 'error'); }
  }
}

// ═══════════════════════════════════════════════════════
// EXPLAIN FILE & README
// ═══════════════════════════════════════════════════════
async function explainSelectedFile() {
  if (!selectedFile) { toast('Select a file in the Explorer first', 'info'); return; }
  switchTab('chat', document.getElementById('chat-tab-btn'));
  const fname = selectedFile.path || selectedFile.name;
  addMsg('user', `Explain <code>${fname}</code>`, true);
  showTyping();
  try {
    const resp = await fetch(`${API}/explain-file`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_key: repoKey, filename: fname }) });
    const data = await resp.json(); hideTyping();
    if (!resp.ok) { toast(data.error || 'Explain failed', 'error'); return; }
    addMsg('ai', fmtReply(data.explanation), true);
  } catch (e) { hideTyping(); toast('Backend error', 'error'); }
}

async function triggerReadme() { switchTab('readme', document.getElementById('readme-tab-btn')); await generateReadme(); }

async function generateReadme() {
  const btn = document.getElementById('readme-btn'); btn.disabled = true;
  btn.innerHTML = `<span class="material-symbols-outlined spin" style="font-size:13px">cycle</span> Generating…`;
  document.getElementById('readme-output').innerHTML = `<div class="flex items-center gap-3 p-6 text-sm text-primary-light"><span class="material-symbols-outlined spin" style="font-size:20px">cycle</span>AI is writing your README…</div>`;
  try {
    const resp = await fetch(`${API}/readme`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_key: repoKey }) });
    const data = await resp.json();
    if (!resp.ok) { toast(data.error, 'error'); document.getElementById('readme-output').innerHTML = `<p class="text-danger p-4">${esc(data.error)}</p>`; }
    else { readmeRaw = data.readme; document.getElementById('readme-output').innerHTML = renderMd(readmeRaw); toast('README generated!', 'success'); }
  } catch (e) { toast('Backend error', 'error'); }
  btn.disabled = false; btn.innerHTML = `<span class="material-symbols-outlined fill" style="font-size:13px">auto_awesome</span> Regenerate`;
}

function copyReadme() {
  if (!readmeRaw) return;
  navigator.clipboard.writeText(readmeRaw).then(() => toast('README copied to clipboard', 'success'));
}

// ═══════════════════════════════════════════════════════
// D3 DEPENDENCY GRAPH — colored by file type, sized by complexity
// ═══════════════════════════════════════════════════════
function renderGraph() {
  const svg = d3.select('#graph-svg'); svg.selectAll('*').remove();
  if (!graphData?.nodes?.length) { svg.append('text').attr('x', '50%').attr('y', '50%').attr('text-anchor', 'middle').attr('fill', '#6E7681').attr('font-size', '13').text('No dependency data available'); return; }
  const area = document.getElementById('graph-area');
  const W = area.clientWidth, H = area.clientHeight;
  svg.attr('viewBox', `0 0 ${W} ${H}`);

  const clusterByFolder = document.getElementById('cluster-toggle')?.checked || false;
  const nodes = graphData.nodes.map(d => ({
    ...d,
    color: fileTypeColor(d.lang, d.id),
    size: Math.max(6, Math.min(28, 6 + (d.complexity || 1) * 1.2)),
  }));
  const links = graphData.links.map(d => ({ ...d }));

  // Arrow marker
  svg.append('defs').append('marker').attr('id', 'arr').attr('viewBox', '0 -4 8 8').attr('refX', 16).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#2D333B');

  const g = svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.2, 3]).on('zoom', e => g.attr('transform', e.transform)));

  // Build simulation
  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(100).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-280))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide(d => d.size + 6));

  // Cluster by folder grouping
  if (clusterByFolder) {
    const folders = {};
    nodes.forEach(d => {
      const parts = (d.path || d.id).split('/');
      const folder = parts.length > 1 ? parts[0] : '_root';
      if (!folders[folder]) folders[folder] = { x: 0, y: 0, count: 0 };
      folders[folder].count++;
    });
    const folderKeys = Object.keys(folders);
    const angleStep = (2 * Math.PI) / folderKeys.length;
    folderKeys.forEach((f, i) => {
      folders[f].x = W / 2 + Math.cos(i * angleStep) * W * 0.25;
      folders[f].y = H / 2 + Math.sin(i * angleStep) * H * 0.25;
    });

    sim.force('x', d3.forceX(d => {
      const parts = (d.path || d.id).split('/');
      const folder = parts.length > 1 ? parts[0] : '_root';
      return folders[folder]?.x || W / 2;
    }).strength(0.15));
    sim.force('y', d3.forceY(d => {
      const parts = (d.path || d.id).split('/');
      const folder = parts.length > 1 ? parts[0] : '_root';
      return folders[folder]?.y || H / 2;
    }).strength(0.15));
  }

  const link = g.append('g').selectAll('line').data(links).join('line')
    .attr('class', 'link').attr('stroke-width', 1.5).attr('marker-end', 'url(#arr)');

  const node = g.append('g').selectAll('g').data(nodes).join('g').attr('class', 'node')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  // Heatmap color overlay for complexity
  node.append('circle')
    .attr('r', d => d.size)
    .attr('fill', d => d.color + '30')
    .attr('stroke', d => d.color)
    .attr('stroke-width', d => d.is_hub ? 2.5 : 1.5)
    .attr('stroke-dasharray', d => d.in_cycle ? '4,2' : 'none');

  node.append('text')
    .attr('y', d => d.size + 12)
    .attr('text-anchor', 'middle')
    .attr('font-size', '9')
    .text(d => d.id.length > 18 ? d.id.slice(0, 16) + '…' : d.id);

  // Tooltip
  const tip = document.getElementById('graph-tooltip');
  node.on('mouseover', (e, d) => {
    const grade = complexityGrade(d.complexity);
    tip.className = 'absolute bg-surface border border-border rounded-xl p-3 shadow-xl text-xs pointer-events-none z-10 min-w-48';
    tip.innerHTML = `<div class="font-mono font-bold mb-2">${d.id}</div>
      <div class="space-y-1 text-text-secondary">
        <div>${fmtNum(d.lines)} lines · ${d.functions||'?'} fn</div>
        <div>Complexity: <span class="font-bold" style="color:${complexityColor(d.complexity)}">${d.complexity}</span> (${grade})</div>
        <div>In: ${d.in_degree} · Out: ${d.out_degree}</div>
        ${d.is_hub ? '<div class="text-warning font-semibold">⚠ Hub node</div>' : ''}
        ${d.in_cycle ? '<div class="text-danger font-semibold">⚠ Circular dep</div>' : ''}
      </div>`;
    tip.style.left = (e.layerX + 12) + 'px'; tip.style.top = (e.layerY - 10) + 'px';
  }).on('mouseout', () => tip.className = 'hidden');

  // Click node to open file
  node.on('click', (e, d) => {
    selectFileByPath(d.path || d.id);
  });

  sim.on('tick', () => {
    link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  });
  document.getElementById('graph-subtitle').textContent = `${nodes.length} nodes · ${links.length} edges · ${graphData.metrics?.cycles_detected || 0} circular deps`;
}

// ═══════════════════════════════════════════════════════
// CODE SMELLS
// ═══════════════════════════════════════════════════════
async function loadSmells() {
  try {
    const resp = await fetch(`${API}/smells?repo=${encodeURIComponent(repoKey)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    smellsData = data.smells || [];

    // Update counts
    const critEl = document.getElementById('smell-critical-count');
    const warnEl = document.getElementById('smell-warning-count');
    if (critEl) critEl.textContent = `${data.critical || 0} critical`;
    if (warnEl) warnEl.textContent = `${data.warning || 0} warnings`;

    // Summary card on summary tab
    const card = document.getElementById('smell-summary-card');
    if (card && smellsData.length > 0) {
      card.classList.remove('hidden');
      card.innerHTML = `<div class="p-4 rounded-xl bg-surface border border-border flex items-center justify-between">
        <div class="flex items-center gap-3">
          <span class="material-symbols-outlined text-warning" style="font-size:22px">bug_report</span>
          <div><div class="text-xs font-bold mb-0.5">Code Smells Detected</div>
            <div class="text-[10px] text-text-secondary">${data.critical} critical · ${data.warning} warnings</div></div>
        </div>
        <button onclick="switchTab('smells',document.getElementById('smells-tab-btn'))" class="px-3 py-1.5 bg-warning/10 text-warning rounded-lg text-[11px] font-bold hover:bg-warning/20 transition-all">View All →</button>
      </div>`;
    }

    // Render smells list
    renderSmellsList();
  } catch (e) { console.error('[smells]', e); }
}

function renderSmellsList() {
  const container = document.getElementById('smells-list');
  if (!smellsData.length) {
    container.innerHTML = '<div class="text-center py-12 text-text-secondary"><span class="material-symbols-outlined text-success" style="font-size:40px">check_circle</span><p class="mt-3 text-sm font-semibold">No code smells detected!</p><p class="text-[10px] text-text-muted mt-1">Your code looks clean.</p></div>';
    return;
  }

  container.innerHTML = smellsData.map(s => {
    const icon = s.severity === 'critical' ? 'error' : 'warning';
    const color = s.severity === 'critical' ? 'danger' : 'warning';
    return `<div class="p-3.5 rounded-xl bg-surface border border-border hover:border-${color}/30 transition-all cursor-pointer" onclick="selectFileByPath('${s.file}')">
      <div class="flex items-start gap-3">
        <span class="material-symbols-outlined text-${color} mt-0.5" style="font-size:16px">${icon}</span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] font-bold uppercase tracking-wider text-${color}">${s.severity}</span>
            <span class="text-[10px] font-mono text-text-muted">${s.type.replace(/_/g, ' ')}</span>
          </div>
          <div class="text-xs font-mono font-semibold truncate">${s.file}</div>
          <div class="text-[11px] text-text-secondary mt-1">${s.description}</div>
        </div>
      </div>
    </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════
// GIT TIMELINE
// ═══════════════════════════════════════════════════════
async function loadTimeline() {
  try {
    const resp = await fetch(`${API}/timeline?repo=${encodeURIComponent(repoKey)}`);
    if (!resp.ok) return;
    timelineData = await resp.json();
    renderTimeline();
  } catch (e) { console.error('[timeline]', e); }
}

function renderTimeline() {
  if (!timelineData) return;
  const container = document.getElementById('timeline-content');
  const s = timelineData.summary;

  container.innerHTML = `
    <!-- Summary stats -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 stats-grid">
      <div class="p-3.5 rounded-xl bg-surface border border-border"><div class="text-xl font-black mb-0.5">${s.total_commits}</div><div class="text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Commits</div></div>
      <div class="p-3.5 rounded-xl bg-surface border border-border"><div class="text-xl font-black mb-0.5">${s.total_contributors}</div><div class="text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Contributors</div></div>
      <div class="p-3.5 rounded-xl bg-surface border border-border"><div class="text-xl font-black mb-0.5">${s.active_days}</div><div class="text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Active Days</div></div>
      <div class="p-3.5 rounded-xl bg-surface border border-border"><div class="text-xl font-black text-primary-light mb-0.5">${s.avg_commits_per_day}</div><div class="text-[10px] uppercase tracking-widest text-text-secondary font-semibold">Avg/Day</div></div>
    </div>
    
    <!-- Commit frequency chart -->
    <div class="bg-surface border border-border rounded-xl p-4">
      <h4 class="text-xs font-bold mb-3">Commit Frequency</h4>
      <svg id="timeline-chart" class="w-full" height="120"></svg>
    </div>
    
    <!-- Contributors -->
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div class="bg-surface border border-border rounded-xl p-4">
        <h4 class="text-xs font-bold mb-3">Top Contributors</h4>
        <div class="space-y-2">${timelineData.contributors.slice(0, 6).map(c => `
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium truncate max-w-[180px]">${c.name}</span>
            <span class="text-[10px] font-mono font-bold text-primary-light bg-primary-dim px-2 py-0.5 rounded-full">${c.commits}</span>
          </div>`).join('')}
        </div>
      </div>
      <div class="bg-surface border border-border rounded-xl p-4">
        <h4 class="text-xs font-bold mb-3">Most Changed Files</h4>
        <div class="space-y-2">${timelineData.most_changed_files.slice(0, 6).map(f => `
          <div class="flex items-center justify-between cursor-pointer hover:text-info transition-colors" onclick="selectFileByPath('${f.file}')">
            <span class="text-xs font-mono truncate max-w-[180px]">${f.file}</span>
            <span class="text-[10px] font-mono font-bold text-warning bg-warning/10 px-2 py-0.5 rounded-full">${f.changes}</span>
          </div>`).join('')}
        </div>
      </div>
    </div>
    
    <!-- Recent commits -->
    <div class="bg-surface border border-border rounded-xl p-4">
      <h4 class="text-xs font-bold mb-3">Recent Commits</h4>
      <div class="space-y-0">${timelineData.commits.slice(0, 20).map(c => `
        <div class="commit-row">
          <span class="commit-sha">${c.sha}</span>
          <div class="flex-1 min-w-0">
            <div class="text-xs truncate">${esc(c.message)}</div>
            <div class="text-[10px] text-text-muted mt-0.5">${c.author} · ${c.date}</div>
          </div>
        </div>`).join('')}
      </div>
    </div>
  `;

  // Render D3 frequency chart
  renderTimelineChart();
}

function renderTimelineChart() {
  if (!timelineData?.weekly?.length) return;
  const svg = d3.select('#timeline-chart');
  const svgNode = svg.node();
  if (!svgNode) return;

  const W = svgNode.clientWidth || svgNode.parentElement?.clientWidth || 400;
  const H = 120;
  const data = timelineData.weekly;
  const margin = { top: 10, right: 10, bottom: 25, left: 30 };
  const w = W - margin.left - margin.right;
  const h = H - margin.top - margin.bottom;

  svg.attr('viewBox', `0 0 ${W} ${H}`);
  const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  const x = d3.scaleBand().domain(data.map(d => d.week)).range([0, w]).padding(0.2);
  const y = d3.scaleLinear().domain([0, d3.max(data, d => d.count) || 1]).range([h, 0]);

  g.selectAll('rect').data(data).join('rect')
    .attr('class', 'timeline-chart-bar')
    .attr('x', d => x(d.week))
    .attr('y', d => y(d.count))
    .attr('width', x.bandwidth())
    .attr('height', d => h - y(d.count));

  // X axis (show every Nth label to avoid overlap)
  const step = Math.max(1, Math.floor(data.length / 6));
  g.append('g').attr('transform', `translate(0,${h})`)
    .call(d3.axisBottom(x).tickValues(data.filter((_, i) => i % step === 0).map(d => d.week)))
    .selectAll('text').attr('font-size', '8').attr('fill', '#6E7681');

  g.append('g')
    .call(d3.axisLeft(y).ticks(4).tickSize(-w).tickFormat(d3.format('d')))
    .selectAll('text').attr('font-size', '8').attr('fill', '#6E7681');

  g.selectAll('.domain').attr('stroke', '#2D333B');
  g.selectAll('.tick line').attr('stroke', '#2D333B').attr('stroke-opacity', 0.3);
}

async function loadInsights() {
  document.getElementById('language-legend').innerHTML = '<div class="text-[10px] text-text-secondary">Loading...</div>';
  document.getElementById('health-status').innerHTML = '<div class="text-[10px] text-text-secondary">Loading...</div>';
  document.getElementById('tech-debt-message').innerHTML = '<div class="text-[10px] text-text-secondary">Loading...</div>';
  try {
    if (!repoKey) {
      document.getElementById('language-legend').innerHTML = '<div class="text-[10px] text-text-secondary">No repo selected</div>';
      return;
    }
    const resp = await fetch(`${API}/insights?repo=${encodeURIComponent(repoKey)}`);
    if (!resp.ok) {
      const error = await resp.text();
      document.getElementById('language-legend').innerHTML = `<div class="text-[10px] text-danger">Error ${resp.status}</div>`;
      return;
    }
    const data = await resp.json();
    if (!data.data) {
      document.getElementById('language-legend').innerHTML = '<div class="text-[10px] text-text-secondary">No data</div>';
      return;
    }
    renderLanguageBreakdown(data.data.language_breakdown);
    renderHealthRadar(data.data.health_radar);
    renderTechDebtGauge(data.data.tech_debt);
  } catch (e) {
    console.error('[insights]', e);
    document.getElementById('language-legend').innerHTML = `<div class="text-[10px] text-danger">${e.message}</div>`;
  }
}

function renderLanguageBreakdown(langData) {
  if (!langData?.languages?.length) {
    document.getElementById('language-legend').innerHTML = '<div class="text-[10px] text-text-secondary py-4">No language data available</div>';
    return;
  }
  
  const svg = d3.select('#language-donut');
  svg.selectAll('*').remove();
  
  const data = langData.languages;
  const size = 200;
  const innerRadius = size / 3;
  const outerRadius = size / 2;
  
  svg.attr('viewBox', `0 0 ${size} ${size}`);
  const g = svg.append('g').attr('transform', `translate(${size / 2},${size / 2})`);
  
  const pie = d3.pie().value(d => d.count);
  const arc = d3.arc().innerRadius(innerRadius).outerRadius(outerRadius);
  
  const arcs = g.selectAll('path').data(pie(data)).join('path')
    .attr('fill', d => d.data.color)
    .attr('d', arc)
    .attr('opacity', 0.85)
    .attr('stroke', '#121313')
    .attr('stroke-width', 2);
  
  // Center text (primary language)
  g.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '0.35em')
    .attr('font-size', '14')
    .attr('font-weight', 'bold')
    .attr('fill', '#E6EDF3')
    .text(langData.primary_language);
  
  g.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '1.5em')
    .attr('font-size', '10')
    .attr('fill', '#8B949E')
    .text(`${langData.total_files} files`);
  
  arcs.on('mouseover', function(e, d) {
    d3.select(this).attr('opacity', 1);
  }).on('mouseout', function(e, d) {
    d3.select(this).attr('opacity', 0.85);
  });
  
  // Legend
  const legend = document.getElementById('language-legend');
  legend.innerHTML = data.map(d => `
    <div class="flex items-center gap-2">
      <div class="w-2 h-2 rounded-full" style="background:${d.color}"></div>
      <span class="text-[10px] text-text-secondary flex-1">${d.language}</span>
      <span class="text-[10px] font-mono font-bold text-text-primary">${d.percentage}%</span>
    </div>`).join('');
}

function renderHealthRadar(healthData) {
  if (!healthData) {
    document.getElementById('health-status').innerHTML = '<div class="text-[10px] text-text-secondary">No data available</div>';
    return;
  }
  
  const svg = d3.select('#health-radar');
  svg.selectAll('*').remove();
  
  const axes = [
    { label: 'Security', value: healthData.security || 50 },
    { label: 'Maintenance', value: healthData.maintenance || 50 },
    { label: 'Documentation', value: healthData.documentation || 50 },
    { label: 'Tests', value: healthData.tests || 50 },
    { label: 'Community', value: healthData.community || 50 }
  ];
  
  const size = 200;
  const levels = 5;
  const radius = size / 2 - 20;
  
  svg.attr('viewBox', `0 0 ${size} ${size}`);
  const g = svg.append('g').attr('transform', `translate(${size / 2},${size / 2})`);
  
  // Draw concentric circles
  for (let i = 1; i <= levels; i++) {
    g.append('circle')
      .attr('cx', 0).attr('cy', 0)
      .attr('r', (radius / levels) * i)
      .attr('fill', 'none')
      .attr('stroke', '#27272A')
      .attr('stroke-width', 0.5)
      .attr('opacity', 0.6);
  }
  
  // Draw axes
  const angle = (2 * Math.PI) / axes.length;
  for (let i = 0; i < axes.length; i++) {
    const x = radius * Math.cos(angle * i - Math.PI / 2);
    const y = radius * Math.sin(angle * i - Math.PI / 2);
    g.append('line')
      .attr('x1', 0).attr('y1', 0)
      .attr('x2', x).attr('y2', y)
      .attr('stroke', '#2D333B')
      .attr('stroke-width', 0.5);
    
    // Axis labels
    const lx = (radius + 30) * Math.cos(angle * i - Math.PI / 2);
    const ly = (radius + 30) * Math.sin(angle * i - Math.PI / 2);
    g.append('text')
      .attr('x', lx).attr('y', ly)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9')
      .attr('font-weight', 'bold')
      .attr('fill', '#8B949E')
      .text(axes[i].label);
  }
  
  // Plot area
  const points = axes.map((d, i) => {
    const r = Math.max(1, Math.min(100, d.value)) / 100 * radius;
    const x = r * Math.cos(angle * i - Math.PI / 2);
    const y = r * Math.sin(angle * i - Math.PI / 2);
    return [x, y];
  });
  
  g.append('polygon')
    .attr('points', points.map(p => p.join(',')).join(' '))
    .attr('fill', 'rgba(255, 96, 68, 0.25)')
    .attr('stroke', '#FF7A62')
    .attr('stroke-width', 1.5);
  
  // Dots on vertices
  g.selectAll('.vertex').data(points).join('circle')
    .attr('cx', d => d[0]).attr('cy', d => d[1])
    .attr('r', 2.5)
    .attr('fill', '#FF7A62');
  
  // Health status
  const statusEl = document.getElementById('health-status');
  const statusColor = healthData.status === 'excellent' ? '#3FB950' : 
                       healthData.status === 'healthy' ? '#58A6FF' :
                       healthData.status === 'fair' ? '#F0883E' : '#F85149';
  statusEl.innerHTML = `<div class="text-xs font-bold mb-1" style="color:${statusColor}">${(healthData.status || 'unknown').toUpperCase()}</div>
    <div class="text-[10px] text-text-secondary">Overall Health: <strong style="color:${statusColor}">${healthData.overall_health || 0}/100</strong></div>`;
}

function renderTechDebtGauge(debtData) {
  if (!debtData) {
    document.getElementById('tech-debt-message').innerHTML = '<div class="text-[10px] text-text-secondary">No data available</div>';
    return;
  }
  
  const svg = d3.select('#tech-debt-gauge');
  svg.selectAll('*').remove();
  
  const size = 200;
  const radius = size / 2 - 20;
  const startAngle = Math.PI;
  const endAngle = 2 * Math.PI;
  const range = endAngle - startAngle;
  
  svg.attr('viewBox', `0 0 ${size} ${size}`);
  const g = svg.append('g').attr('transform', `translate(${size / 2},${size / 2})`);
  
  // Background arc (gray)
  const bgArc = d3.arc()
    .innerRadius(radius - 15)
    .outerRadius(radius);
  
  g.append('path')
    .attr('d', bgArc({
      startAngle: startAngle,
      endAngle: endAngle,
      padAngle: 0
    }))
    .attr('fill', '#27272A');
  
  // Gradient for score arc
  const gradient = svg.append('defs').append('linearGradient')
    .attr('id', 'scoreGradient')
    .attr('x1', '0%').attr('y1', '0%')
    .attr('x2', '100%').attr('y2', '0%');
  
  gradient.append('stop').attr('offset', '0%').attr('stop-color', '#3FB950');
  gradient.append('stop').attr('offset', '50%').attr('stop-color', '#F0883E');
  gradient.append('stop').attr('offset', '100%').attr('stop-color', '#F85149');
  
  // Score arc
  const score = Math.max(0, Math.min(100, debtData.score || 0));
  const scoreAngle = startAngle + (score / 100) * range;
  const scoreArc = d3.arc()
    .innerRadius(radius - 15)
    .outerRadius(radius);
  
  g.append('path')
    .attr('d', scoreArc({
      startAngle: startAngle,
      endAngle: scoreAngle,
      padAngle: 0
    }))
    .attr('fill', 'url(#scoreGradient)');
  
  // Needle
  const needleLength = radius - 5;
  const needleX = needleLength * Math.cos(scoreAngle - Math.PI / 2);
  const needleY = needleLength * Math.sin(scoreAngle - Math.PI / 2);
  
  g.append('line')
    .attr('x1', 0).attr('y1', 0)
    .attr('x2', needleX).attr('y2', needleY)
    .attr('stroke', '#E6EDF3')
    .attr('stroke-width', 2.5)
    .attr('stroke-linecap', 'round');
  
  g.append('circle')
    .attr('cx', 0).attr('cy', 0)
    .attr('r', 4)
    .attr('fill', '#E6EDF3');
  
  // Score text
  g.append('text')
    .attr('x', 0).attr('y', 15)
    .attr('text-anchor', 'middle')
    .attr('font-size', '24')
    .attr('font-weight', 'bold')
    .attr('fill', '#E6EDF3')
    .text(score);
  
  g.append('text')
    .attr('x', 0).attr('y', 35)
    .attr('text-anchor', 'middle')
    .attr('font-size', '10')
    .attr('fill', '#8B949E')
    .text('Tech Debt Score');
  
  // Message
  const msgEl = document.getElementById('tech-debt-message');
  const msgColor = debtData.color === 'green' ? '#3FB950' :
                   debtData.color === 'yellow' ? '#F0883E' :
                   debtData.color === 'red' ? '#F85149' : '#8B949E';
  msgEl.innerHTML = `<div class="text-xs font-bold mb-1" style="color:${msgColor}">${(debtData.message || 'Unknown').slice(0, 40)}</div>
    <div class="text-[10px] text-text-secondary">${(debtData.recommendation || 'No recommendation').slice(0, 100)}…</div>`;
}

// ═══════════════════════════════════════════════════════
// HEALTH CHECK
// ═══════════════════════════════════════════════════════
async function runHealthCheck() {
  const c = document.getElementById('health-cards');
  c.innerHTML = '<div class="p-6 rounded-xl bg-surface border border-border text-center"><span class="material-symbols-outlined spin" style="font-size:24px">cycle</span><p class="mt-2 text-sm text-text-secondary">Checking services…</p></div>';
  try {
    const resp = await fetch(`${API}/health?deep=true`);
    const d = await resp.json();
    c.innerHTML = `
      <div class="p-5 rounded-xl bg-surface border border-border ${d.ollama?.running ? 'health-ok' : 'health-fail'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold">Ollama (Primary AI)</h3><span class="text-xs font-bold ${d.ollama?.running ? 'text-success' : 'text-danger'}">${d.ollama?.running ? '● Running' : '● Offline'}</span></div>
        <p class="text-xs text-text-secondary">Model: <code class="text-primary-light bg-primary-dim px-1 rounded">${d.ollama?.configured_model || '?'}</code> ${d.ollama?.model_available ? '✓ Available' : '✗ Not pulled'}</p>
        ${d.ollama?.installed_models?.length ? `<p class="text-xs text-text-secondary mt-1">Installed: ${d.ollama.installed_models.join(', ')}</p>` : ''}
        ${!d.ollama?.running ? '<p class="text-xs text-warning mt-2">Install from <a href="https://ollama.com" class="underline text-info">ollama.com</a> then run <code class="bg-surface-higher px-1 rounded">ollama pull phi3</code></p>' : ''}
      </div>
      <div class="p-5 rounded-xl bg-surface border border-border ${d.claude?.configured ? (d.claude?.valid ? 'health-ok' : 'health-warn') : 'health-warn'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold">Claude API (Fallback)</h3><span class="text-xs font-bold ${d.claude?.valid ? 'text-success' : d.claude?.configured ? 'text-warning' : 'text-text-secondary'}">${d.claude?.valid ? '● Valid' : d.claude?.configured ? '● Invalid Key' : '○ Not configured'}</span></div>
        <p class="text-xs text-text-secondary">${d.claude?.configured ? 'API key is set in .env' : 'Add ANTHROPIC_API_KEY to .env for fallback'}</p>
        ${d.claude?.error ? `<p class="text-xs text-danger mt-1">${esc(d.claude.error).slice(0,120)}</p>` : ''}
      </div>
      <div class="p-5 rounded-xl bg-surface border border-border ${d.github_token ? 'health-ok' : 'health-warn'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold">GitHub Token</h3><span class="text-xs font-bold ${d.github_token ? 'text-success' : 'text-warning'}">${d.github_token ? '● Configured' : '○ Missing'}</span></div>
        <p class="text-xs text-text-secondary">${d.github_token ? '5000 req/hr rate limit' : '60 req/hr limit — add GITHUB_TOKEN to .env'}</p>
      </div>
      <div class="p-5 rounded-xl bg-surface border border-border health-ok">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold">Backend Server</h3><span class="text-xs font-bold text-success">● Running</span></div>
        <p class="text-xs text-text-secondary">Active engine: <strong class="text-primary-light">${d.engine}</strong> · ${d.repos_loaded} repos loaded</p>
        ${d.cache ? `<p class="text-xs text-text-muted mt-1">Cache: ${d.cache.cached_repos} repos · ${d.cache.cached_file_embeds} file embeds</p>` : ''}
      </div>`;
  } catch (e) {
    c.innerHTML = `<div class="p-6 rounded-xl bg-surface border border-border health-fail"><h3 class="text-sm font-bold text-danger mb-2">Backend Offline</h3><p class="text-xs text-text-secondary">Cannot connect. Run: <code class="bg-surface-higher px-1 rounded">python run.py</code></p></div>`;
  }
}

// ═══════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════
function fmtNum(n) { if (!n) return '0'; return n > 999 ? (n / 1000).toFixed(1) + 'k' : String(n); }
function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// FIX: Extract code blocks BEFORE escaping to prevent hljs receiving HTML entities
function fmtReply(t) {
  const blocks = [];
  // Step 1: Extract and highlight code blocks from raw text first
  let s = t.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    let highlighted = esc(code.trim()); // escape the code content itself
    try {
      if (lang && hljs.getLanguage(lang)) {
        highlighted = hljs.highlight(code.trim(), { language: lang }).value;
      }
    } catch (_) {}
    blocks.push(`<pre style="position:relative">${highlighted}</pre>`);
    return `@@B${blocks.length - 1}@@`;
  });
  // Step 2: Now escape the remaining plain text
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');
  // Step 3: Re-inject the highlighted code blocks
  return s.replace(/@@B(\d+)@@/g, (_, i) => blocks[Number(i)] || '');
}

function gradeStyle(grade) {
  const m = {
    A: { bg: 'bg-success/15', text: 'text-success' },
    B: { bg: 'bg-success/15', text: 'text-success' },
    C: { bg: 'bg-info/15', text: 'text-info' },
    D: { bg: 'bg-warning/15', text: 'text-warning' },
    E: { bg: 'bg-danger/15', text: 'text-danger' },
    F: { bg: 'bg-danger/20', text: 'text-danger' },
  };
  return m[grade] || m['C'];
}

function complexityGrade(score) {
  if (score <= 5)  return 'A (Low)';
  if (score <= 10) return 'B (Low)';
  if (score <= 15) return 'C (Medium)';
  if (score <= 20) return 'D (Medium)';
  if (score <= 30) return 'E (High)';
  return 'F (Critical)';
}

function complexityColor(score) {
  if (score <= 5)  return '#3FB950';
  if (score <= 10) return '#58A6FF';
  if (score <= 20) return '#F0883E';
  return '#F85149';
}

/** Color nodes by file type: .py=blue, .js=yellow, .ts=cyan, .html=orange, .css=pink, other=gray */
function fileTypeColor(lang, filename) {
  const ext = filename?.split('.').pop()?.toLowerCase() || '';
  const map = {
    py: '#58A6FF', python: '#58A6FF',
    js: '#F0883E', jsx: '#F0883E', javascript: '#F0883E',
    ts: '#3FB950', tsx: '#3FB950', typescript: '#3FB950',
    html: '#F85149',
    css: '#E879A6',
    go: '#00ADD8', rust: '#DEA584',
    java: '#B07219', ruby: '#CC342D',
  };
  return map[ext] || map[lang] || '#8B949E';
}

function langIcon(lang) { return { python:'code', javascript:'code', typescript:'code', java:'coffee', html:'html', css:'css' }[lang] || 'insert_drive_file'; }
function langColor(lang) { return { python:'text-info', javascript:'text-warning', typescript:'text-success', java:'text-warning', go:'text-[#00ADD8]', rust:'text-[#DEA584]', ruby:'text-danger' }[lang] || 'text-text-secondary'; }

function renderMd(md) {
  // Extract code blocks BEFORE escaping to prevent double-escaping
  const codeBlocks = [];
  let h = md.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, code) => {
    codeBlocks.push(`<pre><code>${esc(code.trimEnd())}</code></pre>`);
    return `@@CB${codeBlocks.length - 1}@@`;
  });
  // Escape the remaining text
  h = esc(h);
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>').replace(/^## (.+)$/gm, '<h2>$1</h2>').replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\*([^*]+)\*/g, '<em>$1</em>');
  h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  h = h.replace(/^---$/gm, '<hr>').replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  h = h.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
  h = h.replace(/\n\n(?!<)/g, '</p><p>');
  // Re-inject the code blocks
  h = h.replace(/@@CB(\d+)@@/g, (_, i) => codeBlocks[Number(i)] || '');
  return `<p>${h}</p>`;
}

// ═══════════════════════════════════════════════════════
// RESIZABLE CHAT PANEL
// ═══════════════════════════════════════════════════════
(function initResize() {
  const handle = document.getElementById('chat-resize-handle');
  const panel = document.getElementById('chat-panel');
  if (!handle || !panel) return;

  // Restore saved width
  const saved = localStorage.getItem('repolens-chat-width');
  if (saved) panel.style.width = saved + 'px';

  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    dragging = true;
    startX = e.clientX;
    startW = panel.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const delta = startX - e.clientX;
    const newW = Math.min(700, Math.max(280, startW + delta));
    panel.style.width = newW + 'px';
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    localStorage.setItem('repolens-chat-width', panel.offsetWidth);
  });
})();

// ── Init ──
window.onload = () => renderHistory();
