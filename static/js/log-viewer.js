/**
 * RetroDB Universal Log Viewer
 * Client-side parsing, filtering, and rendering of log files across all categories.
 */

const LogViewer = {
    // State
    rawLines: [],
    sessions: [],
    currentView: 'grouped',
    activeLevels: new Set(['INFO', 'WARNING', 'ERROR']),
    activeModule: '',
    searchTerm: '',
    searchDebounce: null,
    currentFile: null,
    currentCategory: '',       // Active category tab filter ('' = all)
    loadedCategory: '',        // Category of the currently loaded file
    allFiles: [],              // All log files from API
    categoryCounts: {},        // { scraping: 3, rom_tools: 1, ... }

    // Category display names
    CATEGORY_LABELS: {
        'scraping': 'Scraping',
        'rom_tools': 'ROM Tools',
        'rom_reports': 'Reports',
        'image_resize': 'Image Resize',
        'system': 'System'
    },

    // Session-start patterns (only meaningful for scraping logs)
    SESSION_PATTERNS: [
        {
            regex: /Searching for: '(.+?)' on system: (.+?) \(folder:/,
            module: 'scraper.scraper_manager',
            extract: (m) => ({ title: m[1], system: m[2] })
        },
        {
            regex: /Scraping: (.+?) for (.+)$/,
            module: 'services.jobs',
            extract: (m) => ({ title: m[1], system: m[2] })
        }
    ],

    // Outcome patterns
    OUTCOME_SUCCESS: /Updated .+ with \d+ fields? from/,
    OUTCOME_SKIPPED: /Skipping |No updates for /,
    OUTCOME_NO_RESULTS: /No results for /,

    // Line parse regex: "YYYY-MM-DD HH:MM:SS | LEVEL    | module | message"
    LINE_REGEX: /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \| (\w+)\s*\| ([^ |]+)\s*\| (.*)$/,

    // =========================================================================
    // INITIALIZATION
    // =========================================================================

    init() {
        this.loadFileList();

        document.getElementById('logFileSelect').addEventListener('change', (e) => {
            if (e.target.value) this.loadFile(e.target.value);
        });

        document.getElementById('logSearch').addEventListener('input', (e) => {
            clearTimeout(this.searchDebounce);
            this.searchDebounce = setTimeout(() => {
                this.searchTerm = e.target.value.trim().toLowerCase();
                this.render();
            }, 300);
        });

        document.getElementById('timeFrom').addEventListener('change', () => this.render());
        document.getElementById('timeTo').addEventListener('change', () => this.render());
    },

    // =========================================================================
    // CATEGORY TABS
    // =========================================================================

    setCategory(category, btn) {
        this.currentCategory = category;

        // Update tab active state
        document.querySelectorAll('.category-tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');

        // Re-populate file dropdown with filtered files
        this.populateFileDropdown();
    },

    updateCategoryCounts() {
        const countEl = (id, count) => {
            const el = document.getElementById(id);
            if (el) el.textContent = count || 0;
        };

        let total = 0;
        for (const c in this.categoryCounts) {
            total += this.categoryCounts[c];
        }

        countEl('countAll', total);
        countEl('countScraping', this.categoryCounts['scraping']);
        countEl('countRomTools', this.categoryCounts['rom_tools']);
        countEl('countReports', this.categoryCounts['rom_reports']);
        countEl('countImageResize', this.categoryCounts['image_resize']);
        countEl('countSystem', this.categoryCounts['system']);
    },

    // =========================================================================
    // FILE LOADING
    // =========================================================================

    async loadFileList() {
        try {
            const data = await API.get('/api/logs/files');
            if (!data.success) return;

            this.allFiles = data.files;
            this.categoryCounts = data.category_counts || {};
            this.updateCategoryCounts();
            this.populateFileDropdown();
        } catch (e) {
            console.error('Error loading log file list:', e);
        }
    },

    populateFileDropdown() {
        const select = document.getElementById('logFileSelect');
        const files = this.currentCategory
            ? this.allFiles.filter(f => f.category === this.currentCategory)
            : this.allFiles;

        select.innerHTML = '<option value="">-- Select log file --</option>';

        files.forEach(f => {
            const sizeKB = (f.size / 1024).toFixed(1);
            const opt = document.createElement('option');
            opt.value = f.filename;

            // Show category prefix when viewing "All"
            const label = this.currentCategory
                ? `${f.date} (${sizeKB} KB)`
                : `[${this.CATEGORY_LABELS[f.category] || f.category}] ${f.date} (${sizeKB} KB)`;
            opt.textContent = label;
            select.appendChild(opt);
        });

        // If current file is still in the filtered list, keep it selected
        if (this.currentFile && files.some(f => f.filename === this.currentFile)) {
            select.value = this.currentFile;
        } else if (files.length > 0) {
            // Auto-select most recent file
            select.value = files[0].filename;
            this.loadFile(files[0].filename);
        } else {
            // No files in this category
            this.currentFile = null;
            document.getElementById('fileActions').style.display = 'none';
            document.getElementById('logStatsBar').style.display = 'none';
            document.getElementById('logContainer').innerHTML =
                '<div class="log-empty"><div class="log-empty-icon">No log files in this category</div></div>';
        }
    },

    async loadFile(filename) {
        this.currentFile = filename;
        const container = document.getElementById('logContainer');
        container.innerHTML = '<div class="log-loading"><div class="loading-spinner"></div> Loading log file...</div>';

        // Show file action buttons
        document.getElementById('fileActions').style.display = 'flex';

        try {
            const data = await API.get(`/api/logs/content/${encodeURIComponent(filename)}`);
            if (!data.success) {
                container.innerHTML = `<div class="log-empty"><div class="log-empty-icon">${escapeHtml(data.error || 'Error loading file')}</div></div>`;
                return;
            }

            this.loadedCategory = data.category || '';
            this.parseContent(data.content);

            // Smart view mode: grouped for scraping, flat for everything else
            this.applySmartViewMode();
            this.render();
        } catch (e) {
            container.innerHTML = '<div class="log-empty"><div class="log-empty-icon">Error loading log file</div></div>';
            console.error('Error loading log file:', e);
        }
    },

    applySmartViewMode() {
        const isScrapingLog = this.loadedCategory === 'scraping';
        const viewToggleGroup = document.getElementById('viewToggleGroup');
        const viewToggleSep = document.getElementById('viewToggleSep');
        const sessionsWrap = document.getElementById('statSessionsWrap');

        if (isScrapingLog) {
            // Show view toggle and sessions stat
            viewToggleGroup.style.display = '';
            viewToggleSep.style.display = '';
            sessionsWrap.style.display = '';
            this.currentView = 'grouped';
        } else {
            // Hide view toggle and sessions stat for non-scraping logs
            viewToggleGroup.style.display = 'none';
            viewToggleSep.style.display = 'none';
            sessionsWrap.style.display = 'none';
            this.currentView = 'flat';
        }

        // Update button active states
        document.querySelectorAll('.view-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.view === this.currentView);
        });
    },

    // =========================================================================
    // FILE ACTIONS
    // =========================================================================

    downloadFile() {
        if (!this.currentFile) return;
        window.open(`/api/logs/download/${encodeURIComponent(this.currentFile)}`, '_blank');
    },

    deleteFile() {
        if (!this.currentFile) return;
        const filename = this.currentFile;

        showConfirm('Delete Log File', `Are you sure you want to delete "${filename}"?`, async () => {
            try {
                const resp = await fetch(`/api/logs/delete/${encodeURIComponent(filename)}`, {
                    method: 'DELETE'
                });
                const data = await resp.json();
                if (data.success) {
                    showNotification('Log file deleted', 'success');
                    this.currentFile = null;
                    document.getElementById('fileActions').style.display = 'none';
                    await this.loadFileList();
                } else {
                    showNotification(data.error || 'Failed to delete', 'error');
                }
            } catch (e) {
                showNotification('Error deleting log file', 'error');
            }
        });
    },

    // =========================================================================
    // PARSING
    // =========================================================================

    parseContent(content) {
        const lines = content.split('\n');
        this.rawLines = [];

        for (let i = 0; i < lines.length; i++) {
            const raw = lines[i];
            if (!raw.trim()) continue;

            const match = raw.match(this.LINE_REGEX);
            if (match) {
                this.rawLines.push({
                    lineNumber: i + 1,
                    date: match[1],
                    time: match[2],
                    timestamp: match[1] + ' ' + match[2],
                    level: match[3],
                    module: match[4],
                    message: match[5],
                    raw: raw
                });
            } else {
                // Non-matching lines (continuation, etc.) — attach to previous line
                if (this.rawLines.length > 0) {
                    this.rawLines[this.rawLines.length - 1].message += '\n' + raw;
                    this.rawLines[this.rawLines.length - 1].raw += '\n' + raw;
                }
            }
        }

        // Only build sessions for scraping logs
        if (this.loadedCategory === 'scraping') {
            this.buildSessions();
        } else {
            this.sessions = [];
        }

        this.populateModuleDropdown();
    },

    buildSessions() {
        this.sessions = [];
        let currentSession = null;

        for (const line of this.rawLines) {
            let sessionStart = null;
            for (const pattern of this.SESSION_PATTERNS) {
                if (line.module === pattern.module || line.message.match(pattern.regex)) {
                    const m = line.message.match(pattern.regex);
                    if (m) {
                        sessionStart = pattern.extract(m);
                        break;
                    }
                }
            }

            if (sessionStart) {
                if (currentSession) {
                    this.finalizeSession(currentSession);
                    this.sessions.push(currentSession);
                }
                currentSession = {
                    title: sessionStart.title,
                    system: sessionStart.system,
                    startTime: line.time,
                    endTime: line.time,
                    lines: [line],
                    outcome: 'unknown'
                };
            } else if (currentSession) {
                currentSession.lines.push(line);
                currentSession.endTime = line.time;
            } else {
                currentSession = {
                    title: 'Pre-session log entries',
                    system: '',
                    startTime: line.time,
                    endTime: line.time,
                    lines: [line],
                    outcome: 'unknown'
                };
            }
        }

        if (currentSession) {
            this.finalizeSession(currentSession);
            this.sessions.push(currentSession);
        }
    },

    finalizeSession(session) {
        for (let i = session.lines.length - 1; i >= 0; i--) {
            const line = session.lines[i];
            if (this.OUTCOME_SUCCESS.test(line.message)) {
                session.outcome = 'success';
                return;
            }
            if (this.OUTCOME_SKIPPED.test(line.message)) {
                session.outcome = 'skipped';
                return;
            }
            if (line.level === 'ERROR' || this.OUTCOME_NO_RESULTS.test(line.message)) {
                session.outcome = 'error';
                return;
            }
        }
    },

    // =========================================================================
    // FILTERING
    // =========================================================================

    _matchesFilters(line, timeFrom, timeTo) {
        if (!this.activeLevels.has(line.level)) return false;
        if (this.activeModule && line.module !== this.activeModule) return false;
        if (timeFrom && line.time < timeFrom) return false;
        if (timeTo && line.time > timeTo) return false;
        if (this.searchTerm) {
            const haystack = (line.message + ' ' + line.module + ' ' + line.level).toLowerCase();
            if (!haystack.includes(this.searchTerm)) return false;
        }
        return true;
    },

    getFilteredLines() {
        const timeFrom = document.getElementById('timeFrom').value || '';
        const timeTo = document.getElementById('timeTo').value || '';
        return this.rawLines.filter(line => this._matchesFilters(line, timeFrom, timeTo));
    },

    getFilteredSessions() {
        const timeFrom = document.getElementById('timeFrom').value || '';
        const timeTo = document.getElementById('timeTo').value || '';

        return this.sessions.map(session => {
            const filteredLines = session.lines.filter(line => this._matchesFilters(line, timeFrom, timeTo));
            return { ...session, filteredLines };
        }).filter(s => s.filteredLines.length > 0);
    },

    // =========================================================================
    // RENDERING
    // =========================================================================

    render() {
        if (this.currentView === 'grouped') {
            this.renderGrouped();
        } else {
            this.renderFlat();
        }
    },

    renderFlat() {
        const filtered = this.getFilteredLines();
        this.updateStats(filtered.length, null);

        const container = document.getElementById('logContainer');

        if (filtered.length === 0) {
            container.innerHTML = '<div class="log-empty"><div class="log-empty-icon">No log lines match current filters</div></div>';
            return;
        }

        const chunks = [];
        for (const line of filtered) {
            chunks.push(this.renderLine(line));
        }
        container.innerHTML = chunks.join('');
    },

    renderGrouped() {
        const filtered = this.getFilteredSessions();
        const totalLines = filtered.reduce((sum, s) => sum + s.filteredLines.length, 0);
        this.updateStats(totalLines, filtered.length);

        const container = document.getElementById('logContainer');

        if (filtered.length === 0) {
            container.innerHTML = '<div class="log-empty"><div class="log-empty-icon">No sessions match current filters</div></div>';
            return;
        }

        const chunks = [];
        for (let i = 0; i < filtered.length; i++) {
            const session = filtered[i];
            const badgeClass = session.outcome;
            const badgeLabel = session.outcome === 'unknown' ? '...' : session.outcome;

            chunks.push(`<div class="log-session" data-session="${i}">`);
            chunks.push(`<div class="log-session-header" onclick="LogViewer.toggleSession(this)">`);
            chunks.push(`<span class="session-toggle">\u25B6</span>`);
            chunks.push(`<span class="session-title">${this.escapeHtml(session.title)}</span>`);
            if (session.system) {
                chunks.push(`<span class="session-system">${this.escapeHtml(session.system)}</span>`);
            }
            chunks.push(`<span class="session-time">${this.escapeHtml(session.startTime)}</span>`);
            chunks.push(`<span class="session-badge ${badgeClass}">${badgeLabel}</span>`);
            chunks.push(`<span class="session-line-count">${session.filteredLines.length} lines</span>`);
            chunks.push(`</div>`);

            chunks.push(`<div class="log-session-body">`);
            for (const line of session.filteredLines) {
                chunks.push(this.renderLine(line));
            }
            chunks.push(`</div></div>`);
        }

        container.innerHTML = chunks.join('');
    },

    renderLine(line) {
        const message = this.searchTerm
            ? this.highlightSearch(this.escapeHtml(line.message))
            : this.escapeHtml(line.message);

        // Pass 36.4 — lineNumber / time / level flow from a log file on disk
        // and land inside innerHTML'd template strings. Escape each one so
        // a malformed rotated-log parser emitting `INFO"><script>` (or a
        // log file a user has write access to) can't smuggle a payload.
        // `level` additionally gets allowlisted before it's used as a CSS
        // class name — arbitrary attacker content would otherwise become
        // a selector and the unquoted class attribute would swallow it.
        const LEVELS = new Set(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']);
        const rawLevel = String(line.level || '');
        const levelClass = LEVELS.has(rawLevel.toUpperCase()) ? rawLevel.toUpperCase() : 'UNKNOWN';
        const lineNumberSafe = this.escapeHtml(String(line.lineNumber || ''));
        const timeSafe = this.escapeHtml(String(line.time || ''));
        const levelSafe = this.escapeHtml(rawLevel);

        return `<div class="log-line level-${levelClass}">` +
            `<span class="log-line-number">${lineNumberSafe}</span>` +
            `<span class="log-line-time">${timeSafe}</span>` +
            `<span class="log-line-level ${levelClass}">${levelSafe}</span>` +
            `<span class="log-line-module">${this.shortenModule(this.escapeHtml(line.module))}</span>` +
            `<span class="log-line-message">${message}</span>` +
            `</div>`;
    },

    highlightSearch(html) {
        if (!this.searchTerm) return html;
        const escaped = this.escapeRegex(this.searchTerm);
        const regex = new RegExp(`(${escaped})`, 'gi');
        return html.replace(regex, '<span class="search-highlight">$1</span>');
    },

    shortenModule(mod) {
        // Generic module name shortening for readability
        return mod
            .replace('scraper.scrape_', '')
            .replace('scraper.', '')
            .replace('services.jobs.', 'jobs/')
            .replace('services.', '');
    },

    // =========================================================================
    // STATS
    // =========================================================================

    updateStats(showingCount, sessionCount) {
        const bar = document.getElementById('logStatsBar');
        bar.style.display = 'flex';

        document.getElementById('statTotal').textContent = formatNumber(this.rawLines.length);
        document.getElementById('statShowing').textContent = formatNumber(showingCount);

        let info = 0, warn = 0, error = 0;
        for (const line of this.rawLines) {
            if (line.level === 'INFO') info++;
            else if (line.level === 'WARNING') warn++;
            else if (line.level === 'ERROR') error++;
        }
        document.getElementById('statInfo').textContent = formatNumber(info);
        document.getElementById('statWarn').textContent = formatNumber(warn);
        document.getElementById('statError').textContent = formatNumber(error);

        const sessionsEl = document.getElementById('statSessions');
        if (sessionsEl) {
            sessionsEl.textContent = formatNumber(sessionCount !== null ? sessionCount : this.sessions.length);
        }
    },

    // =========================================================================
    // UI INTERACTIONS
    // =========================================================================

    toggleLevel(level, btn) {
        btn.classList.toggle('active');
        if (this.activeLevels.has(level)) {
            this.activeLevels.delete(level);
        } else {
            this.activeLevels.add(level);
        }
        this.render();
    },

    setView(view, btn) {
        this.currentView = view;
        document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.render();
    },

    setModuleFilter(module) {
        this.activeModule = module;
        this.render();
    },

    resetFilters() {
        // Reset levels
        this.activeLevels = new Set(['INFO', 'WARNING', 'ERROR']);
        document.querySelectorAll('.level-btn').forEach(btn => btn.classList.add('active'));

        // Reset time
        document.getElementById('timeFrom').value = '';
        document.getElementById('timeTo').value = '';

        // Reset module
        this.activeModule = '';
        document.getElementById('logModuleFilter').value = '';

        // Reset search
        this.searchTerm = '';
        document.getElementById('logSearch').value = '';

        // Reapply smart view mode
        this.applySmartViewMode();

        this.render();
    },

    populateModuleDropdown() {
        const modules = new Set();
        for (const line of this.rawLines) {
            modules.add(line.module);
        }

        const select = document.getElementById('logModuleFilter');
        const current = select.value;
        select.innerHTML = '<option value="">All Sources</option>';

        const sorted = [...modules].sort();
        for (const mod of sorted) {
            const opt = document.createElement('option');
            opt.value = mod;
            opt.textContent = this.shortenModule(mod);
            select.appendChild(opt);
        }

        // Restore previous selection if still valid
        if (current && modules.has(current)) {
            select.value = current;
        }
    },

    toggleSession(headerEl) {
        const sessionEl = headerEl.parentElement;
        sessionEl.classList.toggle('open');
    },

    // =========================================================================
    // UTILITIES
    // =========================================================================

    escapeHtml(text) {
        if (typeof window.escapeHtml === 'function') return window.escapeHtml(text);
        if (!text) return '';
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
        return text.replace(/[&<>"']/g, m => map[m]);
    },

    escapeRegex(str) {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    LogViewer.init();
});
