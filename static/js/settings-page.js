/**
 * RetroDB Settings Page Module
 * Handles all settings page functionality
 * Version: 1.20.0
 *
 * Usage:
 *   SettingsPage.init({ scraperSettings: {...} });
 *
 * Sections:
 * - TabController: Tab switching and subnav
 * - UserManager: User profile and management
 * - PathSettings: Path configuration
 * - DisplaySettings: Display preferences
 * - NotificationSettings: Notification timeouts
 * - BonusDiscManager: Bonus disc detection/linking
 * - DatabaseBackup: Backup and restore
 * - ScraperConfig: Scraper priority and toggles
 * - DropdownManager: Dropdown options management
 * - ControllerManager: Controller configuration
 * - LogoReference: System logo reference
 * - TroubleshootingTools: Diagnostics and repair
 * - LoggingSettings: Log configuration
 */

// =============================================================================
// SETTINGS PAGE MAIN CONTROLLER
// =============================================================================

const SettingsPage = {
    config: {},

    /**
     * Initialize settings page
     * @param {Object} config - Initial configuration from server
     */
    init(config = {}) {
        this.config = config;

        // Initialize sub-modules
        TabController.init();
        ScraperConfig.init(config.scraperSettings || {});

        // Load data on page ready
        document.addEventListener('DOMContentLoaded', () => {
            PathSettings.load();
            DisplaySettings.load();
        });
    }
};

// =============================================================================
// TAB CONTROLLER
// =============================================================================

const TabController = {
    init() {
        // URL hash takes priority, then localStorage fallback
        const validTabs = ['account', 'library', 'scraping', 'data', 'customization', 'system'];
        const hashTab = window.location.hash.replace('#', '');
        if (hashTab && validTabs.includes(hashTab)) {
            this.switchTab(hashTab, true);
        } else {
            const savedTab = localStorage.getItem('settingsActiveTab');
            if (savedTab && validTabs.includes(savedTab)) {
                this.switchTab(savedTab, true);
            }
        }

        // Listen for hash changes (browser back/forward)
        window.addEventListener('hashchange', () => {
            const tab = window.location.hash.replace('#', '');
            if (tab && validTabs.includes(tab)) {
                this.switchTab(tab, true);
            }
        });

        // Initialize scroll observer for subnav
        this.initScrollObserver();
    },

    /**
     * Switch to a specific tab
     * @param {string} tabId - Tab identifier
     */
    switchTab(tabId, skipScroll) {
        // Update tab buttons
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.classList.remove('active');
            if (tab.dataset.tab === tabId) {
                tab.classList.add('active');
            }
        });

        // Update tab panels
        document.querySelectorAll('.settings-tab-panel').forEach(panel => {
            panel.classList.remove('active');
            if (panel.id === 'tab-' + tabId) {
                panel.classList.add('active');
            }
        });

        // Save active tab to localStorage and update URL hash
        localStorage.setItem('settingsActiveTab', tabId);
        if (window.location.hash !== '#' + tabId) {
            history.replaceState(null, '', '#' + tabId);
        }

        // Handle customization tab special cases
        if (tabId === 'customization') {
            setTimeout(() => {
                if (typeof ControllerManager !== 'undefined' && ControllerManager.applyMasonry) {
                    ControllerManager.applyMasonry();
                }
                LogoReference.reload();
                this.initScrollObserver();
            }, 50);
        }

        // Scroll to top (skip on initial page load)
        if (!skipScroll) {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    },

    /**
     * Scroll to a specific section
     * @param {string} sectionId - Section element ID
     */
    scrollToSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) return;

        // Update subnav active state
        const activePanel = document.querySelector('.settings-tab-panel.active');
        if (activePanel) {
            activePanel.querySelectorAll('.subnav-link').forEach(link => {
                link.classList.remove('active');
                if (link.getAttribute('href') === '#' + sectionId ||
                    link.getAttribute('onclick')?.includes(sectionId)) {
                    link.classList.add('active');
                }
            });
        }

        // Scroll with offset for sticky header
        const offset = 120;
        const elementPosition = section.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - offset;

        window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
        });
    },

    /**
     * Initialize intersection observer for subnav
     */
    _scrollObserver: null,

    initScrollObserver() {
        // Disconnect previous observer if re-initialized
        if (this._scrollObserver) {
            this._scrollObserver.disconnect();
            this._scrollObserver = null;
        }

        const sections = document.querySelectorAll('section[id]');
        const observerOptions = {
            root: null,
            rootMargin: '-120px 0px -60% 0px',
            threshold: 0
        };

        this._scrollObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const sectionId = entry.target.id;
                    const activePanel = document.querySelector('.settings-tab-panel.active');
                    if (activePanel) {
                        activePanel.querySelectorAll('.subnav-link').forEach(link => {
                            link.classList.remove('active');
                            if (link.getAttribute('href') === '#' + sectionId ||
                                link.getAttribute('onclick')?.includes("'" + sectionId + "'")) {
                                link.classList.add('active');
                            }
                        });
                    }
                }
            });
        }, observerOptions);

        sections.forEach(section => this._scrollObserver.observe(section));
    }
};

