/**
 * RetroDB Settings Page Module
 *
 * Holds only what the inline script in templates/settings.html does not
 * define: the field-normalization manager.
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

// Name fields list spelling groups (PASS-59-298) instead of value rules.
const NORM_NAME_FIELDS = ['franchise', 'publisher', 'developer'];

const NormalizationManager = {
    currentField: 'genre',
    data: [],
    canonicalOptions: [],
    filterChanged: false,

    /** Is the current field a name field, listed as spelling groups? */
    isNames() {
        return NORM_NAME_FIELDS.includes(this.currentField);
    },

    /**
     * Load normalization preview data for a field
     * @param {string} [field] - genre, modes, franchise, publisher or developer; defaults to current
     */
    async load(field) {
        if (field) {
            this.currentField = field;
        }

        // Update button states
        document.querySelectorAll('.norm-field-btn').forEach(btn => {
            const on = btn.dataset.field === this.currentField;
            btn.classList.toggle('active', on);
            btn.classList.toggle('btn-primary', on);
            btn.classList.toggle('btn-secondary', !on);
        });

        // Show loading
        const loading = document.getElementById('normLoading');
        const tableContainer = document.getElementById('normTableContainer');
        const empty = document.getElementById(this.isNames() ? 'normEmptyNames' : 'normEmpty');
        if (loading) loading.style.display = '';
        if (tableContainer) tableContainer.style.display = 'none';
        ['normEmpty', 'normEmptyNames'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });

        try {
            const field = encodeURIComponent(this.currentField);
            const result = await API.get(this.isNames()
                ? `/api/normalize/spellings/${field}`
                : `/api/normalize/preview/${field}`);

            if (loading) loading.style.display = 'none';
            CompanyMerge.load(this.currentField);

            if (result.success) {
                // A spelling group becomes a row: every spelling with its count,
                // the most-used one pre-selected.
                this.data = this.isNames()
                    ? (result.groups || []).map(g => ({
                        value: g.spellings.map(s => s.value).join(', '),
                        count: g.count,
                        suggested: g.suggested,
                        spellings: g.spellings,
                        needs_change: true,
                    }))
                    : (result.values || []);
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
            html += `<td><input type="checkbox" class="norm-row-check" data-idx="${idx}" data-on-change="NormalizationManager.updateApplyButton" ${item.needs_change ? 'checked' : ''}></td>`;

            // Current value — escapeHtml from utils.js per security standards
            html += `<td><code>${escapeHtml(item.value)}</code></td>`;

            // Game count
            html += `<td style="text-align: right;">${formatNumber(item.count)}</td>`;

            if (item.spellings) {
                // A name: pick one of its spellings, nothing else
                html += `<td><select class="form-select norm-target-input" data-idx="${idx}" data-on-change="NormalizationManager.updateApplyButton">`;
                item.spellings.forEach(sp => {
                    const selected = sp.value === item.suggested ? ' selected' : '';
                    html += `<option value="${escapeHtml(sp.value)}"${selected}>${escapeHtml(sp.value)} (${formatNumber(sp.count)})</option>`;
                });
                html += '</select></td></tr>';
                return;
            }

            // Normalize To input — free-text with datalist autocomplete
            html += '<td>';
            const inputValue = item.needs_change ? item.suggested : item.value;
            html += `<input type="text" class="form-input norm-target-input" data-idx="${idx}" list="normCanonicalList" value="${escapeHtml(inputValue)}" style="min-width: 180px;" data-on-change="NormalizationManager.updateApplyButton" data-on-input="NormalizationManager.updateApplyButton">`;
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

            if (item.spellings) {
                const others = item.spellings.map(s => s.value).filter(v => v !== newVal);
                mappings.push({ old: others.join(', '), new: newVal, count: item.count });
                return;
            }

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

        // Build confirmation message. It renders with allowHtml, so every
        // interpolated value goes through escapeHtml (PASS-59-63).
        let msg = '<div style="max-height: 300px; overflow-y: auto; margin-bottom: var(--spacing-sm);">';
        msg += '<table style="width: 100%; font-size: 0.85rem;">';
        msg += `<tr style="border-bottom: 1px solid var(--border-color);"><th style="text-align:left; padding: 4px;">${escapeHtml(t('From'))}</th><th style="text-align:left; padding: 4px;">${escapeHtml(t('To'))}</th><th style="text-align:right; padding: 4px;">${escapeHtml(t('Games'))}</th></tr>`;
        mappings.forEach(m => {
            msg += `<tr><td style="padding: 4px;"><code>${escapeHtml(m.old)}</code></td>`;
            msg += `<td style="padding: 4px;"><code>${escapeHtml(m.new)}</code></td>`;
            msg += `<td style="text-align:right; padding: 4px;">${escapeHtml(String(m.count))}</td></tr>`;
        });
        msg += '</table></div>';
        let ruleQuestion;
        if (this.isNames()) {
            ruleQuestion = mappings.length !== 1
                ? t('Use these {n} spellings?', {n: mappings.length})
                : t('Use this spelling?');
        } else {
            ruleQuestion = mappings.length !== 1
                ? t('Apply {n} normalization rules?', {n: mappings.length})
                : t('Apply {n} normalization rule?', {n: mappings.length});
        }
        msg += `<p>${escapeHtml(ruleQuestion)}</p>`;

        // Use custom confirm dialog — never browser confirm() per standards
        showConfirm(t('Apply Normalization'), msg, async () => {
            await this._doApply(mappings);
        }, { allowHtml: true });
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
            const names = this.isNames();
            const result = names
                ? await API.post('/api/normalize/spellings', {
                    field: this.currentField,
                    spellings: mappings.map(m => m.new)
                })
                : await API.post('/api/normalize/apply', {
                    field: this.currentField,
                    mappings: mappings.map(m => ({ old: m.old, new: m.new }))
                });

            if (result.success) {
                showNotification(
                    names
                        ? t('Spellings applied: {games} games updated', {games: formatNumber(result.games_updated)})
                        : t('Normalization applied: {games} games updated, {rules} rules saved', {games: formatNumber(result.games_updated), rules: formatNumber(result.rules_saved)}),
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


// =============================================================================
// ONE COMPANY UNDER DIFFERENT NAMES (PASS-59-300)
// =============================================================================

// Look-alike publisher and developer names, one row each. Nothing is ticked:
// only the user says two names are one company.
const CompanyMerge = {
    groups: [],

    /** List the look-alikes for publisher or developer; hide the list otherwise. */
    async load(field) {
        const box = document.getElementById('normCompanies');
        if (!box) return;
        if (field !== 'publisher' && field !== 'developer') {
            box.style.display = 'none';
            return;
        }
        try {
            const result = await API.get(`/api/normalize/companies/${encodeURIComponent(field)}`);
            if (!result.success) {
                showNotification(result.error || t('Failed to load normalization data'), 'error');
                return;
            }
            this.groups = result.groups || [];
            box.style.display = '';
            this.render();
        } catch (err) {
            console.error('Company look-alike load error:', err);
            showNotification(t('Failed to load normalization data'), 'error');
        }
    },

    render() {
        const table = document.getElementById('normCompaniesTable');
        const empty = document.getElementById('normCompaniesEmpty');
        if (empty) empty.style.display = this.groups.length ? 'none' : '';
        if (!table) return;
        if (!this.groups.length) {
            table.innerHTML = '';
            return;
        }
        // One block per group: the names to tick, then the kept name and Merge.
        // Blocks, not a table, so a phone wraps them instead of cutting them off.
        const keepLabel = escapeHtml(t('Name to keep'));
        let html = '';
        this.groups.forEach((g, i) => {
            const args = escapeHtml(JSON.stringify([i]));
            html += '<div class="norm-company-row" style="padding: var(--spacing-md) 0; border-bottom: 1px solid var(--border-color);">';
            g.names.forEach(n => {
                html += `<label style="display: block;"><input type="checkbox" class="norm-company-check" data-group="${i}" value="${escapeHtml(n.value)}" data-on-change="CompanyMerge.sync" data-args="${args}"> ${escapeHtml(n.value)} (${formatNumber(n.count)})</label>`;
            });
            html += `<div style="display: flex; flex-wrap: wrap; gap: var(--spacing-sm); align-items: center; margin-top: var(--spacing-sm);"><span>${keepLabel}</span>`;
            html += `<select class="form-select norm-company-keep" data-group="${i}" aria-label="${keepLabel}" style="flex: 1 1 200px; max-width: 360px;" data-on-change="CompanyMerge.sync" data-args="${args}">`;
            g.names.forEach(n => {
                const selected = n.value === g.suggested ? ' selected' : '';
                html += `<option value="${escapeHtml(n.value)}"${selected}>${escapeHtml(n.value)}</option>`;
            });
            html += `</select><button type="button" class="btn btn-sm btn-primary norm-company-merge" data-group="${i}" data-on-click="CompanyMerge.merge" data-args="${args}" disabled>${escapeHtml(t('Merge'))}</button></div></div>`;
        });
        table.innerHTML = html;
        this.groups.forEach((g, i) => this.sync(i));
    },

    _keep(i) {
        return document.querySelector(`.norm-company-keep[data-group="${i}"]`)?.value || '';
    },

    /** Names ticked in row i, apart from the kept one. */
    _ticked(i) {
        const keep = this._keep(i);
        return Array.from(document.querySelectorAll(`.norm-company-check[data-group="${i}"]:checked`))
            .map(cb => cb.value).filter(v => v !== keep);
    },

    /** The kept name cannot be ticked; Merge needs one ticked name. */
    sync(i) {
        const keep = this._keep(i);
        document.querySelectorAll(`.norm-company-check[data-group="${i}"]`).forEach(cb => {
            const isKeep = cb.value === keep;
            cb.disabled = isKeep;
            if (isKeep) cb.checked = false;
        });
        const btn = document.querySelector(`.norm-company-merge[data-group="${i}"]`);
        if (btn) btn.disabled = this._ticked(i).length === 0;
    },

    merge(i) {
        const keep = this._keep(i);
        const merge = this._ticked(i);
        if (!keep || !merge.length) return;
        // Renders with allowHtml, so every name goes through escapeHtml.
        let msg = `<p>${escapeHtml(t('Change these names to "{name}" on every game?', {name: keep}))}</p><ul>`;
        merge.forEach(m => { msg += `<li><code>${escapeHtml(m)}</code></li>`; });
        msg += '</ul>';
        showConfirm(t('Merge'), msg, async () => {
            try {
                const result = await API.post('/api/normalize/companies', {keep, merge});
                if (result.success) {
                    showNotification(t('Names merged: {games} games updated', {games: formatNumber(result.games_updated)}), 'success');
                    await NormalizationManager.load();
                } else {
                    showNotification(result.error || t('Failed to apply normalization'), 'error');
                }
            } catch (err) {
                console.error('Company merge error:', err);
                showNotification(t('Failed to apply normalization'), 'error');
            }
        }, { allowHtml: true });
    },
};


window.NormalizationManager = NormalizationManager;
window.CompanyMerge = CompanyMerge;
