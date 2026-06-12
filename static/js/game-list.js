/**
 * RetroDB Game List Module
 * Shared controllers used by game list pages.
 * Version: 2.1.0
 *
 * Features:
 * - FanartController: Hover-triggered fanart background display
 * - BackToTopController: Scroll-based back-to-top button
 * - RARefreshController: RetroAchievements data refresh for systems
 *
 * Note: SearchController, GameBulkSelection, FilterModalController,
 * GameFilterEngine, PageStateController, GameAlphabetNav, and GameListPage
 * were removed in v2.0.0 — they were unused dead code fully superseded by
 * AllGamesController (all-games-controller.js) for game list pages.
 */

window.RetroDB = window.RetroDB || {};

// =============================================================================
// FANART BACKGROUND
// =============================================================================

const FanartController = {
    element: null,
    timeout: null,

    /**
     * Initialize fanart controller
     */
    init() {
        this.element = document.getElementById('fanartBg');
    },

    /**
     * Show fanart background
     * @param {string} fanartPath - Path to fanart image
     */
    show(fanartPath) {
        if (!fanartPath || !this.element) return;
        clearTimeout(this.timeout);
        this.element.style.backgroundImage = `url('/static/images/fanart/${fanartPath}')`;
        this.element.classList.add('active');
    },

    /**
     * Hide fanart background with delay
     */
    hide() {
        if (!this.element) return;
        this.timeout = setTimeout(() => {
            this.element.classList.remove('active');
        }, 300);
    }
};

// Expose to global scope for inline event handlers
window.showFanart = (path) => FanartController.show(path);
window.hideFanart = () => FanartController.hide();

// =============================================================================
// BACK TO TOP BUTTON
// =============================================================================

const BackToTopController = {
    button: null,
    scrollThreshold: 400,
    _scrollHandler: null,

    /**
     * Initialize back to top button
     */
    init() {
        this.button = document.getElementById('backToTopBtn');
        if (!this.button) return;

        // Store throttled scroll listener reference for cleanup
        this._scrollHandler = throttle(() => {
            this.updateVisibility();
        }, 100);
        window.addEventListener('scroll', this._scrollHandler, { passive: true });

        // Initial state
        this.updateVisibility();

        // Mark as initialized so main.js skips its duplicate scroll handler
        this._isInit = true;
    },

    /**
     * Update button visibility based on scroll position
     */
    updateVisibility() {
        if (!this.button) return;

        if (window.scrollY > this.scrollThreshold) {
            this.button.classList.add('visible');
        } else {
            this.button.classList.remove('visible');
        }
    },

    /**
     * Scroll to top of page
     */
    scrollToTop() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    /**
     * Clean up event listeners
     */
    destroy() {
        if (this._scrollHandler) {
            window.removeEventListener('scroll', this._scrollHandler);
            this._scrollHandler = null;
        }
    }
};

// Global function for onclick handlers
window.scrollToTop = () => BackToTopController.scrollToTop();

// =============================================================================
// RETROACHIEVEMENTS REFRESH
// =============================================================================

const RARefreshController = {
    /**
     * Refresh RetroAchievements for a system
     * @param {number} systemId - System ID
     * @param {string} systemName - System name for display
     */
    async refreshForSystem(systemId, systemName) {
        const btn = document.getElementById('refreshRABtn');
        if (!btn) return;

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ starting: '\u23F3', queued: '\uD83D\uDCCB', running: '\u23F3', error: '\u274C' }[k] || k);
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="filter-icon">${_ti('starting')}</span> ${t('Starting...')}`;
        btn.disabled = true;

        try {
            const data = await API.post(`/api/refresh-retroachievements/${systemId}`);

            if (data.success) {
                // Check if operation was queued (blocked by another RA operation)
                if (data.queued) {
                    // Add to unified queue
                    const queue = safeParseJSON('raOperationsQueue', []);

                    // Don't add duplicates
                    if (!queue.find(q => q.type === 'refresh' && q.systemId === systemId)) {
                        const newItem = {
                            type: 'refresh',
                            systemId: systemId,
                            systemName: systemName || 'Unknown System',
                            gameCount: data.game_count,
                            timestamp: Date.now()
                        };
                        queue.push(newItem);
                        localStorage.setItem('raOperationsQueue', JSON.stringify(queue));

                        // Add queued toast if UnifiedToastController is available
                        if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                            UnifiedToastController.addRAOperationToQueue(newItem);
                            UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                        }
                    }

                    // Update button to show queued state
                    btn.innerHTML = `<span class="filter-icon">${_ti('queued')}</span> ${t('Queued')}`;
                    if (typeof showNotification !== 'undefined') {
                        showNotification(t('Added to queue - will start when current operation completes'), 'info');
                    }
                    return;
                }

                // RA Refresh started successfully - show active toast
                if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                    const initialData = {
                        running: true,
                        completed: false,
                        current_system: systemName || 'Unknown System',
                        current_game: 'Starting...',
                        total: data.game_count || 0,
                        current: 0,
                        processed: 0,
                        success: 0,
                        failed: 0,
                        percent: 0,
                        paused: false
                    };
                    UnifiedToastController.showActiveToast('ra-refresh', UnifiedToastController.getTypeConfig('ra-refresh'), initialData);
                    UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                    UnifiedToastController.broadcast('job-started', 'ra-refresh', initialData);
                }

                // Update button to show running state
                btn.innerHTML = `<span class="filter-icon">${_ti('running')}</span> ${t('Running...')}`;
                if (typeof showNotification !== 'undefined') {
                    showNotification(t('Refreshing RA for {system}...', {system: systemName || t('system')}), 'info');
                }
            } else {
                if (typeof showModal !== 'undefined') {
                    showModal(`${_ti('error')} ${t('Error')}`, data.error || t('Unknown error'));
                }
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        } catch (err) {
            if (typeof showModal !== 'undefined') {
                showModal(`${_ti('error')} ${t('Error')}`, t('Error refreshing RetroAchievements: ') + err.message);
            }
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
};

// Global function for RA refresh
window.refreshRAForSystem = (systemId, systemName) => RARefreshController.refreshForSystem(systemId, systemName);

// =============================================================================
// REGISTER WITH RETRODB NAMESPACE
// =============================================================================

RetroDB.FanartController = FanartController;
RetroDB.BackToTopController = BackToTopController;
RetroDB.RARefreshController = RARefreshController;

// =============================================================================
// EXPORT GLOBALS (backward compatibility)
// =============================================================================

window.FanartController = FanartController;
window.BackToTopController = BackToTopController;
window.RARefreshController = RARefreshController;

// Cleanup on page unload to prevent orphaned timers/listeners
window.addEventListener('beforeunload', () => {
    if (FanartController.timeout) {
        clearTimeout(FanartController.timeout);
        FanartController.timeout = null;
    }
    BackToTopController.destroy();
});