// =============================================================================
// USER MANAGER
// =============================================================================

const UserManager = {
    /**
     * Save current user's settings
     */
    saveSettings() {
        const data = {
            rpcs3_trophy_path: document.getElementById('userTrophyPath')?.value.trim() || '',
            ra_username: document.getElementById('userRaUsername')?.value.trim() || '',
            ra_api_key: document.getElementById('userRaApiKey')?.value.trim() || '',
            psn_username: document.getElementById('userPsnUsername')?.value.trim() || '',
            psn_npsso: document.getElementById('userPsnNpsso')?.value.trim() || ''
        };

        API.post('/api/users/settings', data)
            .then(result => {
                if (result.success) {
                    showNotification('Your settings have been saved!', 'success');
                } else {
                    showNotification(result.error || 'Failed to save settings', 'error');
                }
            })
            .catch(() => showNotification('Network error saving settings', 'error'));
    },

    /**
     * Save the UI language preference, then reload so the page re-renders in
     * the new locale (Pass 43.1). A second open tab keeps its locale until its
     * own reload — acceptable for v1 (no live broadcast).
     */
    saveLanguage(locale) {
        API.post('/api/users/settings', { locale_preference: locale })
            .then(result => {
                if (result.success) {
                    location.reload();
                } else {
                    showNotification(result.error || 'Failed to save language', 'error');
                }
            })
            .catch(() => showNotification('Network error saving language', 'error'));
    },

    /**
     * Change current user's password
     */
    changePassword() {
        const currentPassword = document.getElementById('currentPassword')?.value || '';
        const newPassword = document.getElementById('newPassword')?.value || '';

        if (!newPassword) {
            showNotification('Please enter a new password', 'warning');
            return;
        }

        API.post('/api/profile/password', {
            current_password: currentPassword,
            new_password: newPassword
        })
            .then(result => {
                if (result.success) {
                    showNotification('Password changed successfully!', 'success');
                    document.getElementById('currentPassword').value = '';
                    document.getElementById('newPassword').value = '';
                } else {
                    showNotification(result.error || 'Failed to change password', 'error');
                }
            })
            .catch(() => showNotification('Network error changing password', 'error'));
    },

    /**
     * Show add user modal
     */
    showAddModal() {
        document.getElementById('userModalTitle').textContent = 'Add User';
        document.getElementById('editUserId').value = '';
        document.getElementById('userUsername').value = '';
        document.getElementById('userUsername').disabled = false;
        document.getElementById('userDisplayName').value = '';
        document.getElementById('userRole').value = 'viewer';
        document.getElementById('resetPasswordGroup').style.display = 'none';
        document.getElementById('userModal').classList.add('active');
    },

    /**
     * Edit existing user
     * @param {number} userId - User ID
     */
    edit(userId) {
        API.get('/api/users')
            .then(data => {
                if (data.success) {
                    const user = data.users.find(u => u.id === userId);
                    if (user) {
                        document.getElementById('userModalTitle').textContent = 'Edit User';
                        document.getElementById('editUserId').value = userId;
                        document.getElementById('userUsername').value = user.username;
                        document.getElementById('userUsername').disabled = true;
                        document.getElementById('userDisplayName').value = user.display_name || '';
                        document.getElementById('userRole').value = user.role;

                        document.getElementById('resetPasswordGroup').style.display =
                            user.role === 'admin' ? 'block' : 'none';
                        document.getElementById('userNewPassword').value = '';

                        document.getElementById('userModal').classList.add('active');
                    }
                }
            });
    },

    /**
     * Close user modal
     */
    closeModal() {
        document.getElementById('userModal').classList.remove('active');
    },

    /**
     * Save user (create or update)
     */
    save() {
        const userId = document.getElementById('editUserId').value;
        const isEdit = !!userId;

        const data = {
            username: document.getElementById('userUsername').value.trim(),
            display_name: document.getElementById('userDisplayName').value.trim(),
            role: document.getElementById('userRole').value
        };

        if (isEdit) {
            const newPassword = document.getElementById('userNewPassword').value;
            if (newPassword) {
                data.new_password = newPassword;
            }
        }

        const url = isEdit ? `/api/users/${userId}/update` : '/api/users/create';

        API.post(url, data)
            .then(result => {
                if (result.success) {
                    showNotification(result.message || 'User saved successfully!', 'success');
                    this.closeModal();
                    setTimeout(() => location.reload(), 1000);
                } else {
                    showNotification(result.error || 'Failed to save user', 'error');
                }
            })
            .catch(() => showNotification('Network error saving user', 'error'));
    },

    /**
     * Delete user
     * @param {number} userId - User ID
     * @param {string} username - Username for confirmation
     */
    delete(userId, username) {
        showConfirm(
            '🗑️ Delete User',
            `Are you sure you want to delete user "${username}"? This action cannot be undone.`,
            () => {
                API.post(`/api/users/${userId}/delete`)
                    .then(result => {
                        if (result.success) {
                            showNotification('User deleted successfully', 'success');
                            const row = document.querySelector(`tr[data-user-id="${userId}"]`);
                            if (row) row.remove();
                        } else {
                            showNotification(result.error || 'Failed to delete user', 'error');
                        }
                    })
                    .catch(() => showNotification('Network error deleting user', 'error'));
            },
            {danger: true}
        );
    }
};

