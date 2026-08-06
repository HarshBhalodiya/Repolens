/**
 * RepoLens Frontend Controller
 * Vanilla JavaScript for the Git repository analysis dashboard
 */

// ============================
// DOM References
// ============================
const repoPathInput = document.getElementById('repo-path');
const btnAnalyze = document.getElementById('btn-analyze');
const btnForceRefresh = document.getElementById('btn-force-refresh');
const btnText = btnAnalyze.querySelector('.btn-text');
const btnSpinner = btnAnalyze.querySelector('.btn-spinner');
const btnRefreshText = btnForceRefresh.querySelector('.btn-text');
const btnRefreshSpinner = btnForceRefresh.querySelector('.btn-spinner');
const loadingSpinner = document.getElementById('loading-spinner');
const loadingText = document.getElementById('loading-text');
const errorBanner = document.getElementById('error-banner');
const errorMessage = document.getElementById('error-message');
const btnDismissError = document.getElementById('btn-dismiss-error');
const dashboard = document.getElementById('tab-dashboard');
const cacheBadge = document.getElementById('cache-badge');
const cacheBadgeTime = document.getElementById('cache-badge-time');

// Summary card values
const valueTotalCommits = document.getElementById('value-total-commits');
const valueTotalAuthors = document.getElementById('value-total-authors');
const valueAvgMsgLen = document.getElementById('value-avg-msg-len');

// Canvas for Chart.js
const hourlyChartCanvas = document.getElementById('hourlyChart');
const churnChartCanvas = document.getElementById('churnChart');
const churnChartWrapper = document.getElementById('churn-chart-wrapper');
const churnEmpty = document.getElementById('churn-empty');
const topAuthorsList = document.getElementById('top-authors-list');
const hotspotsTable = document.getElementById('hotspots-table');
const hotspotsEmpty = document.getElementById('hotspots-empty');

// AI features (standup summary)
const btnGenerateSummary = document.getElementById('btn-generate-summary');
const standupContent = document.getElementById('standup-content');
const btnGenerateText = btnGenerateSummary.querySelector('.btn-text');
const btnGenerateSpinner = btnGenerateSummary.querySelector('.btn-spinner');



// RAG codebase chat
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const btnSendChat = document.getElementById('btn-send-chat');
const btnSendText = btnSendChat.querySelector('.btn-text');
const btnSendSpinner = btnSendChat.querySelector('.btn-spinner');

// Dependency graph
const graphStatus = document.getElementById('graph-status');

// ============================
// Global State
// ============================
let hourlyChartInstance = null;
let churnChartInstance = null;
let showAllAuthors = false;
let allAuthorsData = [];

// ============================
// Helpers
// ============================

/**
 * Show or hide a DOM element.
 */
function setVisible(element, visible) {
    if (!element) return;
    if (visible) {
        element.classList.remove('hidden');
    } else {
        element.classList.add('hidden');
    }
}

/**
 * Show an error message in the alert banner.
 */
function showError(message) {
    errorMessage.textContent = message;
    setVisible(errorBanner, true);
}

/**
 * Hide the error banner.
 */
function hideError() {
    setVisible(errorBanner, false);
}

/**
 * Set the loading state of the UI.
 * @param {boolean} loading - Whether to show or hide loading
 * @param {string} [message] - Optional custom loading message
 */
function setLoading(loading, message) {
    setVisible(btnText, !loading);
    setVisible(btnSpinner, loading);
    setVisible(btnRefreshText, !loading);
    setVisible(btnRefreshSpinner, loading);
    btnAnalyze.disabled = loading;
    btnForceRefresh.disabled = loading;
    repoPathInput.disabled = loading;
    setVisible(loadingSpinner, loading);
    if (loading && message && loadingText) {
        loadingText.textContent = message;
    } else if (loading) {
        loadingText.textContent = 'Processing Git history...';
    }
}

/**
 * Check if a string looks like a GitHub URL.
 */
function isGitHubUrl(value) {
    if (!value) return false;
    const trimmed = value.trim();
    // HTTPS only: the backend's GITHUB_HTTPS_PATTERN (app/utils.py) does
    // not accept plain http:// URLs, so they must not be treated as GitHub
    // here either (handleAnalyzeClick rejects them with a clear message).
    return /^https:\/\/github\.com\//.test(trimmed)
        || /^git@github\.com:/.test(trimmed);
}

