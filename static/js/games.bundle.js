(function(){
/**
 * RetroDB Filtering & Sorting Module
 * Shared filtering functionality for games lists
 * Version: 2.0.0
 *
 * Features:
 * - AlphabetNav: A-Z quick navigation (used by achievements, trophies, etc.)
 *
 * Note: FilterController, SortController, and BulkSelectionController were
 * removed in v2.0.0 — they were unused dead code superseded by
 * AllGamesController (all-games-controller.js) for game list pages.
 */

window.RetroDB = window.RetroDB || {};

const AlphabetNav = {
    /**
     * Initialize alphabet navigation
     * Scans DOM items to build a letter map and wires up A-Z buttons.
     * @param {Object} config - Configuration options
     * @param {string} config.itemSelector - CSS selector for items (default: '.game-card-wrapper')
     */
    init(config = {}) {
        const nav = document.getElementById('alphabetNav');
        if (!nav) return;

        const buttons = nav.querySelectorAll('.alphabet-btn');
        const itemSelector = config.itemSelector || '.game-card-wrapper';
        const items = document.querySelectorAll(itemSelector);

        const letterMap = new Map();
        items.forEach(item => {
            const title = (item.dataset.sortTitle || item.dataset.title || item.dataset.name || '').toUpperCase();
            const firstChar = title.charAt(0);
            const letter = /[A-Z]/.test(firstChar) ? firstChar : '#';

            if (!letterMap.has(letter)) {
                letterMap.set(letter, item);
            }
        });

        buttons.forEach(btn => {
            const letter = btn.dataset.letter;
            if (letterMap.has(letter)) {
                btn.classList.remove('disabled');
                btn.onclick = () => this.scrollToLetter(letterMap.get(letter));
            } else {
                btn.classList.add('disabled');
                btn.onclick = null;
            }
        });
    },

    /**
     * Scroll to first game starting with letter
     * @param {Element} element - Target element
     */
    scrollToLetter(element) {
        if (!element) return;

        const headerOffset = 150;
        const elementPosition = element.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

        window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
        });

        element.classList.add('highlight-jump');
        setTimeout(() => {
            element.classList.remove('highlight-jump');
        }, 1500);
    }
};

RetroDB.AlphabetNav = AlphabetNav;

window.AlphabetNav = AlphabetNav;

})();

(function(){
/**
 * RetroDB Bulk Scrape Module
 * Shared JavaScript for bulk scraping functionality
 * Used by games.html and all_games.html
 */

window.RetroDB = window.RetroDB || {};

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
        if (window.ModalFocusTrap) {
            ModalFocusTrap.activate(el.modal.querySelector('.modal-content') || el.modal,
                                    document.activeElement,
                                    { onEscape: () => this.closeModal() });
        }
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

            const data = await API.post('/api/bulk-scrape-job/start', payload);

            if (data.success) {
                if (data.queued) {
                    const _qi = typeof getThemedIcon === 'function' ? getThemedIcon('queued') : '📋';
                    showModal(`${_qi} Queued`, `Your bulk scrape has been queued (position ${data.queue_position}). It will start automatically when the current scrape finishes.`);

                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }
                } else {
                    this.resetUI(gameIds.length, data.first_game);
                    this.startPolling();

                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }

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

        if (data.recently_scraped_ids && data.recently_scraped_ids.length > 0 &&
            typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
            const newIds = data.recently_scraped_ids.filter(id => !this._refreshedCardIds.has(id));
            if (newIds.length > 0) {
                newIds.forEach(id => this._refreshedCardIds.add(id));
                if (this._refreshedCardIds.size > this._MAX_REFRESHED_IDS) {
                    const it = this._refreshedCardIds.values();
                    for (let i = 0; i < 100; i++) it.next();
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

        const finalPercent = data.cancelled ? (data.percent || 0) : 100;
        el.progressFill.style.setProperty('--progress', finalPercent + '%');
        el.progress.textContent = formatNumber(data.processed || data.total || 0);
        el.total.textContent = formatNumber(data.total || 0);

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ cancelled: '❌' }[k] || k);
        if (data.cancelled) {
            el.status.textContent = `${_ti('cancelled')} Cancelled by user`;
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
            const statusData = await API.get('/api/bulk-scrape-job/status');

            const endpoint = statusData.paused
                ? '/api/bulk-scrape-job/resume'
                : '/api/bulk-scrape-job/pause';

            const data = await API.post(endpoint);

            if (data.success) {
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
                const data = await API.post('/api/bulk-scrape-job/cancel');

                if (data.success) {
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

        this.stopPolling();

        if (el.modal) {
            el.modal.classList.remove('active');
            if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
        }

        if (typeof UnifiedToastController !== 'undefined') {
            UnifiedToastController.adjustPollingSpeed('bulk-scrape', true);
        }

        if (typeof exitBulkMode === 'function') {
            exitBulkMode();
        } else if (typeof toggleBulkMode === 'function') {
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
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    },

    /**
     * Check for running job on page load and resume if needed
     */
    async checkOnLoad() {
        if (localStorage.getItem('showBulkScrapeModal') === 'true') {
            localStorage.removeItem('showBulkScrapeModal');

            try {
                const data = await API.get('/api/bulk-scrape-job/status');

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

    }
};

RetroDB.BulkScrapeController = BulkScrapeController;
window.BulkScrapeController = BulkScrapeController;

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

document.addEventListener('DOMContentLoaded', () => {
    BulkScrapeController.checkOnLoad();
});

})();

(function(){
/**
 * RetroDB Bulk Edit Controller
 * Handles bulk editing of game fields from game list pages.
 * Version: 2.4.0
 */

window.RetroDB = window.RetroDB || {};

const BulkEditController = (function() {
    'use strict';

    let gameIds = [];
    let _abortController = null;

    const APPENDABLE_FIELDS = ['genre', 'publisher', 'developer', 'franchise', 'region', 'game_structure'];

    /**
     * Open the bulk edit modal with the given game IDs
     * @param {number[]} ids - Array of game IDs to edit
     */
    async function open(ids) {
        if (!ids || ids.length === 0) {
            showModal('No Games Selected', 'Please select at least one game to edit.');
            return;
        }

        gameIds = ids;

        if (_abortController) _abortController.abort();
        _abortController = new AbortController();

        const modal = document.getElementById('bulkEditModal');
        if (!modal) return;

        modal.querySelectorAll('select[data-field]').forEach(sel => { sel.value = ''; });
        modal.querySelectorAll('input[data-field]').forEach(inp => { inp.value = ''; });
        modal.querySelectorAll('.bulk-append-toggle').forEach(toggle => { toggle.checked = false; });

        const countEl = document.getElementById('bulkEditCount');
        if (countEl) countEl.textContent = formatNumber(ids.length);

        await Promise.all([
            loadGameStructureOptions(),
            loadGenreOptions(),
            loadPerspectiveOptions(),
            loadDimensionOptions()
        ]);

        modal.classList.add('active');
        if (window.ModalFocusTrap) {
            ModalFocusTrap.activate(modal.querySelector('.modal-content') || modal,
                                    document.activeElement,
                                    { onEscape: () => close() });
        }
    }

    /**
     * Load game_structure dropdown options from API
     */
    async function loadGameStructureOptions() {
        const select = document.getElementById('bulkEditGameStructure');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const data = await API.get('/api/dropdown-options/game_structure', {
                signal: _abortController ? _abortController.signal : undefined
            });

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load game structure options:', err);
        }
    }

    /**
     * Load perspective dropdown options from API
     */
    async function loadPerspectiveOptions() {
        const select = document.getElementById('bulkEditPerspective');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const data = await API.get('/api/dropdown-options/perspective', {
                signal: _abortController ? _abortController.signal : undefined
            });

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load perspective options:', err);
        }
    }

    /**
     * Load dimension dropdown options from API
     */
    async function loadDimensionOptions() {
        const select = document.getElementById('bulkEditDimension');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const data = await API.get('/api/dropdown-options/dimension', {
                signal: _abortController ? _abortController.signal : undefined
            });

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load dimension options:', err);
        }
    }

    /**
     * Load genre dropdown options from API
     */
    async function loadGenreOptions() {
        const select = document.getElementById('bulkEditGenre');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const data = await API.get('/api/dropdown-options/genre', {
                signal: _abortController ? _abortController.signal : undefined
            });

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load genre options:', err);
        }
    }

    /**
     * Collect changed fields from the form
     * @returns {Object} - Object with field names and their new values
     */
    function collectChanges() {
        const modal = document.getElementById('bulkEditModal');
        if (!modal) return {};

        const changes = {};

        modal.querySelectorAll('select[data-field]').forEach(sel => {
            if (sel.value !== '') {
                changes[sel.dataset.field] = sel.value;
            }
        });

        modal.querySelectorAll('input[data-field]').forEach(inp => {
            if (inp.value.trim() !== '') {
                changes[inp.dataset.field] = inp.value.trim();
            }
        });

        return changes;
    }

    /**
     * Collect append modes for applicable fields
     * @returns {Object} - Object mapping field names to 'append' or 'replace'
     */
    function collectAppendModes() {
        const modes = {};
        document.querySelectorAll('.bulk-append-toggle').forEach(toggle => {
            const field = toggle.dataset.field;
            if (field && APPENDABLE_FIELDS.includes(field)) {
                modes[field] = toggle.checked ? 'append' : 'replace';
            }
        });
        return modes;
    }

    /**
     * Apply bulk edit changes
     */
    function apply() {
        const fields = collectChanges();

        if (Object.keys(fields).length === 0) {
            showModal('No Changes', 'Please change at least one field before applying.');
            return;
        }

        const fieldNames = Object.keys(fields).map(f => f.replace(/_/g, ' ')).join(', ');
        const msg = `Update ${formatNumber(gameIds.length)} game${gameIds.length !== 1 ? 's' : ''}?\n\nFields: ${fieldNames}`;

        showConfirm('Confirm Bulk Edit', msg, async function() {
            await sendBulkEdit(fields);
        });
    }

    /**
     * Send bulk edit request to the API
     * @param {Object} fields - Fields to update
     */
    async function sendBulkEdit(fields) {
        const applyBtn = document.getElementById('bulkEditApplyBtn');
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.textContent = 'Applying...';
        }

        try {
            const appendModes = collectAppendModes();

            const fieldModes = {};
            for (const field of Object.keys(fields)) {
                if (appendModes[field]) {
                    fieldModes[field] = appendModes[field];
                }
            }

            const data = await API.post('/api/games/bulk-edit', {
                game_ids: gameIds,
                fields: fields,
                field_modes: fieldModes
            });

            if (data.success) {
                close();
                showNotification(`Successfully updated ${formatNumber(data.updated)} games`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showModal('Error', data.error || 'Unknown error occurred.');
            }
        } catch (err) {
            console.error('Bulk edit error:', err);
            showModal('Error', 'Failed to apply bulk edit. Check console for details.');
        } finally {
            if (applyBtn) {
                applyBtn.disabled = false;
                applyBtn.textContent = 'Apply Changes';
            }
        }
    }

    /**
     * Close the bulk edit modal
     */
    function close() {
        const modal = document.getElementById('bulkEditModal');
        if (modal) modal.classList.remove('active');
        gameIds = [];
        if (_abortController) {
            _abortController.abort();
            _abortController = null;
        }
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    }

    window.closeBulkEditModal = close;

    return {
        open,
        apply,
        close
    };
})();

RetroDB.BulkEditController = BulkEditController;
window.BulkEditController = BulkEditController;

})();

(function(){
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

window.showFanart = (path) => FanartController.show(path);
window.hideFanart = () => FanartController.hide();

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

        this._scrollHandler = throttle(() => {
            this.updateVisibility();
        }, 100);
        window.addEventListener('scroll', this._scrollHandler, { passive: true });

        this.updateVisibility();

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

window.scrollToTop = () => BackToTopController.scrollToTop();

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
        btn.innerHTML = `<span class="filter-icon">${_ti('starting')}</span> Starting...`;
        btn.disabled = true;

        try {
            const data = await API.post(`/api/refresh-retroachievements/${systemId}`);

            if (data.success) {
                if (data.queued) {
                    const queue = safeParseJSON('raOperationsQueue', []);

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

                        if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                            UnifiedToastController.addRAOperationToQueue(newItem);
                            UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                        }
                    }

                    btn.innerHTML = `<span class="filter-icon">${_ti('queued')}</span> Queued`;
                    if (typeof showNotification !== 'undefined') {
                        showNotification('Added to queue - will start when current operation completes', 'info');
                    }
                    return;
                }

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

                btn.innerHTML = `<span class="filter-icon">${_ti('running')}</span> Running...`;
                if (typeof showNotification !== 'undefined') {
                    showNotification(`Refreshing RA for ${systemName || 'system'}...`, 'info');
                }
            } else {
                if (typeof showModal !== 'undefined') {
                    showModal(`${_ti('error')} Error`, data.error || 'Unknown error');
                }
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        } catch (err) {
            if (typeof showModal !== 'undefined') {
                showModal(`${_ti('error')} Error`, 'Error refreshing RetroAchievements: ' + err.message);
            }
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
};

window.refreshRAForSystem = (systemId, systemName) => RARefreshController.refreshForSystem(systemId, systemName);

RetroDB.FanartController = FanartController;
RetroDB.BackToTopController = BackToTopController;
RetroDB.RARefreshController = RARefreshController;

window.FanartController = FanartController;
window.BackToTopController = BackToTopController;
window.RARefreshController = RARefreshController;

window.addEventListener('beforeunload', () => {
    if (FanartController.timeout) {
        clearTimeout(FanartController.timeout);
        FanartController.timeout = null;
    }
    BackToTopController.destroy();
});

})();