// =============================================================================
// PATH SETTINGS
// =============================================================================

const PathSettings = {
    /**
     * Load path settings from server
     */
    load() {
        API.get('/api/settings/paths')
            .then(data => {
                if (data.success) {
                    // Set input values
                    const romPath = document.getElementById('romPathInput');
                    const esdeGamelists = document.getElementById('esdeGamelistsInput');
                    const esdeMedia = document.getElementById('esdeMediaInput');
                    const rpcs3Trophy = document.getElementById('rpcs3TrophyInput');

                    if (romPath) romPath.value = data.user_overrides.rom_path || '';
                    if (esdeGamelists) esdeGamelists.value = data.user_overrides.esde_gamelists_path || '';
                    if (esdeMedia) esdeMedia.value = data.user_overrides.esde_downloaded_media_path || '';
                    if (rpcs3Trophy) rpcs3Trophy.value = data.user_overrides.rpcs3_trophy_path || '';

                    // Show defaults
                    const romDefault = document.getElementById('romPathDefault');
                    const esdeGlDefault = document.getElementById('esdeGamelistsDefault');
                    const esdeMediaDefault = document.getElementById('esdeMediaDefault');
                    const rpcs3Default = document.getElementById('rpcs3TrophyDefault');

                    if (romDefault) romDefault.textContent = 'Default: ' + (data.config_defaults.rom_path || '(not set)');
                    if (esdeGlDefault) esdeGlDefault.textContent = 'Default: ' + (data.config_defaults.esde_gamelists || '(not set)');
                    if (esdeMediaDefault) esdeMediaDefault.textContent = 'Default: ' + (data.config_defaults.esde_media || '(auto-detect)');
                    if (rpcs3Default) rpcs3Default.textContent = 'Default: ' + (data.config_defaults.rpcs3_trophy || '(not set)');
                }
            })
            .catch(e => console.error('Failed to load path settings:', e));
    },

    /**
     * Save path settings
     */
    save() {
        const data = {
            rom_path: document.getElementById('romPathInput')?.value.trim() || '',
            esde_gamelists: document.getElementById('esdeGamelistsInput')?.value.trim() || '',
            esde_media: document.getElementById('esdeMediaInput')?.value.trim() || '',
            rpcs3_trophy: document.getElementById('rpcs3TrophyInput')?.value.trim() || ''
        };

        API.post('/api/settings/paths', data)
            .then(result => {
                if (result.success) {
                    showNotification('Path settings saved!', 'success');
                    if (result.restart_required) {
                        showNotification('Restart required for changes to take full effect', 'warning');
                    }
                } else {
                    showNotification('Failed to save: ' + result.error, 'error');
                }
            })
            .catch(e => showNotification('Error saving settings: ' + e, 'error'));
    }
};

// =============================================================================
// DISPLAY SETTINGS
// =============================================================================

const DisplaySettings = {
    /**
     * Load display settings
     */
    load() {
        API.get('/api/settings')
            .then(data => {
                if (data.success) {
                    const preferredBoxart = data.settings.preferred_boxart || '2d';
                    const select = document.getElementById('preferredBoxartSelect');
                    if (select) select.value = preferredBoxart;

                    // Set active theme in selector
                    const currentTheme = localStorage.getItem('retrodb-theme') || data.settings.theme || 'cyberpunk';
                    document.querySelectorAll('.theme-option').forEach(el => {
                        el.classList.toggle('active', el.dataset.theme === currentTheme);
                    });
                }
            })
            .catch(e => console.error('Failed to load display settings:', e));
    },

    /**
     * Save display settings
     */
    save() {
        const data = {
            preferred_boxart: document.getElementById('preferredBoxartSelect')?.value || '2d'
        };

        API.post('/api/settings', data)
            .then(result => {
                if (result.success) {
                    showNotification('Display settings saved!', 'success');
                } else {
                    showNotification('Failed to save: ' + result.error, 'error');
                }
            })
            .catch(e => showNotification('Error saving settings: ' + e, 'error'));
    }
};

// =============================================================================
// NOTIFICATION SETTINGS
// =============================================================================