/**
 * Format a number with comma separators.
 */
function formatNumber(num) {
    if (num == null || isNaN(num)) return '\u2014';
    return Number(num).toLocaleString();
}

// ============================
// Chart Rendering
// ============================

/**
 * Render (or update) the hourly commit activity bar chart.
 * @param {Array<{hour: number, commits: number}>} hourlyData
 */
function renderHourlyChart(hourlyData) {
    // Destroy existing chart instance if it exists
    if (hourlyChartInstance) {
        hourlyChartInstance.destroy();
        hourlyChartInstance = null;
    }

    const ctx = hourlyChartCanvas.getContext('2d');

    const labels = hourlyData.map(d => `${String(d.hour).padStart(2, '0')}:00`);
    const values = hourlyData.map(d => d.commits);

    hourlyChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Commits',
                data: values,
                backgroundColor: '#2EA043',
                hoverBackgroundColor: '#3FB950',
                borderRadius: 3,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    backgroundColor: '#161B22',
                    titleColor: '#F0F6FC',
                    bodyColor: '#8B949E',
                    borderColor: '#30363D',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 6,
                    displayColors: false,
                    callbacks: {
                        title: function(items) {
                            return items[0].label;
                        },
                        label: function(item) {
                            return `${item.raw} commit${item.raw !== 1 ? 's' : ''}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: '#30363D',
                        drawBorder: false,
                    },
                    ticks: {
                        color: '#8B949E',
                        font: {
                            size: 11,
                            family: "'SFMono-Regular', Consolas, monospace",
                        },
                        maxRotation: 45,
                        autoSkipPadding: 8,
                    },
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: '#30363D',
                        drawBorder: false,
                    },
                    ticks: {
                        color: '#8B949E',
                        font: {
                            size: 11,
                        },
                        precision: 0,
                    },
                }
            },
            animation: {
                duration: 600,
                easing: 'easeOutQuart',
            },
        }
    });
}

// ============================
// Code Churn Chart Rendering
// ============================

/**
 * Render (or update) the code churn line/bar chart.
 * Uses a bar chart with additions in green and deletions in red.
 * @param {Array<{date: string, insertions: number, deletions: number}>} churnData
 */
function renderChurnChart(churnData) {
    // We have data, so make sure the chart is visible and the empty state
    // is hidden (they can be left over from a previously analyzed repo).
    // setVisible() null-checks internally, so no guards are needed.
    setVisible(churnChartWrapper, true);
    setVisible(churnEmpty, false);

    // Destroy existing chart instance if it exists
    if (churnChartInstance) {
        churnChartInstance.destroy();
        churnChartInstance = null;
    }

    const ctx = churnChartCanvas.getContext('2d');

    const labels = churnData.map(d => {
        const dt = new Date(d.date + 'T00:00:00');
        return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    });
    const insertions = churnData.map(d => d.insertions);
    const deletions = churnData.map(d => d.deletions);

    churnChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Additions',
                    data: insertions,
                    backgroundColor: 'rgba(46, 160, 67, 0.8)',
                    hoverBackgroundColor: 'rgba(46, 160, 67, 1)',
                    borderRadius: 3,
                    borderSkipped: false,
                },
                {
                    label: 'Deletions',
                    data: deletions,
                    backgroundColor: 'rgba(248, 81, 73, 0.8)',
                    hoverBackgroundColor: 'rgba(248, 81, 73, 1)',
                    borderRadius: 3,
                    borderSkipped: false,
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    align: 'end',
                    labels: {
                        color: '#8B949E',
                        font: {
                            size: 12,
                            family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
                        },
                        padding: 16,
                        usePointStyle: true,
                        pointStyle: 'circle',
                    },
                },
                tooltip: {
                    backgroundColor: '#161B22',
                    titleColor: '#F0F6FC',
                    bodyColor: '#8B949E',
                    borderColor: '#30363D',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 6,
                    displayColors: true,
                    callbacks: {
                        title: function(items) {
                            return items[0].label;
                        },
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: '#30363D',
                        drawBorder: false,
                    },
                    ticks: {
                        color: '#8B949E',
                        font: {
                            size: 11,
                            family: "'SFMono-Regular', Consolas, monospace",
                        },
                        maxRotation: 45,
                        autoSkipPadding: 8,
                    },
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: '#30363D',
                        drawBorder: false,
                    },
                    ticks: {
                        color: '#8B949E',
                        font: {
                            size: 11,
                        },
                        precision: 0,
                    },
                }
            },
            animation: {
                duration: 600,
                easing: 'easeOutQuart',
            },
        }
    });
}

/**
 * Clear the code churn chart and show the empty state.
 * Called when a repo has no churn data, so a stale chart from a
 * previously analyzed repo cannot linger under the new results.
 */
function clearChurnChart() {
    if (churnChartInstance) {
        churnChartInstance.destroy();
        churnChartInstance = null;
    }
    setVisible(churnChartWrapper, false);
    setVisible(churnEmpty, true);
}

// ============================
// File Hotspots Table Rendering
// ============================

/**
 * Render the top file hotspots table.
 * @param {Array<{file_path: string, changes: number}>} hotspotsData
 */
function renderHotspotsTable(hotspotsData) {
    if (!hotspotsTable) return;

    const tbody = hotspotsTable.querySelector('tbody');
    if (!tbody) return;

    if (!hotspotsData || hotspotsData.length === 0) {
        setVisible(hotspotsTable, false);
        setVisible(hotspotsEmpty, true);
        return;
    }

    setVisible(hotspotsTable, true);
    setVisible(hotspotsEmpty, false);

    // Clear existing rows
    tbody.innerHTML = '';

    const rowHtml = hotspotsData.map(item => {
        const safePath = escapeHtml(item.file_path);
        const safeChanges = formatNumber(item.changes);
        return `
            <tr>
                <td class="file-path-cell">${safePath}</td>
                <td class="changes-cell"><span class="changes-badge">${safeChanges} changes</span></td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = rowHtml;
}

// ============================
// Authors List Rendering
// ============================

/**
 * Render the top authors list.
 * @param {Array<{author: string, commits: number}>} authors
 */
function renderTopAuthors(authors) {
    if (!topAuthorsList) return;

    if (!authors || authors.length === 0) {
        topAuthorsList.innerHTML = '<p style="font-size:14px;color:var(--text-secondary);">No author data available.</p>';
        const btn = document.getElementById('btn-toggle-authors');
        if (btn) setVisible(btn, false);
        return;
    }

    allAuthorsData = authors;

    const btn = document.getElementById('btn-toggle-authors');
    if (btn) {
        if (authors.length > 4) {
            setVisible(btn, true);
            btn.textContent = showAllAuthors ? 'Show Less' : 'View More';
        } else {
            setVisible(btn, false);
        }
    }

    const displayAuthors = showAllAuthors ? authors : authors.slice(0, 4);
    const maxCommits = authors[0]?.commits || 1;

    const html = displayAuthors.map((author, index) => {
        const rank = index + 1;
        const barWidth = (author.commits / maxCommits) * 100;
        const initials = author.author
            .split(' ')
            .map(w => w[0])
            .filter(Boolean)
            .slice(0, 2)
            .join('')
            .toUpperCase() || '?';

        let rankClass = '';
        if (rank === 1) rankClass = 'top-1';
        else if (rank === 2) rankClass = 'top-2';
        else if (rank === 3) rankClass = 'top-3';

        return `
            <div class="author-row">
                <span class="author-rank ${rankClass}">${rank}</span>
                <div class="author-avatar">${escapeHtml(initials)}</div>
                <div class="author-info">
                    <div class="author-name">${escapeHtml(author.author)}</div>
                    <div class="author-commits">${formatNumber(author.commits)} commit${author.commits !== 1 ? 's' : ''}</div>
                </div>
                <div class="author-bar">
                    <div class="author-bar-fill" style="width: ${barWidth}%"></div>
                </div>
            </div>
        `;
    }).join('');

    topAuthorsList.innerHTML = html;
}

// ============================
// Languages Rendering
// ============================

const LANGUAGE_COLORS = {
    'Python': '#3572A5',
    'JavaScript': '#f1e05a',
    'TypeScript': '#3178c6',
    'HTML': '#e34c26',
    'CSS': '#563d7c',
    'Go': '#00ADD8',
    'Rust': '#dea584',
    'Java': '#b07219',
    'C++': '#f34b7d',
    'C': '#555555',
    'C#': '#178600',
    'SQL': '#e98615',
    'Shell': '#89e051',
    'YAML': '#cb171e',
    'Markdown': '#083fa1',
    'JSON': '#292929',
};

/**
 * Render the programming languages card.
 * @param {Array<{language: string, percentage: number, size: number}>} languages
 */
function renderLanguages(languages) {
    const listEl = document.getElementById('languages-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (!languages || languages.length === 0) {
        listEl.innerHTML = '<p style="font-size:14px;color:var(--text-secondary);padding:var(--spacing-md) 0;">No language data available.</p>';
        return;
    }

    // Create progress bar container
    const bar = document.createElement('div');
    bar.className = 'language-bar';

    // Create legend container
    const legend = document.createElement('div');
    legend.className = 'languages-legend';

    languages.forEach(item => {
        const color = LANGUAGE_COLORS[item.language] || '#8b949e';

        // Segment element
        const segment = document.createElement('div');
        segment.className = 'language-bar-segment';
        segment.style.width = `${item.percentage}%`;
        segment.style.backgroundColor = color;
        segment.title = `${item.language}: ${item.percentage}%`;
        bar.appendChild(segment);

        // Legend element
        const legendItem = document.createElement('div');
        legendItem.className = 'languages-legend-item';
        legendItem.innerHTML = `
            <span class="language-color-dot" style="background-color: ${color};"></span>
            <span class="language-name">${escapeHtml(item.language)}</span>
            <span class="language-percentage">${item.percentage}%</span>
        `;
        legend.appendChild(legendItem);
    });

    listEl.appendChild(bar);
    listEl.appendChild(legend);
}

/**
 * Simple HTML escaping to prevent XSS.
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================
// Dashboard Population
// ============================

/**
 * Populate the dashboard with analysis results.
 * @param {Object} data - Response from /api/analyze
 */
function populateDashboard(data) {
    // Update summary cards
    if (data.summary) {
        valueTotalCommits.textContent = formatNumber(data.summary.total_commits);
        valueTotalAuthors.textContent = formatNumber(data.summary.total_authors);
    }
    valueAvgMsgLen.textContent = data.avg_message_length != null
        ? `${data.avg_message_length} chars`
        : '\u2014';

    // Render chart
    if (data.hourly_distribution && Array.isArray(data.hourly_distribution)) {
        renderHourlyChart(data.hourly_distribution);
    }

    // Render top authors
    if (data.top_authors && Array.isArray(data.top_authors)) {
        renderTopAuthors(data.top_authors);
    }

    // Render languages
    if (data.languages && Array.isArray(data.languages)) {
        renderLanguages(data.languages);
    } else {
        renderLanguages([]);
    }

    // Render code churn chart
    if (data.code_churn && Array.isArray(data.code_churn) && data.code_churn.length > 0) {
        renderChurnChart(data.code_churn);
    } else {
        // Root cause: without this branch a newly analyzed repo with zero
        // churn data left the previous repo's chart on screen, mislabeled
        // under the new results. Clear/hide it, mirroring how the hotspots
        // table handles its empty case.
        clearChurnChart();
    }

    // Render file hotspots table
    if (data.hotspots && Array.isArray(data.hotspots)) {
        renderHotspotsTable(data.hotspots);
    }

    // Show dashboard
    setVisible(dashboard, true);
}

// ============================
// Analysis Request
// ============================

/**
 * Show the cache-hit badge with the retrieval time.
 * @param {number} elapsedMs - Round-trip time in milliseconds
 */
function showCacheBadge(elapsedMs) {
    if (cacheBadgeTime) {
        cacheBadgeTime.textContent = String(elapsedMs);
    }
    setVisible(cacheBadge, true);
}

/**
 * Hide the cache-hit badge.
 */
function hideCacheBadge() {
    setVisible(cacheBadge, false);
}

/**
 * Send analysis request to the backend.
 * @param {boolean} [forceRefresh] - When true, bypass the cache
 */
async function handleAnalyzeClick(forceRefresh) {
    const repoPath = repoPathInput.value;

    // Validate input
    if (!repoPath || !repoPath.trim()) {
        showError('Please enter a valid directory path.');
        return;
    }

    // Root cause of the misleading error: isGitHubUrl() used to accept
    // http:// links, so they showed a "Cloning..." loading state and were
    // only rejected server-side with a confusing "Path does not exist"
    // message (the backend accepts https:// only). Reject upfront instead.
    if (/^http:\/\/(?:www\.)?github\.com\//.test(repoPath.trim())) {
        showError('Unsupported URL scheme: only https:// GitHub URLs are supported (use https://github.com/owner/repo).');
        return;
    }

    // Reset UI
    hideError();
    hideCacheBadge();
    setVisible(dashboard, false);
    if (chatHistory) chatHistory.innerHTML = '';
    if (chatInput) chatInput.value = '';
    showAllAuthors = false;
    allAuthorsData = [];

    // Choose loading message based on input type
    let loadingMsg = isGitHubUrl(repoPath)
        ? 'Cloning remote repository...'
        : 'Processing Git history...';
    if (forceRefresh) {
        loadingMsg = 'Re-analyzing repository (bypassing cache)...';
    }
    setLoading(true, loadingMsg);

    const startTime = performance.now();

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                repo_path: repoPath.trim(),
                force_refresh: Boolean(forceRefresh),
            }),
        });

        if (!response.ok) {
            // Parse error detail from JSON response
            let detail = `Request failed with status ${response.status}`;
            try {
                const errorData = await response.json();
                if (errorData.detail) {
                    detail = errorData.detail;
                }
            } catch (_) {
                // Use default detail if parsing fails
            }
            throw new Error(detail);
        }

        const payload = await response.json();
        const elapsedMs = Math.round(performance.now() - startTime);

        // Serve cached payloads instantly and flag them with a badge
        if (payload.cached) {
            showCacheBadge(elapsedMs);
        } else {
            hideCacheBadge();
        }

        // Note: extraction failures (git log timeout, etc.) are now surfaced
        // as a non-2xx response with `detail` (handled by the error path
        // below) rather than a 200 payload carrying `_error`, so no `_error`
        // check is needed here anymore.
        populateDashboard(payload.data || {});
        loadDependencyGraph();

    } catch (error) {
        // Show error in the banner
        showError(error.message || 'An unexpected error occurred while analyzing the repository.');
        setVisible(dashboard, false);
    } finally {
        // Always re-enable the UI
        setLoading(false);
    }
}

