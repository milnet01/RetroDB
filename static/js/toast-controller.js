/**
 * RetroDB Unified Toast Controller
 * Handles all toast notifications: Bulk Scrape, RA Sync, RA Refresh, PSN Refresh
 * Version: 1.21.0
 *
 * Polling strategy (v1.21.0):
 *   - On page load: one-time burst poll of all endpoints to detect in-progress jobs
 *   - Active jobs: 2s polling until complete
 *   - No idle polling — cross-tab events use BroadcastChannel
 *   - Tab re-focus: burst poll to catch anything missed while hidden
 */

window.RetroDB = window.RetroDB || {};

// =============================================================================
// TOAST TYPES AND COLORS
// =============================================================================

const ToastTypes = {
    BULK_SCRAPE: {
        id: 'bulk-scrape',
        name: 'Bulk Scrape',
        icon: '⏳',
        activeColor: '#4cc9f0',     // Cyan
        queuedColor: '#3a9fc2',      // Darker cyan
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    RA_SYNC: {
        id: 'ra-sync',
        name: 'RA Sync',
        icon: '🏆',
        activeColor: '#f59e0b',      // Orange
        queuedColor: '#c47d09',      // Darker orange
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    RA_REFRESH: {
        id: 'ra-refresh',
        name: 'RA Refresh',
        icon: '🔄',
        activeColor: '#a855f7',      // Purple
        queuedColor: '#8b46d4',      // Darker purple
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    PSN_REFRESH: {
        id: 'psn-refresh',
        name: 'PSN Refresh',
        icon: '🏆',
        activeColor: '#0070d1',      // PlayStation blue
        queuedColor: '#00439c',      // Darker PS blue
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    IMAGE_RESIZE: {
        id: 'image-resize',
        name: 'Image Resize',
        icon: '🖼️',
        activeColor: '#22c55e',      // Green
        queuedColor: '#16a34a',      // Darker green
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    }
};

// =============================================================================
// THEME-AWARE TOAST ICONS
// Each theme gets unique icons that match its aesthetic
// =============================================================================

const ThemeIcons = {
    cyberpunk: {
        // Job types
        'bulk-scrape': '⏳', 'ra-sync': '🏆', 'ra-refresh': '🔄',
        'psn-refresh': '🏆', 'image-resize': '🖼️',
        // Job states
        paused: '⏸️', resume: '▶️', complete: '✅', queued: '📋',
        cancelled: '❌', background: '🔽',
        // Notification types
        success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️',
        // Stats
        'stat-success': '✅', 'stat-failed': '❌', 'stat-skipped': '⏭️',
        // Actions
        starting: '⏳', running: '⏳', cancel: '❌', save: '✅',
        loading: '🔄'
    },
    matrix: {
        'bulk-scrape': '⟩⟩', 'ra-sync': '◈', 'ra-refresh': '⟳',
        'psn-refresh': '◈', 'image-resize': '⊞',
        paused: '▮▮', resume: '▶', complete: '✓', queued: '≡',
        cancelled: '✗', background: '▼',
        success: '✓', error: '✗', warning: '▲', info: '◆',
        'stat-success': '✓', 'stat-failed': '✗', 'stat-skipped': '▷',
        starting: '▶', running: '▶', cancel: '✗', save: '✓',
        loading: '⟳'
    },
    amber: {
        'bulk-scrape': '►', 'ra-sync': '★', 'ra-refresh': '↻',
        'psn-refresh': '★', 'image-resize': '▦',
        paused: '‖', resume: '►', complete: '●', queued: '░',
        cancelled: '■', background: '▾',
        success: '●', error: '■', warning: '▲', info: '◦',
        'stat-success': '●', 'stat-failed': '■', 'stat-skipped': '▻',
        starting: '►', running: '►', cancel: '■', save: '●',
        loading: '↻'
    },
    ocean: {
        'bulk-scrape': '≋', 'ra-sync': '⚓', 'ra-refresh': '↺',
        'psn-refresh': '⚓', 'image-resize': '◇',
        paused: '∿', resume: '▶', complete: '◉', queued: '⊕',
        cancelled: '⊘', background: '▿',
        success: '◉', error: '⊘', warning: '◈', info: '◎',
        'stat-success': '◉', 'stat-failed': '⊘', 'stat-skipped': '▹',
        starting: '≋', running: '≋', cancel: '⊘', save: '◉',
        loading: '↺'
    },
    christian: {
        'bulk-scrape': '✦', 'ra-sync': '☩', 'ra-refresh': '❋',
        'psn-refresh': '☩', 'image-resize': '✥',
        paused: '◆', resume: '▶', complete: '✧', queued: '⚜',
        cancelled: '✘', background: '▽',
        success: '✧', error: '✘', warning: '◈', info: '✦',
        'stat-success': '✧', 'stat-failed': '✘', 'stat-skipped': '▸',
        starting: '✦', running: '✦', cancel: '✘', save: '✧',
        loading: '❋'
    },
    bladerunner: {
        'bulk-scrape': '▸▸', 'ra-sync': '◆', 'ra-refresh': '⟲',
        'psn-refresh': '◆', 'image-resize': '⬡',
        paused: '▪▪', resume: '▶', complete: '◉', queued: '▫',
        cancelled: '✕', background: '▾',
        success: '◉', error: '✕', warning: '◈', info: '◇',
        'stat-success': '◉', 'stat-failed': '✕', 'stat-skipped': '▹',
        starting: '▸▸', running: '▸▸', cancel: '✕', save: '◉',
        loading: '⟲'
    },
    elite: {
        'bulk-scrape': '>>>', 'ra-sync': '*', 'ra-refresh': '~',
        'psn-refresh': '*', 'image-resize': '#',
        paused: '||', resume: '>', complete: 'OK', queued: '...',
        cancelled: 'X', background: 'v',
        success: 'OK', error: 'X', warning: '!', info: '>',
        'stat-success': 'OK', 'stat-failed': 'X', 'stat-skipped': '-',
        starting: '>>>', running: '>>>', cancel: 'X', save: 'OK',
        loading: '~'
    }
};

/**
 * Get a themed icon by key.
 * @param {string} key - Icon key (job type, state, or notification type)
 * @param {string} [fallback] - Fallback if key not found
 * @returns {string} Themed icon character(s)
 */
function getThemedIcon(key, fallback) {
    const theme = document.documentElement.getAttribute('data-theme') || 'cyberpunk';
    const icons = ThemeIcons[theme] || ThemeIcons.cyberpunk;
    return icons[key] || fallback || ThemeIcons.cyberpunk[key] || key;
}

// =============================================================================
// UNIFIED TOAST CONTROLLER
// =============================================================================

const UnifiedToastController = {
    container: null,
    activeToasts: new Map(),  // Map of jobId -> toast element
    pollingIntervals: new Map(),  // Map of type -> interval
    pollingEndpoints: new Map(),  // Map of type -> endpoint URL
    activeOperations: new Map(),  // Map of type -> boolean (is running)
    pollCallbacks: new Map(),     // Map of type -> callback fn (external consumers of poll data)
    _pollAbortControllers: new Map(),  // Map of type -> AbortController (cancel in-flight fetches)
    _initialized: false,          // Guard against duplicate init
    _resizeHandler: null,         // Stored for cleanup
    _visibilityHandler: null,     // Stored for cleanup
    _broadcastChannel: null,      // BroadcastChannel for cross-tab communication
    activePollIntervalMs: 2000,   // 2 seconds when operation is active

    /**
     * Initialize the toast controller
     */
    init() {
        if (this._initialized) return;  // Prevent duplicate initialization
        this._initialized = true;
        this.createContainer();
        this.cleanupOldCompletionKeys();
        this.setupBroadcastChannel();
        this.startPolling();
        this.restoreSavedState();
        this.setupVisibilityHandler();
    },
    
    /**
     * Clean up old completion tracking keys from localStorage
     * Keeps only keys from the last hour
     */
    cleanupOldCompletionKeys() {
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith('toast_completion_')) {
                // Parse job ID to get timestamp (e.g., "rasync_1706601234" -> 1706601234)
                const match = key.match(/_(\d{10,})$/);
                if (match) {
                    const timestamp = parseInt(match[1], 10);
                    const hourAgo = Math.floor(Date.now() / 1000) - 3600;
                    if (timestamp < hourAgo) {
                        keysToRemove.push(key);
                    }
                }
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));
    },
    
    // =========================================================================
    // BROADCAST CHANNEL — cross-tab job notifications
    // =========================================================================

    /**
     * Set up BroadcastChannel for cross-tab communication.
     * Messages: job-started, job-completed, job-cancelled
     */
    setupBroadcastChannel() {
        try {
            this._broadcastChannel = new BroadcastChannel('retrodb-jobs');
            this._broadcastChannel.onmessage = (event) => {
                this._handleBroadcast(event.data);
            };
        } catch (e) {
            // BroadcastChannel not supported — fall back to polling only
            console.debug('BroadcastChannel not available:', e.message);
        }
    },

    /**
     * Broadcast a job event to all other tabs.
     * @param {string} event - Event type: 'job-started', 'job-completed', 'job-cancelled'
     * @param {string} jobType - Operation type (e.g. 'bulk-scrape', 'ra-sync')
     * @param {Object} [data] - Optional status data to include
     */
    broadcast(event, jobType, data) {
        if (!this._broadcastChannel) return;
        try {
            this._broadcastChannel.postMessage({ event, jobType, data: data || {} });
        } catch (e) {
            // Channel may be closed; ignore
        }
    },

    /**
     * Handle an incoming broadcast from another tab.
     */
    _handleBroadcast(msg) {
        if (!msg || !msg.event || !msg.jobType) return;
        const { event, jobType, data } = msg;

        switch (event) {
            case 'job-started': {
                // Another tab started a job — create toast and begin active polling
                this.activeOperations.set(jobType, true);
                const config = this.getTypeConfig(jobType);
                if (config && data && !this.activeToasts.has(`active-${jobType}`)) {
                    this.showActiveToast(jobType, config, data);
                }
                this._startActivePolling(jobType);
                break;
            }
            case 'job-completed': {
                // Another tab's poll detected completion — update our toast
                this.activeOperations.set(jobType, false);
                const endpoint = this.pollingEndpoints.get(jobType);
                if (endpoint) {
                    // Do one final poll to get accurate completion data
                    this.pollStatus(jobType, endpoint);
                }
                break;
            }
            case 'job-cancelled': {
                this.activeOperations.set(jobType, false);
                this.hideActiveToast(jobType);
                this._stopTypePolling(jobType);
                break;
            }
        }
    },

    /**
     * Handle tab visibility changes - pause polling when hidden
     */
    setupVisibilityHandler() {
        if (this._visibilityHandlerSet) return;
        this._visibilityHandlerSet = true;
        this._visibilityHandler = () => {
            if (document.hidden) {
                // Tab is hidden - stop all polling to save resources
                this.stopAllPolling();
            } else {
                // Tab is visible again — burst poll to catch anything that
                // started/completed while hidden, then resume active-only polling
                this._burstPollAll();
                // Restart active polling for any operations still marked as active
                // (stopAllPolling cleared intervals but not activeOperations)
                for (const [type, isActive] of this.activeOperations) {
                    if (isActive && !this.pollingIntervals.has(type)) {
                        this._startActivePolling(type);
                    }
                }
            }
        };
        document.addEventListener('visibilitychange', this._visibilityHandler);
    },
    
    /**
     * Stop all polling intervals and abort in-flight requests
     */
    stopAllPolling() {
        for (const [type, intervalId] of this.pollingIntervals) {
            clearInterval(intervalId);
        }
        this.pollingIntervals.clear();
        // Abort any in-flight fetch requests
        for (const [type, ac] of this._pollAbortControllers) {
            ac.abort();
        }
        this._pollAbortControllers.clear();
    },
    
    /**
     * Create the unified toast container
     */
    createContainer() {
        // Check for and remove any duplicate containers
        const existingContainers = document.querySelectorAll('.unified-toast-container, #unifiedToastContainer');
        if (existingContainers.length > 1) {
            console.warn(`Found ${existingContainers.length} toast containers, cleaning up...`);
            // Keep only the first one
            for (let i = 1; i < existingContainers.length; i++) {
                existingContainers[i].remove();
            }
        }
        
        if (document.getElementById('unifiedToastContainer')) {
            this.container = document.getElementById('unifiedToastContainer');
            this.positionContainer();
            this.positionBackToTop();
            return;
        }
        
        this.container = document.createElement('div');
        this.container.id = 'unifiedToastContainer';
        this.container.className = 'unified-toast-container';
        document.body.appendChild(this.container);
        
        // Position container dynamically - try multiple times to ensure layout is ready
        this.positionContainer();
        this.positionBackToTop();

        // Guard against duplicate window listeners (only add once)
        if (!this._containerListenersSet) {
            this._containerListenersSet = true;

            // Also position after window load (when all CSS is applied)
            window.addEventListener('load', () => {
                this.positionContainer();
                this.positionBackToTop();
            });

            // And after a short delay for good measure
            setTimeout(() => {
                this.positionContainer();
                this.positionBackToTop();
            }, 500);

            // Reposition on resize (debounced to avoid layout thrashing during drag)
            let resizeTimer;
            this._resizeHandler = () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => {
                    this.positionContainer();
                    this.positionBackToTop();
                }, 150);
            };
            window.addEventListener('resize', this._resizeHandler, { passive: true });
        }
    },
    
    /**
     * Position the toast container based on actual content wrapper position.
     * Toast sits to the LEFT of content with a 25px gap between toast right edge and content left edge.
     * Dynamically adjusts toast width to fit the available space.
     */
    positionContainer() {
        // Wait for DOM if content wrapper isn't ready yet
        const contentWrapper = document.querySelector('.content-wrapper');
        if (!contentWrapper) {
            if (!this._positionRetryCount) this._positionRetryCount = 0;
            if (this._positionRetryCount < 10) {
                this._positionRetryCount++;
                setTimeout(() => this.positionContainer(), 100);
            }
            return;
        }
        
        if (!this.container) return;
        
        this._positionRetryCount = 0;
        
        const contentRect = contentWrapper.getBoundingClientRect();
        const gap = 25;
        const maxToastWidth = 360;
        const minToastWidth = 260;
        
        // Calculate sidebar right edge
        const sidebar = document.querySelector('.sidebar');
        const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : 260;
        const sidebarGap = 10;  // Minimum gap from sidebar
        const minLeft = sidebarRight + sidebarGap;
        
        // Available space between sidebar and content
        const availableSpace = contentRect.left - minLeft - gap;
        
        // Determine toast width - fit within available space, clamped to min/max
        let toastWidth = Math.min(maxToastWidth, Math.max(minToastWidth, availableSpace));
        
        // Calculate left position so right edge is {gap}px from content left edge
        let leftPos = contentRect.left - toastWidth - gap;
        
        // Ensure not behind sidebar
        if (leftPos < minLeft) {
            leftPos = minLeft;
            // Recalculate toast width to maintain gap from content
            const fitWidth = contentRect.left - leftPos - gap;
            toastWidth = Math.max(minToastWidth, Math.min(maxToastWidth, fitWidth));
        }
        
        // Apply positioning
        this.container.style.setProperty('left', leftPos + 'px', 'important');
        this.container.style.setProperty('width', toastWidth + 'px', 'important');
        
        // Update individual toast widths to match container
        this.container.querySelectorAll('.unified-toast').forEach(t => {
            t.style.width = toastWidth + 'px';
        });
        
        // Store current width for new toasts
        this._currentToastWidth = toastWidth;
    },
    
    /**
     * Position the Back to Top button 25px to the right of the content wrapper's right edge.
     * Falls back to right: 20px if it would go off-screen.
     */
    positionBackToTop() {
        const btn = document.getElementById('backToTopBtn');
        if (!btn) return;
        
        const contentWrapper = document.querySelector('.content-wrapper');
        if (!contentWrapper) return;
        
        const contentRect = contentWrapper.getBoundingClientRect();
        const gap = 25;
        const btnSize = 50;
        
        const leftPos = contentRect.right + gap;
        
        // Ensure button doesn't go off screen (10px safety margin)
        if (leftPos + btnSize > window.innerWidth - 10) {
            btn.style.left = 'auto';
            btn.style.right = '20px';
        } else {
            btn.style.right = 'auto';
            btn.style.left = leftPos + 'px';
        }
    },
    
    /**
     * Register endpoints and run a one-time burst poll to detect in-progress jobs.
     * No idle polling is started — only active jobs get polled.
     */
    startPolling() {
        // Store endpoints for each type
        this.pollingEndpoints.set('bulk-scrape', '/api/bulk-scrape-job/status');
        this.pollingEndpoints.set('ra-sync', '/api/achievements/sync-status');
        this.pollingEndpoints.set('ra-refresh', '/api/refresh-retroachievements/status');
        this.pollingEndpoints.set('psn-refresh', '/api/psn/bulk-refresh/status');
        this.pollingEndpoints.set('image-resize', '/api/maintenance/image-resize/status');

        // Initialize all as inactive
        this.activeOperations.set('bulk-scrape', false);
        this.activeOperations.set('ra-sync', false);
        this.activeOperations.set('ra-refresh', false);
        this.activeOperations.set('psn-refresh', false);
        this.activeOperations.set('image-resize', false);

        // One-time burst poll to detect any already-running jobs
        this._burstPollAll();
    },

    /**
     * Burst poll all endpoints once (no recurring interval).
     * If a job is found active, starts active polling for that type.
     */
    _burstPollAll() {
        for (const [type, endpoint] of this.pollingEndpoints) {
            this.pollStatus(type, endpoint);
        }
    },

    /**
     * Start active (2s) polling for a specific type.
     * @param {string} type - Operation type
     */
    _startActivePolling(type) {
        // Clear existing interval (idempotent)
        if (this.pollingIntervals.has(type)) {
            clearInterval(this.pollingIntervals.get(type));
        }
        const endpoint = this.pollingEndpoints.get(type);
        if (!endpoint) return;

        const intervalId = setInterval(() => {
            this.pollStatus(type, endpoint);
        }, this.activePollIntervalMs);
        this.pollingIntervals.set(type, intervalId);
    },

    /**
     * Stop polling for a specific type.
     */
    _stopTypePolling(type) {
        const intervalId = this.pollingIntervals.get(type);
        if (intervalId) {
            clearInterval(intervalId);
            this.pollingIntervals.delete(type);
        }
    },

    /**
     * Adjust polling speed for a specific type based on whether it's active.
     * When isActive is true, ensures active (2s) polling is running.
     * When false, stops polling for this type.
     */
    adjustPollingSpeed(type, isActive) {
        this.activeOperations.set(type, isActive);
        if (isActive) {
            this._startActivePolling(type);
        } else {
            this._stopTypePolling(type);
        }
    },

    /**
     * Immediately poll all types so toasts appear without waiting.
     * Polls twice (now + 2s) to handle the race where a just-started job
     * hasn't registered with its status endpoint yet on the first poll.
     */
    pollAllNow() {
        this._burstPollAll();
        // Second poll after a short delay to catch jobs that needed a moment to start
        setTimeout(() => {
            this._burstPollAll();
        }, 2000);
    },

    /**
     * Register a callback to receive poll data for a type.
     * This makes the toast controller the single poller — the callback
     * receives the same data the toast uses, so both stay perfectly in sync.
     * Also switches to a faster poll rate while a callback is registered.
     */
    registerPollCallback(type, callback) {
        this.pollCallbacks.set(type, callback);
        // Switch to faster polling (1500ms) for responsive modal updates
        const endpoint = this.pollingEndpoints.get(type);
        if (endpoint) {
            this._stopTypePolling(type);
            this.pollStatus(type, endpoint);
            this.pollingIntervals.set(type, setInterval(() => {
                this.pollStatus(type, endpoint);
            }, 1500));
        }
    },

    /**
     * Unregister a poll callback and revert to normal polling speed
     */
    unregisterPollCallback(type) {
        this.pollCallbacks.delete(type);
        // Revert: active jobs keep polling, inactive stop
        const isActive = this.activeOperations.get(type) || false;
        if (isActive) {
            this._startActivePolling(type);
        } else {
            this._stopTypePolling(type);
        }
    },

    /**
     * Poll status for a specific type
     */
    async pollStatus(type, endpoint) {
        try {
            // Abort any previous in-flight request for this type to prevent pileup
            const prevAbort = this._pollAbortControllers.get(type);
            if (prevAbort) prevAbort.abort();

            const ac = new AbortController();
            this._pollAbortControllers.set(type, ac);

            const data = await API.get(endpoint, { signal: ac.signal });
            this._pollAbortControllers.delete(type);

            // Different endpoints have different response formats
            // bulk-scrape-job/status returns { success: true, running: ..., ... }
            // achievements/sync-status returns { running: ..., ... } directly
            // Only skip if explicitly success: false
            if (data.success === false) return;

            this.updateToasts(type, data);

            // Manage polling lifecycle based on active state
            const isActive = data.running && !data.completed;
            const wasActive = this.activeOperations.get(type) || false;
            const hasToast = this.activeToasts.has(`active-${type}`);

            if (isActive && (!wasActive || !this.pollingIntervals.has(type))) {
                // Job is active but polling isn't running (new discovery, or
                // interval lost to visibility change / stopAllPolling)
                this._startActivePolling(type);
            } else if (!isActive && wasActive && data.completed) {
                // Job completed normally — stop polling, broadcast
                this._stopTypePolling(type);
                this.broadcast('job-completed', type, data);
            } else if (!isActive && wasActive && !data.completed && hasToast) {
                // Job stopped without completing (server restart) but toast still visible.
                // Keep polling at a slower rate to detect auto-resume.
                this._stopTypePolling(type);
                const endpoint2 = this.pollingEndpoints.get(type);
                if (endpoint2) {
                    this.pollingIntervals.set(type, setInterval(() => {
                        this.pollStatus(type, endpoint2);
                    }, 5000));
                }
            } else if (!isActive && wasActive) {
                // Job stopped, no toast — just stop polling
                this._stopTypePolling(type);
                this.broadcast('job-completed', type, data);
            } else if (!isActive && !this.pollCallbacks.has(type) && !hasToast) {
                // Not active, no callback, no toast — ensure no interval is running
                this._stopTypePolling(type);
            }

            // Forward to registered callback (e.g. bulk scrape modal)
            const callback = this.pollCallbacks.get(type);
            if (callback) callback(data);

        } catch (e) {
            if (e.name === 'AbortError') return;  // Expected when aborting stale requests
            console.debug(`Toast poll error for ${type}:`, e.message || e);
        }
    },
    
    /**
     * Update toasts based on status data
     * Creates active toasts if an operation is running but no toast exists (self-healing).
     * Toast removal is handled by completion or explicit cancel.
     */
    updateToasts(type, data) {
        const typeConfig = this.getTypeConfig(type);
        if (!typeConfig) return;

        // Determine if operation is active
        const isActive = data.running && !data.completed;

        // Track active state (polling lifecycle managed by pollStatus)
        this.activeOperations.set(type, isActive);

        // If active toast exists, update it with new data
        const toastId = `active-${type}`;
        const existingToast = this.activeToasts.get(toastId);

        if (isActive && !existingToast) {
            // Self-healing: create toast if operation is running but no toast exists
            this.showActiveToast(type, typeConfig, data);
        } else if (existingToast && (isActive || data.completed)) {
            // Update the existing toast with fresh data (including final update on completion)
            this.updateActiveToastContent(existingToast, type, typeConfig, data);
        }

        // Handle completion - this is the ONLY place that removes active toasts
        if (data.completed && existingToast) {
            this.handleCompletion(type, data);
        }

        // If the job completed before a toast was ever shown (e.g. fast failure),
        // show a one-shot notification so the user gets feedback
        if (data.completed && !existingToast) {
            const completionKey = `toast_completion_${type}_${data.job_id || data.start_time || Date.now()}`;
            if (!localStorage.getItem(completionKey)) {
                localStorage.setItem(completionKey, 'true');
                if (data.error) {
                    showNotification(`${typeConfig.name} failed: ${data.error}`, 'error');
                } else if (data.cancelled) {
                    showNotification(`${typeConfig.name} cancelled`, 'warning');
                } else {
                    const total = data.success || data.processed || 0;
                    showNotification(`${typeConfig.name} completed (${total} processed)`, 'success');
                }
            }
        }
        
        // Handle queue (bulk scrape specific - server-side queue)
        if (type === 'bulk-scrape' && data.queue) {
            this.updateQueuedToasts(type, data.queue);
        }
        
        // For RA operations: if nothing running and no active toast, check if unified queue needs processing
        // This handles the case where page loads and there's a queue but nothing running
        // IMPORTANT: Only trigger from ra-sync poll to avoid duplicate triggers from both ra-sync and ra-refresh
        if (type === 'ra-sync' && !isActive && !existingToast) {
            // Also check if ra-refresh is active
            const raRefreshToast = this.activeToasts.get('active-ra-refresh');
            if (!raRefreshToast) {
                const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
                if (queue.length > 0 && !this._triggeringRAQueue) {
                    this.triggerNextRAOperationFromQueue();
                }
            }
        }
    },
    
    /**
     * Trigger the next RA operation from the unified queue
     * Queue can contain both 'sync' and 'refresh' operations
     */
    triggerNextRAOperationFromQueue() {
        // Get unified queue from localStorage
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
        if (queue.length === 0) {
            this._triggeringRAQueue = false;
            return;
        }
        
        // Prevent double-triggering with a flag
        if (this._triggeringRAQueue) return;
        this._triggeringRAQueue = true;
        
        // Also check if there's already an active RA toast - don't trigger if so
        const syncToast = this.activeToasts.get('active-ra-sync');
        const refreshToast = this.activeToasts.get('active-ra-refresh');
        if (syncToast || refreshToast) {
            console.debug('RA operation already active, not triggering queue');
            this._triggeringRAQueue = false;
            return;
        }
        
        const next = queue[0];
        
        // Validate queue item
        if (!next || !next.type) {
            console.error('Invalid queue item:', next);
            // Remove invalid item
            const newQueue = queue.slice(1);
            localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
            this._triggeringRAQueue = false;
            return;
        }
        
        // Determine endpoint based on operation type
        let endpoint;
        if (next.type === 'sync') {
            endpoint = `/api/achievements/sync-system/${next.systemId}`;
        } else if (next.type === 'refresh') {
            endpoint = next.systemId 
                ? `/api/refresh-retroachievements/${next.systemId}`
                : '/api/refresh-retroachievements';
        } else {
            console.error('Unknown RA operation type:', next.type);
            // Remove invalid item
            const newQueue = queue.slice(1);
            localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
            this._triggeringRAQueue = false;
            return;
        }
        
        console.debug(`Triggering queued RA ${next.type} for ${next.systemName}`);
        
        API.post(endpoint)
            .then(result => {
                // Only proceed if operation actually STARTED (not just re-queued)
                if (result.success && !result.queued) {
                    // Operation started successfully - remove the queued toast
                    this.removeRAQueuedToast(next);
                    
                    // Remove from queue in localStorage
                    const updatedQueue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
                    const newQueue = updatedQueue.slice(1); // Remove first item
                    localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
                    
                    // Update remaining queue positions
                    this.updateRAQueuePositions();
                    
                    // Show active toast based on type
                    const initialData = {
                        running: true,
                        completed: false,
                        current_system: next.systemName,
                        current_game: 'Starting...',
                        total: next.gameCount || 0,
                        current: 0,
                        percent: 0,
                        paused: false
                    };
                    
                    if (next.type === 'sync') {
                        this.showActiveToast('ra-sync', ToastTypes.RA_SYNC, initialData);
                        this.adjustPollingSpeed('ra-sync', true);
                        this.broadcast('job-started', 'ra-sync', initialData);
                    } else {
                        this.showActiveToast('ra-refresh', ToastTypes.RA_REFRESH, initialData);
                        this.adjustPollingSpeed('ra-refresh', true);
                        this.broadcast('job-started', 'ra-refresh', initialData);
                    }
                } else if (result.queued) {
                    // Still blocked - keep in queue, retry later
                    console.debug(`RA ${next.type} still queued - another operation is running`);
                } else {
                    console.error(`Failed to start queued RA ${next.type}:`, result.error);
                    // Don't remove from queue - will retry on next poll
                }
            })
            .catch(e => {
                console.error(`Error starting queued RA ${next.type}:`, e);
                // Don't remove from queue - will retry on next poll
            })
            .finally(() => {
                // Reset flag after a delay to allow next poll to work
                setTimeout(() => {
                    this._triggeringRAQueue = false;
                }, 2000);
            });
    },
    
    // Keep old function name for backwards compatibility
    triggerNextRASyncFromQueue() {
        this.triggerNextRAOperationFromQueue();
    },
    
    /**
     * Add an RA operation to the unified queue (sync or refresh)
     */
    addRAOperationToQueue(item) {
        // Ensure container exists
        if (!this.container) {
            this.createContainer();
        }
        
        // Generate unique toast ID based on type and systemId
        const toastId = item.type === 'sync' 
            ? `queued-ra-sync-${item.systemId}`
            : `queued-ra-refresh-${item.systemId || 'all'}`;
        
        // Don't add if already exists
        if (this.activeToasts.has(toastId)) {
            return;
        }
        
        // Get queue to determine position
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
        const position = queue.findIndex(q => 
            q.type === item.type && 
            (q.systemId || 'all') === (item.systemId || 'all')
        ) + 1;
        
        const toast = this.createRAQueuedToast(item, position || queue.length);
        this.activeToasts.set(toastId, toast);
        this.container.appendChild(toast);
    },
    
    // Backwards compatibility alias
    addRASyncQueuedToast(item) {
        item.type = 'sync';
        this.addRAOperationToQueue(item);
    },
    
    /**
     * Remove a queued RA operation toast
     */
    removeRAQueuedToast(item) {
        const toastId = item.type === 'sync'
            ? `queued-ra-sync-${item.systemId}`
            : `queued-ra-refresh-${item.systemId || 'all'}`;
        const toast = this.activeToasts.get(toastId);
        if (toast) {
            toast.remove();
            this.activeToasts.delete(toastId);
        }
    },
    
    // Backwards compatibility alias
    removeRASyncQueuedToast(systemId) {
        this.removeRAQueuedToast({ type: 'sync', systemId });
    },
    
    /**
     * Update queue position numbers for unified queue
     */
    updateRAQueuePositions() {
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
        queue.forEach((item, index) => {
            const toastId = item.type === 'sync'
                ? `queued-ra-sync-${item.systemId}`
                : `queued-ra-refresh-${item.systemId || 'all'}`;
            const toast = this.activeToasts.get(toastId);
            if (toast) {
                const posEl = toast.querySelector('.queue-position');
                if (posEl) posEl.textContent = `#${index + 1}`;
            }
        });
    },
    
    // Backwards compatibility alias
    updateQueuePositions() {
        this.updateRAQueuePositions();
    },
    
    /**
     * Restore RA queued toasts from localStorage (called on page load only)
     */
    restoreRAQueuedToasts() {
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
        if (queue.length === 0) return;
        
        // Ensure container exists
        if (!this.container) {
            this.createContainer();
        }
        
        queue.forEach((item, index) => {
            const toastId = item.type === 'sync'
                ? `queued-ra-sync-${item.systemId}`
                : `queued-ra-refresh-${item.systemId || 'all'}`;
            
            // Skip if already exists
            if (this.activeToasts.has(toastId)) return;
            
            const toast = this.createRAQueuedToast(item, index + 1);
            this.activeToasts.set(toastId, toast);
            this.container.appendChild(toast);
        });
    },
    
    // Backwards compatibility alias
    restoreRASyncQueuedToasts() {
        this.restoreRAQueuedToasts();
    },

    /**
     * Create a queued toast for any RA operation (sync or refresh)
     */
    createRAQueuedToast(item, position) {
        const config = item.type === 'sync' ? ToastTypes.RA_SYNC : ToastTypes.RA_REFRESH;
        const toast = document.createElement('div');
        toast.className = `unified-toast queued-toast ra-${item.type}-queued-toast`;
        toast.dataset.priority = '10';
        toast.style.order = 90;
        toast.style.setProperty('--toast-color', config.queuedColor);
        
        // Build title based on type
        const title = item.type === 'sync' 
            ? `🔄 Sync: ${this.escapeHtml(item.systemName)}`
            : `🏆 Refresh: ${this.escapeHtml(item.systemName || 'All Systems')}`;
        
        // Build cancel function call
        const cancelCall = item.type === 'sync'
            ? `UnifiedToastController.cancelRAQueued('sync', ${item.systemId})`
            : `UnifiedToastController.cancelRAQueued('refresh', ${item.systemId || 'null'})`;
        
        toast.innerHTML = `
            <div class="toast-content">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon(item.type === 'sync' ? 'ra-sync' : 'ra-refresh', 'queued')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${title}</div>
                        <div class="toast-subtitle"><span class="queue-position">#${position}</span> in queue${item.gameCount ? ` • ${this.fmtNum(item.gameCount)} games` : ''}</div>
                    </div>
                </div>
                <div class="toast-controls">
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); ${cancelCall}" title="Remove from queue">
                        ✕
                    </button>
                </div>
            </div>
        `;

        return toast;
    },
    
    // Backwards compatibility alias
    createRASyncQueuedToast(item, position) {
        item.type = 'sync';
        return this.createRAQueuedToast(item, position);
    },
    
    /**
     * Cancel a queued RA operation
     */
    cancelRAQueued(type, systemId) {
        // Remove from localStorage
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
        const newQueue = queue.filter(q => !(q.type === type && (q.systemId || null) === systemId));
        localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
        
        // Remove the toast
        this.removeRAQueuedToast({ type, systemId });
        
        // Update positions of remaining toasts
        this.updateRAQueuePositions();
    },
    
    // Backwards compatibility alias
    cancelRASyncQueued(systemId) {
        this.cancelRAQueued('sync', systemId);
    },
    
    /**
     * Get type configuration
     */
    getTypeConfig(type) {
        switch(type) {
            case 'bulk-scrape': return ToastTypes.BULK_SCRAPE;
            case 'ra-sync': return ToastTypes.RA_SYNC;
            case 'ra-refresh': return ToastTypes.RA_REFRESH;
            case 'psn-refresh': return ToastTypes.PSN_REFRESH;
            case 'image-resize': return ToastTypes.IMAGE_RESIZE;
            default: return null;
        }
    },
    
    /**
     * Show or update an active toast
     */
    showActiveToast(type, config, data) {
        const toastId = `active-${type}`;
        let toast = this.activeToasts.get(toastId);
        
        if (!toast) {
            toast = this.createActiveToast(type, config, data);
            // CSS order is set in createActiveToast based on priority
            this.activeToasts.set(toastId, toast);
            this.container.appendChild(toast);
            // Position container only on first toast creation
            if (this.activeToasts.size === 1) {
                this.positionContainer();
            }
        }
        
        this.updateActiveToastContent(toast, type, config, data);
    },
    
    /**
     * Create an active toast element
     */
    createActiveToast(type, config, data) {
        const toast = document.createElement('div');
        toast.className = `unified-toast active-toast ${type}-toast`;
        toast.dataset.type = type;
        const priority = type === 'bulk-scrape' ? '100' : (type === 'ra-sync' ? '101' : (type === 'ra-refresh' ? '102' : (type === 'image-resize' ? '104' : '103')));
        toast.dataset.priority = priority;
        // Set CSS order: higher priority = lower order = appears at bottom (active toasts)
        // priority 100 -> order 0, priority 101 -> order -1, priority 102 -> order -2
        toast.style.order = 100 - parseInt(priority);
        
        const borderColor = data.paused ? config.pausedColor : config.activeColor;
        toast.style.setProperty('--toast-color', borderColor);
        
        toast.innerHTML = this.getActiveToastHTML(type, config, data);
        
        return toast;
    },
    
    /**
     * Get HTML for active toast
     */
    getActiveToastHTML(type, config, data) {
        const isPaused = data.paused;
        const percent = data.percent || 0;
        const total = data.total || 0;
        // For bulk-scrape, use backend-computed 'processing' (which game we're on now)
        const current = type === 'bulk-scrape' ? (data.processing || 1) : (data.current || 0);

        // Build subtitle - game name only (system shown separately)
        let currentItem;
        if (type === 'image-resize') {
            currentItem = data.current_file || 'Processing...';
        } else if (type === 'ra-refresh' || type === 'psn-refresh') {
            currentItem = data.current_game || 'Processing...';
        } else {
            currentItem = data.current_game || data.current_system || 'Processing...';
        }

        // System name for image-resize shows the current image type folder
        const fmt = (n) => this.fmtNum(n);
        // Themed stat icons
        const si = { s: getThemedIcon('stat-success'), f: getThemedIcon('stat-failed'), k: getThemedIcon('stat-skipped') };
        let statsHTML = '';
        if (type === 'bulk-scrape') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'ra-refresh') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${getThemedIcon('ra-sync')} <span class="stat-value" data-stat="success">${fmt(data.success)}</span> found</span>
                </div>
            `;
        } else if (type === 'psn-refresh') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'ra-sync') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'image-resize') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">⬆️ <span class="stat-value" data-stat="upscaled">${fmt(data.upscaled)}</span></span>
                    <span class="stat failed">⬇️ <span class="stat-value" data-stat="downscaled">${fmt(data.downscaled)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        }

        // System name line (bulk scrape, ra-sync, ra-refresh, image-resize)
        let systemNameValue = '';
        if (type === 'bulk-scrape' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-sync' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-refresh' && data.current_system) {
            systemNameValue = data.current_system;
        } else if (type === 'image-resize' && data.current_type) {
            systemNameValue = data.current_type;
        }
        const systemNameHTML = systemNameValue
            ? `<div class="toast-system-name" data-system-name>${this.escapeHtml(systemNameValue)}</div>`
            : '';

        // NPWR ID line for PSN refresh (shown below game title)
        const npwrHTML = (type === 'psn-refresh' && data.current_npwr)
            ? `<div class="toast-system-name" data-npwr>${this.escapeHtml(data.current_npwr)}</div>`
            : '';

        return `
            <div class="toast-content">
                <div class="toast-main" onclick="UnifiedToastController.navigateTo('${type}', '${data.return_url || ''}')">
                    <div class="toast-icon ${isPaused ? 'paused' : ''}">${isPaused ? getThemedIcon(type, 'paused') : getThemedIcon(type)}</div>
                    <div class="toast-info">
                        <div class="toast-title ${isPaused ? 'paused' : ''}">${config.name} ${isPaused ? '(Paused)' : 'Running'}</div>
                        ${systemNameHTML}
                        <div class="toast-subtitle" data-subtitle>${this.escapeHtml(currentItem)}</div>
                        ${npwrHTML}
                        <div class="toast-progress-bar">
                            <div class="toast-progress-fill" data-progress style="width: ${percent}%"></div>
                        </div>
                        <div class="toast-progress-text">
                            <span data-current>${fmt(current)}</span> / <span data-total>${fmt(total)}</span> (<span data-percent>${percent}</span>%)
                        </div>
                        ${statsHTML}
                    </div>
                </div>
                <div class="toast-controls">
                    ${type === 'bulk-scrape' || type === 'psn-refresh' ? `
                    <button class="toast-btn pause" onclick="event.stopPropagation(); UnifiedToastController.togglePause('${type}')" title="${isPaused ? 'Resume' : 'Pause'}">
                        <span data-pause-icon>${isPaused ? '▶️' : '⏸️'}</span>
                    </button>
                    ` : ''}
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); UnifiedToastController.cancel('${type}')" title="Cancel">
                        ✕
                    </button>
                </div>
            </div>
        `;
    },
    
    /**
     * Update active toast content
     */
    updateActiveToastContent(toast, type, config, data) {
        // Create signature of current state to skip unnecessary updates
        const stateSignature = `${type}-${data.paused}-${data.completed}-${data.percent}-${data.current}-${data.total}-${data.current_game || ''}-${data.current_system || ''}-${data.system_name || ''}-${data.current_file || ''}-${data.current_type || ''}-${data.current_npwr || ''}-${data.success}-${data.failed}-${data.skipped}-${data.upscaled || 0}-${data.downscaled || 0}`;
        if (toast.dataset.lastState === stateSignature) {
            return;  // Skip update - nothing changed
        }
        toast.dataset.lastState = stateSignature;
        
        const isPaused = data.paused;
        const percent = data.percent || 0;
        const total = data.total || 0;
        // For bulk-scrape, use backend-computed 'processing' (which game we're on now)
        const current = type === 'bulk-scrape' ? (data.processing || 1) : (data.current || 0);

        // Build subtitle - game name only (system shown separately)
        let currentItem;
        if (type === 'image-resize') {
            currentItem = data.current_file || 'Processing...';
        } else if (type === 'ra-refresh' || type === 'psn-refresh') {
            currentItem = data.current_game || 'Processing...';
        } else {
            currentItem = data.current_game || data.current_system || 'Processing...';
        }

        // Update color
        const isComplete = data.completed;
        const borderColor = isComplete ? config.completedColor : (isPaused ? config.pausedColor : config.activeColor);
        toast.style.setProperty('--toast-color', borderColor);

        // Update icon (theme-aware)
        const icon = toast.querySelector('.toast-icon');
        if (icon) {
            icon.textContent = isComplete ? getThemedIcon(type, 'complete') : (isPaused ? getThemedIcon(type, 'paused') : getThemedIcon(type));
            icon.classList.toggle('paused', isPaused);
        }

        // Update title
        const title = toast.querySelector('.toast-title');
        if (title) {
            const statusText = isComplete ? 'Complete' : (isPaused ? '(Paused)' : 'Running');
            title.textContent = `${config.name} ${statusText}`;
            title.classList.toggle('paused', isPaused);
        }
        
        // Update system name (bulk scrape, ra-sync, ra-refresh, image-resize)
        let systemNameEl = toast.querySelector('[data-system-name]');
        let systemNameValue = '';
        if (type === 'bulk-scrape' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-sync' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-refresh' && data.current_system) {
            systemNameValue = data.current_system;
        } else if (type === 'image-resize' && data.current_type) {
            systemNameValue = data.current_type;
        }
        if (systemNameValue) {
            if (systemNameEl) {
                systemNameEl.textContent = systemNameValue;
            } else {
                // Create element if it wasn't in the initial HTML
                const titleEl = toast.querySelector('.toast-title');
                if (titleEl) {
                    const nameDiv = document.createElement('div');
                    nameDiv.className = 'toast-system-name';
                    nameDiv.setAttribute('data-system-name', '');
                    nameDiv.textContent = systemNameValue;
                    titleEl.insertAdjacentElement('afterend', nameDiv);
                }
            }
        }

        // Update subtitle
        const subtitle = toast.querySelector('[data-subtitle]');
        if (subtitle) subtitle.textContent = currentItem;

        // Update NPWR ID line (PSN refresh)
        if (type === 'psn-refresh') {
            let npwrEl = toast.querySelector('[data-npwr]');
            if (data.current_npwr) {
                if (npwrEl) {
                    npwrEl.textContent = data.current_npwr;
                } else if (subtitle) {
                    const npwrDiv = document.createElement('div');
                    npwrDiv.className = 'toast-system-name';
                    npwrDiv.setAttribute('data-npwr', '');
                    npwrDiv.textContent = data.current_npwr;
                    subtitle.insertAdjacentElement('afterend', npwrDiv);
                }
            } else if (npwrEl) {
                npwrEl.remove();
            }
        }

        // Update progress
        const progressFill = toast.querySelector('[data-progress]');
        if (progressFill) progressFill.style.width = `${percent}%`;
        
        const currentEl = toast.querySelector('[data-current]');
        if (currentEl) currentEl.textContent = this.fmtNum(current);

        const totalEl = toast.querySelector('[data-total]');
        if (totalEl) totalEl.textContent = this.fmtNum(total);

        const percentEl = toast.querySelector('[data-percent]');
        if (percentEl) percentEl.textContent = percent;

        // Update stats (bulk scrape, ra-sync, ra-refresh, psn-refresh)
        if (type === 'bulk-scrape' || type === 'ra-sync' || type === 'ra-refresh' || type === 'psn-refresh') {
            const successEl = toast.querySelector('[data-stat="success"]');
            if (successEl) successEl.textContent = this.fmtNum(data.success);
        }

        if (type === 'bulk-scrape' || type === 'ra-sync' || type === 'psn-refresh') {
            const failedEl = toast.querySelector('[data-stat="failed"]');
            if (failedEl) failedEl.textContent = this.fmtNum(data.failed);

            const skippedEl = toast.querySelector('[data-stat="skipped"]');
            if (skippedEl) skippedEl.textContent = this.fmtNum(data.skipped);
        }

        if (type === 'image-resize') {
            const upscaledEl = toast.querySelector('[data-stat="upscaled"]');
            if (upscaledEl) upscaledEl.textContent = this.fmtNum(data.upscaled);

            const downscaledEl = toast.querySelector('[data-stat="downscaled"]');
            if (downscaledEl) downscaledEl.textContent = this.fmtNum(data.downscaled);

            const skippedEl = toast.querySelector('[data-stat="skipped"]');
            if (skippedEl) skippedEl.textContent = this.fmtNum(data.skipped);
        }
        
        // Update pause button
        const pauseIcon = toast.querySelector('[data-pause-icon]');
        if (pauseIcon) pauseIcon.textContent = isPaused ? '▶️' : '⏸️';
        
        const pauseBtn = toast.querySelector('.toast-btn.pause');
        if (pauseBtn) {
            pauseBtn.title = isPaused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('is-paused', isPaused);
        }
    },
    
    /**
     * Hide active toast
     */
    hideActiveToast(type) {
        const toastId = `active-${type}`;
        const toast = this.activeToasts.get(toastId);
        if (toast) {
            toast.remove();
            this.activeToasts.delete(toastId);
        }
    },
    
    /**
     * Handle completion - removes toast and processes queue
     * This is the ONLY place that removes active toasts (besides cancel)
     */
    handleCompletion(type, data) {
        // Prevent handling the same completion multiple times
        const completionKey = `toast_completion_${type}_${data.job_id || data.start_time || Date.now()}`;
        if (localStorage.getItem(completionKey)) {
            return;  // Already handled
        }
        localStorage.setItem(completionKey, 'true');
        
        console.debug(`Handling completion for ${type}`, data.job_id);
        
        // Hide the toast after a brief delay to show completion state
        setTimeout(() => {
            this.hideActiveToast(type);
            
            // For any RA operation (sync or refresh): check unified queue and start next
            if (type === 'ra-sync' || type === 'ra-refresh') {
                // Wait a bit longer to ensure server state is clean
                setTimeout(() => {
                    const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
                    // Double-check no active toasts exist
                    const syncToast = this.activeToasts.get('active-ra-sync');
                    const refreshToast = this.activeToasts.get('active-ra-refresh');
                    
                    if (queue.length > 0 && !this._triggeringRAQueue && !syncToast && !refreshToast) {
                        console.debug(`Queue has ${queue.length} items, triggering next`);
                        this.triggerNextRAOperationFromQueue();
                    }
                }, 1000);
            }
        }, 2000);
    },
    
    /**
     * Update queued toasts
     */
    updateQueuedToasts(type, queue) {
        // Skip if queue hasn't changed
        const queueSignature = JSON.stringify(queue.map(j => j.job_id));
        const signatureKey = `_lastQueueSig_${type}`;
        if (this[signatureKey] === queueSignature) {
            return;  // No changes, skip all DOM operations
        }
        this[signatureKey] = queueSignature;
        
        // Remove toasts for jobs no longer in queue
        const queueJobIds = new Set(queue.map(j => j.job_id));
        
        this.activeToasts.forEach((toast, toastId) => {
            if (toastId.startsWith(`queued-${type}-`)) {
                const jobId = toastId.replace(`queued-${type}-`, '');
                if (!queueJobIds.has(jobId)) {
                    toast.remove();
                    this.activeToasts.delete(toastId);
                }
            }
        });
        
        // Add/update queued toasts
        queue.forEach((job, index) => {
            const toastId = `queued-${type}-${job.job_id}`;
            let toast = this.activeToasts.get(toastId);
            
            if (!toast) {
                toast = this.createQueuedToast(type, job, index + 1);
                // Order is set in createQueuedToast
                this.activeToasts.set(toastId, toast);
                this.container.appendChild(toast);
            } else {
                // Only update position number, not recreate
                const posEl = toast.querySelector('.queue-position');
                if (posEl && posEl.textContent !== `#${index + 1}`) {
                    posEl.textContent = `#${index + 1}`;
                }
            }
        });
        
        // Order is set at creation time via CSS flex order
    },
    
    /**
     * Create a queued toast
     */
    createQueuedToast(type, job, position) {
        const config = this.getTypeConfig(type);
        const toast = document.createElement('div');
        toast.className = `unified-toast queued-toast ${type}-queued-toast`;
        toast.dataset.type = type;
        toast.dataset.jobId = job.job_id;
        toast.dataset.priority = '10';  // Queued toasts above active (lower priority = higher in stack)
        // Set CSS order at creation time (queued = order 90)
        toast.style.order = 90;
        toast.style.setProperty('--toast-color', config.queuedColor);
        
        toast.innerHTML = `
            <div class="toast-content queued">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon(type, 'queued')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${config.name} Queued (#${position})</div>
                        <div class="toast-subtitle">${job.system_name || 'Multi-System'}</div>
                        <div class="toast-meta">${this.fmtNum(job.total)} games</div>
                    </div>
                </div>
                <div class="toast-controls">
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); UnifiedToastController.cancelQueued('${type}', '${job.job_id}')" title="Remove from queue">
                        ✕
                    </button>
                </div>
            </div>
        `;
        
        return toast;
    },
    
    /**
     * Toggle pause for an operation
     */
    async togglePause(type) {
        try {
            let endpoint;
            switch(type) {
                case 'bulk-scrape':
                    const status = await API.get('/api/bulk-scrape-job/status');
                    endpoint = status.paused ? '/api/bulk-scrape-job/resume' : '/api/bulk-scrape-job/pause';
                    break;
                case 'ra-sync':
                    endpoint = '/api/ra-sync/toggle-pause';
                    break;
                case 'ra-refresh':
                    endpoint = '/api/ra-refresh/toggle-pause';
                    break;
                case 'psn-refresh':
                    const psnStatus = await API.get('/api/psn/bulk-refresh/status');
                    endpoint = psnStatus.paused ? '/api/psn/bulk-refresh/resume' : '/api/psn/bulk-refresh/pause';
                    break;
            }
            
            if (endpoint) {
                await API.post(endpoint);
            }
        } catch (e) {
            console.error(`Error toggling pause for ${type}:`, e);
        }
    },
    
    /**
     * Cancel an operation
     */
    cancel(type) {
        const config = this.getTypeConfig(type);
        if (typeof showConfirm === 'function') {
            showConfirm(`⚠️ Cancel ${config.name}`, `Are you sure you want to cancel?`, async () => {
                await this.performCancel(type);
            });
        } else {
            this.performCancel(type);
        }
    },
    
    /**
     * Perform cancellation
     */
    async performCancel(type) {
        try {
            let endpoint;
            switch(type) {
                case 'bulk-scrape':
                    endpoint = '/api/bulk-scrape-job/cancel';
                    break;
                case 'ra-sync':
                    endpoint = '/api/achievements/sync-cancel';
                    break;
                case 'ra-refresh':
                    endpoint = '/api/refresh-retroachievements/cancel';
                    break;
                case 'psn-refresh':
                    endpoint = '/api/psn/bulk-refresh/cancel';
                    break;
                case 'image-resize':
                    endpoint = '/api/maintenance/image-resize/cancel';
                    break;
            }

            if (endpoint) {
                await API.post(endpoint);
                this.hideActiveToast(type);
                this._stopTypePolling(type);
                this.activeOperations.set(type, false);
                this.broadcast('job-cancelled', type);
            }
        } catch (e) {
            console.error(`Error cancelling ${type}:`, e);
        }
    },
    
    /**
     * Cancel a queued job
     */
    async cancelQueued(type, jobId) {
        try {
            if (type === 'bulk-scrape') {
                await API.post(`/api/bulk-scrape-job/cancel-queued/${jobId}`);
                
                const toastId = `queued-${type}-${jobId}`;
                const toast = this.activeToasts.get(toastId);
                if (toast) {
                    toast.remove();
                    this.activeToasts.delete(toastId);
                }
            }
        } catch (e) {
            console.error(`Error cancelling queued job ${jobId}:`, e);
        }
    },
    
    /**
     * Navigate to the appropriate page
     */
    navigateTo(type, returnUrl) {
        if (type === 'bulk-scrape') {
            localStorage.setItem('showBulkScrapeModal', 'true');
        }

        if (returnUrl && window.location.pathname !== returnUrl) {
            window.location.href = returnUrl;
        } else if (type === 'ra-sync' || type === 'ra-refresh') {
            window.location.href = '/achievements';
        } else if (type === 'psn-refresh') {
            window.location.href = '/psn-trophies';
        }
    },
    
    /**
     * Restore saved toast state on page load
     */
    restoreSavedState() {
        // Clean up legacy localStorage key (replaced by BroadcastChannel)
        localStorage.removeItem('bulkScrapeJustStarted');
        localStorage.removeItem('bulkScrapeToastState');

        // Migrate old raSyncQueue to unified raOperationsQueue if needed
        this.migrateOldQueue();

        // Restore RA operations queue display immediately (before first poll completes)
        this.restoreRAQueuedToasts();
    },
    
    /**
     * Migrate old raSyncQueue to unified raOperationsQueue
     */
    migrateOldQueue() {
        const oldQueue = localStorage.getItem('raSyncQueue');
        if (oldQueue) {
            try {
                const oldItems = JSON.parse(oldQueue);
                if (oldItems.length > 0) {
                    // Get current unified queue
                    const unifiedQueue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
                    
                    // Add old items with type='sync' if not already present
                    oldItems.forEach(item => {
                        if (!item.type) item.type = 'sync';
                        if (!unifiedQueue.find(q => q.type === 'sync' && q.systemId === item.systemId)) {
                            unifiedQueue.push(item);
                        }
                    });
                    
                    localStorage.setItem('raOperationsQueue', JSON.stringify(unifiedQueue));
                }
            } catch (e) {
                console.error('Error migrating old queue:', e);
            }
            // Remove old queue
            localStorage.removeItem('raSyncQueue');
        }
    },
    
    
    /**
     * Format a number with thin-space thousands separators (delegates to global formatNumber)
     */
    fmtNum(n) {
        return typeof formatNumber === 'function' ? formatNumber(n || 0) : String(n || 0);
    },

    /**
     * Escape HTML
     */
    escapeHtml(text) {
        return window.escapeHtml ? window.escapeHtml(text) : (text || '');
    },
    
    /**
     * Cleanup - call on page unload
     */
    cleanup() {
        // Stop all polling intervals
        this.pollingIntervals.forEach(interval => clearInterval(interval));
        this.pollingIntervals.clear();
        // Abort in-flight fetch requests
        this._pollAbortControllers.forEach(ac => ac.abort());
        this._pollAbortControllers.clear();
        // Close BroadcastChannel
        if (this._broadcastChannel) {
            this._broadcastChannel.close();
            this._broadcastChannel = null;
        }
        // Remove window/document event listeners
        if (this._resizeHandler) {
            window.removeEventListener('resize', this._resizeHandler);
            this._resizeHandler = null;
        }
        if (this._visibilityHandler) {
            document.removeEventListener('visibilitychange', this._visibilityHandler);
            this._visibilityHandler = null;
        }
        // Clear all toast references
        this.activeToasts.clear();
        // Clear callback references
        this.pollCallbacks.clear();
        this.activeOperations.clear();
        // Allow re-initialization on bfcache restore
        this._initialized = false;
        this._containerListenersSet = false;
        this._visibilityHandlerSet = false;
    }
};