const NotificationSettings = {
    /**
     * Save notification timeout settings
     */
    save() {
        const btn = document.getElementById('saveNotifSettingsBtn');
        if (!btn) return;

        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> Saving...';

        const data = {
            notification_timeouts: {
                success: parseInt(document.getElementById('notifTimeoutSuccess')?.value) || 3,
                info: parseInt(document.getElementById('notifTimeoutInfo')?.value) || 3,
                warning: parseInt(document.getElementById('notifTimeoutWarning')?.value) || 5,
                error: parseInt(document.getElementById('notifTimeoutError')?.value) || 8
            }
        };

        API.post('/api/settings', data)
            .then(result => {
                btn.disabled = false;
                btn.innerHTML = originalText;
                if (result.success) {
                    // Update global notification timeouts
                    if (typeof Notifications !== 'undefined') {
                        Notifications.timeouts = data.notification_timeouts;
                    }
                    showNotification('Notification settings saved!', 'success');
                } else {
                    showNotification('Failed to save: ' + result.error, 'error');
                }
            })
            .catch(e => {
                btn.disabled = false;
                btn.innerHTML = originalText;
                showNotification('Error saving settings: ' + e, 'error');
            });
    },

    /**
     * Test notification with current settings
     */
    test() {
        const successTimeout = parseInt(document.getElementById('notifTimeoutSuccess')?.value) || 3;
        const infoTimeout = parseInt(document.getElementById('notifTimeoutInfo')?.value) || 3;
        const warningTimeout = parseInt(document.getElementById('notifTimeoutWarning')?.value) || 5;
        const errorTimeout = parseInt(document.getElementById('notifTimeoutError')?.value) || 8;

        showNotification(`Success - disappears in ${successTimeout}s`, 'success', successTimeout * 1000);
        showNotification(`Info - disappears in ${infoTimeout}s`, 'info', infoTimeout * 1000);
        showNotification(`Warning - disappears in ${warningTimeout}s`, 'warning', warningTimeout * 1000);
        showNotification(`Error - disappears in ${errorTimeout}s`, 'error', errorTimeout * 1000);
    }
};

// =============================================================================
// CONFIRM MODAL
// =============================================================================

const ConfirmModal = {
    pendingAction: null,

    /**
     * Show confirmation modal
     * @param {string} title - Modal title
     * @param {string} message - Modal message (plain text by default; HTML
     *   only when options.allowHtml is true — Pass 29.1)
     * @param {Function} onConfirm - Callback on confirm
     * @param {Object} [options] - Optional settings
     * @param {boolean} [options.danger=false] - Use red danger styling for destructive actions
     * @param {boolean} [options.allowHtml=false] - Treat `message` as HTML.
     *   Default is text so callers can't inadvertently inject a script sink.
     */
    show(title, message, onConfirm, options = {}) {
        document.getElementById('confirmTitle').textContent = title;
        const messageEl = document.getElementById('confirmMessage');
        if (options.allowHtml) {
            messageEl.innerHTML = message;
        } else {
            messageEl.textContent = message;
        }
        this.pendingAction = onConfirm;

        const cancelBtn = document.getElementById('confirmCancelBtn');
        const confirmBtn = document.getElementById('confirmBtn');

        const isInfoModal = !onConfirm || onConfirm === this.close;

        if (isInfoModal) {
            cancelBtn.style.display = 'none';
            confirmBtn.textContent = 'OK';
            confirmBtn.className = 'btn btn-primary';
        } else {
            cancelBtn.style.display = '';
            confirmBtn.textContent = 'Confirm';
            confirmBtn.className = options.danger ? 'btn btn-danger' : 'btn btn-primary';
        }

        document.getElementById('confirmModal').classList.add('active');
    },

    /**
     * Show info modal (OK button only)
     * @param {string} title - Modal title
     * @param {string} message - Modal message
     * @param {Function} onOk - Optional callback
     */
    showInfo(title, message, onOk, options = {}) {
        document.getElementById('confirmTitle').textContent = title;
        // Pass 29.1: default to textContent so admin-settings diagnostics
        // that pass through arbitrary strings can't become XSS sinks.
        const messageEl = document.getElementById('confirmMessage');
        if (options.allowHtml) {
            messageEl.innerHTML = message;
        } else {
            messageEl.textContent = message;
        }
        this.pendingAction = onOk || null;

        const cancelBtn = document.getElementById('confirmCancelBtn');
        const confirmBtn = document.getElementById('confirmBtn');

        cancelBtn.style.display = 'none';
        confirmBtn.textContent = 'OK';
        confirmBtn.className = 'btn btn-primary';

        document.getElementById('confirmModal').classList.add('active');
    },

    /**
     * Close the modal
     */
    close() {
        document.getElementById('confirmModal').classList.remove('active');
        ConfirmModal.pendingAction = null;

        // Reset button states
        const cancelBtn = document.getElementById('confirmCancelBtn');
        const confirmBtn = document.getElementById('confirmBtn');
        if (cancelBtn) cancelBtn.style.display = '';
        if (confirmBtn) {
            confirmBtn.textContent = 'Confirm';
            confirmBtn.className = 'btn btn-primary';
        }
    },

    /**
     * Execute the pending action
     */
    execute() {
        if (this.pendingAction) {
            this.pendingAction();
        }
        this.close();
    }
};