// ============================
// AI Features: Standup Summary & Codebase Indexing
// ============================

// Skeleton loader shown while waiting on Ollama.
const SKELETON_HTML = `
    <div class="skeleton-loader" aria-hidden="true">
        <div class="skeleton-line"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line skeleton-line-short"></div>
    </div>
    <p class="standup-caption">Connecting to Ollama...</p>
`;

/**
 * Toggle the loading state of the "Generate Report" button and content.
 */
function setStandupLoading(loading) {
    setVisible(btnGenerateText, !loading);
    setVisible(btnGenerateSpinner, loading);
    btnGenerateSummary.disabled = loading;
    if (loading) {
        standupContent.innerHTML = SKELETON_HTML;
    }
}

/**
 * Render the standup summary response into #standup-content.
 * @param {Object} payload - Response from /api/summarize
 */
function renderStandupSummary(payload) {
    if (payload.status === 'error') {
        const message = payload.summary || 'Ollama service unavailable. Please make sure Ollama is running locally.';
        standupContent.innerHTML = `
            <div class="ai-warning">
                <span class="ai-warning-icon" aria-hidden="true">⚠️</span>
                <div>
                    <strong>Request failed</strong>
                    <p>${escapeHtml(message)}</p>
                </div>
            </div>
        `;
        return;
    }

    const text = payload.summary || '';

    // Informational payloads (e.g. no commits to summarize) have no status.
    if (payload.status !== 'success') {
        standupContent.innerHTML = `<p class="standup-info">${escapeHtml(text)}</p>`;
        return;
    }

    if (!text) {
        standupContent.innerHTML = '<p class="standup-info">No summary returned by the model.</p>';
        return;
    }

    // Strip bullet markers and render each line as a styled list item.
    const lines = text.split('\n')
        .map(line => line.trim())
        .filter(Boolean);
    const bullets = lines
        .map(line => line.replace(/^[-*•]\s+/, '').replace(/^\d+[.)]\s+/, ''))
        .filter(line => line.length > 0);
    const items = bullets.length > 0 ? bullets : [text];

    const listHtml = items.map(item =>
        `<li class="standup-bullet">${escapeHtml(item)}</li>`
    ).join('');

    standupContent.innerHTML = `
        <ul class="standup-list">${listHtml}</ul>
        <p class="standup-caption standup-success">✓ Report generated from the last 30 commits.</p>
    `;
}



