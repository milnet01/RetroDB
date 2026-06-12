/**
 * RetroDB Achievements Module
 * Shared utilities for RetroAchievements pages
 * Version: 1.20.0
 *
 * Features:
 * - RASync: RetroAchievements sync operations
 * - ProgressCalculator: Achievement progress calculations
 */

// =============================================================================
// RA SYNC CONTROLLER
// =============================================================================

const RASync = {
    isLoading: false,
    pollTimeout: null,

    /**
     * Sync RetroAchievements for a system
     * @param {number} systemId - System ID
     * @param {string} systemName - System name for display
     * @param {Object} options - Additional options
     */
    async syncSystem(systemId, systemName, options = {}) {
        if (this.isLoading) return;
        this.isLoading = true;

        const btn = options.button || document.getElementById('refreshBtn');
        const statusEl = options.statusElement || document.getElementById('cacheStatus');

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Starting...');
        }
        if (statusEl) {
            statusEl.textContent = t('Syncing...');
            statusEl.style.display = 'inline';
        }

        try {
            const data = await API.post(`/api/achievements/sync-system/${systemId}`);

            if (data.success) {
                if (data.queued) {
                    // Sync was queued
                    this.handleQueued(data, btn, statusEl);
                } else {
                    // Sync started
                    this.handleStarted(data, btn, systemName, options);
                }
            } else {
                this.handleError(data, btn, statusEl);
            }
        } catch (e) {
            console.error('Error starting sync:', e);
            if (btn) {
                btn.innerHTML = '<span class="btn-icon">❌</span> ' + t('Network error');
                setTimeout(() => {
                    btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                    btn.disabled = false;
                }, 3000);
            }
            this.isLoading = false;
        }
    },

    /**
     * Handle queued sync response
     */
    handleQueued(data, btn, statusEl) {
        try {
            // Add to unified RA operations queue
            const queue = safeParseJSON('raOperationsQueue', []);

            if (!queue.find(q => q.type === 'sync' && q.systemId === data.system_id)) {
                const newItem = {
                    type: 'sync',
                    systemId: data.system_id,
                    systemName: data.system_name,
                    gameCount: data.game_count,
                    timestamp: Date.now()
                };
                queue.push(newItem);
                localStorage.setItem('raOperationsQueue', JSON.stringify(queue));

                // Add to toast controller if available
                if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                    UnifiedToastController.addRAOperationToQueue(newItem);
                    if (UnifiedToastController.adjustPollingSpeed) {
                        UnifiedToastController.adjustPollingSpeed('ra-sync', true);
                    }
                }
            }
        } catch (queueError) {
            console.error('Error adding to queue:', queueError);
        }

        if (typeof showModal === 'function') {
            showModal('📋 ' + t('Sync Queued'), t('{system} has been added to the sync queue.', {system: data.system_name}));
        }

        if (btn) {
            btn.innerHTML = '<span class="btn-icon">📋</span> ' + t('Queued');
            setTimeout(() => {
                btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                btn.disabled = false;
            }, 2000);
        }
        if (statusEl) statusEl.style.display = 'none';
        this.isLoading = false;
    },

    /**
     * Handle sync started response
     */
    handleStarted(data, btn, systemName, options) {
        // Trigger toast controller if available
        if (typeof UnifiedToastController !== 'undefined') {
            const initialData = {
                running: true,
                completed: false,
                current_system: systemName,
                total: options.gameCount || 0,
                current: 0,
                percent: 0,
                paused: false
            };
            UnifiedToastController.showActiveToast('ra-sync', UnifiedToastController.getTypeConfig('ra-sync'), initialData);
            UnifiedToastController.adjustPollingSpeed('ra-sync', true);
            UnifiedToastController.broadcast('job-started', 'ra-sync', initialData);
        }

        if (btn) {
            btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Syncing...');
        }
    },

    /**
     * Handle sync error response
     */
    handleError(data, btn, statusEl) {
        if (data.already_running) {
            if (btn) {
                btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Already Syncing');
                setTimeout(() => {
                    btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                    btn.disabled = false;
                }, 2000);
            }
            if (typeof showModal === 'function') {
                showModal('ℹ️ ' + t('Sync In Progress'), data.error || t('This system is already being synced.'));
            }
        } else {
            if (btn) {
                btn.innerHTML = `<span class="btn-icon">❌</span> ${escapeHtml(data.error || t('Sync failed'))}`;
                setTimeout(() => {
                    btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                    btn.disabled = false;
                }, 3000);
            }
        }
        this.isLoading = false;
    },

    /**
     * Poll sync status
     * @param {Object} options - Polling options
     */
    async pollStatus(options = {}) {
        const btn = options.button || document.getElementById('refreshBtn');
        const statusEl = options.statusElement || document.getElementById('cacheStatus');

        try {
            const data = await API.get('/api/achievements/sync-status');

            if (data.running && !data.completed) {
                if (btn) {
                    btn.innerHTML = `<span class="btn-icon">🔄</span> ${formatNumber(data.processed || 0)} / ${formatNumber(data.total || 0)}`;
                }
                if (statusEl) {
                    statusEl.textContent = t('Syncing: {processed} / {total}', {processed: formatNumber(data.processed || 0), total: formatNumber(data.total || 0)});
                }

                // Continue polling
                this.pollTimeout = setTimeout(() => this.pollStatus(options), 2000);
            } else if (data.completed) {
                if (btn) {
                    btn.innerHTML = '<span class="btn-icon">✅</span> ' + t('Complete!');
                    btn.disabled = false;
                    setTimeout(() => {
                        btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                    }, 3000);
                }
                if (statusEl) {
                    statusEl.textContent = t('Just synced');
                }
                this.isLoading = false;

                if (typeof showNotification === 'function') {
                    showNotification(t('Sync complete! Refresh page to see updated progress.'), 'success');
                }
            } else {
                // Not running
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Sync Progress');
                }
                this.isLoading = false;
            }
        } catch (error) {
            console.error('Error polling sync status:', error);
        }
    },

    /**
     * Clear RA data for a system
     * @param {number} systemId - System ID
     * @param {string} systemName - System name for display
     */
    async clearSystemData(systemId, systemName) {
        showConfirm(
            '🗑️ ' + t('Clear RetroAchievements Data'),
            t('This will remove "{system}" from the Achievements page. Continue?', {system: systemName}),
            async () => {
                const btn = document.getElementById('clearRABtn');

                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="btn-icon">⏳</span> ' + t('Clearing...');
                }

                try {
                    const data = await API.post(`/api/clear-ra-data/${systemId}`);

                    if (data.success) {
                        showNotification(t('Cleared RA data for {count} games in {system}', {count: formatNumber(data.cleared), system: systemName}), 'success');
                        setTimeout(() => {
                            window.location.href = '/achievements';
                        }, 1500);
                    } else {
                        showNotification(data.error || t('Failed to clear RA data'), 'error');
                        if (btn) {
                            btn.disabled = false;
                            btn.innerHTML = '<span class="btn-icon">🗑️</span> ' + t('Clear RA Data');
                        }
                    }
                } catch (error) {
                    console.error('Error clearing RA data:', error);
                    showNotification(t('Failed to clear RA data'), 'error');
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<span class="btn-icon">🗑️</span> ' + t('Clear RA Data');
                    }
                }
            }
        );
    }
};