// =============================================================================
// SCRAPER CONFIGURATION
// =============================================================================

const ScraperConfig = {
    settings: {
        priority: [],
        enabled: {}
    },

    /**
     * Initialize scraper configuration
     * @param {Object} initialSettings - Initial settings from server
     */
    init(initialSettings) {
        this.settings = {
            priority: initialSettings.priority || ['esde', 'tgdb', 'igdb', 'rawg', 'screenscraper'],
            enabled: initialSettings.enabled || {}
        };

        document.addEventListener('DOMContentLoaded', () => {
            this.reorderList();
            this.checkStatus();
            this.initDragDrop();
        });
    },

    /**
     * Reorder scraper list based on priority
     */
    reorderList() {
        const list = document.getElementById('scraperPriorityList');
        if (!list) return;

        const items = Array.from(list.children);

        this.settings.priority.forEach(scraper => {
            const item = items.find(i => i.dataset.scraper === scraper);
            if (item) {
                list.appendChild(item);
            }
        });
    },

    /**
     * Check API status for all scrapers
     */
    checkStatus() {
        API.get('/api/scraper-status')
            .then(data => {
                if (data.success) {
                    Object.entries(data.status).forEach(([scraper, status]) => {
                        const indicator = document.querySelector(
                            `.scraper-item[data-scraper="${scraper}"] .status-indicator`
                        );
                        if (indicator) {
                            indicator.className = 'status-indicator ' +
                                (status.configured ? 'status-ok' : 'status-missing');
                            indicator.title = status.configured ?
                                'API configured' : 'API key missing';
                        }
                    });
                }
            })
            .catch(console.error);
    },

    /**
     * Initialize drag and drop for priority
     */
    initDragDrop() {
        const list = document.getElementById('scraperPriorityList');
        if (!list) return;

        list.querySelectorAll('.scraper-item').forEach(item => {
            item.setAttribute('draggable', 'true');

            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.scraper);
                item.classList.add('dragging');
            });

            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
            });

            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                const dragging = list.querySelector('.dragging');
                if (dragging && dragging !== item) {
                    const rect = item.getBoundingClientRect();
                    const midY = rect.top + rect.height / 2;
                    if (e.clientY < midY) {
                        list.insertBefore(dragging, item);
                    } else {
                        list.insertBefore(dragging, item.nextSibling);
                    }
                }
            });
        });
    },

    /**
     * Toggle scraper enabled state
     * @param {string} scraper - Scraper ID
     * @param {boolean} enabled - Enabled state
     */
    toggle(scraper, enabled) {
        this.settings.enabled[scraper] = enabled;
    },

    /**
     * Save scraper settings
     */
    save() {
        const list = document.getElementById('scraperPriorityList');
        if (!list) return;

        // Get current priority order
        const priority = Array.from(list.children).map(item => item.dataset.scraper);

        // Get enabled states
        const enabled = {};
        list.querySelectorAll('.scraper-toggle').forEach(toggle => {
            const scraper = toggle.closest('.scraper-item')?.dataset.scraper;
            if (scraper) {
                enabled[scraper] = toggle.checked;
            }
        });

        API.post('/api/settings/scrapers', { priority, enabled })
            .then(result => {
                if (result.success) {
                    showNotification('Scraper settings saved!', 'success');
                    this.settings.priority = priority;
                    this.settings.enabled = enabled;
                } else {
                    showNotification('Failed to save: ' + result.error, 'error');
                }
            })
            .catch(e => showNotification('Error saving settings: ' + e, 'error'));
    },

    /**
     * Save API keys
     */
    saveApiKeys() {
        const data = {
            tgdb: document.getElementById('tgdbApiKey')?.value.trim() || '',
            igdb_client_id: document.getElementById('igdbClientId')?.value.trim() || '',
            igdb_client_secret: document.getElementById('igdbClientSecret')?.value.trim() || '',
            rawg: document.getElementById('rawgApiKey')?.value.trim() || '',
            screenscraper_username: document.getElementById('ssUsername')?.value.trim() || '',
            screenscraper_password: document.getElementById('ssPassword')?.value.trim() || '',
            screenscraper_devpassword: document.getElementById('ssDevPassword')?.value.trim() || '',
            ra_username: document.getElementById('raUsername')?.value.trim() || '',
            ra_apikey: document.getElementById('raApiKey')?.value.trim() || ''
        };

        API.post('/api/settings/api-keys', data)
            .then(result => {
                if (result.success) {
                    showNotification('API keys saved!', 'success');
                    this.checkStatus();
                } else {
                    showNotification('Failed to save: ' + result.error, 'error');
                }
            })
            .catch(e => showNotification('Error saving API keys: ' + e, 'error'));
    }
};

// =============================================================================
// LOGO REFERENCE
// =============================================================================