// =============================================================================
// COMPATIBILITY WRAPPERS
// =============================================================================

// Bulk scrape compatibility
function goToBulkScrape() {
    UnifiedToastController.navigateTo('bulk-scrape', localStorage.getItem('bulkScrapeReturnUrl') || '/all-games');
}

function toggleToastPause() {
    UnifiedToastController.togglePause('bulk-scrape');
}

function cancelFromToast() {
    UnifiedToastController.cancel('bulk-scrape');
}

// RA sync compatibility
function cancelRASync() {
    UnifiedToastController.cancel('ra-sync');
}

// =============================================================================
// INITIALIZATION
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
    UnifiedToastController.init();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    UnifiedToastController.cleanup();
});

// Register with RetroDB namespace
RetroDB.UnifiedToastController = UnifiedToastController;
RetroDB.ToastController = UnifiedToastController;
RetroDB.ToastTypes = ToastTypes;
RetroDB.ThemeIcons = ThemeIcons;
RetroDB.getThemedIcon = getThemedIcon;

// Export (backward compatibility)
window.UnifiedToastController = UnifiedToastController;
window.ToastController = UnifiedToastController;
window.ToastTypes = ToastTypes;
window.ThemeIcons = ThemeIcons;
window.getThemedIcon = getThemedIcon;
