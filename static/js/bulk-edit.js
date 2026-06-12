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

    // Fields that support append mode (comma-separated values)
    // Keep in lockstep with appendable_fields in routes/games.py (region is a
    // single-value field and is intentionally NOT appendable).
    const APPENDABLE_FIELDS = ['genre', 'publisher', 'developer', 'franchise', 'game_structure'];

    /**
     * Open the bulk edit modal with the given game IDs
     * @param {number[]} ids - Array of game IDs to edit
     */
    async function open(ids) {
        if (!ids || ids.length === 0) {
            showModal(t('No Games Selected'), t('Please select at least one game to edit.'));
            return;
        }

        gameIds = ids;

        // Abort any in-flight dropdown fetches from a previous open
        if (_abortController) _abortController.abort();
        _abortController = new AbortController();

        // Reset all form fields
        const modal = document.getElementById('bulkEditModal');
        if (!modal) return;

        // Reset selects to default
        modal.querySelectorAll('select[data-field]').forEach(sel => { sel.value = ''; });
        // Reset text/number inputs
        modal.querySelectorAll('input[data-field]').forEach(inp => { inp.value = ''; });
        // Reset all append toggles to unchecked (Replace mode)
        modal.querySelectorAll('.bulk-append-toggle').forEach(toggle => { toggle.checked = false; });

        // Update count
        const countEl = document.getElementById('bulkEditCount');
        if (countEl) countEl.textContent = formatNumber(ids.length);

        // Load dropdown options in parallel
        await Promise.all([
            loadGameStructureOptions(),
            loadGenreOptions(),
            loadPerspectiveOptions(),
            loadDimensionOptions()
        ]);

        // Show modal
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

        select.innerHTML = `<option value="">${t("-- Don't change --")}</option>`;

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

        select.innerHTML = `<option value="">${t("-- Don't change --")}</option>`;

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

        select.innerHTML = `<option value="">${t("-- Don't change --")}</option>`;

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

        select.innerHTML = `<option value="">${t("-- Don't change --")}</option>`;

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

        // Collect from selects
        modal.querySelectorAll('select[data-field]').forEach(sel => {
            if (sel.value !== '') {
                changes[sel.dataset.field] = sel.value;
            }
        });

        // Collect from text/number inputs (only if user typed something)
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
            showModal(t('No Changes'), t('Please change at least one field before applying.'));
            return;
        }

        const fieldNames = Object.keys(fields).map(f => f.replace(/_/g, ' ')).join(', ');
        const msg = t('Update {count} game(s)?\n\nFields: {fields}', { count: formatNumber(gameIds.length), fields: fieldNames });

        // Use custom confirm dialog — never browser confirm() per standards
        showConfirm(t('Confirm Bulk Edit'), msg, async function() {
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
            applyBtn.textContent = t('Applying...');
        }

        try {
            const appendModes = collectAppendModes();

            // Build field_modes: only include modes for fields being changed
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
                showNotification(t('Successfully updated {count} games', {count: formatNumber(data.updated)}), 'success');
                // Reload page to reflect changes
                setTimeout(() => location.reload(), 500);
            } else {
                showModal(t('Error'), data.error || t('Unknown error occurred.'));
            }
        } catch (err) {
            console.error('Bulk edit error:', err);
            showModal(t('Error'), t('Failed to apply bulk edit. Check console for details.'));
        } finally {
            if (applyBtn) {
                applyBtn.disabled = false;
                applyBtn.textContent = t('Apply Changes');
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

    // Expose globally
    window.closeBulkEditModal = close;

    return {
        open,
        apply,
        close
    };
})();

RetroDB.BulkEditController = BulkEditController;
window.BulkEditController = BulkEditController;
