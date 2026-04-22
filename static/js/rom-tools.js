/**
 * RetroDB ROM Tools Module
 * Shared utilities for ROM tool pages (archive scanner, CHD converter, etc.)
 * Version: 1.25.0
 *
 * Features:
 * - TaskPoller: Async job status polling
 * - ProgressTracker: Progress bar management
 * - SessionState: Session storage for preserving state
 */

// =============================================================================
// TASK POLLER - Polls async task status
// =============================================================================

const TaskPoller = {
    taskId: null,
    pollInterval: null,
    pollRate: 1000,  // Default 1 second
    isPaused: false,

    callbacks: {
        onProgress: null,
        onComplete: null,
        onError: null,
        onCancel: null,
        onNotFound: null
    },

    /**
     * Start polling a task
     * @param {string} taskId - Task ID to poll
     * @param {Object} callbacks - Callback functions
     * @param {number} pollRate - Poll interval in ms
     */
    start(taskId, callbacks = {}, pollRate = 1000) {
        this.taskId = taskId;
        this.pollRate = pollRate;
        this.isPaused = false;
        this.callbacks = {
            onProgress: callbacks.onProgress || null,
            onComplete: callbacks.onComplete || null,
            onError: callbacks.onError || null,
            onCancel: callbacks.onCancel || null,
            onNotFound: callbacks.onNotFound || null
        };

        // Clear any existing interval
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }

        // Start polling
        this.pollInterval = setInterval(() => this.poll(), this.pollRate);
        // Initial poll
        this.poll();
    },

    /**
     * Stop polling
     */
    stop() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        this.taskId = null;
    },

    /**
     * Poll the current task
     */
    async poll() {
        if (!this.taskId) return;

        try {
            const task = await API.get(`/api/rom-tools/task/${this.taskId}`);

            // Task not found (server restarted)
            if (task.error === 'Task not found') {
                this.stop();
                if (this.callbacks.onNotFound) {
                    this.callbacks.onNotFound();
                }
                return;
            }

            // Progress update
            if (this.callbacks.onProgress) {
                this.callbacks.onProgress(task);
            }

            // Check completion
            if (task.status === 'completed') {
                this.stop();
                if (this.callbacks.onComplete) {
                    this.callbacks.onComplete(task);
                }
            } else if (task.status === 'error') {
                this.stop();
                if (this.callbacks.onError) {
                    this.callbacks.onError(task);
                }
            } else if (task.status === 'cancelled') {
                this.stop();
                if (this.callbacks.onCancel) {
                    this.callbacks.onCancel(task);
                }
            }
        } catch (error) {
            console.error('Error polling task status:', error);
            this.stop();
            if (this.callbacks.onError) {
                this.callbacks.onError({ error: error.message });
            }
        }
    },

    /**
     * Pause the current task
     */
    async pause() {
        if (!this.taskId) return;

        try {
            await API.post(`/api/rom-tools/task/${this.taskId}/pause`);
            this.isPaused = true;
        } catch (error) {
            console.error('Error pausing task:', error);
        }
    },

    /**
     * Resume the current task
     */
    async resume() {
        if (!this.taskId) return;

        try {
            await API.post(`/api/rom-tools/task/${this.taskId}/resume`);
            this.isPaused = false;
        } catch (error) {
            console.error('Error resuming task:', error);
        }
    },

    /**
     * Toggle pause state
     * @returns {boolean} New pause state
     */
    async togglePause() {
        if (this.isPaused) {
            await this.resume();
        } else {
            await this.pause();
        }
        return this.isPaused;
    },

    /**
     * Cancel the current task
     */
    async cancel() {
        if (!this.taskId) return;

        try {
            await API.post(`/api/rom-tools/task/${this.taskId}/cancel`);
            this.stop();
        } catch (error) {
            console.error('Error cancelling task:', error);
        }
    }
};

// =============================================================================
// PROGRESS TRACKER - Manages progress bar UI
// =============================================================================