/**
 * Send a standup summary request to the backend.
 */
async function handleGenerateSummaryClick() {
    const repoPath = repoPathInput.value;
    if (!repoPath || !repoPath.trim()) {
        showError('Please enter a repository path first.');
        return;
    }

    hideError();
    setStandupLoading(true);

    try {
        const response = await fetch('/api/summarize', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ repo_path: repoPath.trim() }),
        });

        if (!response.ok) {
            let detail = `Request failed with status ${response.status}`;
            try {
                const errorData = await response.json();
                if (errorData.detail) detail = errorData.detail;
            } catch (_) { /* use default detail */ }
            throw new Error(detail);
        }

        const payload = await response.json();
        renderStandupSummary(payload);
    } catch (error) {
        standupContent.innerHTML = `
            <div class="ai-warning">
                <span class="ai-warning-icon" aria-hidden="true">⚠️</span>
                <div>
                    <strong>Request failed</strong>
                    <p>${escapeHtml(error.message || 'An unexpected error occurred.')}</p>
                </div>
            </div>
        `;
    } finally {
        setStandupLoading(false);
    }
}



/** Last rendered graph payload. */
let graphData = null;

// ============================
// RAG Codebase Chat
// ============================

/**
 * Minimal markdown-ish formatter for AI responses.
 *
 * Splits on ``` fences first: fenced blocks become <pre><code>, everything
 * else gets inline `code` highlighting and newline-><br> conversion. All
 * content is HTML-escaped before formatting, so markup can never execute.
 */