const LogoReference = {
    /**
     * Reload logo reference table
     */
    async reload() {
        try {
            const data = await API.get('/api/systems-list');
            if (data.success && data.systems) {
                this.load(data.systems);
            }
        } catch (error) {
            console.error('Error reloading logo reference:', error);
        }
    },

    /**
     * Load logo reference with systems data
     * @param {Array} systems - Array of system objects
     */
    load(systems) {
        const container = document.getElementById('logoReferenceBody');
        if (!container) return;

        // Pass 29.1: escape every field coming from the /api/systems-list
        // response — slug/id/name/logo can all be edited via the system
        // admin modal, and even under the admin-only threat model escape
        // removes the possibility of a self-XSS / stored-XSS chain.
        let html = '';
        systems.forEach(system => {
            const slugSafe = escapeHtml(system.slug || system.id);
            const nameSafe = escapeHtml(system.name);
            const logoSafe = system.logo ? encodeURIComponent(system.logo) : '';
            html += `
                <tr>
                    <td><code>${slugSafe}</code></td>
                    <td>${nameSafe}</td>
                    <td>
                        ${logoSafe ?
                            `<img src="/static/images/logos/${logoSafe}" alt="${nameSafe}" style="height: 24px;">` :
                            '<span class="text-muted">No logo</span>'
                        }
                    </td>
                </tr>
            `;
        });

        container.innerHTML = html || '<tr><td colspan="3">No systems found</td></tr>';
    }
};

// =============================================================================
// DATABASE BACKUP
// =============================================================================

const DatabaseBackup = {
    /**
     * Create database backup
     */
    create() {
        const btn = document.getElementById('backupBtn');
        if (!btn) return;

        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> Creating backup...';

        API.post('/api/backup/create')
            .then(data => {
                btn.disabled = false;
                btn.innerHTML = '<span class="btn-icon">💾</span> Create Backup';

                if (data.success) {
                    showNotification('Backup created successfully!', 'success');
                    // Refresh backup list if exists
                    if (typeof this.loadList === 'function') {
                        this.loadList();
                    }
                } else {
                    showNotification('Backup failed: ' + data.error, 'error');
                }
            })
            .catch(e => {
                btn.disabled = false;
                btn.innerHTML = '<span class="btn-icon">💾</span> Create Backup';
                showNotification('Error creating backup: ' + e, 'error');
            });
    },

    /**
     * Restore from backup
     * @param {string} filename - Backup filename
     */
    restore(filename) {
        showConfirm(
            '⚠️ Restore Database',
            `Are you sure you want to restore from "${filename}"? This will replace all current data.`,
            () => {
                API.post('/api/backup/restore', { filename })
                    .then(data => {
                        if (data.success) {
                            showNotification('Database restored! Reloading...', 'success');
                            setTimeout(() => location.reload(), 2000);
                        } else {
                            showNotification('Restore failed: ' + data.error, 'error');
                        }
                    })
                    .catch(e => showNotification('Error restoring: ' + e, 'error'));
            },
            {danger: true}
        );
    }
};

// =============================================================================
// CONTROLLER MANAGER
// =============================================================================

const ControllerManager = {
    /**
     * Apply masonry layout to controller grid
     */
    applyMasonry() {
        // Implementation depends on page-specific masonry library
        if (typeof applyControllerMasonry === 'function') {
            applyControllerMasonry();
        }
    }
};

// =============================================================================
// NORMALIZATION MANAGER
// =============================================================================

