/* ═══════════ RepoLens — SPA Application Logic ═══════════ */
const API = window.location.origin + '/api';

// ── State ───────────────────────────────
let repoData = null, repoKey = '', selectedFile = null;
let chatHistory = [], readmeRaw = '', complexityData = [], graphData = null;

// ══════════════════════════════════════════
// TOAST NOTIFICATIONS
// ══════════════════════════════════════════
function toast(msg, type = 'info', duration = 4000) {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  const icons = { success: 'check_circle', error: 'error', info: 'info' };
  el.innerHTML = `<span class="material-symbols-outlined fill" style="font-size:18px">${icons[type] || 'info'}</span><span>${msg}</span>`;
  c.appendChild(el);
  setTimeout(() => { el.classList.add('removing'); setTimeout(() => el.remove(), 300); }, duration);
}

// ══════════════════════════════════════════
// VIEW ROUTER
// ══════════════════════════════════════════
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

// ══════════════════════════════════════════
// DARK MODE
// ══════════════════════════════════════════
function toggleDark() {
  document.documentElement.classList.toggle('dark');
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('repolens-dark', isDark ? '1' : '0');
  // Swap highlight.js theme
  document.getElementById('hljs-light').disabled = isDark;
  document.getElementById('hljs-dark').disabled = !isDark;
}
if (localStorage.getItem('repolens-dark') === '1') {
  document.documentElement.classList.add('dark');
  document.getElementById('hljs-light').disabled = true;
  document.getElementById('hljs-dark').disabled = false;
}

