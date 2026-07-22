/**
 * RepoLens Frontend Controller
 * Vanilla JavaScript for the Git repository analysis dashboard
 */

// ============================
// DOM References
// ============================
const repoPathInput = document.getElementById('repo-path');
const btnAnalyze = document.getElementById('btn-analyze');
const btnText = btnAnalyze.querySelector('.btn-text');
const btnSpinner = btnAnalyze.querySelector('.btn-spinner');
const loadingSpinner = document.getElementById('loading-spinner');
const loadingText = document.getElementById('loading-text');
const errorBanner = document.getElementById('error-banner');
const errorMessage = document.getElementById('error-message');
const btnDismissError = document.getElementById('btn-dismiss-error');
const dashboard = document.getElementById('dashboard');

// Summary card values
const valueTotalCommits = document.getElementById('value-total-commits');
const valueTotalAuthors = document.getElementById('value-total-authors');
const valueAvgMsgLen = document.getElementById('value-avg-msg-len');

// Canvas for Chart.js
const hourlyChartCanvas = document.getElementById('hourlyChart');
const topAuthorsList = document.getElementById('top-authors-list');

// ============================
// Global State
// ============================
let hourlyChartInstance = null;

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
    btnAnalyze.disabled = loading;
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

    // Show dashboard
    setVisible(dashboard, true);
}

// ============================
// Analysis Request
// ============================

/**
 * Send analysis request to the backend.
 */
async function handleAnalyzeClick() {
    const repoPath = repoPathInput.value;

    // Validate input
    if (!repoPath || !repoPath.trim()) {
        showError('Please enter a valid directory path.');
        return;
    }

    // Reset UI
    hideError();
    setVisible(dashboard, false);

    // Choose loading message based on input type
    const loadingMsg = isGitHubUrl(repoPath)
        ? 'Cloning remote repository...'
        : 'Processing Git history...';
    setLoading(true, loadingMsg);

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ repo_path: repoPath.trim() }),
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

        const data = await response.json();
        populateDashboard(data);

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
// Event Listeners
// ============================

// Analyze button click
btnAnalyze.addEventListener('click', handleAnalyzeClick);

// Enter key in input field
repoPathInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !btnAnalyze.disabled) {
        handleAnalyzeClick();
    }
});

// Dismiss error banner
btnDismissError.addEventListener('click', hideError);

// ============================
// Initialization
// ============================
document.addEventListener('DOMContentLoaded', () => {
    // Focus the input on load
    repoPathInput.focus();
});