const NormalizationManager = {
    currentField: 'genre',
    data: [],
    canonicalOptions: [],
    filterChanged: false,

    /**
     * Load normalization preview data for a field
     * @param {string} [field] - Field to load ('genre' or 'modes'), defaults to current
     */
    async load(field) {
        if (field) {
            this.currentField = field;
        }

        // Update button states
        document.querySelectorAll('.norm-field-btn').forEach(btn => btn.classList.remove('active'));
        const activeBtn = document.getElementById(this.currentField === 'genre' ? 'normBtnGenre' : 'normBtnModes');
        if (activeBtn) {
            activeBtn.classList.remove('btn-secondary');
            activeBtn.classList.add('btn-primary', 'active');
        }
        const inactiveBtn = document.getElementById(this.currentField === 'genre' ? 'normBtnModes' : 'normBtnGenre');
        if (inactiveBtn) {
            inactiveBtn.classList.remove('btn-primary', 'active');
            inactiveBtn.classList.add('btn-secondary');
        }

        // Show loading
        const loading = document.getElementById('normLoading');
        const tableContainer = document.getElementById('normTableContainer');
        const empty = document.getElementById('normEmpty');
        if (loading) loading.style.display = '';
        if (tableContainer) tableContainer.style.display = 'none';
        if (empty) empty.style.display = 'none';

        try {
            const result = await API.get(`/api/normalize/preview/${encodeURIComponent(this.currentField)}`);

            if (loading) loading.style.display = 'none';

            if (result.success) {
                this.data = result.values || [];
                this.canonicalOptions = result.canonical_options || [];

                if (this.data.length === 0) {
                    if (empty) empty.style.display = '';
                    return;
                }

                if (tableContainer) tableContainer.style.display = '';
                this.render();
            } else {
                showNotification(result.error || 'Failed to load normalization data', 'error');
            }
        } catch (err) {
            if (loading) loading.style.display = 'none';
            console.error('Normalization load error:', err);
            showNotification('Failed to load normalization data', 'error');
        }
    },

    /**
     * Render the normalization table
     */
    render() {
        const tbody = document.getElementById('normTableBody');
        if (!tbody) return;

        // Build shared datalist with all canonical options
        const allCanonical = new Set(this.canonicalOptions);
        this.data.forEach(item => {
            if (item.suggested) allCanonical.add(item.suggested);
            if (item.value) allCanonical.add(item.value);
        });
        const sortedCanonical = Array.from(allCanonical).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
        let html = '<datalist id="normCanonicalList">';
        sortedCanonical.forEach(opt => {
            html += `<option value="${escapeHtml(opt)}">`;
        });
        html += '</datalist>';

        this.data.forEach((item, idx) => {
            const isHidden = this.filterChanged && !item.needs_change;
            const borderStyle = item.needs_change
                ? 'border-left: 3px solid var(--neon-orange);'
                : '';

            html += `<tr data-idx="${idx}" style="${borderStyle} ${isHidden ? 'display: none;' : ''}">`;

            // Checkbox (row-selection checkboxes are standard table UI, not boolean toggles)
            html += `<td><input type="checkbox" class="norm-row-check" data-idx="${idx}" onchange="NormalizationManager.updateApplyButton()" ${item.needs_change ? 'checked' : ''}></td>`;

            // Current value — escapeHtml from utils.js per security standards
            html += `<td><code>${escapeHtml(item.value)}</code></td>`;

            // Game count
            html += `<td style="text-align: right;">${formatNumber(item.count)}</td>`;

            // Normalize To input — free-text with datalist autocomplete
            html += '<td>';
            const inputValue = item.needs_change ? item.suggested : item.value;
            html += `<input type="text" class="form-input norm-target-input" data-idx="${idx}" list="normCanonicalList" value="${escapeHtml(inputValue)}" style="min-width: 180px;" onchange="NormalizationManager.updateApplyButton()" oninput="NormalizationManager.updateApplyButton()">`;
            html += '</td>';
            html += '</tr>';
        });

        tbody.innerHTML = html;
        this.updateApplyButton();
    },

    /**
     * Toggle filter to show only values needing changes
     */
    toggleFilter() {
        this.filterChanged = document.getElementById('normFilterChanged')?.checked || false;
        this.render();
    },

    /**
     * Select/deselect all visible checkboxes
     */
    toggleSelectAll(checked) {
        document.querySelectorAll('.norm-row-check').forEach(cb => {
            const row = cb.closest('tr');
            if (row && row.style.display !== 'none') {
                cb.checked = checked;
            }
        });
        this.updateApplyButton();
    },

    /**
     * Select all rows that have auto-suggested changes
     */
    selectAllChanged() {
        document.querySelectorAll('.norm-row-check').forEach(cb => {
            const idx = parseInt(cb.dataset.idx);
            const item = this.data[idx];
            cb.checked = item && item.needs_change;
        });
        this.updateApplyButton();
    },

    /**
     * Get selected mappings (old → new)
     */
    getSelectedMappings() {
        const mappings = [];
        document.querySelectorAll('.norm-row-check:checked').forEach(cb => {
            const idx = parseInt(cb.dataset.idx);
            const item = this.data[idx];
            if (!item) return;

            const input = document.querySelector(`.norm-target-input[data-idx="${idx}"]`);
            const newVal = input ? input.value.trim() : '';

            // Only include if there's a target and it differs from current
            if (newVal && newVal.toLowerCase() !== item.value.toLowerCase()) {
                mappings.push({ old: item.value, new: newVal, count: item.count });
            }
        });
        return mappings;
    },

    /**
     * Update the apply button text with count
     */
    updateApplyButton() {
        const mappings = this.getSelectedMappings();
        const btn = document.getElementById('normApplyBtn');
        if (btn) {
            btn.textContent = `Apply ${formatNumber(mappings.length)} Selected`;
            btn.disabled = mappings.length === 0;
        }
    },

    /**
     * Apply selected normalizations
     */
    async apply() {
        const mappings = this.getSelectedMappings();
        if (mappings.length === 0) return;

        // Build confirmation message — escapeHtml from utils.js per security standards
        let msg = '<div style="max-height: 300px; overflow-y: auto; margin-bottom: var(--spacing-sm);">';
        msg += '<table style="width: 100%; font-size: 0.85rem;">';
        msg += '<tr style="border-bottom: 1px solid var(--border-subtle);"><th style="text-align:left; padding: 4px;">From</th><th style="text-align:left; padding: 4px;">To</th><th style="text-align:right; padding: 4px;">Games</th></tr>';
        mappings.forEach(m => {
            msg += `<tr><td style="padding: 4px;"><code>${escapeHtml(m.old)}</code></td>`;
            msg += `<td style="padding: 4px;"><code>${escapeHtml(m.new)}</code></td>`;
            msg += `<td style="text-align:right; padding: 4px;">${m.count}</td></tr>`;
        });
        msg += '</table></div>';
        msg += `<p>Apply ${mappings.length} normalization rule${mappings.length !== 1 ? 's' : ''}?</p>`;

        // Use custom confirm dialog — never browser confirm() per standards
        showConfirm('Apply Normalization', msg, async () => {
            await this._doApply(mappings);
        });
    },

    /**
     * Execute the normalization apply
     */
    async _doApply(mappings) {
        const btn = document.getElementById('normApplyBtn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Applying...';
        }

        try {
            const result = await API.post('/api/normalize/apply', {
                field: this.currentField,
                mappings: mappings.map(m => ({ old: m.old, new: m.new }))
            });

            if (result.success) {
                showNotification(
                    `Normalization applied: ${formatNumber(result.games_updated)} games updated, ${formatNumber(result.rules_saved)} rules saved`,
                    'success'
                );
                // Reload to show updated data
                await this.load();
            } else {
                showNotification(result.error || 'Failed to apply normalization', 'error');
            }
        } catch (err) {
            console.error('Normalization apply error:', err);
            showNotification('Failed to apply normalization', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
            }
            this.updateApplyButton();
        }
    }
};