function formatChatMessage(text) {
    const escaped = escapeHtml(text);
    return escaped.split(/```/).map((part, index) => {
        if (index % 2 === 1) {
            // Inside a fenced code block: no <br> mangling, preserve as-is.
            return `<pre class="chat-code">${part.replace(/^\n/, '')}</pre>`;
        }
        return part
            .replace(/`([^`\n]+)`/g, (_, code) => `<code class="chat-inline-code">${code}</code>`)
            .replace(/\n/g, '<br>');
    }).join('');
}

/**
 * Append a message bubble to the chat history and scroll it into view.
 * @param {string} role - 'user' or 'ai'
 * @param {string} text - Message body (escaped internally)
 */
function appendChatMessage(role, text) {
    const div = document.createElement('div');
    div.className = `chat-msg ${role}`;
    if (role === 'user') {
        div.innerHTML = `<div class="chat-bubble user-bubble">${escapeHtml(text)}</div>`;
    } else {
        div.innerHTML = `<div class="chat-bubble ai-bubble">${formatChatMessage(text)}</div>`;
    }
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

/** Show an animated typing indicator while waiting on Ollama. */
function showTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'chat-msg ai';
    div.id = 'typing-indicator';
    div.innerHTML = `
        <div class="chat-bubble ai-bubble typing">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>
    `;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

/** Remove the typing indicator once the response arrives. */
function removeTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

/**
 * Send the current chat input to /api/chat and render the response.
 */
async function handleSendChatClick() {
    const query = chatInput.value.trim();
    if (!query) return;

    appendChatMessage('user', query);
    chatInput.value = '';
    showTypingIndicator();

    setVisible(btnSendText, false);
    setVisible(btnSendSpinner, true);
    btnSendChat.disabled = true;

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                repo_path: repoPathInput.value.trim(),
                query: query,
            }),
        });

        if (!response.ok) {
            let detail = `Request failed with status ${response.status}`;
            try {
                const errorData = await response.json();
                if (errorData.detail) detail = errorData.detail;
            } catch (_) { /* use default detail */ }
            throw new Error(detail);
        }

        const payload = await response.json();
        removeTypingIndicator();
        appendChatMessage('ai', payload.answer || '(no answer returned)');

        // Surface which files the answer was grounded on as chips.
        if (payload.sources && payload.sources.length) {
            const chips = document.createElement('div');
            chips.className = 'source-chips';
            chips.innerHTML = payload.sources
                .map(source => `<span class="source-chip">${escapeHtml(source)}</span>`)
                .join('');
            chatHistory.appendChild(chips);
        }
    } catch (error) {
        removeTypingIndicator();
        appendChatMessage('ai', error.message || 'An unexpected error occurred.');
    } finally {
        setVisible(btnSendText, true);
        setVisible(btnSendSpinner, false);
        btnSendChat.disabled = false;
        chatInput.focus();
    }
}