(function(){
/**
 * RetroDB Game Modals Module
 * Handles Game Detail Modal and Game Edit Modal functionality
 * Extracted from base.html for better maintainability
 * Version: 1.22.0
 */

window.RetroDB = window.RetroDB || {};

/** Rating system column mapping */
const _MODAL_RATING_COLS = {
    esrb: 'esrb_rating', pegi: 'pegi_rating', cero: 'cero_rating',
    usk: 'usk_rating', acb: 'acb_rating', fpb: 'fpb_rating',
    grac: 'grac_rating', classind: 'classind_rating'
};

/**
 * Get ALL ratings present on a game (for admin view).
 * @param {Object} game - Game data from API
 * @returns {Array} [{system, value, image, name}, ...]
 */
function _getAllRatingsFromGame(game) {
    const imgMap = window.RATING_IMAGE_MAP || {};
    const keys = window.RATING_SYSTEM_KEYS || Object.keys(_MODAL_RATING_COLS);
    const names = window.RATING_SYSTEM_NAMES || {};
    const ratings = [];
    for (const sysKey of keys) {
        const col = _MODAL_RATING_COLS[sysKey];
        const val = game[col];
        if (val) {
            ratings.push({
                system: sysKey,
                value: val,
                image: imgMap[`${sysKey}:${val}`] || '',
                name: names[sysKey] || sysKey.toUpperCase()
            });
        }
    }
    return ratings;
}

/**
 * Get the preferred rating for a game, cross-mapping if needed.
 * Uses global RATING_IMAGE_MAP, RATING_TO_TIER, TIER_TO_RATING, RATING_SYSTEM_NAMES.
 * @param {Object} game - Game data from API
 * @returns {Object|null} {value, image, label, crossmapped} or null
 */
function _getPreferredRatingFromGame(game) {
    const pref = window.PREFERRED_RATING_SYSTEM || 'esrb';
    const imgMap = window.RATING_IMAGE_MAP || {};
    const sysNames = window.RATING_SYSTEM_NAMES || {};
    const keys = window.RATING_SYSTEM_KEYS || Object.keys(_MODAL_RATING_COLS);
    const label = sysNames[pref] || pref.toUpperCase();

    const prefCol = _MODAL_RATING_COLS[pref];
    if (prefCol && game[prefCol]) {
        return { value: game[prefCol], image: imgMap[`${pref}:${game[prefCol]}`] || '', label, crossmapped: false };
    }

    const r2t = window.RATING_TO_TIER || {};
    const t2r = window.TIER_TO_RATING || {};
    for (const sysKey of keys) {
        if (sysKey === pref) continue;
        const col = _MODAL_RATING_COLS[sysKey];
        const val = game[col];
        if (val) {
            const tier = r2t[`${sysKey}:${val}`];
            if (tier !== undefined) {
                const mapped = t2r[`${pref}:${tier}`];
                if (mapped) {
                    return { value: mapped, image: imgMap[`${pref}:${mapped}`] || '', label, crossmapped: true };
                }
            }
        }
    }
    return null;
}

/** Build age-rating badge HTML (admin sees all, users see preferred only) */
function _buildAgeRatingBadgesHtml(game) {
    let html = '';
    if (window.IS_ADMIN) {
        const allRatings = _getAllRatingsFromGame(game);
        for (const r of allRatings) {
            const tooltip = `${r.name}: ${r.value}`;
            if (r.image) {
                html += `<span class="game-badge age-rating-badge" title="${escapeHtml(tooltip)}"><img src="/static/images/ratings/${r.image}" alt="${escapeHtml(r.value)}" class="age-rating-img"></span>`;
            } else {
                html += `<span class="game-badge age-rating-badge" title="${escapeHtml(tooltip)}">${escapeHtml(r.name.split(' (')[0])} ${escapeHtml(r.value)}</span>`;
            }
        }
    } else {
        const ageRating = _getPreferredRatingFromGame(game);
        if (ageRating) {
            const tooltip = ageRating.crossmapped ? `${ageRating.label}: ${ageRating.value} (cross-mapped)` : `${ageRating.label}: ${ageRating.value}`;
            if (ageRating.image) {
                html += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${escapeHtml(tooltip)}"><img src="/static/images/ratings/${ageRating.image}" alt="${escapeHtml(ageRating.value)}" class="age-rating-img"></span>`;
            } else {
                html += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${escapeHtml(tooltip)}">${escapeHtml(ageRating.label.split(' (')[0])} ${escapeHtml(ageRating.value)}</span>`;
            }
        }
    }
    return html;
}

/**
 * Build a game detail URL with the appropriate ?from= breadcrumb param
 * based on the current page path.
 */
function gameDetailUrl(gameId) {
    const path = window.location.pathname;
    let from = '';
    if (path === '/games') from = 'library';
    else if (path.startsWith('/reports')) from = 'rom_reports';
    else if (path.startsWith('/achievements')) from = 'achievements';
    return `/game/${gameId}` + (from ? `?from=${from}` : '');
}

const GameDetailModal = {
    cache: new Map(),
    currentId: null,
    maxCacheSize: 50,
    _screenshots: [],
    _screenshotIndex: 0,

    /**
     * Open the game detail modal
     * @param {number} gameId - The game ID to display
     */
    open(gameId) {
        this.currentId = gameId;
        const modal = document.getElementById('gameDetailModal');
        const loading = document.getElementById('gameDetailLoading');
        const content = document.getElementById('gameDetailContent');

        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        loading.style.display = 'flex';
        content.style.display = 'none';

        if (window.ModalFocusTrap) {
            ModalFocusTrap.activate(modal, document.activeElement, { onEscape: () => this.close() });
        }

        if (this.cache.has(gameId)) {
            this.populate(this.cache.get(gameId));
            return;
        }

        API.get(`/api/game/${gameId}/detail`)
            .then(data => {
                if (data.success) {
                    this.cache.set(gameId, data.game);
                    if (this.cache.size > this.maxCacheSize) {
                        const firstKey = this.cache.keys().next().value;
                        this.cache.delete(firstKey);
                    }
                    this.populate(data.game);
                } else {
                    this.showError(data.error || 'Failed to load game');
                }
            })
            .catch(err => this.showError('Network error'));
    },

    /**
     * Populate the detail modal with game data
     * @param {Object} game - The game data object
     */
    populate(game) {
        const loading = document.getElementById('gameDetailLoading');
        const content = document.getElementById('gameDetailContent');

        document.getElementById('gdmTitle').textContent = game.title;
        document.getElementById('gdmSystem').textContent = game.system_name;

        const yearEl = document.getElementById('gdmYear');
        if (game.release_date) {
            yearEl.textContent = game.release_date.substring(0, 4);
            yearEl.style.display = '';
        } else {
            yearEl.style.display = 'none';
        }

        const playersEl = document.getElementById('gdmPlayers');
        if (game.players) {
            playersEl.textContent = `${game.players} Player${game.players > 1 ? 's' : ''}`;
            playersEl.style.display = '';
        } else {
            playersEl.style.display = 'none';
        }

        const boxart = document.getElementById('gdmBoxart');
        if (game.boxart) {
            boxart.src = `/static/images/boxart/${game.boxart}`;
            boxart.style.display = 'block';
        } else {
            boxart.style.display = 'none';
        }

        const desc = game.description || 'No description available.';
        document.getElementById('gdmDescription').textContent =
            desc.length > 300 ? desc.substring(0, 300) + '...' : desc;

        document.getElementById('gdmDeveloper').textContent = game.developer || '-';
        document.getElementById('gdmPublisher').textContent = game.publisher || '-';
        document.getElementById('gdmGenre').textContent = game.genre || '-';
        document.getElementById('gdmFranchise').textContent = game.franchise || '-';

        const ratingsEl = document.getElementById('gdmRatings');
        let ratingsHtml = _buildAgeRatingBadgesHtml(game);
        if (game.critic_score) {
            const scoreClass = game.critic_score >= 75 ? 'score-good' : (game.critic_score >= 50 ? 'score-mixed' : 'score-bad');
            ratingsHtml += `<span class="game-badge score-badge ${scoreClass}">⭐ ${Math.round(game.critic_score)}</span>`;
        }
        if (game.user_score) {
            const userScoreClass = game.user_score >= 75 ? 'score-good' : (game.user_score >= 50 ? 'score-mixed' : 'score-bad');
            ratingsHtml += `<span class="game-badge score-badge user-score ${userScoreClass}">👤 ${Math.round(game.user_score)}</span>`;
        }
        ratingsEl.innerHTML = ratingsHtml;

        const completionEl = document.getElementById('gdmCompletion');
        if (game.completion_status && game.completion_status !== 'not_started') {
            const completionLabels = {
                'in_progress': 'In Progress',
                'played': 'Played',
                'completed': 'Completed',
                '100_percent': '100%'
            };
            const label = completionLabels[game.completion_status] || game.completion_status;
            completionEl.innerHTML = `<span class="completion-badge status-${game.completion_status}">${label}</span>`;
            completionEl.style.display = 'block';
        } else {
            completionEl.style.display = 'none';
        }

        const raEl = document.getElementById('gdmAchievements');
        let achHtml = '';

        if (game.achievement_total > 0 && game.achievement_earned != null) {
            const earned = game.achievement_earned;
            const pct = Math.round((earned / game.achievement_total) * 100);
            const pctClass = pct >= 100 ? 'ach-complete' : pct >= 50 ? 'ach-good' : 'ach-low';
            const srcImages = { ra: '/static/images/trophies/ra.webp', steam: '/static/images/trophies/steam.png', xbox: '/static/images/trophies/xbox.png' };
            const srcLabels = { ra: 'RetroAchievements', steam: 'Steam', xbox: 'Xbox' };
            const src = game.achievement_source || 'ra';
            const iconImg = `<img class="ach-icon" src="${srcImages[src] || srcImages.ra}" alt="${srcLabels[src] || 'Achievements'}">`;
            const label = srcLabels[src] || 'Achievements';
            achHtml += `<span class="game-badge achievement-progress ${src} ${pctClass}" title="${label}: ${earned}/${game.achievement_total} (${pct}%)">${iconImg} ${earned}/${game.achievement_total}<span class="ach-bar"><span class="ach-fill" style="width:${pct}%"></span></span></span>`;
        } else if (game.has_retroachievements && game.ra_achievement_count) {
            achHtml += `<span class="ra-badge-modal">${getThemedIcon('ra-sync', '🏆')} ${formatNumber(game.ra_achievement_count)} Achievements</span>`;
        }

        if (game.psn_total > 0 && game.psn_earned != null) {
            const psnPct = Math.round((game.psn_earned / game.psn_total) * 100);
            const psnClass = psnPct >= 100 ? 'ach-complete' : psnPct >= 50 ? 'ach-good' : 'ach-low';
            achHtml += `<span class="game-badge achievement-progress psn ${psnClass}" title="PSN Trophies: ${game.psn_earned}/${game.psn_total} (${psnPct}%)"><img class="ach-icon" src="/static/images/trophies/platinum.png" alt="PSN"> ${game.psn_earned}/${game.psn_total}<span class="ach-bar"><span class="ach-fill" style="width:${psnPct}%"></span></span></span>`;
        }

        if (game.rpcs3_total > 0 && game.rpcs3_earned != null) {
            const rpcs3Pct = Math.round((game.rpcs3_earned / game.rpcs3_total) * 100);
            const rpcs3Class = rpcs3Pct >= 100 ? 'ach-complete' : rpcs3Pct >= 50 ? 'ach-good' : 'ach-low';
            achHtml += `<span class="game-badge achievement-progress rpcs3 ${rpcs3Class}" title="RPCS3 Trophies: ${game.rpcs3_earned}/${game.rpcs3_total} (${rpcs3Pct}%)"><img class="ach-icon" src="/static/images/trophies/rpcs3.png" alt="RPCS3"> ${game.rpcs3_earned}/${game.rpcs3_total}<span class="ach-bar"><span class="ach-fill" style="width:${rpcs3Pct}%"></span></span></span>`;
        }

        if (achHtml) {
            raEl.innerHTML = achHtml;
            raEl.style.display = 'flex';
        } else {
            raEl.style.display = 'none';
        }

        const ssEl = document.getElementById('gdmScreenshots');
        if (game.screenshots && game.screenshots.length > 0) {
            this._screenshots = game.screenshots.map(s =>
                `/static/images/screenshots/${encodeURIComponent(s)}`
            );
            ssEl.innerHTML = this._screenshots.map((src, i) =>
                `<img src="${src}" alt="" class="gdm-screenshot" data-index="${i}" loading="lazy" decoding="async">`
            ).join('');
            ssEl.style.display = 'flex';

            if (!ssEl._delegated) {
                ssEl.addEventListener('click', (e) => {
                    const img = e.target.closest('.gdm-screenshot');
                    if (img && img.dataset.index != null) {
                        this.openLightbox(parseInt(img.dataset.index));
                    }
                });
                ssEl._delegated = true;
            }
        } else {
            this._screenshots = [];
            ssEl.style.display = 'none';
        }

        const videoEl = document.getElementById('gdmVideo');
        const videoPlayer = document.getElementById('gdmVideoPlayer');
        if (game.video && videoEl && videoPlayer) {
            const ext = game.video.split('.').pop();
            videoPlayer.innerHTML = `<source src="/static/videos/${encodeURIComponent(game.video)}" type="video/${ext}">`;
            videoPlayer.load();
            videoEl.style.display = 'block';
        } else if (videoEl) {
            videoEl.style.display = 'none';
            if (videoPlayer) {
                videoPlayer.pause();
                videoPlayer.innerHTML = '';
            }
        }

        document.getElementById('gdmViewFull').href = gameDetailUrl(game.id);

        const aiFillBtn = document.getElementById('gdmAiFill');
        if (aiFillBtn) {
            aiFillBtn.style.display = window.AI_SCRAPER_ENABLED ? '' : 'none';
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    },

    /**
     * Show an error message in the modal
     * @param {string} message - The error message
     */
    showError(message) {
        document.getElementById('gameDetailLoading').innerHTML =
            `<p style="color: var(--neon-red);">${escapeHtml(message)}</p>
             <button class="btn btn-secondary" onclick="closeGameDetailModal()">Close</button>`;
    },

    /**
     * Open the screenshot lightbox at a given index
     * @param {number} index - Screenshot index
     */
    openLightbox(index) {
        this._screenshotIndex = index;
        this._updateLightbox();
        const lb = document.getElementById('gdmScreenshotLightbox');
        if (lb) lb.classList.add('active');
        if (window.ModalFocusTrap && lb) {
            ModalFocusTrap.activate(lb, document.activeElement, {
                onEscape: () => this.closeLightbox(),
                onArrowLeft: () => this.navigateScreenshot(-1),
                onArrowRight: () => this.navigateScreenshot(1),
            });
        }
    },

    /**
     * Close the screenshot lightbox
     */
    closeLightbox() {
        const lb = document.getElementById('gdmScreenshotLightbox');
        if (lb) lb.classList.remove('active');
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    },

    /**
     * Navigate screenshots in the lightbox
     * @param {number} direction - -1 for prev, 1 for next
     */
    navigateScreenshot(direction) {
        const newIndex = this._screenshotIndex + direction;
        if (newIndex >= 0 && newIndex < this._screenshots.length) {
            this._screenshotIndex = newIndex;
            this._updateLightbox();
        }
    },

    /**
     * Update the lightbox image and counter
     */
    _updateLightbox() {
        const img = document.getElementById('gdmLightboxImage');
        const counter = document.getElementById('gdmLightboxCounter');
        if (img) img.src = this._screenshots[this._screenshotIndex] || '';
        if (counter) counter.textContent = `${this._screenshotIndex + 1} / ${this._screenshots.length}`;

        const prev = document.querySelector('.gdm-lightbox-nav.prev');
        const next = document.querySelector('.gdm-lightbox-nav.next');
        if (prev) prev.style.opacity = this._screenshotIndex === 0 ? '0.3' : '1';
        if (next) next.style.opacity = this._screenshotIndex === this._screenshots.length - 1 ? '0.3' : '1';
    },

    /**
     * Close the detail modal
     */
    close() {
        const modal = document.getElementById('gameDetailModal');
        modal.classList.remove('active');
        document.body.style.overflow = '';
        this.currentId = null;

        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();

        const videoPlayer = document.getElementById('gdmVideoPlayer');
        if (videoPlayer) {
            videoPlayer.pause();
            videoPlayer.removeAttribute('src');
            videoPlayer.innerHTML = '';
            videoPlayer.load();  // Abort pending network request & release buffers
        }

        this.closeLightbox();
    },

    /**
     * Clear the cache (e.g., on bfcache restore)
     */
    clearCache() {
        this.cache.clear();
    }
};

const HLTBManager = {
    pendingData: {},  // Keyed by context name

    /**
     * Lookup HLTB data for a given context
     * @param {Object} ctx - Context configuration object
     */
    lookup(ctx) {
        const query = document.getElementById(ctx.searchInputId)?.value?.trim();
        if (!query) {
            showNotification('Please enter a game title', 'warning');
            return;
        }

        const btn = document.getElementById(ctx.lookupBtnId);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '⏳ Searching...';
        }

        const pendingDiv = document.getElementById(ctx.pendingDivId);
        const savedDiv = document.getElementById(ctx.savedDivId);
        const searchingDiv = document.getElementById(ctx.searchingDivId);
        const resultDiv = document.getElementById(ctx.resultDivId);
        const errorDiv = document.getElementById(ctx.errorDivId);

        if (pendingDiv) pendingDiv.style.display = 'block';
        if (savedDiv) savedDiv.style.display = 'none';
        if (searchingDiv) searchingDiv.style.display = 'flex';
        if (resultDiv) resultDiv.style.display = 'none';
        if (errorDiv) errorDiv.style.display = 'none';

        API.post('/api/hltb/search', {
            query: query,
            system_folder: ctx.systemFolder || '',
            year: ctx.year || '',
            game_id: ctx.gameId || null
        })
        .then(data => {
            if (searchingDiv) searchingDiv.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🔍 Lookup HLTB';
            }

            if (data.success && data.result) {
                HLTBManager.pendingData[ctx.name] = {
                    hltb_id: data.result.hltb_id || null,
                    match_name: data.result.match_name || query,
                    match_platform: data.result.match_platform || '',
                    confidence: data.result.confidence || 0,
                    platform_mismatch: data.result.platform_mismatch || false,
                    main_story: data.result.main_story || '--',
                    main_extra: data.result.main_extra || '--',
                    completionist: data.result.completionist || '--',
                    release_year: data.result.release_year || null,
                    developer: data.result.developer || null,
                    search_term_used: data.result.search_term_used || null,
                    matched_via_alternate: !!data.result.matched_via_alternate
                };

                const pending = HLTBManager.pendingData[ctx.name];
                const confidence = Math.round(pending.confidence);

                const matchTitle = document.getElementById(ctx.matchTitleId);
                const matchPlatform = document.getElementById(ctx.matchPlatformId);
                const matchConfidence = document.getElementById(ctx.matchConfidenceId);
                const matchHeader = document.getElementById(ctx.matchHeaderId);

                if (matchTitle) matchTitle.textContent = pending.match_name;
                if (matchPlatform) matchPlatform.textContent = pending.match_platform;
                if (matchConfidence) matchConfidence.textContent = confidence > 0 ? `${confidence}% match` : '';

                if (matchHeader) {
                    let headerHtml = `<span class="hltb-match-title">${escapeHtml(pending.match_name)}</span>`;
                    if (pending.match_platform) {
                        headerHtml += `<span class="hltb-match-platform">${escapeHtml(pending.match_platform)}</span>`;
                    }
                    if (pending.platform_mismatch) {
                        headerHtml += `<span class="hltb-match-warning">Platform not found</span>`;
                    }
                    if (pending.release_year) {
                        headerHtml += `<span class="hltb-match-year">${escapeHtml(String(pending.release_year))}</span>`;
                    }
                    if (pending.developer) {
                        headerHtml += `<span class="hltb-match-developer">${escapeHtml(pending.developer)}</span>`;
                    }
                    if (confidence > 0) {
                        headerHtml += `<span class="hltb-match-confidence">${confidence}% match</span>`;
                    }
                    if (pending.matched_via_alternate && pending.search_term_used) {
                        headerHtml += `<span class="hltb-match-alt-notice" title="Matched using this alternate/regional title — confirm it refers to the same game before saving.">⚡ via &ldquo;${escapeHtml(pending.search_term_used)}&rdquo;</span>`;
                    }
                    matchHeader.innerHTML = headerHtml;
                }

                const mainEl = document.getElementById(ctx.mainTimeId);
                const extrasEl = document.getElementById(ctx.extrasTimeId);
                const completeEl = document.getElementById(ctx.completeTimeId);

                if (mainEl) mainEl.textContent = pending.main_story;
                if (extrasEl) extrasEl.textContent = pending.main_extra;
                if (completeEl) completeEl.textContent = pending.completionist;

                if (resultDiv) resultDiv.style.display = 'block';
                if (pending.matched_via_alternate && pending.search_term_used) {
                    showNotification(
                        `Matched via alternate title "${pending.search_term_used}" — HLTB shows it as "${pending.match_name}". Confirm before saving.`,
                        'warning',
                        9000
                    );
                } else {
                    showNotification('Match found - please confirm to save', 'info');
                }
            } else {
                if (pendingDiv && !resultDiv) pendingDiv.style.display = 'none';
                if (errorDiv) {
                    errorDiv.textContent = data.error || 'No results found on HowLongToBeat';
                    errorDiv.style.display = 'block';
                } else {
                    showNotification(data.error || 'No HLTB data found', 'warning');
                }
            }
        })
        .catch(err => {
            if (searchingDiv) searchingDiv.style.display = 'none';
            if (pendingDiv && !resultDiv) pendingDiv.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🔍 Lookup HLTB';
            }
            if (errorDiv) {
                errorDiv.textContent = 'Error connecting to HowLongToBeat';
                errorDiv.style.display = 'block';
            } else {
                showNotification('Error looking up HLTB', 'error');
            }
        });
    },

    /**
     * Save pending HLTB data
     * @param {Object} ctx - Context configuration object
     */
    save(ctx) {
        const pending = HLTBManager.pendingData[ctx.name];
        if (!pending) return;

        const playtime = `Main: ${pending.main_story} | Main+Extras: ${pending.main_extra} | 100%: ${pending.completionist}`;

        const savePromise = ctx.customSave
            ? ctx.customSave(pending, playtime)
            : API.post(`/api/hltb-save/${ctx.gameId}`, {
                playtime: playtime,
                match_name: pending.match_name,
                match_platform: pending.match_platform,
                confidence: pending.confidence
            });

        savePromise
        .then(data => {
            if (data.success) {
                HLTBManager.updateSavedDisplay(ctx, pending);

                const pendingDiv = document.getElementById(ctx.pendingDivId);
                const savedDiv = document.getElementById(ctx.savedDivId);
                if (pendingDiv) pendingDiv.style.display = 'none';
                if (savedDiv) savedDiv.style.display = 'block';

                if (ctx.onSave) ctx.onSave(pending, playtime);

                HLTBManager.pendingData[ctx.name] = null;
                showNotification('HLTB data saved', 'success');
            } else {
                showNotification('Failed to save HLTB: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(err => showNotification('Error saving HLTB data', 'error'));
    },

    /**
     * Update the saved display section
     * @param {Object} ctx - Context configuration object
     * @param {Object} data - HLTB data to display
     */
    updateSavedDisplay(ctx, data) {
        const savedDiv = document.getElementById(ctx.savedDivId);
        if (!savedDiv || !data) return;

        const confidence = Math.round(data.confidence || 0);
        let headerHtml = '';
        if (data.match_name) {
            headerHtml = `<div class="hltb-match-header">
                <span class="hltb-match-title">${escapeHtml(data.match_name)}</span>
                ${data.match_platform ? `<span class="hltb-match-platform">${escapeHtml(data.match_platform)}</span>` : ''}
                ${data.platform_mismatch ? `<span class="hltb-match-warning">Platform not found</span>` : ''}
                ${data.release_year ? `<span class="hltb-match-year">${escapeHtml(String(data.release_year))}</span>` : ''}
                ${data.developer ? `<span class="hltb-match-developer">${escapeHtml(data.developer)}</span>` : ''}
                ${confidence > 0 ? `<span class="hltb-match-confidence">${confidence}% match</span>` : ''}
            </div>`;
        }

        savedDiv.innerHTML = `
            ${headerHtml}
            <div class="hltb-results">
                <div class="hltb-time-row">
                    <span class="hltb-label">Main Story</span>
                    <span class="hltb-value">${data.main_story ? escapeHtml(String(data.main_story)) : '--'}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Main + Extras</span>
                    <span class="hltb-value">${data.main_extra ? escapeHtml(String(data.main_extra)) : '--'}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Completionist</span>
                    <span class="hltb-value">${data.completionist ? escapeHtml(String(data.completionist)) : '--'}</span>
                </div>
            </div>
            <div class="hltb-actions" style="margin-top: var(--spacing-sm);">
                <button class="btn btn-sm btn-danger" data-hltb-clear>✕ Clear</button>
            </div>
        `;
        const clearBtn = savedDiv.querySelector('[data-hltb-clear]');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                const fn = window[ctx.clearFnName];
                if (typeof fn === 'function') {
                    fn();
                } else {
                    HLTBManager.clear(ctx);
                }
            });
        }
    },

    /**
     * Cancel pending lookup
     * @param {Object} ctx - Context configuration object
     */
    cancel(ctx) {
        HLTBManager.pendingData[ctx.name] = null;
        const pendingDiv = document.getElementById(ctx.pendingDivId);
        const savedDiv = document.getElementById(ctx.savedDivId);
        if (pendingDiv) pendingDiv.style.display = 'none';
        if (ctx.hasSavedData && savedDiv) savedDiv.style.display = 'block';
        showNotification('HLTB lookup cancelled', 'info');
    },

    /**
     * Clear saved HLTB data
     * @param {Object} ctx - Context configuration object
     */
    clear(ctx) {
        showConfirm('🗑️ Clear HLTB Data', 'Clear HLTB data for this game?', () => {
            const clearPromise = ctx.customClear
                ? ctx.customClear()
                : API.post(`/api/hltb-clear/${ctx.gameId}`);

            clearPromise
            .then(data => {
                if (data.success) {
                    const savedDiv = document.getElementById(ctx.savedDivId);
                    if (savedDiv) savedDiv.style.display = 'none';
                    if (ctx.onClear) ctx.onClear();
                    showNotification('HLTB data cleared', 'success');
                } else {
                    showNotification('Failed to clear HLTB: ' + (data.error || 'Unknown error'), 'error');
                }
            })
            .catch(err => showNotification('Error clearing HLTB data', 'error'));
        });
    }
};

const GameEditModal = {
    currentData: null,
    pendingHltbData: null,
    _dropdownAbortController: null,

    genreOptions: [],
    modesOptions: [],
    saveTypeOptions: [],
    gameStructureOptions: [],
    perspectiveOptions: [],
    dimensionOptions: [],
    controllerOptions: { defaults: [], others: [] },

    hltbContext: {
        name: 'gem',
        searchInputId: 'gemHltbSearchQuery',
        lookupBtnId: 'gemHltbLookupBtn',
        pendingDivId: 'gemHltbPending',
        savedDivId: 'gemHltbSaved',
        searchingDivId: 'gemHltbSearching',
        resultDivId: 'gemHltbResult',
        errorDivId: 'gemHltbError',
        matchTitleId: 'gemHltbMatchTitle',
        matchPlatformId: 'gemHltbMatchPlatform',
        matchConfidenceId: 'gemHltbMatchConfidence',
        mainTimeId: 'gemHltbMain',
        extrasTimeId: 'gemHltbExtras',
        completeTimeId: 'gemHltbComplete',
        clearFnName: 'clearHltbFromModal',
        get gameId() { return GameEditModal.currentData?.id; },
        get systemFolder() { return GameEditModal.currentData?.system_folder || ''; },
        get year() { const rd = GameEditModal.currentData?.release_date; return rd ? rd.substring(0, 4) : ''; },
        get hasSavedData() { return !!GameEditModal.currentData?.playtime_estimate; },
        onSave: function(pending, playtime) {
            if (GameEditModal.currentData) {
                GameEditModal.currentData.playtime_estimate = playtime;
                GameEditModal.currentData.hltb_match_name = pending.match_name;
                GameEditModal.currentData.hltb_match_platform = pending.match_platform;
                GameEditModal.currentData.hltb_match_confidence = pending.confidence;
                GameDetailModal.cache.set(GameEditModal.currentData.id, GameEditModal.currentData);
            }
        },
        onClear: function() {
            if (GameEditModal.currentData) {
                GameEditModal.currentData.playtime_estimate = null;
                GameEditModal.currentData.hltb_match_name = null;
                GameEditModal.currentData.hltb_match_platform = null;
                GameEditModal.currentData.hltb_match_confidence = null;
                GameDetailModal.cache.set(GameEditModal.currentData.id, GameEditModal.currentData);
            }
        }
    },

    /**
     * Open the game edit modal
     */
    open() {
        if (!GameDetailModal.currentId) return;

        const editModal = document.getElementById('gameEditModal');
        const game = GameDetailModal.cache.get(GameDetailModal.currentId);

        if (!game) {
            console.error('Game data not in cache');
            return;
        }

        if (this._dropdownAbortController) this._dropdownAbortController.abort();
        this._dropdownAbortController = new AbortController();

        this.currentData = game;

        document.getElementById('gemTitle').textContent = `Edit: ${game.title}`;

        this.switchTab('quick');

        const completionSelect = document.getElementById('gemCompletionStatus');
        completionSelect.value = game.completion_status || 'not_started';

        this.updateHltbDisplay(game);

        document.getElementById('gemTitle_field').value = game.title || '';
        document.getElementById('gemSortTitle').value = game.sort_title || '';
        document.getElementById('gemFranchise').value = game.franchise || '';
        this.initFranchiseToggle(game.franchise || '');
        document.getElementById('gemSimilarGames').value = game.similar_games || '';
        document.getElementById('gemEdition').value = game.edition || '';

        document.getElementById('gemReleaseDate').value = game.release_date || '';
        document.getElementById('gemRegion').value = game.region || '';
        document.getElementById('gemPublisher').value = game.publisher || '';
        document.getElementById('gemDeveloper').value = game.developer || '';

        this.initGenreTags(game.genre || '');
        this.loadGenreDropdown();
        this.initModesTags(game.modes || '');
        this.loadModesDropdown();
        document.getElementById('gemPlayers').value = game.players || 1;
        this.initGameStructureTags(game.game_structure || '');
        this.loadGameStructureDropdown();
        this.initPerspectiveTags(game.perspective || '');
        this.loadPerspectiveDropdown();
        this.initDimensionTags(game.dimension || '');
        this.loadDimensionDropdown();
        this.initCampaignToggle(game.campaign);

        this.initControllerTags(game.controller_support || '');
        this.loadControllerDropdown(game.system_id);
        this.initSaveTypeTags(game.save_type || '');
        this.loadSaveTypeDropdown();
        this.initExclusiveToggle(game.other_platforms || '');
        document.getElementById('gemEsrbRating').value = game.esrb_rating || '';
        document.getElementById('gemPegiRating').value = game.pegi_rating || '';
        document.getElementById('gemCeroRating').value = game.cero_rating || '';
        document.getElementById('gemUskRating').value = game.usk_rating || '';
        document.getElementById('gemAcbRating').value = game.acb_rating || '';
        document.getElementById('gemFpbRating').value = game.fpb_rating || '';
        document.getElementById('gemGracRating').value = game.grac_rating || '';
        document.getElementById('gemClassindRating').value = game.classind_rating || '';

        document.getElementById('gemDescription').value = game.description || '';

        document.getElementById('gemFullEdit').href = gameDetailUrl(game.id);

        document.getElementById('gemHltbSearchQuery').value = game.title || '';
        document.getElementById('gemHltbPending').style.display = 'none';
        document.getElementById('gemHltbLookupBtn').disabled = false;
        document.getElementById('gemHltbLookupBtn').innerHTML = '🔍 Lookup HLTB';
        this.pendingHltbData = null;

        editModal.classList.add('active');

        if (window.ModalFocusTrap) {
            ModalFocusTrap.activate(editModal, document.activeElement, { onEscape: () => this.close() });
        }
    },

    /**
     * Switch to a specific tab
     * @param {string} tabId - The tab ID to switch to
     */
    switchTab(tabId) {
        document.querySelectorAll('.gem-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabId);
        });

        document.querySelectorAll('.gem-tab-content').forEach(content => {
            content.classList.toggle('active', content.id === 'gemTab' + tabId.charAt(0).toUpperCase() + tabId.slice(1));
        });
    },

    /**
     * Generate sort title from title
     */
    generateSortTitle() {
        const titleField = document.getElementById('gemTitle_field');
        const sortTitleField = document.getElementById('gemSortTitle');

        if (!titleField.value) return;

        let sortTitle = titleField.value.trim();

        const articles = ['the ', 'a ', 'an '];
        const lowerTitle = sortTitle.toLowerCase();
        for (const article of articles) {
            if (lowerTitle.startsWith(article)) {
                sortTitle = sortTitle.substring(article.length);
                break;
            }
        }

        const romanMap = [
            ['XVIII', '18'],
            ['XVII', '17'], ['XIII', '13'], ['VIII', '8'],
            ['XVI', '16'], ['XIV', '14'], ['XII', '12'], ['XIX', '19'], ['VII', '7'], ['III', '3'],
            ['XV', '15'], ['XI', '11'], ['XX', '20'], ['VI', '6'], ['IV', '4'], ['IX', '9'], ['II', '2'],
            ['X', '10'], ['V', '5'], ['I', '1']
        ];

        const singleLetterRomans = new Set(['I', 'V', 'X']);

        for (const [roman, arabic] of romanMap) {
            const padded = arabic.padStart(2, '0');
            if (singleLetterRomans.has(roman)) {
                sortTitle = sortTitle.replace(new RegExp('(?<![-\\w])' + roman + '(?![-\\w])', 'g'), padded);
            } else {
                sortTitle = sortTitle.replace(new RegExp('\\b' + roman + '\\b', 'g'), padded);
            }
        }

        sortTitle = sortTitle.replace(/\b(\d+)\b/g, (match) => {
            return match.length === 1 ? match.padStart(2, '0') : match;
        });

        sortTitleField.value = sortTitle;
    },

    /**
     * Save game edits
     */
    save() {
        if (!this.currentData) return;

        const formData = {
            title: document.getElementById('gemTitle_field').value.trim(),
            sort_title: document.getElementById('gemSortTitle').value.trim(),
            franchise: document.getElementById('gemFranchise').value.trim(),
            similar_games: document.getElementById('gemSimilarGames').value.trim(),
            edition: document.getElementById('gemEdition').value.trim(),
            release_date: document.getElementById('gemReleaseDate').value.trim(),
            region: document.getElementById('gemRegion').value.trim(),
            publisher: document.getElementById('gemPublisher').value.trim(),
            developer: document.getElementById('gemDeveloper').value.trim(),
            genre: document.getElementById('gemGenreHidden').value.trim(),
            modes: document.getElementById('gemModesHidden').value.trim(),
            players: parseInt(document.getElementById('gemPlayers').value) || 1,
            game_structure: document.getElementById('gemGameStructureHidden').value.trim(),
            perspective: document.getElementById('gemPerspectiveHidden').value.trim(),
            dimension: document.getElementById('gemDimensionHidden').value.trim(),
            campaign: document.getElementById('gemCampaign').value,
            controller_support: document.getElementById('gemControllerHidden').value.trim(),
            save_type: document.getElementById('gemSaveTypeHidden').value.trim(),
            other_platforms: this.getOtherPlatformsValue(),
            esrb_rating: document.getElementById('gemEsrbRating').value,
            pegi_rating: document.getElementById('gemPegiRating').value,
            cero_rating: document.getElementById('gemCeroRating').value,
            usk_rating: document.getElementById('gemUskRating').value,
            acb_rating: document.getElementById('gemAcbRating').value,
            fpb_rating: document.getElementById('gemFpbRating').value,
            grac_rating: document.getElementById('gemGracRating').value,
            classind_rating: document.getElementById('gemClassindRating').value,
            description: document.getElementById('gemDescription').value.trim()
        };

        const saveBtn = document.querySelector('.gem-footer-right .btn-primary');
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="btn-icon">⏳</span> Saving...';
        saveBtn.disabled = true;

        API.post(`/api/game/${this.currentData.id}/edit`, formData)
        .then(data => {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;

            if (data.success) {
                GameDetailModal.cache.delete(this.currentData.id);

                document.getElementById('gdmTitle').textContent = formData.title;
                document.getElementById('gdmDeveloper').textContent = formData.developer || '-';
                document.getElementById('gdmPublisher').textContent = formData.publisher || '-';
                document.getElementById('gdmGenre').textContent = formData.genre || '-';
                document.getElementById('gdmFranchise').textContent = formData.franchise || '-';

                if (formData.description) {
                    const desc = formData.description;
                    document.getElementById('gdmDescription').textContent =
                        desc.length > 300 ? desc.substring(0, 300) + '...' : desc;
                }

                const ratingsEl = document.getElementById('gdmRatings');
                let ratingsHtml = _buildAgeRatingBadgesHtml(formData);
                if (this.currentData.critic_score) {
                    const scoreClass = this.currentData.critic_score >= 75 ? 'score-good' : (this.currentData.critic_score >= 50 ? 'score-mixed' : 'score-bad');
                    ratingsHtml += `<span class="game-badge score-badge ${scoreClass}">⭐ ${Math.round(this.currentData.critic_score)}</span>`;
                }
                ratingsEl.innerHTML = ratingsHtml;

                if (typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
                    AllGamesController.refreshCards(this.currentData.id);
                }

                this.close();

                const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ save: '✅', error: '❌' }[k] || k);
                if (typeof showModal === 'function') {
                    showModal(`${_ti('save')} Saved`, 'Game details updated successfully.');
                }
            } else {
                const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ error: '❌' }[k] || k);
                showModal(`${_ti('error')} Save Failed`, 'Failed to save: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
            const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ error: '❌' }[k] || k);
            showModal(`${_ti('error')} Error`, 'Error saving game: ' + err.message);
        });
    },

    /**
     * Close the edit modal
     */
    close() {
        const editModal = document.getElementById('gameEditModal');
        editModal.classList.remove('active');
        this.currentData = null;
        this.pendingHltbData = null;
        if (this._dropdownAbortController) {
            this._dropdownAbortController.abort();
            this._dropdownAbortController = null;
        }
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    },

    /**
     * Update the game card in the page after saving
     * @param {number} gameId - The game ID
     * @param {Object} formData - The updated form data
     */
    updateGameCardInPage(gameId, formData) {
        const card = document.querySelector(`.game-card-new[data-game-id="${gameId}"]`);
        if (!card) return;

        const titleEl = card.querySelector('.game-card-title');
        if (titleEl && formData.title) {
            titleEl.textContent = formData.title;
        }

        card.querySelectorAll('.meta-item').forEach(item => {
            const label = item.querySelector('.meta-label');
            const value = item.querySelector('.meta-value');
            if (!label || !value) return;

            const labelText = label.textContent;
            if (labelText === 'Genre' && formData.genre !== undefined) {
                if (formData.genre) {
                    value.textContent = formData.genre.split(',')[0].trim();
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Series' && formData.franchise !== undefined) {
                if (formData.franchise) {
                    value.textContent = formData.franchise.substring(0, 20) + (formData.franchise.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Developer' && formData.developer !== undefined) {
                if (formData.developer) {
                    const dev = formData.developer.split(',')[0].trim();
                    value.textContent = dev.substring(0, 20) + (dev.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Publisher' && formData.publisher !== undefined) {
                if (formData.publisher) {
                    const pub = formData.publisher.split(',')[0].trim();
                    value.textContent = pub.substring(0, 20) + (pub.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            }
        });

        const existingAgeBadge = card.querySelector('.game-badge.age-rating-badge');
        const updatedRating = _getPreferredRatingFromGame(formData);
        if (updatedRating) {
            const tooltip = updatedRating.crossmapped ? `${updatedRating.label}: ${updatedRating.value} (cross-mapped)` : `${updatedRating.label}: ${updatedRating.value}`;
            let badgeHtml;
            if (updatedRating.image) {
                badgeHtml = `<img src="/static/images/ratings/${updatedRating.image}" alt="${escapeHtml(updatedRating.value)}" class="age-rating-img">`;
            } else {
                badgeHtml = `${escapeHtml(updatedRating.label.split(' (')[0])} ${escapeHtml(updatedRating.value)}`;
            }
            if (existingAgeBadge) {
                existingAgeBadge.className = `game-badge age-rating-badge${updatedRating.crossmapped ? ' crossmapped' : ''}`;
                existingAgeBadge.title = tooltip;
                existingAgeBadge.innerHTML = badgeHtml;
            } else {
                const badgeContainer = card.querySelector('.rating-badges');
                if (badgeContainer) {
                    const completionBadge = badgeContainer.querySelector('.game-badge.completion');
                    const newBadge = document.createElement('span');
                    newBadge.className = `game-badge age-rating-badge${updatedRating.crossmapped ? ' crossmapped' : ''}`;
                    newBadge.title = tooltip;
                    newBadge.innerHTML = badgeHtml;
                    if (completionBadge) {
                        completionBadge.after(newBadge);
                    } else {
                        badgeContainer.insertBefore(newBadge, badgeContainer.firstChild);
                    }
                }
            }
        } else if (existingAgeBadge) {
            existingAgeBadge.remove();
        }

        if (typeof window.relayoutMasonry === 'function') {
            requestAnimationFrame(() => window.relayoutMasonry());
        }
    },

    /**
     * Update HLTB display in the edit modal
     * @param {Object} game - The game data
     */
    updateHltbDisplay(game) {
        const savedDiv = document.getElementById('gemHltbSaved');
        let display = document.getElementById('gemHltbDisplay');

        if (!display && savedDiv) {
            savedDiv.innerHTML = `
                <div id="gemHltbDisplay" class="hltb-compact"></div>
                <div class="hltb-actions" style="margin-top: var(--spacing-sm);">
                    <button class="btn btn-danger btn-sm" onclick="clearHltbFromModal()">✕ Clear</button>
                </div>`;
            display = document.getElementById('gemHltbDisplay');
        }

        if (!display || !savedDiv) return;

        if (game.playtime_estimate) {
            const parts = game.playtime_estimate.split(' | ');
            const times = { main: '--', extras: '--', complete: '--' };

            parts.forEach(part => {
                const [key, val] = part.split(': ');
                if (key === 'Main') times.main = val;
                else if (key === 'Main+Extras') times.extras = val;
                else if (key === '100%') times.complete = val;
            });

            let matchHeader = '';
            if (game.hltb_match_name) {
                const confidence = game.hltb_match_confidence ? Math.min(Math.round(game.hltb_match_confidence * 100), 100) : null;
                matchHeader = `
                    <div class="hltb-match-header">
                        <span class="hltb-match-title">${escapeHtml(game.hltb_match_name)}</span>
                        ${game.hltb_match_platform ? `<span class="hltb-match-platform">${escapeHtml(game.hltb_match_platform)}</span>` : ''}
                        ${confidence ? `<span class="hltb-match-confidence">${confidence}% match</span>` : ''}
                    </div>`;
            }

            display.innerHTML = `
                ${matchHeader}
                <div class="hltb-time-row">
                    <span class="hltb-label">Main Story</span>
                    <span class="hltb-value">${escapeHtml(times.main)}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Main + Extras</span>
                    <span class="hltb-value">${escapeHtml(times.extras)}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Completionist</span>
                    <span class="hltb-value">${escapeHtml(times.complete)}</span>
                </div>`;
            savedDiv.style.display = 'block';
        } else {
            display.innerHTML = '<div class="hltb-empty">No playtime data</div>';
            savedDiv.style.display = 'none';
        }
    },

    /**
     * Update game completion status
     */
    updateCompletion() {
        if (!this.currentData) return;

        const status = document.getElementById('gemCompletionStatus').value;

        API.post(`/api/game/${this.currentData.id}/completion`, { status: status })
        .then(data => {
            if (data.success) {
                this.currentData.completion_status = status;
                GameDetailModal.cache.set(this.currentData.id, this.currentData);

                const completionEl = document.getElementById('gdmCompletion');
                const labels = {
                    'in_progress': 'In Progress',
                    'played': 'Played',
                    'completed': 'Completed',
                    '100_percent': '100%'
                };
                const emojis = {
                    'in_progress': '🎮',
                    'played': '🕹️',
                    'completed': '✅',
                    '100_percent': '🏆'
                };
                if (status && status !== 'not_started') {
                    completionEl.innerHTML = `<span class="completion-badge status-${status}">${labels[status] || status}</span>`;
                    completionEl.style.display = 'block';
                } else {
                    completionEl.style.display = 'none';
                }

                const card = document.querySelector(`.game-card-new[data-game-id="${this.currentData.id}"]`);
                if (card) {
                    const badgeContainer = card.querySelector('.rating-badges');
                    let completionBadge = card.querySelector('.game-badge.completion');

                    if (status && status !== 'not_started') {
                        const statusClass = status === '100_percent' ? 'hundred-percent' : status.replace('_', '-');
                        const badgeContent = `${emojis[status]} ${labels[status]}`;

                        if (completionBadge) {
                            completionBadge.className = `game-badge completion ${statusClass}`;
                            completionBadge.textContent = badgeContent;
                        } else if (badgeContainer) {
                            completionBadge = document.createElement('span');
                            completionBadge.className = `game-badge completion ${statusClass}`;
                            completionBadge.title = 'Completion Status';
                            completionBadge.textContent = badgeContent;
                            badgeContainer.insertBefore(completionBadge, badgeContainer.firstChild);
                        }
                    } else if (completionBadge) {
                        completionBadge.remove();
                    }
                }
            } else {
                const _ei = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
                showModal(`${_ei} Update Failed`, 'Failed to update completion status: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            const _ei = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
            showModal(`${_ei} Error`, 'Error updating completion status');
        });
    },

    _createTag(container, className, value, onRemove) {
        const tag = document.createElement('span');
        tag.className = className;
        tag.textContent = value + ' ';
        const btn = document.createElement('span');
        btn.className = className === 'controller-tag' ? 'remove-controller' : 'remove-genre';
        btn.textContent = '×';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            onRemove();
        });
        tag.appendChild(btn);
        container.appendChild(tag);
    },

    loadGenreDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/genre', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.genreOptions = data.options;
                    this.updateGenreDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load genres:', err); });
    },

    updateGenreDropdown() {
        const dropdown = document.getElementById('gemGenreDropdown');
        const currentGenres = document.getElementById('gemGenreHidden').value.split(',').map(g => g.trim().toLowerCase()).filter(g => g);

        dropdown.innerHTML = '<option value="">+ Add genre...</option>';
        this.genreOptions.forEach(opt => {
            const genreValue = opt.value || opt;
            if (!currentGenres.includes(genreValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = genreValue;
                option.textContent = genreValue;
                dropdown.appendChild(option);
            }
        });
    },

    initGenreTags(genreString) {
        const container = document.getElementById('gemGenreContainer');
        const hidden = document.getElementById('gemGenreHidden');
        container.innerHTML = '';
        hidden.value = genreString;

        if (!genreString) return;

        genreString.split(',').forEach(genre => {
            genre = genre.trim();
            if (genre) {
                this._createTag(container, 'genre-tag', genre, () => this.removeGenre(genre));
            }
        });
    },

    addGenre(genre) {
        if (!genre) return;

        const hidden = document.getElementById('gemGenreHidden');
        const container = document.getElementById('gemGenreContainer');
        const currentGenres = hidden.value ? hidden.value.split(',').map(g => g.trim()) : [];

        if (currentGenres.some(g => g.toLowerCase() === genre.toLowerCase())) return;

        currentGenres.push(genre);
        hidden.value = currentGenres.join(', ');

        this._createTag(container, 'genre-tag', genre, () => this.removeGenre(genre));

        this.updateGenreDropdown();
    },

    removeGenre(genre) {
        const hidden = document.getElementById('gemGenreHidden');
        const container = document.getElementById('gemGenreContainer');

        const currentGenres = hidden.value.split(',').map(g => g.trim()).filter(g => g.toLowerCase() !== genre.toLowerCase());
        hidden.value = currentGenres.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === genre.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateGenreDropdown();
    },

    loadModesDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/game_modes', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.modesOptions = data.options;
                    this.updateModesDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load game modes:', err); });
    },

    updateModesDropdown() {
        const dropdown = document.getElementById('gemModesDropdown');
        const currentModes = document.getElementById('gemModesHidden').value.split(',').map(m => m.trim().toLowerCase()).filter(m => m);

        dropdown.innerHTML = '<option value="">+ Add mode...</option>';
        this.modesOptions.forEach(opt => {
            const modeValue = opt.value || opt;
            if (!currentModes.includes(modeValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = modeValue;
                option.textContent = modeValue;
                dropdown.appendChild(option);
            }
        });
    },

    initModesTags(modesString) {
        const container = document.getElementById('gemModesContainer');
        const hidden = document.getElementById('gemModesHidden');
        container.innerHTML = '';
        hidden.value = modesString;

        if (!modesString) return;

        modesString.split(',').forEach(mode => {
            mode = mode.trim();
            if (mode) {
                this._createTag(container, 'genre-tag', mode, () => this.removeMode(mode));
            }
        });
    },

    addMode(mode) {
        if (!mode) return;

        const hidden = document.getElementById('gemModesHidden');
        const container = document.getElementById('gemModesContainer');
        const currentModes = hidden.value ? hidden.value.split(',').map(m => m.trim()) : [];

        if (currentModes.some(m => m.toLowerCase() === mode.toLowerCase())) return;

        currentModes.push(mode);
        hidden.value = currentModes.join(', ');

        this._createTag(container, 'genre-tag', mode, () => this.removeMode(mode));

        this.updateModesDropdown();
    },

    removeMode(mode) {
        const hidden = document.getElementById('gemModesHidden');
        const container = document.getElementById('gemModesContainer');

        const currentModes = hidden.value.split(',').map(m => m.trim()).filter(m => m.toLowerCase() !== mode.toLowerCase());
        hidden.value = currentModes.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === mode.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateModesDropdown();
    },

    loadSaveTypeDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/save_type', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.saveTypeOptions = data.options;
                    this.updateSaveTypeDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load save types:', err); });
    },

    updateSaveTypeDropdown() {
        const dropdown = document.getElementById('gemSaveTypeDropdown');
        const currentSaveTypes = document.getElementById('gemSaveTypeHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add save type...</option>';
        this.saveTypeOptions.forEach(opt => {
            const saveTypeValue = opt.value || opt;
            if (!currentSaveTypes.includes(saveTypeValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = saveTypeValue;
                option.textContent = saveTypeValue;
                dropdown.appendChild(option);
            }
        });
    },

    initSaveTypeTags(saveTypeString) {
        const container = document.getElementById('gemSaveTypeContainer');
        const hidden = document.getElementById('gemSaveTypeHidden');
        container.innerHTML = '';
        hidden.value = saveTypeString;

        if (!saveTypeString) return;

        saveTypeString.split(',').forEach(saveType => {
            saveType = saveType.trim();
            if (saveType) {
                this._createTag(container, 'genre-tag', saveType, () => this.removeSaveType(saveType));
            }
        });
    },

    addSaveType(saveType) {
        if (!saveType) return;

        const hidden = document.getElementById('gemSaveTypeHidden');
        const container = document.getElementById('gemSaveTypeContainer');
        const currentSaveTypes = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentSaveTypes.some(s => s.toLowerCase() === saveType.toLowerCase())) return;

        currentSaveTypes.push(saveType);
        hidden.value = currentSaveTypes.join(', ');

        this._createTag(container, 'genre-tag', saveType, () => this.removeSaveType(saveType));

        this.updateSaveTypeDropdown();
    },

    removeSaveType(saveType) {
        const hidden = document.getElementById('gemSaveTypeHidden');
        const container = document.getElementById('gemSaveTypeContainer');

        const currentSaveTypes = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== saveType.toLowerCase());
        hidden.value = currentSaveTypes.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === saveType.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateSaveTypeDropdown();
    },

    loadControllerDropdown(systemId) {
        if (!systemId) return;

        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get(`/api/systems/${systemId}/controllers`, { signal })
            .then(data => {
                if (data.success) {
                    this.controllerOptions.defaults = data.default_controllers || [];
                    this.controllerOptions.others = data.controllers || [];
                    this.updateControllerDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load controllers:', err); });
    },

    updateControllerDropdown() {
        const dropdown = document.getElementById('gemControllerDropdown');
        const currentControllers = document.getElementById('gemControllerHidden').value.split(',').map(c => c.trim().toLowerCase()).filter(c => c);

        dropdown.innerHTML = '<option value="">+ Add controller...</option>';

        const getCtrlName = (ctrl) => {
            if (typeof ctrl === 'string') return ctrl;
            return ctrl.name || '';
        };

        const defaultNames = this.controllerOptions.defaults.map(d => getCtrlName(d).toLowerCase());

        if (this.controllerOptions.defaults.length > 0) {
            const defGroup = document.createElement('optgroup');
            defGroup.label = '★ System Defaults';
            this.controllerOptions.defaults.forEach(ctrl => {
                const ctrlName = getCtrlName(ctrl);
                if (ctrlName && !currentControllers.includes(ctrlName.toLowerCase())) {
                    const opt = document.createElement('option');
                    opt.value = ctrlName;
                    opt.textContent = ctrlName;
                    defGroup.appendChild(opt);
                }
            });
            if (defGroup.children.length > 0) dropdown.appendChild(defGroup);
        }

        if (this.controllerOptions.others.length > 0) {
            const otherGroup = document.createElement('optgroup');
            otherGroup.label = 'Other Controllers';
            this.controllerOptions.others.forEach(ctrl => {
                const ctrlName = getCtrlName(ctrl);
                if (ctrlName && !currentControllers.includes(ctrlName.toLowerCase()) &&
                    !defaultNames.includes(ctrlName.toLowerCase())) {
                    const opt = document.createElement('option');
                    opt.value = ctrlName;
                    opt.textContent = ctrlName;
                    otherGroup.appendChild(opt);
                }
            });
            if (otherGroup.children.length > 0) dropdown.appendChild(otherGroup);
        }
    },

    initControllerTags(controllerString) {
        const container = document.getElementById('gemControllerContainer');
        const hidden = document.getElementById('gemControllerHidden');
        container.innerHTML = '';
        hidden.value = controllerString;

        if (!controllerString) return;

        controllerString.split(',').forEach(ctrl => {
            ctrl = ctrl.trim();
            if (ctrl) {
                this._createTag(container, 'controller-tag', ctrl, () => this.removeController(ctrl));
            }
        });
    },

    addController(controller) {
        if (!controller) return;
        controller = controller.trim();
        if (!controller) return;

        const hidden = document.getElementById('gemControllerHidden');
        const container = document.getElementById('gemControllerContainer');
        const currentControllers = hidden.value ? hidden.value.split(',').map(c => c.trim()) : [];

        if (currentControllers.some(c => c.toLowerCase() === controller.toLowerCase())) return;

        currentControllers.push(controller);
        hidden.value = currentControllers.join(', ');

        this._createTag(container, 'controller-tag', controller, () => this.removeController(controller));

        this.updateControllerDropdown();
    },

    removeController(controller) {
        const hidden = document.getElementById('gemControllerHidden');
        const container = document.getElementById('gemControllerContainer');

        const currentControllers = hidden.value.split(',').map(c => c.trim()).filter(c => c.toLowerCase() !== controller.toLowerCase());
        hidden.value = currentControllers.join(', ');

        container.querySelectorAll('.controller-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === controller.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateControllerDropdown();
    },

    initCampaignToggle(value) {
        const toggle = document.getElementById('gemCampaignToggle');
        const hidden = document.getElementById('gemCampaign');
        const label = document.getElementById('gemCampaignLabel');

        hidden.value = value || '';

        if (value === 'Yes' || value === '1' || value === 1) {
            toggle.checked = true;
            toggle.indeterminate = false;
            label.textContent = 'Yes';
        } else if (value === 'No' || value === '0' || value === 0) {
            toggle.checked = false;
            toggle.indeterminate = false;
            label.textContent = 'No';
        } else {
            toggle.checked = false;
            toggle.indeterminate = false;
            label.textContent = 'No';
        }
    },

    updateCampaignLabel() {
        const toggle = document.getElementById('gemCampaignToggle');
        const hidden = document.getElementById('gemCampaign');
        const label = document.getElementById('gemCampaignLabel');

        if (toggle.indeterminate) {
            toggle.indeterminate = false;
            toggle.checked = true;
        }

        if (toggle.checked) {
            hidden.value = 'Yes';
            label.textContent = 'Yes';
        } else {
            hidden.value = 'No';
            label.textContent = 'No';
        }
    },

    initExclusiveToggle(otherPlatforms) {
        const toggle = document.getElementById('gemExclusiveToggle');
        const label = document.getElementById('gemExclusiveLabel');
        const input = document.getElementById('gemOtherPlatforms');
        const hidden = document.getElementById('gemOtherPlatformsHidden');

        const isExclusive = !otherPlatforms || otherPlatforms.toLowerCase() === 'exclusive';

        toggle.checked = isExclusive;
        label.textContent = isExclusive ? 'Exclusive' : 'Multi-platform';
        input.style.display = isExclusive ? 'none' : 'block';
        input.value = isExclusive ? '' : otherPlatforms;
        hidden.value = otherPlatforms || '';
    },

    updateExclusiveToggle() {
        const toggle = document.getElementById('gemExclusiveToggle');
        const label = document.getElementById('gemExclusiveLabel');
        const input = document.getElementById('gemOtherPlatforms');
        const hidden = document.getElementById('gemOtherPlatformsHidden');

        if (toggle.checked) {
            label.textContent = 'Exclusive';
            input.style.display = 'none';
            hidden.value = 'Exclusive';
        } else {
            label.textContent = 'Multi-platform';
            input.style.display = 'block';
            hidden.value = input.value;
        }
    },

    getOtherPlatformsValue() {
        const toggle = document.getElementById('gemExclusiveToggle');
        if (toggle.checked) {
            return 'Exclusive';
        }
        return document.getElementById('gemOtherPlatforms').value.trim();
    },

    initFranchiseToggle(franchise) {
        const toggle = document.getElementById('gemFranchiseToggle');
        const label = document.getElementById('gemFranchiseLabel');
        const input = document.getElementById('gemFranchise');

        if (!toggle || !input) return;

        const isStandalone = !franchise || franchise.toLowerCase() === 'standalone';

        toggle.checked = isStandalone;
        label.textContent = isStandalone ? 'Standalone' : 'Part of a Series';
        input.style.display = isStandalone ? 'none' : 'block';
        if (isStandalone) input.value = '';
    },

    updateFranchiseToggle() {
        const toggle = document.getElementById('gemFranchiseToggle');
        const label = document.getElementById('gemFranchiseLabel');
        const input = document.getElementById('gemFranchise');

        if (toggle.checked) {
            label.textContent = 'Standalone';
            input.style.display = 'none';
            input.value = '';
        } else {
            label.textContent = 'Part of a Series';
            input.style.display = 'block';
        }
    },

    loadGameStructureDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/game_structure', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.gameStructureOptions = data.options;
                    this.updateGameStructureDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load game structures:', err); });
    },

    updateGameStructureDropdown() {
        const dropdown = document.getElementById('gemGameStructureDropdown');
        const currentStructures = document.getElementById('gemGameStructureHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add structure...</option>';
        this.gameStructureOptions.forEach(opt => {
            const structValue = opt.value || opt;
            if (!currentStructures.includes(structValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = structValue;
                option.textContent = structValue;
                dropdown.appendChild(option);
            }
        });
    },

    initGameStructureTags(structureString) {
        const container = document.getElementById('gemGameStructureContainer');
        const hidden = document.getElementById('gemGameStructureHidden');
        container.innerHTML = '';
        hidden.value = structureString;

        if (!structureString) return;

        structureString.split(',').forEach(structure => {
            structure = structure.trim();
            if (structure) {
                this._createTag(container, 'genre-tag', structure, () => this.removeGameStructure(structure));
            }
        });
    },

    addGameStructure(structure) {
        if (!structure) return;

        const hidden = document.getElementById('gemGameStructureHidden');
        const container = document.getElementById('gemGameStructureContainer');
        const currentStructures = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentStructures.some(s => s.toLowerCase() === structure.toLowerCase())) return;

        currentStructures.push(structure);
        hidden.value = currentStructures.join(', ');

        this._createTag(container, 'genre-tag', structure, () => this.removeGameStructure(structure));

        this.updateGameStructureDropdown();
    },

    removeGameStructure(structure) {
        const hidden = document.getElementById('gemGameStructureHidden');
        const container = document.getElementById('gemGameStructureContainer');

        const currentStructures = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== structure.toLowerCase());
        hidden.value = currentStructures.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === structure.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateGameStructureDropdown();
    },

    loadPerspectiveDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/perspective', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.perspectiveOptions = data.options;
                    this.updatePerspectiveDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load perspectives:', err); });
    },

    updatePerspectiveDropdown() {
        const dropdown = document.getElementById('gemPerspectiveDropdown');
        if (!dropdown) return;
        const currentPerspectives = document.getElementById('gemPerspectiveHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add perspective...</option>';
        this.perspectiveOptions.forEach(opt => {
            const val = opt.value || opt;
            if (!currentPerspectives.includes(val.toLowerCase())) {
                const option = document.createElement('option');
                option.value = val;
                option.textContent = val;
                dropdown.appendChild(option);
            }
        });
    },

    initPerspectiveTags(perspectiveString) {
        const container = document.getElementById('gemPerspectiveContainer');
        const hidden = document.getElementById('gemPerspectiveHidden');
        container.innerHTML = '';
        hidden.value = perspectiveString;

        if (!perspectiveString) return;

        perspectiveString.split(',').forEach(perspective => {
            perspective = perspective.trim();
            if (perspective) {
                this._createTag(container, 'genre-tag', perspective, () => this.removePerspective(perspective));
            }
        });
    },

    addPerspective(perspective) {
        if (!perspective) return;

        const hidden = document.getElementById('gemPerspectiveHidden');
        const container = document.getElementById('gemPerspectiveContainer');
        const currentPerspectives = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentPerspectives.some(s => s.toLowerCase() === perspective.toLowerCase())) return;

        currentPerspectives.push(perspective);
        hidden.value = currentPerspectives.join(', ');

        this._createTag(container, 'genre-tag', perspective, () => this.removePerspective(perspective));

        this.updatePerspectiveDropdown();
    },

    removePerspective(perspective) {
        const hidden = document.getElementById('gemPerspectiveHidden');
        const container = document.getElementById('gemPerspectiveContainer');

        const currentPerspectives = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== perspective.toLowerCase());
        hidden.value = currentPerspectives.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('\u00d7', '').trim().toLowerCase() === perspective.toLowerCase()) {
                tag.remove();
            }
        });

        this.updatePerspectiveDropdown();
    },

    loadDimensionDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        API.get('/api/dropdown-options/dimension', { signal })
            .then(data => {
                if (data.success && data.options) {
                    this.dimensionOptions = data.options;
                    this.updateDimensionDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load dimensions:', err); });
    },

    updateDimensionDropdown() {
        const dropdown = document.getElementById('gemDimensionDropdown');
        if (!dropdown) return;
        const currentDimensions = document.getElementById('gemDimensionHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add dimension...</option>';
        this.dimensionOptions.forEach(opt => {
            const val = opt.value || opt;
            if (!currentDimensions.includes(val.toLowerCase())) {
                const option = document.createElement('option');
                option.value = val;
                option.textContent = val;
                dropdown.appendChild(option);
            }
        });
    },

    initDimensionTags(dimensionString) {
        const container = document.getElementById('gemDimensionContainer');
        const hidden = document.getElementById('gemDimensionHidden');
        container.innerHTML = '';
        hidden.value = dimensionString;

        if (!dimensionString) return;

        dimensionString.split(',').forEach(dimension => {
            dimension = dimension.trim();
            if (dimension) {
                this._createTag(container, 'genre-tag', dimension, () => this.removeDimension(dimension));
            }
        });
    },

    addDimension(dimension) {
        if (!dimension) return;

        const hidden = document.getElementById('gemDimensionHidden');
        const container = document.getElementById('gemDimensionContainer');
        const currentDimensions = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentDimensions.some(s => s.toLowerCase() === dimension.toLowerCase())) return;

        currentDimensions.push(dimension);
        hidden.value = currentDimensions.join(', ');

        this._createTag(container, 'genre-tag', dimension, () => this.removeDimension(dimension));

        this.updateDimensionDropdown();
    },

    removeDimension(dimension) {
        const hidden = document.getElementById('gemDimensionHidden');
        const container = document.getElementById('gemDimensionContainer');

        const currentDimensions = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== dimension.toLowerCase());
        hidden.value = currentDimensions.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('\u00d7', '').trim().toLowerCase() === dimension.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateDimensionDropdown();
    }
};

window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        GameDetailModal.clearCache();
    }
});

RetroDB.GameDetailModal = GameDetailModal;
RetroDB.GameEditModal = GameEditModal;
RetroDB.HLTBManager = HLTBManager;
RetroDB.gameDetailUrl = gameDetailUrl;

window.gameDetailCache = GameDetailModal.cache;
window.currentGameDetailId = null;
Object.defineProperty(window, 'currentGameDetailId', {
    get: () => GameDetailModal.currentId,
    set: (v) => { GameDetailModal.currentId = v; }
});

window.openGameDetailModal = (gameId) => GameDetailModal.open(gameId);
window.populateGameDetailModal = (game) => GameDetailModal.populate(game);
window.showGameDetailError = (message) => GameDetailModal.showError(message);
window.closeGameDetailModal = () => GameDetailModal.close();

window.HLTBManager = HLTBManager;

window.currentEditGameData = null;
Object.defineProperty(window, 'currentEditGameData', {
    get: () => GameEditModal.currentData,
    set: (v) => { GameEditModal.currentData = v; }
});

window.openGameEditModal = () => GameEditModal.open();
window.switchEditTab = (tabId) => GameEditModal.switchTab(tabId);
window.generateModalSortTitle = () => GameEditModal.generateSortTitle();
window.saveGameEdits = () => GameEditModal.save();
window.closeGameEditModal = () => GameEditModal.close();
window.updateGameCardInPage = (gameId, formData) => GameEditModal.updateGameCardInPage(gameId, formData);
window.updateHltbDisplay = (game) => GameEditModal.updateHltbDisplay(game);
window.updateGameCompletion = () => GameEditModal.updateCompletion();

window.gemHltbCtx = GameEditModal.hltbContext;
window.lookupHltbFromModal = () => HLTBManager.lookup(GameEditModal.hltbContext);
window.saveHltbFromModal = () => HLTBManager.save(GameEditModal.hltbContext);
window.cancelHltbFromModal = () => HLTBManager.cancel(GameEditModal.hltbContext);
window.clearHltbFromModal = () => HLTBManager.clear(GameEditModal.hltbContext);

window.loadModalGenreDropdown = () => GameEditModal.loadGenreDropdown();
window.updateModalGenreDropdown = () => GameEditModal.updateGenreDropdown();
window.initModalGenreTags = (s) => GameEditModal.initGenreTags(s);
window.addModalGenre = (g) => GameEditModal.addGenre(g);
window.removeModalGenre = (g) => GameEditModal.removeGenre(g);

window.loadModalModesDropdown = () => GameEditModal.loadModesDropdown();
window.updateModalModesDropdown = () => GameEditModal.updateModesDropdown();
window.initModalModesTags = (s) => GameEditModal.initModesTags(s);
window.addModalMode = (m) => GameEditModal.addMode(m);
window.removeModalMode = (m) => GameEditModal.removeMode(m);

window.loadModalSaveTypeDropdown = () => GameEditModal.loadSaveTypeDropdown();
window.updateModalSaveTypeDropdown = () => GameEditModal.updateSaveTypeDropdown();
window.initModalSaveTypeTags = (s) => GameEditModal.initSaveTypeTags(s);
window.addModalSaveType = (t) => GameEditModal.addSaveType(t);
window.removeModalSaveType = (t) => GameEditModal.removeSaveType(t);

window.loadModalControllerDropdown = (id) => GameEditModal.loadControllerDropdown(id);
window.updateModalControllerDropdown = () => GameEditModal.updateControllerDropdown();
window.initModalControllerTags = (s) => GameEditModal.initControllerTags(s);
window.addModalController = (c) => GameEditModal.addController(c);
window.removeModalController = (c) => GameEditModal.removeController(c);

window.initModalCampaignToggle = (v) => GameEditModal.initCampaignToggle(v);
window.updateModalCampaignLabel = () => GameEditModal.updateCampaignLabel();

window.initModalExclusiveToggle = (p) => GameEditModal.initExclusiveToggle(p);
window.updateModalExclusiveToggle = () => GameEditModal.updateExclusiveToggle();
window.getOtherPlatformsValue = () => GameEditModal.getOtherPlatformsValue();
window.updateGemFranchiseToggle = () => GameEditModal.updateFranchiseToggle();

window.loadModalGameStructureDropdown = () => GameEditModal.loadGameStructureDropdown();
window.addModalGameStructure = (v) => GameEditModal.addGameStructure(v);
window.removeModalGameStructure = (v) => GameEditModal.removeGameStructure(v);

window.loadModalPerspectiveDropdown = () => GameEditModal.loadPerspectiveDropdown();
window.addModalPerspective = (v) => GameEditModal.addPerspective(v);
window.removeModalPerspective = (v) => GameEditModal.removePerspective(v);

window.loadModalDimensionDropdown = () => GameEditModal.loadDimensionDropdown();
window.addModalDimension = (v) => GameEditModal.addDimension(v);
window.removeModalDimension = (v) => GameEditModal.removeDimension(v);

window.formatHltbTime = (hours) => {
    if (!hours || hours === 0) return '-';
    if (hours < 1) return Math.round(hours * 60) + ' mins';
    return hours.toFixed(1).replace('.0', '') + ' hrs';
};

window.addEventListener('beforeunload', () => {
    GameDetailModal.cache.clear();
});

window.GameDetailModal = GameDetailModal;
window.GameEditModal = GameEditModal;

/**
 * Initialize a date text input with auto-formatting and validation.
 * - Only allows digits, auto-inserts / after YYYY and MM
 * - On blur, validates the date is real (rejects 2024/02/30 etc.)
 * - Syncs with a companion hidden date picker if present
 * @param {string} textId - ID of the text input
 * @param {string} [pickerId] - ID of the hidden date picker input
 */
window.initDateMask = function(textId, pickerId) {
    const input = document.getElementById(textId);
    if (!input) return;

    input.addEventListener('input', function() {
        let v = this.value.replace(/[^\d]/g, '');
        if (v.length > 8) v = v.slice(0, 8);
        if (v.length > 4) v = v.slice(0, 4) + '-' + v.slice(4);
        if (v.length > 7) v = v.slice(0, 7) + '-' + v.slice(7);
        this.value = v;
    });

    input.addEventListener('blur', function() {
        const v = this.value;
        if (!v) return;
        const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!m) { this.value = ''; return; }
        const d = new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
        if (d.getFullYear() !== parseInt(m[1]) || d.getMonth() + 1 !== parseInt(m[2]) || d.getDate() !== parseInt(m[3])) {
            this.value = '';
        }
    });

    if (pickerId) {
        const picker = document.getElementById(pickerId);
        if (picker) {
            picker.addEventListener('change', function() {
                input.value = this.value;
            });
        }
    }
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        initDateMask('gemReleaseDate', 'gemReleaseDatePicker');
    });
} else {
    initDateMask('gemReleaseDate', 'gemReleaseDatePicker');
}

/**
 * Trigger AI metadata fill for the currently open game detail modal.
 * POSTs to /api/game/{id}/ai-fill, refreshes modal on success.
 */
window.triggerAiFill = function() {
    const gameId = GameDetailModal.currentId;
    if (!gameId) return;

    const btn = document.getElementById('gdmAiFill');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Filling...';

    API.post(`/api/game/${gameId}/ai-fill`)
        .then(data => {
            if (data.success) {
                const count = data.filled_count || 0;
                if (count > 0) {
                    showNotification(`AI filled ${count} field${count !== 1 ? 's' : ''}: ${data.filled_fields.join(', ')}`, 'success');
                    GameDetailModal.cache.delete(gameId);
                    GameDetailModal.open(gameId);
                    if (typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
                        AllGamesController.refreshCards(gameId);
                    }
                } else {
                    showNotification('AI found no missing fields to fill', 'info');
                }
            } else {
                showNotification(data.error || 'AI fill failed', 'error');
            }
        })
        .catch(err => {
            showNotification('AI fill request failed: ' + err.message, 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        });
};

})();