// =============================================================================
// LEGACY FUNCTION EXPORTS (Backward Compatibility)
// =============================================================================

// Tab Controller
window.switchSettingsTab = (tabId) => TabController.switchTab(tabId);
window.scrollToSection = (sectionId) => TabController.scrollToSection(sectionId);

// User Manager
window.saveUserSettings = () => UserManager.saveSettings();
window.changePassword = () => UserManager.changePassword();
window.showAddUserModal = () => UserManager.showAddModal();
window.editUser = (userId) => UserManager.edit(userId);
window.closeUserModal = () => UserManager.closeModal();
window.saveUser = () => UserManager.save();
window.deleteUser = (userId, username) => UserManager.delete(userId, username);

// Path Settings
window.loadPathSettings = () => PathSettings.load();
window.savePathSettings = () => PathSettings.save();

// Display Settings
window.loadDisplaySettings = () => DisplaySettings.load();
window.saveDisplaySettings = () => DisplaySettings.save();

// Notification Settings
window.saveNotificationSettings = () => NotificationSettings.save();
window.testNotifications = () => NotificationSettings.test();

// Confirm Modal
window.showConfirmModal = (title, message, onConfirm, options) => ConfirmModal.show(title, message, onConfirm, options);
window.showInfoModal = (title, message, onOk) => ConfirmModal.showInfo(title, message, onOk);
window.closeConfirmModal = () => ConfirmModal.close();
window.executeConfirm = () => ConfirmModal.execute();
// Deferred alias — resolves showConfirmModal at call time so the inline
// template version (which shares pendingConfirmAction with executeConfirm) wins.
window.showConfirm = function(title, message, onConfirm, options) { return window.showConfirmModal(title, message, onConfirm, options); };

// Scraper Config
window.reorderScraperList = () => ScraperConfig.reorderList();
window.checkScraperStatus = () => ScraperConfig.checkStatus();
window.initDragAndDrop = () => ScraperConfig.initDragDrop();
window.toggleScraper = (scraper, enabled) => ScraperConfig.toggle(scraper, enabled);
window.saveScraperSettings = () => ScraperConfig.save();
window.saveApiKeys = () => ScraperConfig.saveApiKeys();

// Logo Reference
window.reloadLogoReference = () => LogoReference.reload();
window.loadLogoReference = (systems) => LogoReference.load(systems);

// Database Backup
window.createBackup = () => DatabaseBackup.create();
window.restoreBackup = (filename) => DatabaseBackup.restore(filename);

// Controller Manager
window.applyControllerMasonry = () => ControllerManager.applyMasonry();

// Export modules
window.SettingsPage = SettingsPage;
window.TabController = TabController;
window.UserManager = UserManager;
window.PathSettings = PathSettings;
window.DisplaySettings = DisplaySettings;
window.NotificationSettings = NotificationSettings;
window.ConfirmModal = ConfirmModal;
window.ScraperConfig = ScraperConfig;
window.LogoReference = LogoReference;
window.DatabaseBackup = DatabaseBackup;
window.ControllerManager = ControllerManager;
window.NormalizationManager = NormalizationManager;

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (TabController._scrollObserver) {
        TabController._scrollObserver.disconnect();
        TabController._scrollObserver = null;
    }
});