// ============================
// Dependency Graph (D3.js)
// ============================

/**
 * Set the status line above the graph SVG.
 * @param {string} message - Status text
 * @param {string} state - 'active' | 'success' | 'error' | 'info'
 */
function setGraphStatus(message, state) {
    if (!graphStatus) return;
    graphStatus.textContent = message;
    graphStatus.className = `graph-status ${state}`;
    setVisible(graphStatus, true);
}

/** Remove all children from the graph SVG. */
function clearGraph() {
    const svgEl = document.getElementById('dependency-svg');
    if (!svgEl) return;
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
}

/**
 * Render a force-directed dependency graph with D3.js v7.
 * @param {{nodes: Array<{id: string, label: string}>, edges: Array<{source: string, target: string}>}} data
 */
function renderDependencyGraph(data) {
    if (typeof d3 === 'undefined') {
        setGraphStatus('D3.js failed to load (CDN unreachable).', 'error');
        return;
    }

    const svgEl = document.getElementById('dependency-svg');
    if (!svgEl) return;

    const svg = d3.select(svgEl);
    svg.selectAll('*').remove();

    const nodes = (data.nodes || []).map(n => ({ id: n.id, label: n.label }));
    const nodeIds = new Set(nodes.map(n => n.id));
    const edges = (data.edges || [])
        .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map(e => ({ source: e.source, target: e.target }));

    if (!nodes.length) {
        setGraphStatus('No files to display.', 'info');
        return;
    }

    const width = svgEl.clientWidth || 800;
    const height = svgEl.clientHeight || 400;

    // Degree (number of connections) drives node size for readability.
    const degree = new Map();
    edges.forEach(e => {
        degree.set(e.source, (degree.get(e.source) || 0) + 1);
        degree.set(e.target, (degree.get(e.target) || 0) + 1);
    });
    const nodeRadius = d => Math.min(4 + (degree.get(d.id) || 0) * 1.2, 14);

    // Root <g> that the zoom transform applies to.
    const g = svg.append('g');

    const zoom = d3.zoom()
        .scaleExtent([0.2, 4])
        .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    const link = g.append('g')
        .attr('class', 'graph-links')
        .selectAll('line')
        .data(edges)
        .join('line')
        .attr('stroke', '#30363D')
        .attr('stroke-width', 1);

    const node = g.append('g')
        .attr('class', 'graph-nodes')
        .selectAll('g')
        .data(nodes)
        .join('g');

    node.append('circle')
        .attr('r', nodeRadius)
        .attr('fill', '#58A6FF')
        .attr('fill-opacity', 0.85)
        .attr('stroke', '#79C0FF')
        .attr('stroke-width', 1);

    node.append('title').text(d => d.id);  // native hover tooltip

    node.append('text')
        .attr('class', 'graph-label')
        .attr('dy', -12)
        .attr('text-anchor', 'middle')
        .text(d => d.label);

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id(d => d.id).distance(45).strength(0.8))
        .force('charge', d3.forceManyBody().strength(-100))
        .force('x', d3.forceX(width / 2).strength(0.08))
        .force('y', d3.forceY(height / 2).strength(0.08))
        .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 8))
        .on('tick', () => {
            link
                .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

    // Drag behavior: pin the dragged node, stop the zoom gesture hijacking it.
    // Root cause note: d3.drag reports pointer coordinates in the SVG's
    // coordinate space, but simulation positions (d.x/d.y) live inside the
    // zoom-transformed <g>. Converting with the inverse zoom transform keeps
    // the node glued to the cursor at any zoom level (without it, dragging
    // while zoomed makes the node jump to an unrelated position).
    node.call(d3.drag()
        .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            const t = d3.zoomTransform(svgEl);
            d.fx = (event.x - t.x) / t.k;
            d.fy = (event.y - t.y) / t.k;
            event.sourceEvent.stopPropagation();
        })
        .on('drag', (event, d) => {
            const t = d3.zoomTransform(svgEl);
            d.fx = (event.x - t.x) / t.k;
            d.fy = (event.y - t.y) / t.k;
        })
        .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }));

    // Fade unrelated nodes/links on hover so dense graphs stay readable.
    function fadeNeighbors(hovered) {
        const connected = new Set(edges
            .filter(e => e.source.id === hovered.id || e.target.id === hovered.id)
            .flatMap(e => [e.source.id, e.target.id]));
        connected.add(hovered.id);
        node.select('circle')
            .attr('fill-opacity', n => connected.has(n.id) ? 0.95 : 0.12);
        node.select('text')
            .attr('opacity', n => connected.has(n.id) ? 1 : 0.2);
        link.attr('stroke-opacity', e =>
            e.source.id === hovered.id || e.target.id === hovered.id ? 1 : 0.06);
    }

    node.on('mouseover', (event, d) => fadeNeighbors(d))
        .on('mouseout', () => {
            node.select('circle').attr('fill-opacity', 0.85);
            node.select('text').attr('opacity', 1);
            link.attr('stroke-opacity', 1);
        });
}