// =============================================================================
// PROGRESS CALCULATOR
// =============================================================================

const ProgressCalculator = {
    /**
     * Calculate achievement progress percentage
     * @param {number} earned - Earned achievements
     * @param {number} total - Total achievements
     * @returns {number} Progress percentage (0-100)
     */
    percentage(earned, total) {
        if (!total || total === 0) return 0;
        return Math.round((earned / total) * 100);
    },

    /**
     * Get progress bar color class
     * @param {number} percent - Progress percentage
     * @returns {string} CSS class name
     */
    colorClass(percent) {
        if (percent >= 100) return 'progress-gold';
        if (percent >= 75) return 'progress-green';
        if (percent >= 50) return 'progress-cyan';
        if (percent >= 25) return 'progress-blue';
        return 'progress-default';
    },

    /**
     * Format progress as display string
     * @param {number} earned - Earned achievements
     * @param {number} total - Total achievements
     * @returns {string} Formatted progress string
     */
    format(earned, total) {
        const percent = this.percentage(earned, total);
        return `${formatNumber(earned)} / ${formatNumber(total)} (${percent}%)`;
    }
};

// =============================================================================
// ACHIEVEMENT CARD RENDERER
// =============================================================================

const AchievementCard = {
    /**
     * Render an achievement card
     * @param {Object} achievement - Achievement data
     * @returns {string} HTML string
     */
    render(achievement) {
        const earnedClass = achievement.earned ? 'earned' : 'unearned';
        const iconClass = achievement.earned ? 'achievement-icon-earned' : 'achievement-icon-locked';

        // Pass 29.1: escape badge_url and title in the <img> attributes.
        // badge_url is upstream-controlled (RA / Steam / Xbox) and title is
        // user-visible; an attacker-influenced upstream could otherwise
        // close the attribute and inject an onerror handler.
        const badgeUrlSafe = achievement.badge_url ? escapeHtml(achievement.badge_url) : '';
        const titleSafe = escapeHtml(achievement.title);
        return `
            <div class="achievement-card ${earnedClass}">
                <div class="achievement-icon ${iconClass}">
                    ${badgeUrlSafe ?
                        `<img src="${badgeUrlSafe}" alt="${titleSafe}">` :
                        '🏆'
                    }
                </div>
                <div class="achievement-info">
                    <div class="achievement-title">${titleSafe}</div>
                    <div class="achievement-description">${escapeHtml(achievement.description || '')}</div>
                    ${achievement.points ? `<div class="achievement-points">${t('{points} pts', {points: achievement.points})}</div>` : ''}
                </div>
            </div>
        `;
    },

    /**
     * Render multiple achievement cards
     * @param {Array} achievements - Array of achievements
     * @param {Object} options - Render options
     * @returns {string} HTML string
     */
    renderList(achievements, options = {}) {
        if (!achievements || achievements.length === 0) {
            return `<div class="no-achievements">${t('No achievements found')}</div>`;
        }

        const { showEarnedFirst = true, limit = null } = options;

        let sorted = [...achievements];
        if (showEarnedFirst) {
            sorted.sort((a, b) => (b.earned ? 1 : 0) - (a.earned ? 1 : 0));
        }

        if (limit) {
            sorted = sorted.slice(0, limit);
        }

        return sorted.map(a => this.render(a)).join('');
    }
};

// =============================================================================
// EXPORT GLOBALS
// =============================================================================

window.RASync = RASync;
window.ProgressCalculator = ProgressCalculator;
window.AchievementCard = AchievementCard;

// Clear poll timeout on page unload to prevent orphaned timeout chains
window.addEventListener('beforeunload', () => {
    if (RASync.pollTimeout) {
        clearTimeout(RASync.pollTimeout);
        RASync.pollTimeout = null;
    }
});

// Legacy function exports
window.syncRAForSystem = (systemId, systemName, options) => RASync.syncSystem(systemId, systemName, options);
window.clearSystemRAData = (systemId, systemName) => RASync.clearSystemData(systemId, systemName);
window.pollSyncStatus = (options) => RASync.pollStatus(options);
