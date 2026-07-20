/**
 * RepoLens Frontend Controller
 * Vanilla JavaScript for handling repository analysis requests
 */

// DOM Elements
const analyzeBtn = document.getElementById('analyze-btn');
const repoPathInput = document.getElementById('repo-path');
const outputLog = document.getElementById('output-log');
const btnText = analyzeBtn.querySelector('.btn-text');
const btnSpinner = analyzeBtn.querySelector('.btn-spinner');

/**
 * Display a message in the output log
 * @param {string} message - Message to display
 * @param {string} type - Message type: 'info', 'success', 'error', or 'loading'
 */
function displayMessage(message, type = 'info') {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = {
        info: '[INFO]',
        success: '[SUCCESS]',
        error: '[ERROR]',
        loading: '[LOADING]'
    }[type] || '[INFO]';

    const formattedMessage = `\n${timestamp} ${prefix} ${message}`;
    outputLog.textContent += formattedMessage;
    
    // Auto-scroll to bottom
    outputLog.scrollTop = outputLog.scrollHeight;
}

/**
 * Clear the output log
 */
function clearOutput() {
    outputLog.textContent = '';
}

/**
 * Set the loading state of the analyze button
 * @param {boolean} loading - Whether the button is in loading state
 */
function setLoadingState(loading) {
    analyzeBtn.disabled = loading;
    btnText.classList.toggle('hidden', loading);
    btnSpinner.classList.toggle('hidden', !loading);
}

/**
 * Validate the repository path input
 * @param {string} path - Path to validate
 * @returns {{ valid: boolean, error?: string }}
 */
function validatePath(path) {
    if (!path || !path.trim()) {
        return { valid: false, error: 'Repository path cannot be empty' };
    }
    
    if (path.trim().length < 2) {
        return { valid: false, error: 'Please enter a valid repository path' };
    }
    
    return { valid: true };
}

/**
 * Send analysis request to the backend
 * @param {string} repoPath - Path to the repository
 * @returns {Promise<Object>} Analysis response
 */
async function sendAnalysisRequest(repoPath) {
    const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            repo_path: repoPath.trim()
        })
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return response.json();
}

/**
 * Format the analysis results for display
 * @param {Object} data - Analysis response data
 * @returns {string} Formatted string
 */
function formatResults(data) {
    const output = [];
    
    output.push('═══════════════════════════════════════════');
    output.push('           ANALYSIS COMPLETE');
    output.push('═══════════════════════════════════════════');
    output.push('');
    
    // Basic info
    output.push(`Status: ${data.status || 'N/A'}`);
    output.push(`Message: ${data.message || 'N/A'}`);
    output.push(`Input Path: ${data.input_path || 'N/A'}`);
    output.push('');
    
    // Data section
    if (data.data) {
        output.push('───────────────────────────────────────────');
        output.push('Commit Activity by Hour (Mock Data)');
        output.push('───────────────────────────────────────────');
        
        if (data.data.hours && data.data.commit_counts) {
            // Create a simple text-based chart
            const maxCount = Math.max(...data.data.commit_counts);
            const barWidth = 20;
            
            for (let i = 0; i < data.data.hours.length; i++) {
                const hour = String(data.data.hours[i]).padStart(2, '0');
                const count = data.data.commit_counts[i];
                const barLength = Math.round((count / maxCount) * barWidth);
                const bar = '█'.repeat(barLength);
                output.push(`${hour}:00 │ ${bar} ${count}`);
            }
        }
        
        output.push('');
        
        // Summary
        if (data.data.summary) {
            output.push('───────────────────────────────────────────');
            output.push('Summary');
            output.push('───────────────────────────────────────────');
            output.push(`Total Commits: ${data.data.summary.total_commits || 0}`);
            output.push(`Peak Hour: ${data.data.summary.peak_hour || 'N/A'}:00`);
            output.push(`Average Commits/Hour: ${data.data.summary.average_commits || 0}`);
        }
    }
    
    // Metadata
    if (data.metadata) {
        output.push('');
        output.push('───────────────────────────────────────────');
        output.push('Metadata');
        output.push('───────────────────────────────────────────');
        output.push(`Analysis Type: ${data.metadata.analysis_type || 'N/A'}`);
        output.push(`Generated At: ${data.metadata.generated_at || 'N/A'}`);
        output.push(`Version: ${data.metadata.version || 'N/A'}`);
    }
    
    output.push('');
    output.push('═══════════════════════════════════════════');
    output.push('  Note: This is Week 1 mock data.');
    output.push('  Real analysis coming in Week 2!');
    output.push('═══════════════════════════════════════════');
    
    return output.join('\n');
}

/**
 * Handle the analyze button click
 */
async function handleAnalyzeClick() {
    const repoPath = repoPathInput.value;
    
    // Validate input
    const validation = validatePath(repoPath);
    if (!validation.valid) {
        clearOutput();
        displayMessage(validation.error, 'error');
        return;
    }
    
    // Set loading state
    setLoadingState(true);
    clearOutput();
    displayMessage(`Starting analysis for: ${repoPath.trim()}`, 'info');
    displayMessage('Sending request to server...', 'loading');
    
    try {
        // Send request
        const result = await sendAnalysisRequest(repoPath);
        
        // Display results
        clearOutput();
        displayMessage(formatResults(result), 'success');
        
    } catch (error) {
        // Handle errors
        clearOutput();
        displayMessage(`Analysis failed: ${error.message}`, 'error');
        displayMessage('Please check the repository path and try again.', 'info');
    } finally {
        // Always re-enable the button
        setLoadingState(false);
    }
}

/**
 * Handle Enter key press in the input field
 * @param {KeyboardEvent} event 
 */
function handleKeyPress(event) {
    if (event.key === 'Enter' && !analyzeBtn.disabled) {
        handleAnalyzeClick();
    }
}

// Event Listeners
analyzeBtn.addEventListener('click', handleAnalyzeClick);
repoPathInput.addEventListener('keypress', handleKeyPress);

// Initialize - show welcome message
document.addEventListener('DOMContentLoaded', () => {
    displayMessage('RepoLens v1.0.0 initialized', 'info');
    displayMessage('Ready to analyze repositories', 'info');
});