const ProgressTracker = {
    elements: {
        bar: null,
        status: null,
        count: null,
        container: null
    },

    /**
     * Initialize progress tracker
     * @param {Object} elementIds - IDs of progress elements
     */
    init(elementIds = {}) {
        this.elements = {
            bar: document.getElementById(elementIds.bar || 'progressBar'),
            status: document.getElementById(elementIds.status || 'progressStatus'),
            count: document.getElementById(elementIds.count || 'progressCount'),
            container: document.getElementById(elementIds.container || 'progressSection')
        };
    },

    /**
     * Show the progress section
     */
    show() {
        if (this.elements.container) {
            this.elements.container.style.display = 'block';
        }
    },

    /**
     * Hide the progress section
     */
    hide() {
        if (this.elements.container) {
            this.elements.container.style.display = 'none';
        }
    },

    /**
     * Update progress
     * @param {number} percent - Progress percentage (0-100)
     * @param {string} status - Status text
     * @param {number} current - Current count
     * @param {number} total - Total count
     */
    update(percent, status = '', current = null, total = null) {
        const roundedPercent = Math.round(percent || 0);

        if (this.elements.bar) {
            this.elements.bar.style.width = roundedPercent + '%';
            if (roundedPercent > 0) {
                this.elements.bar.textContent = roundedPercent + '%';
                this.elements.bar.style.minWidth = '50px';
            } else {
                this.elements.bar.textContent = '';
                this.elements.bar.style.minWidth = '0';
            }
        }

        if (this.elements.status && status) {
            this.elements.status.textContent = status;
        }

        if (this.elements.count && current !== null && total !== null) {
            this.elements.count.textContent = `${formatNumber(current)} / ${formatNumber(total)}`;
        }
    },

    /**
     * Reset progress to initial state
     */
    reset() {
        this.update(0, 'Ready', 0, 0);
    },

    /**
     * Update from task object
     * @param {Object} task - Task status object
     */
    updateFromTask(task) {
        const status = task.current_file ? `Processing: ${task.current_file}` : 'Processing...';
        this.update(task.percent || 0, status, task.progress, task.total);
    }
};

// =============================================================================
// SESSION STATE - Preserves state across page reloads
// =============================================================================

const SessionState = {
    storageKey: 'romToolsState',

    /**
     * Set storage key for this tool
     * @param {string} key - Unique key for this tool
     */
    setKey(key) {
        this.storageKey = key;
    },

    /**
     * Save state to session storage
     * @param {Object} state - State to save
     */
    save(state) {
        try {
            sessionStorage.setItem(this.storageKey, JSON.stringify(state));
        } catch (e) {
            console.warn('Failed to save session state:', e);
        }
    },

    /**
     * Load state from session storage
     * @returns {Object|null} Saved state or null
     */
    load() {
        try {
            const saved = sessionStorage.getItem(this.storageKey);
            return saved ? JSON.parse(saved) : null;
        } catch (e) {
            console.warn('Failed to load session state:', e);
            return null;
        }
    },

    /**
     * Clear saved state
     */
    clear() {
        try {
            sessionStorage.removeItem(this.storageKey);
        } catch (e) {
            console.warn('Failed to clear session state:', e);
        }
    },

    /**
     * Update specific fields in saved state
     * @param {Object} updates - Fields to update
     */
    update(updates) {
        const current = this.load() || {};
        this.save({ ...current, ...updates });
    }
};

// =============================================================================
// BATCH OPERATIONS - Common batch action patterns
// =============================================================================

const BatchOperations = {
    /**
     * Execute batch operation with confirmation
     * @param {Object} options - Batch operation options
     */
    async execute(options) {
        const {
            title = 'Confirm Action',
            message = 'Are you sure?',
            endpoint,
            data,
            onSuccess,
            onError,
            successMessage = 'Operation completed',
            errorMessage = 'Operation failed'
        } = options;

        // Show confirmation if title/message provided
        showConfirm(title, message, async () => {
            await this._doExecute(endpoint, data, onSuccess, onError, successMessage, errorMessage);
        });
    },

    /**
     * Internal execute method
     */
    async _doExecute(endpoint, data, onSuccess, onError, successMessage, errorMessage) {
        try {
            const result = await API.post(endpoint, data);

            if (result.success) {
                if (typeof showNotification === 'function') {
                    showNotification(result.message || successMessage, 'success');
                }
                if (onSuccess) onSuccess(result);
            } else {
                if (typeof showNotification === 'function') {
                    showNotification(result.error || errorMessage, 'error');
                }
                if (onError) onError(result);
            }
        } catch (error) {
            console.error('Batch operation error:', error);
            if (typeof showNotification === 'function') {
                showNotification(errorMessage + ': ' + error.message, 'error');
            }
            if (onError) onError({ error: error.message });
        }
    }
};

// =============================================================================
// RESULTS TABLE - Common results display patterns
// =============================================================================