// ══════════════════════════════════════════
// REPO HISTORY (localStorage)
// ══════════════════════════════════════════
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
    <button onclick="fillExample('${r.url}')" class="w-full text-left flex items-center justify-between p-3 rounded-lg bg-surface-container-lowest border border-outline-variant/15 hover:border-primary/30 transition-all group">
      <div class="flex items-center gap-3"><span class="material-symbols-outlined text-primary" style="font-size:16px">folder</span><span class="text-sm font-mono font-medium text-on-surface">${r.name}</span></div>
      <span class="text-[10px] text-on-surface-variant">${new Date(r.ts).toLocaleDateString()}</span>
    </button>`).join('');
}

function fillExample(url) { document.getElementById('repo-url').value = url; }

// ══════════════════════════════════════════
// ANALYSIS (with SSE progress)
// ══════════════════════════════════════════
async function startAnalysis() {
  const url = document.getElementById('repo-url').value.trim();
  if (!url) { document.getElementById('input-wrapper').classList.add('border-red-400'); setTimeout(() => document.getElementById('input-wrapper').classList.remove('border-red-400'), 1500); return; }
  if (!url.includes('github.com')) { toast('Please enter a valid GitHub URL', 'error'); return; }

  const btn = document.getElementById('analyze-btn');
  btn.disabled = true;
  document.getElementById('btn-text').textContent = 'Analyzing…';
  document.getElementById('progress-wrap').classList.remove('hidden');
  setProgress(0, 'Starting analysis…', '');

  const analysisId = 'a' + Date.now();

  // Start SSE listener
  let evtSource;
  try {
    evtSource = new EventSource(`${API}/progress/${analysisId}`);
    evtSource.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.pct >= 0) setProgress(d.pct, d.step, d.detail);
        if (d.pct >= 100 || d.pct < 0) evtSource.close();
      } catch (_) {}
    };
    evtSource.onerror = () => evtSource.close();
  } catch (_) {}

  try {
    const resp = await fetch(`${API}/analyze`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: url, analysis_id: analysisId }),
    });
    if (evtSource) evtSource.close();
    const data = await resp.json();
    if (!resp.ok) { toast(data.error || 'Analysis failed', 'error'); resetBtn(); return; }

    setProgress(100, 'Analysis complete!', 'DONE');
    repoData = data;
    repoKey = data.repo_key || data.meta?.full_name || '';
    saveToHistory(url, repoKey);

    setTimeout(() => { resetBtn(); loadDashboard(); }, 500);
  } catch (err) {
    if (evtSource) evtSource.close();
    toast('Cannot connect to backend. Run: python run.py', 'error');
    resetBtn();
  }
}

function setProgress(pct, label, sub) {
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-pct').textContent = pct + '%';
  document.getElementById('progress-step').textContent = label;
  document.getElementById('progress-sub').textContent = sub;
}

function resetBtn() {
  document.getElementById('analyze-btn').disabled = false;
  document.getElementById('btn-text').textContent = 'Analyze';
  document.getElementById('progress-wrap').classList.add('hidden');
}

// ══════════════════════════════════════════
// LOAD DASHBOARD
// ══════════════════════════════════════════
async function loadDashboard() {
  if (!repoData) return;
  complexityData = repoData.complexity || [];
  graphData = repoData.graph || null;

  showView('dashboard');
  document.querySelectorAll('.tab-content').forEach((el, i) => {
    el.style.display = i === 0 ? 'flex' : 'none'; el.style.flex = '1'; el.style.overflow = 'hidden';
  });
  document.getElementById('tab-summary').style.overflow = 'auto';

  populateHeader(); populateSummary(); renderFileTree(repoData.file_tree || []);
  renderHeatTable(); renderGraphInsights(); renderComplexityCards(); initChat();
}

// ══════════════════════════════════════════
// HEADER & SUMMARY
// ══════════════════════════════════════════
function populateHeader() {
  const m = repoData.meta;
  document.getElementById('header-repo').textContent = m.full_name;
  document.getElementById('pill-files').textContent = repoData.stats?.total_files + ' files';
  document.getElementById('pill-lines').textContent = fmtNum(repoData.stats?.total_lines) + ' lines';
  document.getElementById('pill-lang').textContent = m.language || '?';
  document.title = m.full_name + ' — RepoLens';
}

function populateSummary() {
  const m = repoData.meta, s = repoData.stats;
  document.getElementById('sum-name').textContent = m.full_name;
  document.getElementById('sum-desc').textContent = m.description || '';
  document.getElementById('s-files').textContent = s?.total_files ?? '–';
  document.getElementById('s-lines').textContent = fmtNum(s?.total_lines);
  document.getElementById('s-funcs').textContent = fmtNum(s?.total_functions);
  document.getElementById('s-cmplx').textContent = s?.avg_complexity ?? '–';
  document.getElementById('sum-topics').innerHTML = (m.topics || []).map(t => `<span class="px-2.5 py-0.5 bg-secondary-container text-on-secondary-fixed-variant text-[10px] font-semibold rounded-full">${t}</span>`).join('');
}

function renderGraphInsights() {
  const g = graphData?.metrics; if (!g) return;
  document.getElementById('graph-insights').innerHTML = `
    <div class="p-4 rounded-xl bg-surface-container-low"><div class="flex items-center gap-2 mb-3"><span class="material-symbols-outlined text-primary" style="font-size:18px">hub</span><span class="text-xs font-bold text-on-surface">Dependency Graph</span></div>
      <div class="grid grid-cols-2 gap-2 text-xs"><div class="text-on-surface-variant">Nodes</div><div class="font-mono font-bold text-on-surface">${g.total_nodes}</div><div class="text-on-surface-variant">Edges</div><div class="font-mono font-bold text-on-surface">${g.total_edges}</div><div class="text-on-surface-variant">Circular deps</div><div class="font-mono font-bold ${g.cycles_detected > 0 ? 'text-red-600' : 'text-green-600'}">${g.cycles_detected}</div><div class="text-on-surface-variant">Isolated</div><div class="font-mono font-bold text-on-surface">${g.isolated_files?.length || 0}</div></div></div>
    <div class="p-4 rounded-xl bg-surface-container-low"><div class="flex items-center gap-2 mb-3"><span class="material-symbols-outlined text-tertiary" style="font-size:18px">star</span><span class="text-xs font-bold text-on-surface">Most Imported</span></div>
      <ul class="space-y-1.5">${(g.most_imported || []).slice(0, 4).map(([n, c]) => `<li class="flex items-center justify-between"><span class="text-xs font-mono text-on-surface truncate max-w-[150px]">${n}</span><span class="text-[10px] font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">${c}</span></li>`).join('')}</ul></div>`;
}

function renderHeatTable() {
  const sorted = [...complexityData].sort((a, b) => b.complexity - a.complexity).slice(0, 8);
  document.getElementById('heat-table').innerHTML = sorted.map(f => {
    const g = gradeStyle(f.grade);
    return `<tr class="hover:bg-surface-container-low transition-colors"><td class="px-5 py-3 font-mono text-on-surface truncate max-w-[180px]">${f.path || f.file}</td><td class="px-5 py-3 font-bold text-on-surface">${f.complexity}</td><td class="px-5 py-3"><span class="inline-flex px-2 py-0.5 rounded text-[10px] font-bold ${g.bg} ${g.text}">${f.grade_label}</span></td><td class="px-5 py-3 text-right font-mono text-on-surface-variant">${fmtNum(f.lines)}</td></tr>`;
  }).join('');
}

// ══════════════════════════════════════════
// COMPLEXITY CARDS
// ══════════════════════════════════════════
function renderComplexityCards() {
  const sortKey = document.getElementById('sort-select')?.value || 'score';
  const sorted = [...complexityData].sort((a, b) => (b[sortKey] || b.complexity) - (a[sortKey] || a.complexity));
  const max_c = Math.max(...sorted.map(f => f.complexity), 10);
  document.getElementById('complexity-cards').innerHTML = sorted.map(f => {
    const g = gradeStyle(f.grade);
    const pct = Math.min(100, Math.round(f.complexity / max_c * 100));
    const barColor = { A:'#22c55e', B:'#22c55e', C:'#0969da', D:'#0969da', E:'#f97316', F:'#ba1a1a' }[f.grade] || '#0969da';
    const topFns = (f.top_functions || []).slice(0, 3);
    return `<div class="p-4 rounded-xl bg-surface-container-lowest border border-outline-variant/15 hover:border-outline-variant/35 transition-all cursor-pointer" onclick="selectFileByPath('${f.path||f.file}')"><div class="flex items-start justify-between mb-3"><div class="min-w-0"><div class="text-xs font-mono font-semibold text-on-surface truncate">${f.path||f.file}</div><div class="text-[10px] text-on-surface-variant mt-0.5">${fmtNum(f.lines)} lines · ${f.functions||'?'} fn · ${f.lang}</div></div><div class="text-right ml-3 shrink-0"><div class="text-xl font-black text-on-surface">${f.complexity}</div><span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold ${g.bg} ${g.text}">${f.grade_label}</span></div></div><div class="w-full h-1.5 bg-surface-container rounded-full overflow-hidden mb-2"><div class="h-full rounded-full" style="width:${pct}%;background:${barColor}"></div></div>${topFns.length ? '<div class="mt-2 space-y-1">' + topFns.map(fn => `<div class="flex items-center justify-between"><span class="text-[10px] font-mono text-on-surface-variant truncate">${fn.name}()</span><span class="text-[10px] font-bold ${fn.complexity > 10 ? 'text-orange-600' : 'text-on-surface-variant'}">${fn.complexity}</span></div>`).join('') + '</div>' : '' }${f.maintainability_index ? `<div class="mt-2 text-[10px] text-on-surface-variant">MI: <strong class="${f.maintainability_index < 20 ? 'text-red-600' : f.maintainability_index < 65 ? 'text-orange-600' : 'text-green-600'}">${f.maintainability_index}</strong>/100</div>` : ''}</div>`;
  }).join('');
}

