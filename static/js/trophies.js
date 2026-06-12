/**
 * RetroDB Trophies Module
 * Shared utilities for RPCS3 and PSN trophy pages
 * Version: 1.20.0
 *
 * Features:
 * - TrophySync: Trophy sync operations
 * - TrophyDisplay: Trophy rendering utilities
 * - PSNConnection: PSN connection testing
 */

// =============================================================================
// TROPHY SYNC CONTROLLER
// =============================================================================

const TrophySync = {
    isLoading: false,

    /**
     * Sync trophies for a game
     * @param {number} gameId - Game ID
     * @param {Object} options - Sync options
     */
    async syncGame(gameId, options = {}) {
        if (this.isLoading) return;
        this.isLoading = true;

        const btn = options.button;
        const originalText = btn ? btn.innerHTML : '';

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">🔄</span> ' + t('Syncing...');
        }

        try {
            const data = await API.post(`/api/trophies/sync/${gameId}`);

            if (data.success) {
                if (typeof showNotification === 'function') {
                    showNotification(t('Trophies synced successfully!'), 'success');
                }
                if (options.onSuccess) {
                    options.onSuccess(data);
                } else {
                    // Default: reload page
                    setTimeout(() => location.reload(), 1000);
                }
            } else {
                if (typeof showNotification === 'function') {
                    showNotification(data.error || t('Failed to sync trophies'), 'error');
                }
            }
        } catch (error) {
            console.error('Error syncing trophies:', error);
            if (typeof showNotification === 'function') {
                showNotification(t('Network error syncing trophies'), 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
            this.isLoading = false;
        }
    },

    /**
     * Scan for local RPCS3 trophies
     * @param {Object} options - Scan options
     */
    async scanLocal(options = {}) {
        if (this.isLoading) return;
        this.isLoading = true;

        const btn = options.button || document.getElementById('scanTrophiesBtn');
        const originalText = btn ? btn.innerHTML : '';

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">🔄</span> Scanning...';
        }

        try {
            const data = await API.post('/api/trophies/scan');

            if (data.success) {
                if (typeof showNotification === 'function') {
                    showNotification(`Found trophies for ${formatNumber(data.games_found)} games`, 'success');
                }
                if (options.onSuccess) {
                    options.onSuccess(data);
                } else {
                    setTimeout(() => location.reload(), 1500);
                }
            } else {
                if (typeof showNotification === 'function') {
                    showNotification(data.error || 'Failed to scan trophies', 'error');
                }
            }
        } catch (error) {
            console.error('Error scanning trophies:', error);
            if (typeof showNotification === 'function') {
                showNotification('Network error scanning trophies', 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
            this.isLoading = false;
        }
    }
};

// =============================================================================
// PSN CONNECTION
// =============================================================================

const PSNConnection = {
    /**
     * Test PSN connection
     * @param {Object} options - Test options
     */
    async test(options = {}) {
        const btn = options.button || document.getElementById('testPsnBtn');
        const statusEl = options.statusElement || document.getElementById('psnStatus');
        const originalText = btn ? btn.innerHTML : '';

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">🔄</span> Testing...';
        }

        try {
            const data = await API.get('/api/psn/test-connection');

            if (data.success) {
                if (statusEl) {
                    statusEl.className = 'status-indicator status-ok';
                    statusEl.title = 'Connected';
                }
                if (typeof showNotification === 'function') {
                    showNotification('PSN connection successful!', 'success');
                }
            } else {
                if (statusEl) {
                    statusEl.className = 'status-indicator status-error';
                    statusEl.title = 'Connection failed';
                }
                if (typeof showNotification === 'function') {
                    showNotification(data.error || 'PSN connection failed', 'error');
                }
            }
        } catch (error) {
            console.error('Error testing PSN connection:', error);
            if (statusEl) {
                statusEl.className = 'status-indicator status-error';
                statusEl.title = 'Connection error';
            }
            if (typeof showNotification === 'function') {
                showNotification('Network error testing PSN connection', 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    },

    /**
     * Sync PSN trophies
     * @param {Object} options - Sync options
     */
    async sync(options = {}) {
        const btn = options.button || document.getElementById('syncPsnBtn');
        const originalText = btn ? btn.innerHTML : '';

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="btn-icon">🔄</span> Syncing...';
        }

        try {
            const data = await API.post('/api/psn/sync');

            if (data.success) {
                if (typeof showNotification === 'function') {
                    showNotification(`Synced ${formatNumber(data.games_synced)} games from PSN`, 'success');
                }
                if (options.onSuccess) {
                    options.onSuccess(data);
                } else {
                    setTimeout(() => location.reload(), 1500);
                }
            } else {
                if (typeof showNotification === 'function') {
                    showNotification(data.error || 'PSN sync failed', 'error');
                }
            }
        } catch (error) {
            console.error('Error syncing PSN:', error);
            if (typeof showNotification === 'function') {
                showNotification('Network error syncing PSN', 'error');
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }
    }
};

// =============================================================================
// TROPHY DISPLAY UTILITIES
// =============================================================================

const TrophyDisplay = {
    // Trophy type icons
    icons: {
        platinum: '🏆',
        gold: '🥇',
        silver: '🥈',
        bronze: '🥉'
    },

    // Trophy type colors
    colors: {
        platinum: '#E5E4E2',
        gold: '#FFD700',
        silver: '#C0C0C0',
        bronze: '#CD7F32'
    },

    /**
     * Get trophy icon
     * @param {string} type - Trophy type
     * @returns {string} Icon string
     */
    getIcon(type) {
        return this.icons[type?.toLowerCase()] || '🏆';
    },

    /**
     * Get trophy color
     * @param {string} type - Trophy type
     * @returns {string} Color hex code
     */
    getColor(type) {
        return this.colors[type?.toLowerCase()] || '#4cc9f0';
    },

    /**
     * Format trophy counts
     * @param {Object} counts - Trophy counts by type
     * @returns {string} Formatted string
     */
    formatCounts(counts) {
        const parts = [];
        if (counts.platinum) parts.push(`${this.icons.platinum} ${counts.platinum}`);
        if (counts.gold) parts.push(`${this.icons.gold} ${counts.gold}`);
        if (counts.silver) parts.push(`${this.icons.silver} ${counts.silver}`);
        if (counts.bronze) parts.push(`${this.icons.bronze} ${counts.bronze}`);
        return parts.join(' ');
    },

    /**
     * Calculate completion percentage
     * @param {number} earned - Earned trophies
     * @param {number} total - Total trophies
     * @returns {number} Percentage (0-100)
     */
    completionPercent(earned, total) {
        if (!total || total === 0) return 0;
        return Math.round((earned / total) * 100);
    },

    /**
     * Render a trophy card
     * @param {Object} trophy - Trophy data
     * @returns {string} HTML string
     */
    renderCard(trophy) {
        const earned = trophy.earned || trophy.unlocked;
        const earnedClass = earned ? 'trophy-earned' : 'trophy-locked';
        const icon = this.getIcon(trophy.type || trophy.trophy_type);

        // Pass 29.1: escape icon_url and displayed trophy name so a
        // malformed PSN/upstream response can't close the src attribute.
        const iconUrlSafe = trophy.icon_url ? escapeHtml(trophy.icon_url) : '';
        const nameSafe = escapeHtml(trophy.name || trophy.title || '');
        const typeSafe = escapeHtml(trophy.type || trophy.trophy_type || '');
        return `
            <div class="trophy-card ${earnedClass}">
                <div class="trophy-icon">
                    ${iconUrlSafe ?
                        `<img src="${iconUrlSafe}" alt="${nameSafe}">` :
                        icon
                    }
                </div>
                <div class="trophy-info">
                    <div class="trophy-name">${nameSafe}</div>
                    <div class="trophy-description">${escapeHtml(trophy.description || trophy.detail || '')}</div>
                    <div class="trophy-type">${icon} ${typeSafe}</div>
                </div>
                ${earned && trophy.earned_date ?
                    `<div class="trophy-date">Earned: ${(typeof DateUtils !== 'undefined') ? DateUtils.formatShort(new Date(trophy.earned_date)) : escapeHtml((trophy.earned_date || '').replace('T', ' ').slice(0, 16))}</div>` : ''
                }
            </div>
        `;
    },

    /**
     * Render a list of trophy cards
     * @param {Array} trophies - Array of trophies
     * @param {Object} options - Render options
     * @returns {string} HTML string
     */
    renderList(trophies, options = {}) {
        if (!trophies || trophies.length === 0) {
            return '<div class="no-trophies">No trophies found</div>';
        }

        const { showEarnedFirst = true, groupByType = false } = options;

        let sorted = [...trophies];

        if (showEarnedFirst) {
            sorted.sort((a, b) => {
                const aEarned = a.earned || a.unlocked ? 1 : 0;
                const bEarned = b.earned || b.unlocked ? 1 : 0;
                return bEarned - aEarned;
            });
        }

        if (groupByType) {
            const typeOrder = ['platinum', 'gold', 'silver', 'bronze'];
            sorted.sort((a, b) => {
                const aType = (a.type || a.trophy_type || '').toLowerCase();
                const bType = (b.type || b.trophy_type || '').toLowerCase();
                return typeOrder.indexOf(aType) - typeOrder.indexOf(bType);
            });
        }

        return sorted.map(t => this.renderCard(t)).join('');
    }
};

// =============================================================================
// EXPORT GLOBALS
// =============================================================================

window.TrophySync = TrophySync;
window.PSNConnection = PSNConnection;
window.TrophyDisplay = TrophyDisplay;

// Legacy function exports
window.syncTrophiesForGame = (gameId, options) => TrophySync.syncGame(gameId, options);
window.scanLocalTrophies = (options) => TrophySync.scanLocal(options);
window.testPSNConnection = (options) => PSNConnection.test(options);
window.syncPSNTrophies = (options) => PSNConnection.sync(options);