const ResultsTable = {
    container: null,
    emptyMessage: 'No results',
    columns: [],

    /**
     * Initialize results table
     * @param {Object} options - Configuration options
     */
    init(options = {}) {
        this.container = document.getElementById(options.containerId || 'resultsBody');
        this.emptyMessage = options.emptyMessage || 'No results';
        this.columns = options.columns || [];
    },

    /**
     * Render results
     * @param {Array} results - Array of result objects
     * @param {Function} rowRenderer - Function to render each row
     */
    render(results, rowRenderer) {
        if (!this.container) return;

        if (!results || results.length === 0) {
            this.container.innerHTML = `<tr><td colspan="${this.columns.length || 4}" class="text-center text-muted">${this.emptyMessage}</td></tr>`;
            return;
        }

        let html = '';
        results.forEach((result, index) => {
            html += rowRenderer(result, index);
        });
        this.container.innerHTML = html;
    },

    /**
     * Clear results
     */
    clear() {
        if (this.container) {
            this.container.innerHTML = '';
        }
    },

    /**
     * Update stats display
     * @param {Object} stats - Stats object
     * @param {Object} elementIds - Element IDs for stats display
     */
    updateStats(stats, elementIds) {
        Object.entries(elementIds).forEach(([key, elementId]) => {
            const el = document.getElementById(elementId);
            if (el && stats[key] !== undefined) {
                el.textContent = stats[key];
            }
        });
    }
};

// =============================================================================
// TOGGLE HELPERS - Shared toggle label and select-all logic
// =============================================================================

/**
 * Update toggle label styling when checkbox state changes
 * @param {HTMLInputElement} checkbox - The checkbox element
 */
function updateToggleLabel(checkbox) {
    const label = checkbox.closest('.toggle-item')?.querySelector('.toggle-label');
    if (label) {
        label.classList.toggle('active', checkbox.checked);
    }
}

/**
 * Toggle all checkboxes in the nearest file list or card
 * @param {HTMLInputElement} masterCheckbox - The master checkbox element
 */
function toggleAll(masterCheckbox) {
    const container = masterCheckbox.closest('.file-list') || masterCheckbox.closest('.card') || document.body;
    container.querySelectorAll('.file-list-item input[type="checkbox"]').forEach(cb => {
        if (cb !== masterCheckbox) cb.checked = masterCheckbox.checked;
    });
}

// =============================================================================
// FILE SIZE FORMATTER
// =============================================================================

/**
 * Format bytes to human readable size
 * @param {number} bytes - Size in bytes
 * @param {number} decimals - Decimal places
 * @returns {string} Formatted size string
 */
function formatFileSize(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return '0 B';

    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
}

// =============================================================================
// PAUSE BUTTON CONTROLLER
// =============================================================================

const PauseButton = {
    element: null,
    iconElement: null,
    textElement: null,
    isPaused: false,

    /**
     * Initialize pause button
     * @param {Object} elementIds - Element IDs
     */
    init(elementIds = {}) {
        this.element = document.getElementById(elementIds.button || 'pauseBtn');
        this.iconElement = document.getElementById(elementIds.icon || 'pauseIcon');
        this.textElement = document.getElementById(elementIds.text || 'pauseText');
        this.isPaused = false;
    },

    /**
     * Toggle pause state
     * @returns {boolean} New pause state
     */
    toggle() {
        this.isPaused = !this.isPaused;
        this.updateUI();
        return this.isPaused;
    },

    /**
     * Set pause state
     * @param {boolean} paused - Pause state
     */
    set(paused) {
        this.isPaused = paused;
        this.updateUI();
    },

    /**
     * Update UI based on pause state
     */
    updateUI() {
        if (!this.element) return;

        if (this.isPaused) {
            if (this.iconElement) this.iconElement.textContent = '▶️';
            if (this.textElement) this.textElement.textContent = 'Resume';
            this.element.classList.remove('btn-warning');
            this.element.classList.add('btn-success');
        } else {
            if (this.iconElement) this.iconElement.textContent = '⏸️';
            if (this.textElement) this.textElement.textContent = 'Pause';
            this.element.classList.remove('btn-success');
            this.element.classList.add('btn-warning');
        }
    },

    /**
     * Show/hide button
     * @param {boolean} visible - Visibility state
     */
    setVisible(visible) {
        if (this.element) {
            this.element.style.display = visible ? '' : 'none';
        }
    }
};

// Clear poll interval on page unload to prevent orphaned intervals
window.addEventListener('beforeunload', () => {
    TaskPoller.stop();
});

// =============================================================================
// EXPORT GLOBALS
// =============================================================================

window.TaskPoller = TaskPoller;
window.ProgressTracker = ProgressTracker;
window.SessionState = SessionState;
window.BatchOperations = BatchOperations;
window.ResultsTable = ResultsTable;
window.PauseButton = PauseButton;
window.updateToggleLabel = updateToggleLabel;
window.toggleAll = toggleAll;
window.formatFileSize = formatFileSize;