/**
 * Request the dependency graph from the backend and render it automatically.
 */
async function loadDependencyGraph() {
    const repoPath = repoPathInput.value;
    if (!repoPath || !repoPath.trim()) {
        return;
    }

    setGraphStatus('Parsing dependencies with Tree-sitter...', 'active');

    try {
        const response = await fetch('/api/dependencies', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ repo_path: repoPath.trim() }),
        });

        if (!response.ok) {
            let detail = `Request failed with status ${response.status}`;
            try {
                const errorData = await response.json();
                if (errorData.detail) detail = errorData.detail;
            } catch (_) { /* use default detail */ }
            throw new Error(detail);
        }

        const payload = await response.json();

        if (payload.status === 'error') {
            clearGraph();
            graphData = null;
            setGraphStatus(payload.message || 'Failed to build the dependency graph.', 'error');
            return;
        }

        if (!payload.nodes || payload.nodes.length === 0) {
            clearGraph();
            graphData = null;
            setGraphStatus(payload.message || 'No files to display.', 'info');
            return;
        }

        graphData = payload;
        renderDependencyGraph(payload);
        setGraphStatus(
            `Graph: ${payload.nodes.length} files, ${payload.edges.length} dependencies`,
            'success'
        );
    } catch (error) {
        clearGraph();
        graphData = null;
        setGraphStatus(error.message || 'Failed to build the dependency graph.', 'error');
    }
}

// ============================
// Event Listeners
// ============================

// Analyze button click
btnAnalyze.addEventListener('click', () => handleAnalyzeClick(false));

// Re-analyze (force refresh) button click - bypasses the cache
btnForceRefresh.addEventListener('click', () => handleAnalyzeClick(true));

// Enter key in input field
repoPathInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !btnAnalyze.disabled) {
        handleAnalyzeClick(false);
    }
});

// Dismiss error banner
btnDismissError.addEventListener('click', hideError);

// AI features
btnGenerateSummary.addEventListener('click', handleGenerateSummaryClick);
// RAG codebase chat
btnSendChat.addEventListener('click', handleSendChatClick);
chatInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !btnSendChat.disabled) {
        handleSendChatClick();
    }
});

// Toggle contributors button click
const btnToggleAuthors = document.getElementById('btn-toggle-authors');
if (btnToggleAuthors) {
    btnToggleAuthors.addEventListener('click', () => {
        showAllAuthors = !showAllAuthors;
        renderTopAuthors(allAuthorsData);
    });
}
// ============================
// Initialization
// ============================
document.addEventListener('DOMContentLoaded', () => {
    // Focus the input on load
    repoPathInput.focus();
});
