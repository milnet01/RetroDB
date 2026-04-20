/**
 * RetroDB Bulk Scrape Module
 * Shared JavaScript for bulk scraping functionality
 * Used by games.html and all_games.html
 */

window.RetroDB = window.RetroDB || {};

// ============================================
// BULK SCRAPE CONTROLLER
// ============================================

const BulkScrapeController = {
    pollingInterval: null,  // Flag: true when registered with toast controller's shared poller
    
    /**
     * Initialize bulk scrape UI elements
     * @returns {Object} DOM element references
     */
    getElements() {
        return {
            modal: document.getElementById('bulkScrapeModal'),
            currentGame: document.getElementById('bulkCurrentGame'),
            status: document.getElementById('bulkStatus'),
            results: document.getElementById('bulkResults'),
            resultsLive: document.getElementById('bulkResultsLive'),
            footer: document.getElementById('bulkFooter'),
            closeBtn: document.getElementById('bulkCloseBtn'),
            controlsRow: document.getElementById('bulkControlsRow'),
            backgroundBtn: document.getElementById('bulkBackgroundBtn'),
            progressFill: document.getElementById('bulkProgressFill'),
            progress: document.getElementById('bulkProgress'),
            total: document.getElementById('bulkTotal'),
            successLive: document.getElementById('bulkSuccessCountLive'),
            failedLive: document.getElementById('bulkFailedCountLive'),
            skippedLive: document.getElementById('bulkSkippedCountLive'),
            successFinal: document.getElementById('bulkSuccessCount'),
            failedFinal: document.getElementById('bulkFailedCount'),
            skippedFinal: document.getElementById('bulkSkippedCount'),
            pauseBtn: document.getElementById('bulkPauseBtn'),
            pauseIcon: document.getElementById('bulkPauseBtnIcon'),
            pauseText: document.getElementById('bulkPauseBtnText')
        };
    },
    
    /**
     * Reset the modal UI to initial state
     * @param {number} totalGames - Total number of games to scrape
     * @param {string|null} firstGame - Title of the first game (for immediate feedback)
     */
    resetUI(totalGames, firstGame = null) {
        const el = this.getElements();
        
        el.modal.classList.add('active');
        el.total.textContent = formatNumber(totalGames);
        el.progress.textContent = '1';  // Show 1/x immediately (we're about to scrape game 1)
        el.progressFill.style.setProperty('--progress', '0%');
        el.successLive.textContent = '0';
        el.failedLive.textContent = '0';
        el.skippedLive.textContent = '0';
        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ paused: '⏸️', resume: '▶️', cancelled: '❌', 'stat-success': '✅', 'stat-failed': '❌', 'stat-skipped': '⏭️' }[k] || k);
        el.pauseIcon.textContent = _ti('paused');
        el.pauseText.textContent = 'Pause';
        el.pauseBtn.classList.remove('btn-success');
        el.pauseBtn.classList.add('btn-warning');

        // Use provided first game title if available
        el.currentGame.textContent = firstGame || 'Starting...';
        el.status.textContent = firstGame ? `Scraped 0/${formatNumber(totalGames)} - 0%` : 'Initializing bulk scrape...';
        el.results.style.display = 'none';
        el.resultsLive.style.display = 'flex';
        el.footer.style.display = 'none';
        if (el.closeBtn) el.closeBtn.style.display = 'none';
        if (el.backgroundBtn) el.backgroundBtn.style.display = 'inline-flex';
        el.controlsRow.style.display = 'flex';
    },
    
    /**
     * Start a bulk scrape job
     * @param {Array<number>} gameIds - Array of game IDs to scrape
     * @param {number|null} systemId - Optional system ID (for games.html)
     * @param {string} scrapeMode - 'fill_missing' or 'full_rescrape'
     */
    async start(gameIds, systemId = null, scrapeMode = 'fill_missing') {
        if (gameIds.length === 0) {
            const _wi = typeof getThemedIcon === 'function' ? getThemedIcon('warning') : '⚠️';
            showModal(`${_wi} No Games Selected`, 'Please select at least one game to scrape.');
            return;
        }
        
        const returnUrl = window.location.href;
        
        try {
            const payload = { 
                game_ids: gameIds, 
                return_url: returnUrl,
                scrape_mode: scrapeMode
            };
            if (systemId) payload.system_id = systemId;
            
            const response = await fetch('/api/bulk-scrape-job/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await response.json();
            
            if (data.success) {
                if (data.queued) {
                    // Job was queued, show queued notification and exit bulk mode
                    const _qi = typeof getThemedIcon === 'function' ? getThemedIcon('queued') : '📋';
                    showModal(`${_qi} Queued`, `Your bulk scrape has been queued (position ${data.queue_position}). It will start automatically when the current scrape finishes.`);
                    
                    // Exit bulk mode if the function exists on this page
                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        // Fallback: toggle bulk mode off if we're in bulk mode
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }
                } else {
                    // Job started immediately, show modal with first game and poll
                    this.resetUI(gameIds.length, data.first_game);
                    this.startPolling();

                    // Exit bulk mode since scrape has started
                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }

                    // Create active toast immediately - don't wait for poll
                    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                        const initialData = {
                            running: true,
                            completed: false,
                            job_id: data.job_id,
                            current_game: data.first_game || 'Starting...',
                            system_name: data.system_name || null,
                            total: gameIds.length,
                            current: 0,
                            processed: 0,
                            success: 0,
                            failed: 0,
                            skipped: 0,
                            percent: 0,
                            paused: false
                        };
                        UnifiedToastController.showActiveToast('bulk-scrape', UnifiedToastController.getTypeConfig('bulk-scrape'), initialData);
                        UnifiedToastController.adjustPollingSpeed('bulk-scrape', true);
                        UnifiedToastController.broadcast('job-started', 'bulk-scrape', initialData);
                    }
                }
            } else {
                if (data.error && data.error.includes('already')) {
                    showNotification(data.error, 'warning');
                } else {
                    const _ei2 = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
                    showModal(`${_ei2} Error`, data.error || 'Failed to start bulk scrape');
                }
            }
        } catch (error) {
            console.error('Error starting bulk scrape:', error);
            const _ei3 = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
            showModal(`${_ei3} Error`, 'Network error starting bulk scrape');
        }
    },
    
    /**
     * Handle poll data received from the toast controller (single shared poller)
     */
    // Track which game IDs we've already refreshed to avoid duplicate fetches
    _refreshedCardIds: new Set(),
    _MAX_REFRESHED_IDS: 500,  // Prevent unbounded growth during long scrapes

    handlePollData(data) {
        const el = this.getElements();
        const isModalOpen = el.modal && el.modal.classList.contains('active');

        if (!data.running && !data.completed) {
            this.stopPolling();
            return;
        }

        if (isModalOpen) {
            this.updateUI(data);
        }

        // Live-refresh game cards for recently scraped games
        if (data.recently_scraped_ids && data.recently_scraped_ids.length > 0 &&
            typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
            const newIds = data.recently_scraped_ids.filter(id => !this._refreshedCardIds.has(id));
            if (newIds.length > 0) {
                newIds.forEach(id => this._refreshedCardIds.add(id));
                // Evict oldest entries if Set grows too large
                if (this._refreshedCardIds.size > this._MAX_REFRESHED_IDS) {
                    const it = this._refreshedCardIds.values();
                    for (let i = 0; i < 100; i++) it.next();
                    // Rebuild without oldest 100
                    const keep = [];
                    let v = it.next();
                    while (!v.done) { keep.push(v.value); v = it.next(); }
                    this._refreshedCardIds = new Set(keep);
                }
                AllGamesController.refreshCards(newIds);
            }
        }

        if (data.completed) {
            this._refreshedCardIds.clear();
            this.stopPolling();
            if (isModalOpen) {
                this.showResults(data);
            }
        }
    },
    
    /**
     * Update modal UI with current status
     * @param {Object} data - Status data from backend
     */
    updateUI(data) {
        const el = this.getElements();
        
        el.currentGame.textContent = data.current_game || 'Processing...';
        el.progress.textContent = formatNumber(data.processing || 1);
        el.total.textContent = formatNumber(data.total || 0);
        el.successLive.textContent = formatNumber(data.success || 0);
        el.failedLive.textContent = formatNumber(data.failed || 0);
        el.skippedLive.textContent = formatNumber(data.skipped || 0);
        
        const percent = data.percent || 0;
        el.progressFill.style.setProperty('--progress', percent + '%');
        
        // Use processed count (completed games) for the status line
        const processed = data.processed || 0;
        
        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ paused: '⏸️', resume: '▶️', cancelled: '❌' }[k] || k);
        if (data.paused) {
            el.status.textContent = `${_ti('paused')} Paused - Click Resume to continue`;
            el.pauseIcon.textContent = _ti('resume');
            el.pauseText.textContent = 'Resume';
            el.pauseBtn.classList.remove('btn-warning');
            el.pauseBtn.classList.add('btn-success');
        } else if (data.cancelled) {
            el.status.textContent = `${_ti('cancelled')} Cancelled`;
        } else {
            el.status.textContent = `Scraped ${formatNumber(processed)} / ${formatNumber(data.total)} - ${percent}%`;
            el.pauseIcon.textContent = _ti('paused');
            el.pauseText.textContent = 'Pause';
            el.pauseBtn.classList.remove('btn-success');
            el.pauseBtn.classList.add('btn-warning');
        }
    },
    
    /**
     * Show final results
     * @param {Object} data - Final status data
     */
    showResults(data) {
        const el = this.getElements();

        // Set progress bar to final state BEFORE layout changes to prevent visual shift
        const finalPercent = data.cancelled ? (data.percent || 0) : 100;
        el.progressFill.style.setProperty('--progress', finalPercent + '%');
        el.progress.textContent = formatNumber(data.processed || data.total || 0);
        el.total.textContent = formatNumber(data.total || 0);

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ cancelled: '❌' }[k] || k);
        if (data.cancelled) {
            el.status.textContent = `${_ti('cancelled')} Cancelled by user`;
            // Keep the last game title visible
        } else {
            el.status.textContent = 'Bulk scraping complete!';
            el.currentGame.textContent = 'Done';
        }

        el.successFinal.textContent = formatNumber(data.success || 0);
        el.failedFinal.textContent = formatNumber(data.failed || 0);
        el.skippedFinal.textContent = formatNumber(data.skipped || 0);

        el.results.style.display = 'flex';
        el.resultsLive.style.display = 'none';
        el.footer.style.display = 'flex';
        el.controlsRow.style.display = 'none';
        if (el.closeBtn) el.closeBtn.style.display = 'block';
        if (el.backgroundBtn) el.backgroundBtn.style.display = 'none';
    },
    
    /**
     * Start polling for status updates
     */
    startPolling() {
        if (!this.pollingInterval) {
            // Register with the toast controller as the single shared poller
            // Both the modal and toast receive data from the same fetch
            if (typeof UnifiedToastController !== 'undefined') {
                UnifiedToastController.registerPollCallback('bulk-scrape', (data) => this.handlePollData(data));
            }
            this.pollingInterval = true;  // Flag that we're registered
        }
    },

    /**
     * Stop receiving poll updates
     */
    stopPolling() {
        if (this.pollingInterval) {
            this.pollingInterval = null;
            if (typeof UnifiedToastController !== 'undefined') {
                UnifiedToastController.unregisterPollCallback('bulk-scrape');
            }
        }
    },
    
    /**
     * Toggle pause/resume via backend API
     */
    async togglePause() {
        try {
            const response = await fetch('/api/bulk-scrape-job/status');
            const statusData = await response.json();

            const endpoint = statusData.paused
                ? '/api/bulk-scrape-job/resume'
                : '/api/bulk-scrape-job/pause';

            const actionResponse = await fetch(endpoint, { method: 'POST' });
            const data = await actionResponse.json();

            if (data.success) {
                // Trigger an immediate poll through the shared poller
                if (typeof UnifiedToastController !== 'undefined') {
                    UnifiedToastController.pollStatus('bulk-scrape', '/api/bulk-scrape-job/status');
                }
            }
        } catch (e) {
            console.error('Error toggling pause:', e);
        }
    },
    
    /**
     * Cancel bulk scrape via backend API
     */
    cancel() {
        const _wi2 = typeof getThemedIcon === 'function' ? getThemedIcon('warning') : '⚠️';
        showConfirm(`${_wi2} Cancel Bulk Scrape`, 'Are you sure you want to cancel the bulk scrape?', async () => {
            try {
                const response = await fetch('/api/bulk-scrape-job/cancel', { method: 'POST' });
                const data = await response.json();

                if (data.success) {
                    // Trigger an immediate poll through the shared poller
                    if (typeof UnifiedToastController !== 'undefined') {
                        UnifiedToastController.pollStatus('bulk-scrape', '/api/bulk-scrape-job/status');
                    }
                }
            } catch (e) {
                console.error('Error cancelling bulk scrape:', e);
            }
        });
    },
    
    /**
     * Run scrape in background (close modal)
     */
    runInBackground() {
        const el = this.getElements();

        // Stop modal polling - UnifiedToastController handles background updates
        this.stopPolling();

        // Close the modal
        if (el.modal) {
            el.modal.classList.remove('active');
        }

        // The UnifiedToastController already has an active toast (created in start()).
        // Ensure it's polling at active speed so it stays up to date.
        if (typeof UnifiedToastController !== 'undefined') {
            UnifiedToastController.adjustPollingSpeed('bulk-scrape', true);
        }

        // Exit bulk mode if the function exists on this page
        if (typeof exitBulkMode === 'function') {
            exitBulkMode();
        } else if (typeof toggleBulkMode === 'function') {
            // Fallback: toggle bulk mode off if we're in bulk mode
            const bulkModeBtn = document.getElementById('bulkModeBtn');
            if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                toggleBulkMode();
            }
        }
    },
    
    /**
     * Close the modal
     */
    closeModal() {
        this.getElements().modal.classList.remove('active');
        this.stopPolling();
    },
    
    /**
     * Check for running job on page load and resume if needed
     */
    async checkOnLoad() {
        // Check for modal flag (coming from toast click)
        if (localStorage.getItem('showBulkScrapeModal') === 'true') {
            localStorage.removeItem('showBulkScrapeModal');
            
            try {
                const response = await fetch('/api/bulk-scrape-job/status');
                const data = await response.json();
                
                if (data.success && data.running && !data.completed) {
                    const el = this.getElements();
                    if (el.modal) {
                        el.modal.classList.add('active');
                        this.startPolling();
                        this.updateUI(data);
                    }
                }
            } catch (e) {
                console.error('Error checking bulk scrape status:', e);
            }
        }
        
        // Note: We do NOT start modal polling here just because a job is running.
        // The toast poller in base.html handles background updates.
        // Modal polling only starts when the modal is explicitly opened.
    }
};

// ============================================
// REGISTER WITH RETRODB NAMESPACE
// ============================================

RetroDB.BulkScrapeController = BulkScrapeController;
window.BulkScrapeController = BulkScrapeController;

// ============================================
// GLOBAL FUNCTION WRAPPERS (backward compatibility)
// ============================================
// These maintain backward compatibility with onclick handlers in HTML
// Note: startBulkScrape() must be defined by each page (games.html, all_games.html)
// because it needs access to page-specific variables like selectedGames and systemId

window.toggleBulkPause = function() {
    BulkScrapeController.togglePause();
};

window.cancelBulkScrape = function() {
    BulkScrapeController.cancel();
};

window.runInBackground = function() {
    BulkScrapeController.runInBackground();
};

window.closeBulkScrapeModal = function() {
    BulkScrapeController.closeModal();
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    BulkScrapeController.checkOnLoad();
});
