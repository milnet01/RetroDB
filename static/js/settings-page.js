/**
 * RetroDB Settings Page Module
 *
 * Holds only what the inline script in templates/settings.html does not
 * define: the field-normalization manager and the `showConfirm` alias.
 * Everything else on the settings page lives in that inline script.
 *
 * Pass 59.35 — this file used to carry a second copy of the settings
 * functions. The inline script redeclared them at top level, overwriting
 * these, so the copies here never ran and had drifted (the tab allowlist and
 * the URL-hash sync existed only here). Keep a single owner: add settings
 * behaviour to the inline script, not to this file.
 */

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
                showNotification(result.error || t('Failed to load normalization data'), 'error');
            }
        } catch (err) {
            if (loading) loading.style.display = 'none';
            console.error('Normalization load error:', err);
            showNotification(t('Failed to load normalization data'), 'error');
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
            btn.textContent = t('Apply {n} Selected', {n: formatNumber(mappings.length)});
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
        msg += `<tr style="border-bottom: 1px solid var(--border-subtle);"><th style="text-align:left; padding: 4px;">${t('From')}</th><th style="text-align:left; padding: 4px;">${t('To')}</th><th style="text-align:right; padding: 4px;">${t('Games')}</th></tr>`;
        mappings.forEach(m => {
            msg += `<tr><td style="padding: 4px;"><code>${escapeHtml(m.old)}</code></td>`;
            msg += `<td style="padding: 4px;"><code>${escapeHtml(m.new)}</code></td>`;
            msg += `<td style="text-align:right; padding: 4px;">${m.count}</td></tr>`;
        });
        msg += '</table></div>';
        const ruleQuestion = mappings.length !== 1
            ? t('Apply {n} normalization rules?', {n: mappings.length})
            : t('Apply {n} normalization rule?', {n: mappings.length});
        msg += `<p>${ruleQuestion}</p>`;

        // Use custom confirm dialog — never browser confirm() per standards
        showConfirm(t('Apply Normalization'), msg, async () => {
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
            btn.textContent = t('Applying...');
        }

        try {
            const result = await API.post('/api/normalize/apply', {
                field: this.currentField,
                mappings: mappings.map(m => ({ old: m.old, new: m.new }))
            });

            if (result.success) {
                showNotification(
                    t('Normalization applied: {games} games updated, {rules} rules saved', {games: formatNumber(result.games_updated), rules: formatNumber(result.rules_saved)}),
                    'success'
                );
                // Reload to show updated data
                await this.load();
            } else {
                showNotification(result.error || t('Failed to apply normalization'), 'error');
            }
        } catch (err) {
            console.error('Normalization apply error:', err);
            showNotification(t('Failed to apply normalization'), 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
            }
            this.updateApplyButton();
        }
    }
};

// Deferred alias — resolves showConfirmModal at call time so the inline
// template version (which shares pendingConfirmAction with executeConfirm) wins.
window.showConfirm = function(title, message, onConfirm, options) { return window.showConfirmModal(title, message, onConfirm, options); };

window.NormalizationManager = NormalizationManager;