// ══════════════════════════════════════════
// FILE TREE
// ══════════════════════════════════════════
function renderFileTree(items, container, depth = 0) {
  if (!container) container = document.getElementById('file-tree');
  if (depth === 0) container.innerHTML = '';
  for (const item of items) {
    if (item.type === 'folder') {
      const wrap = document.createElement('div');
      const header = document.createElement('div');
      header.className = 'file-row flex items-center gap-2 py-1.5 rounded-lg cursor-pointer text-on-surface select-none';
      header.style.paddingLeft = (12 + depth * 10) + 'px';
      const uid = btoa(unescape(encodeURIComponent(item.name + depth))).replace(/[^a-zA-Z0-9]/g, '_');
      header.innerHTML = `<span class="material-symbols-outlined fill text-secondary" style="font-size:15px" id="fi-${uid}">folder_open</span><span class="text-xs font-medium">${item.name}/</span>`;
      const kids = document.createElement('div'); kids.id = 'fc-' + uid;
      header.onclick = () => { const open = kids.style.display !== 'none'; kids.style.display = open ? 'none' : 'block'; document.getElementById('fi-' + uid).textContent = open ? 'folder' : 'folder_open'; };
      if (item.children?.length) renderFileTree(item.children, kids, depth + 1);
      wrap.append(header, kids); container.appendChild(wrap);
    } else {
      const div = document.createElement('div');
      div.className = 'file-row flex items-center gap-2 py-1.5 rounded-lg cursor-pointer text-on-surface';
      div.style.paddingLeft = (12 + depth * 10) + 'px';
      div.setAttribute('data-path', item.path || item.name);
      div.innerHTML = `<span class="${langColor(item.lang)} material-symbols-outlined" style="font-size:14px">${langIcon(item.lang)}</span><span class="text-xs truncate">${item.name}</span>`;
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

// ══════════════════════════════════════════
// FILE CONTENT VIEWER (with syntax highlighting)
// ══════════════════════════════════════════
async function loadFileViewer(path) {
  switchTab('chat', document.getElementById('chat-tab-btn'));
  document.getElementById('viewer-filename').textContent = path;
  document.getElementById('viewer-content').innerHTML = '<div class="flex items-center justify-center h-full text-on-surface-variant text-sm"><span class="material-symbols-outlined spin mr-2" style="font-size:18px">cycle</span>Loading…</div>';

  try {
    const resp = await fetch(`${API}/file-content?repo=${encodeURIComponent(repoKey)}&path=${encodeURIComponent(path)}`);
    const data = await resp.json();
    if (!resp.ok) { document.getElementById('viewer-content').innerHTML = `<div class="p-6 text-red-600">${data.error}</div>`; return; }

    document.getElementById('viewer-stats').textContent = `${data.lines} lines · ${data.functions} fn · complexity ${data.complexity} · ${data.lang}`;
    const lines = data.content.split('\n');
    const langMap = { python: 'python', javascript: 'javascript', typescript: 'typescript', java: 'java', go: 'go', rust: 'rust', ruby: 'ruby', php: 'php', html: 'xml', css: 'css', yaml: 'yaml', bash: 'bash', cpp: 'cpp', c: 'c', csharp: 'csharp' };
    const hljsLang = langMap[data.lang] || 'plaintext';

    let highlighted;
    try { highlighted = hljs.highlight(data.content, { language: hljsLang }).value; } catch (_) { highlighted = esc(data.content); }
    const hLines = highlighted.split('\n');

    document.getElementById('viewer-content').innerHTML = `<div class="code-viewer font-mono p-0" style="overflow:auto;height:100%"><div class="p-4">${hLines.map((line, i) => `<div class="line"><span class="line-num">${i + 1}</span><span class="line-content">${line || ' '}</span></div>`).join('')}</div></div>`;
  } catch (e) { toast('Failed to load file', 'error'); }
}

// ══════════════════════════════════════════
// TABS
// ══════════════════════════════════════════
function switchTab(name, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(p => { p.classList.remove('active'); p.style.display = 'none'; });
  if (btn) btn.classList.add('active');
  const el = document.getElementById('tab-' + name);
  if (!el) return;
  el.classList.add('active'); el.style.display = 'flex'; el.style.flex = '1';
  el.style.overflow = (name === 'graph' || name === 'chat') ? 'hidden' : 'auto';
  if (name === 'graph') setTimeout(renderGraph, 80);
}

// ══════════════════════════════════════════
// CHAT
// ══════════════════════════════════════════
function initChat() {
  chatHistory = [];
  addMsg('ai', `Hello! I've analyzed <code style="background:#d5e3fc;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:11px">${repoData.meta.full_name}</code>. Found ${repoData.stats?.total_files} files, ${fmtNum(repoData.stats?.total_lines)} lines of ${repoData.meta.language}. Ask me anything!`);
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
}

function showTyping() {
  const wrap = document.getElementById('chat-messages');
  const div = document.createElement('div'); div.id = 'typing'; div.className = 'flex items-center gap-2 px-1 mr-4';
  div.innerHTML = `<div class="flex gap-1"><div class="size-1.5 bg-tertiary rounded-full b1"></div><div class="size-1.5 bg-tertiary rounded-full b2"></div><div class="size-1.5 bg-tertiary rounded-full b3"></div></div><span class="text-[10px] font-medium text-tertiary italic">Analyzing code…</span>`;
  wrap.append(div); wrap.scrollTop = wrap.scrollHeight;
}
function hideTyping() { document.getElementById('typing')?.remove(); }
function onChatKey(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }
function sendQuick(t) { document.getElementById('chat-input').value = t; sendChat(); }

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim(); if (!msg) return;
  input.value = '';
  addMsg('user', esc(msg), true); showTyping();
  try {
    const resp = await fetch(`${API}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_key: repoKey, message: msg, history: chatHistory.slice(-12) }) });
    const data = await resp.json(); hideTyping();
    if (!resp.ok) { toast(data.error || 'Chat error', 'error'); addMsg('ai', `<span class="text-red-500">${esc(data.error || 'Error')}</span>`, true); return; }
    chatHistory.push({ role: 'user', content: msg }, { role: 'assistant', content: data.reply });
    addMsg('ai', fmtReply(data.reply), true);
  } catch (e) { hideTyping(); toast('Cannot reach backend', 'error'); }
}

// ══════════════════════════════════════════
// EXPLAIN FILE & README
// ══════════════════════════════════════════
async function explainSelectedFile() {
  if (!selectedFile) { toast('Select a file in the Explorer first', 'info'); return; }
  switchTab('chat', document.getElementById('chat-tab-btn'));
  const fname = selectedFile.path || selectedFile.name;
  addMsg('user', `Explain <code style="background:#d5e3fc;padding:1px 5px;border-radius:3px;font-size:10px">${fname}</code>`, true);
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
  btn.innerHTML = `<span class="material-symbols-outlined spin" style="font-size:14px">cycle</span> Generating…`;
  document.getElementById('readme-output').innerHTML = `<div class="flex items-center gap-3 p-6 text-sm text-tertiary"><span class="material-symbols-outlined spin" style="font-size:20px">cycle</span>AI is writing your README…</div>`;
  try {
    const resp = await fetch(`${API}/readme`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_key: repoKey }) });
    const data = await resp.json();
    if (!resp.ok) { toast(data.error, 'error'); document.getElementById('readme-output').innerHTML = `<p class="text-red-600 p-4">${esc(data.error)}</p>`; }
    else { readmeRaw = data.readme; document.getElementById('readme-output').innerHTML = renderMd(readmeRaw); toast('README generated!', 'success'); }
  } catch (e) { toast('Backend error', 'error'); }
  btn.disabled = false; btn.innerHTML = `<span class="material-symbols-outlined fill" style="font-size:14px">auto_awesome</span> Regenerate`;
}

function copyReadme() {
  if (!readmeRaw) return;
  navigator.clipboard.writeText(readmeRaw).then(() => toast('README copied to clipboard', 'success'));
}

// ══════════════════════════════════════════
// D3 DEPENDENCY GRAPH
// ══════════════════════════════════════════
function renderGraph() {
  const svg = d3.select('#graph-svg'); svg.selectAll('*').remove();
  if (!graphData?.nodes?.length) { svg.append('text').attr('x', '50%').attr('y', '50%').attr('text-anchor', 'middle').attr('fill', '#727785').attr('font-size', '13').text('No dependency data available'); return; }
  const area = document.getElementById('graph-area');
  const W = area.clientWidth, H = area.clientHeight;
  svg.attr('viewBox', `0 0 ${W} ${H}`);
  const nodes = graphData.nodes.map(d => ({ ...d }));
  const links = graphData.links.map(d => ({ ...d }));
  svg.append('defs').append('marker').attr('id', 'arr').attr('viewBox', '0 -4 8 8').attr('refX', 16).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto').append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#c2c6d6');
  const g = svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.2, 3]).on('zoom', e => g.attr('transform', e.transform)));
  const sim = d3.forceSimulation(nodes).force('link', d3.forceLink(links).id(d => d.id).distance(100).strength(0.4)).force('charge', d3.forceManyBody().strength(-280)).force('center', d3.forceCenter(W / 2, H / 2)).force('collision', d3.forceCollide(d => d.size + 8));
  const link = g.append('g').selectAll('line').data(links).join('line').attr('class', 'link').attr('stroke-width', 1.5).attr('marker-end', 'url(#arr)');
  const node = g.append('g').selectAll('g').data(nodes).join('g').attr('class', 'node').call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }).on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; }).on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
  node.append('circle').attr('r', d => d.size || 10).attr('fill', d => d.color + '25').attr('stroke', d => d.color).attr('stroke-width', d => d.is_hub ? 2.5 : 1.8).attr('stroke-dasharray', d => d.in_cycle ? '4,2' : 'none');
  node.append('text').attr('y', d => (d.size || 10) + 12).attr('text-anchor', 'middle').attr('font-size', '9').text(d => d.id.length > 18 ? d.id.slice(0, 16) + '…' : d.id);
  const tip = document.getElementById('graph-tooltip');
  node.on('mouseover', (e, d) => {
    tip.className = 'absolute bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-3 shadow-xl text-xs pointer-events-none z-10 min-w-44';
    tip.innerHTML = `<div class="font-mono font-bold text-on-surface mb-2">${d.id}</div><div class="space-y-1 text-on-surface-variant"><div>${fmtNum(d.lines)} lines · ${d.functions||'?'} fn</div><div>Complexity: <span class="font-bold">${d.complexity}</span></div><div>In: ${d.in_degree} · Out: ${d.out_degree}</div>${d.is_hub ? '<div class="text-orange-600 font-semibold">⚠ Hub</div>' : ''}${d.in_cycle ? '<div class="text-red-600 font-semibold">⚠ Circular</div>' : ''}</div>`;
    tip.style.left = (e.layerX + 12) + 'px'; tip.style.top = (e.layerY - 10) + 'px';
  }).on('mouseout', () => tip.className = 'hidden');
  sim.on('tick', () => { link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y); node.attr('transform', d => `translate(${d.x},${d.y})`); });
  document.getElementById('graph-subtitle').textContent = `${nodes.length} nodes · ${links.length} edges · ${graphData.metrics?.cycles_detected || 0} circular deps`;
}

// ══════════════════════════════════════════
// HEALTH CHECK
// ══════════════════════════════════════════
async function runHealthCheck() {
  const c = document.getElementById('health-cards');
  c.innerHTML = '<div class="p-6 rounded-xl bg-surface-container-lowest border border-outline-variant/20 text-center"><span class="material-symbols-outlined spin" style="font-size:24px">cycle</span><p class="mt-2 text-sm text-on-surface-variant">Checking services…</p></div>';
  try {
    const resp = await fetch(`${API}/health?deep=true`);
    const d = await resp.json();
    c.innerHTML = `
      <div class="p-5 rounded-xl bg-surface-container-lowest border border-outline-variant/20 ${d.ollama?.running ? 'health-ok' : 'health-fail'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold text-on-surface">Ollama (Primary AI)</h3><span class="text-xs font-bold ${d.ollama?.running ? 'text-green-600' : 'text-red-600'}">${d.ollama?.running ? '● Running' : '● Offline'}</span></div>
        <p class="text-xs text-on-surface-variant">Model: <code>${d.ollama?.configured_model || '?'}</code> ${d.ollama?.model_available ? '✓ Available' : '✗ Not pulled'}</p>
        ${d.ollama?.installed_models?.length ? `<p class="text-xs text-on-surface-variant mt-1">Installed: ${d.ollama.installed_models.join(', ')}</p>` : ''}
        ${!d.ollama?.running ? '<p class="text-xs text-orange-600 mt-2">Install from <a href="https://ollama.com" class="underline">ollama.com</a> then run <code>ollama pull phi3</code></p>' : ''}
      </div>
      <div class="p-5 rounded-xl bg-surface-container-lowest border border-outline-variant/20 ${d.claude?.configured ? (d.claude?.valid ? 'health-ok' : 'health-warn') : 'health-warn'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold text-on-surface">Claude API (Fallback)</h3><span class="text-xs font-bold ${d.claude?.valid ? 'text-green-600' : d.claude?.configured ? 'text-orange-600' : 'text-on-surface-variant'}">${d.claude?.valid ? '● Valid' : d.claude?.configured ? '● Invalid Key' : '○ Not configured'}</span></div>
        <p class="text-xs text-on-surface-variant">${d.claude?.configured ? 'API key is set in .env' : 'Add ANTHROPIC_API_KEY to .env for fallback'}</p>
        ${d.claude?.error ? `<p class="text-xs text-red-600 mt-1">${esc(d.claude.error).slice(0,120)}</p>` : ''}
      </div>
      <div class="p-5 rounded-xl bg-surface-container-lowest border border-outline-variant/20 ${d.github_token ? 'health-ok' : 'health-warn'}">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold text-on-surface">GitHub Token</h3><span class="text-xs font-bold ${d.github_token ? 'text-green-600' : 'text-orange-600'}">${d.github_token ? '● Configured' : '○ Missing'}</span></div>
        <p class="text-xs text-on-surface-variant">${d.github_token ? '5000 req/hr rate limit' : '60 req/hr limit — add GITHUB_TOKEN to .env'}</p>
      </div>
      <div class="p-5 rounded-xl bg-surface-container-lowest border border-outline-variant/20 health-ok">
        <div class="flex items-center justify-between mb-2"><h3 class="text-sm font-bold text-on-surface">Backend Server</h3><span class="text-xs font-bold text-green-600">● Running</span></div>
        <p class="text-xs text-on-surface-variant">Active engine: <strong>${d.engine}</strong> · ${d.repos_loaded} repos loaded</p>
      </div>`;
  } catch (e) {
    c.innerHTML = `<div class="p-6 rounded-xl bg-surface-container-lowest border border-outline-variant/20 health-fail"><h3 class="text-sm font-bold text-red-600 mb-2">Backend Offline</h3><p class="text-xs text-on-surface-variant">Cannot connect. Run: <code>python run.py</code></p></div>`;
  }
}

// ══════════════════════════════════════════
// HELPERS
// ══════════════════════════════════════════
function fmtNum(n) { if (!n) return '0'; return n > 999 ? (n / 1000).toFixed(1) + 'k' : String(n); }
function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function fmtReply(t) {
  let s = esc(t); const blocks = [];
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => { blocks.push(`<pre style="background:#1a1d20;color:#e5e7eb;padding:.7rem 1rem;border-radius:.5rem;overflow-x:auto;margin:.4rem 0;font-family:monospace;font-size:11px">${code.trim()}</pre>`); return `@@B${blocks.length - 1}@@`; });
  s = s.replace(/`([^`]+)`/g, '<code style="background:#d5e3fc;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:10px;color:#3a485b">$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n\n/g, '<br><br>').replace(/\n/g, '<br>');
  return s.replace(/@@B(\d+)@@/g, (_, i) => blocks[Number(i)] || '');
}

function gradeStyle(grade) {
  const m = { A: { bg: 'bg-green-100', text: 'text-green-700' }, B: { bg: 'bg-green-100', text: 'text-green-700' }, C: { bg: 'bg-blue-100', text: 'text-blue-700' }, D: { bg: 'bg-orange-100', text: 'text-orange-700' }, E: { bg: 'bg-red-100', text: 'text-red-700' }, F: { bg: 'bg-red-200', text: 'text-red-800' } };
  return m[grade] || m['C'];
}

function langIcon(lang) { return { python:'code', javascript:'code', typescript:'code', java:'coffee', html:'html', css:'css' }[lang] || 'insert_drive_file'; }
function langColor(lang) { return { python:'text-blue-600', javascript:'text-yellow-500', typescript:'text-blue-500', java:'text-orange-600', go:'text-cyan-500', rust:'text-orange-700', ruby:'text-red-500' }[lang] || 'text-on-surface-variant'; }

function renderMd(md) {
  let h = esc(md);
  h = h.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, code) => `<pre><code>${code.trimEnd()}</code></pre>`);
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>').replace(/^## (.+)$/gm, '<h2>$1</h2>').replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\*([^*]+)\*/g, '<em>$1</em>');
  h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  h = h.replace(/^---$/gm, '<hr>').replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  h = h.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>[\s\S]*?<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
  h = h.replace(/\n\n(?!<)/g, '</p><p>');
  return `<p>${h}</p>`;
}

// ══════════════════════════════════════════
// RESIZABLE CHAT PANEL
// ══════════════════════════════════════════
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
    // Dragging left = making panel wider (since panel is on the right)
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
