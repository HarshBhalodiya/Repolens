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
const dashboard = document.getElementById('dashboard');
const cacheBadge = document.getElementById('cache-badge');
const cacheBadgeTime = document.getElementById('cache-badge-time');

// Summary card values
const valueTotalCommits = document.getElementById('value-total-commits');
const valueTotalAuthors = document.getElementById('value-total-authors');
const valueAvgMsgLen = document.getElementById('value-avg-msg-len');

// Canvas for Chart.js
const hourlyChartCanvas = document.getElementById('hourlyChart');
const churnChartCanvas = document.getElementById('churnChart');
const topAuthorsList = document.getElementById('top-authors-list');
const hotspotsTable = document.getElementById('hotspots-table');
const hotspotsEmpty = document.getElementById('hotspots-empty');

// AI features (standup summary / codebase indexing)
const btnGenerateSummary = document.getElementById('btn-generate-summary');
const btnIndexRepo = document.getElementById('btn-index-repo');
const standupContent = document.getElementById('standup-content');
const indexStatus = document.getElementById('index-status');
const btnGenerateText = btnGenerateSummary.querySelector('.btn-text');
const btnGenerateSpinner = btnGenerateSummary.querySelector('.btn-spinner');
const btnIndexText = btnIndexRepo.querySelector('.btn-text');
const btnIndexSpinner = btnIndexRepo.querySelector('.btn-spinner');

// ============================
// Global State
// ============================
let hourlyChartInstance = null;
let churnChartInstance = null;

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
    return /^https?:\/\/github\.com\//.test(trimmed)
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
        return;
    }

    const maxCommits = authors[0]?.commits || 1;

    const html = authors.map((author, index) => {
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

    // Render code churn chart
    if (data.code_churn && Array.isArray(data.code_churn) && data.code_churn.length > 0) {
        renderChurnChart(data.code_churn);
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

    // Reset UI
    hideError();
    hideCacheBadge();
    setVisible(dashboard, false);

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

        // Surface extraction failures (e.g. git log timeout) instead of
        // rendering a blank dashboard with no explanation
        if (payload.data && payload.data._error) {
            showError(`Analysis did not complete: ${payload.data._error}`);
            setVisible(dashboard, false);
            return;
        }

        populateDashboard(payload.data || {});

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
 * Set the codebase index status badge text and state style.
 * @param {string} message - Status text
 * @param {'idle'|'active'|'success'|'error'} state - Visual state
 */
function setIndexStatus(message, state) {
    indexStatus.textContent = message;
    indexStatus.className = 'index-status';
    indexStatus.classList.add(`index-status-${state}`);
}

/**
 * Toggle the loading state of the "Index Codebase" button.
 */
function setIndexingLoading(loading) {
    setVisible(btnIndexText, !loading);
    setVisible(btnIndexSpinner, loading);
    btnIndexRepo.disabled = loading;
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

/**
 * Send a codebase indexing request to the backend.
 */
async function handleIndexRepoClick() {
    const repoPath = repoPathInput.value;
    if (!repoPath || !repoPath.trim()) {
        showError('Please enter a repository path first.');
        return;
    }

    hideError();
    setIndexingLoading(true);
    setIndexStatus('Indexing files...', 'active');

    try {
        const response = await fetch('/api/index_codebase', {
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
            setIndexStatus(payload.message || 'Indexing failed.', 'error');
        } else {
            setIndexStatus(
                `Indexed ${payload.indexed_files} files (${payload.total_chunks} chunks)`,
                'success'
            );
        }
    } catch (error) {
        setIndexStatus(error.message || 'Indexing failed.', 'error');
    } finally {
        setIndexingLoading(false);
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
btnIndexRepo.addEventListener('click', handleIndexRepoClick);

// ============================
// Initialization
// ============================
document.addEventListener('DOMContentLoaded', () => {
    // Focus the input on load
    repoPathInput.focus();
});
