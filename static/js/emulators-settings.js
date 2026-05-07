// =============================================================================
// RETRODB - Settings → Emulators page
// =============================================================================
// Pass 44 — wires the RetroArch auto-detect button, lists emulators in the
// registry, and lists per-system mappings.  Page-specific JS (not bundled).
//
// Pass 44.1 — adds: AppImage scanner (POST /api/settings/emulators/detect
// with apply=true|false), per-row Edit button → emuEditModal, save via
// PUT /api/emulators/<id>.
// =============================================================================

(function () {
    'use strict';

    const $ = (sel) => document.querySelector(sel);
    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    const fetchJSON = async (url, opts = {}) => {
        opts.headers = Object.assign(
            {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
            opts.headers || {}
        );
        const rv = await fetch(url, opts);
        const body = await rv.json().catch(() => ({}));
        if (!rv.ok || body.success === false) {
            throw new Error(body.error || rv.statusText);
        }
        return body;
    };

    // ----- RetroArch panel ---------------------------------------------------

    const detectBtn = $('#ra-detect-btn');
    const saveBtn = $('#ra-save-btn');
    const statusLine = $('#ra-status');

    if (detectBtn) {
        detectBtn.addEventListener('click', async () => {
            statusLine.textContent = 'Detecting…';
            try {
                const out = await fetchJSON(
                    '/api/settings/retroarch/detect?validate=true',
                    {method: 'POST'}
                );
                $('#ra-binary').value = out.data.binary.path || '';
                $('#ra-cores-dir').value = out.data.cores_dir.path || '';
                const bv = out.data.binary.version || out.data.binary.error || '';
                const cn = out.data.cores_dir.core_count
                    ? `${out.data.cores_dir.core_count} cores`
                    : (out.data.cores_dir.error || '');
                statusLine.textContent = `${bv} · ${cn}`;
            } catch (e) {
                statusLine.textContent = 'Detect failed: ' + e.message;
            }
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            statusLine.textContent = 'Saving…';
            try {
                await fetchJSON('/api/settings', {
                    method: 'PUT',
                    body: JSON.stringify({
                        retroarch_binary:    $('#ra-binary').value.trim(),
                        retroarch_cores_dir: $('#ra-cores-dir').value.trim(),
                    }),
                });
                statusLine.textContent = 'Saved.';
            } catch (e) {
                statusLine.textContent = 'Save failed: ' + e.message;
            }
        });
    }

    // ----- Pass 44.1B — AppImage scanner -------------------------------------

    const emuDetectBtn = $('#emu-detect-btn');
    const emuApplyBtn = $('#emu-apply-btn');
    const emuDetectStatus = $('#emu-detect-status');
    const emuDetectResults = $('#emu-detect-results');

    function renderSuggestions(suggestions) {
        if (!suggestions || suggestions.length === 0) {
            emuDetectResults.innerHTML = '<span class="text-muted">No emulator AppImages found in the scan paths.</span>';
            emuApplyBtn.disabled = true;
            return;
        }
        const wrap = document.createElement('table');
        wrap.className = 'data-table';
        wrap.innerHTML = '<thead><tr><th>Emulator</th><th>Detected path</th><th>Currently set</th><th>Will change?</th></tr></thead>';
        const tbody = document.createElement('tbody');
        for (const s of suggestions) {
            const tr = document.createElement('tr');
            const name = document.createElement('td');
            name.textContent = s.emulator_name;
            const path = document.createElement('td');
            const code = document.createElement('code');
            code.textContent = s.preferred_path;
            path.appendChild(code);
            if (s.has_portable_script) {
                const tag = document.createElement('span');
                tag.style.cssText = 'margin-left:0.4rem;color:var(--neon-green);font-size:0.8rem;';
                tag.textContent = '(portable.sh)';
                path.appendChild(tag);
            }
            const cur = document.createElement('td');
            cur.textContent = s.current_override || '(not set)';
            cur.style.color = 'var(--text-muted)';
            const chg = document.createElement('td');
            chg.textContent = s.would_change ? 'Yes' : 'No (already set)';
            chg.style.color = s.would_change ? 'var(--neon-green)' : 'var(--text-muted)';
            tr.appendChild(name);
            tr.appendChild(path);
            tr.appendChild(cur);
            tr.appendChild(chg);
            tbody.appendChild(tr);
        }
        wrap.appendChild(tbody);
        emuDetectResults.innerHTML = '';
        emuDetectResults.appendChild(wrap);
        emuApplyBtn.disabled = !suggestions.some(s => s.would_change);
    }

    if (emuDetectBtn) {
        emuDetectBtn.addEventListener('click', async () => {
            emuDetectStatus.textContent = 'Scanning…';
            emuDetectResults.innerHTML = '';
            emuApplyBtn.disabled = true;
            try {
                const out = await fetchJSON('/api/settings/emulators/detect', {method: 'POST'});
                emuDetectStatus.textContent = `Scanned ${(out.scanned_paths || []).length} paths · found ${out.found_count || 0} matches.`;
                renderSuggestions(out.suggestions);
            } catch (e) {
                emuDetectStatus.textContent = 'Scan failed: ' + e.message;
            }
        });
    }

    if (emuApplyBtn) {
        emuApplyBtn.addEventListener('click', async () => {
            emuApplyBtn.disabled = true;
            emuDetectStatus.textContent = 'Applying…';
            try {
                const out = await fetchJSON('/api/settings/emulators/detect?apply=true', {method: 'POST'});
                emuDetectStatus.textContent = `Applied ${(out.applied || []).length} update(s).`;
                renderSuggestions(out.suggestions);
                refreshEmulators();
            } catch (e) {
                emuDetectStatus.textContent = 'Apply failed: ' + e.message;
                emuApplyBtn.disabled = false;
            }
        });
    }

    // ----- Pass 44.1C — Edit-emulator modal ----------------------------------

    function openEmuEditModal(row) {
        $('#emu_edit_id').value = row.id;
        $('#emu_edit_name').value = row.name || '';
        $('#emu_edit_binary_name').value = row.binary_name || '';
        $('#emu_edit_binary_path_override').value = row.binary_path_override || '';
        $('#emu_edit_args_template').value = row.args_template || '';
        $('#emu_edit_description').value = row.description || '';
        $('#emu_edit_is_retroarch').checked = !!row.is_retroarch;
        $('#emu_edit_enabled').checked = !!row.enabled;
        $('#emuEditModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    function closeEmuEditModal() {
        $('#emuEditModal').classList.remove('active');
        document.body.style.overflow = '';
    }
    window.closeEmuEditModal = closeEmuEditModal;

    const editForm = $('#emuEditForm');
    if (editForm) {
        editForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const id = $('#emu_edit_id').value;
            const payload = {
                name:                 $('#emu_edit_name').value.trim(),
                binary_name:          $('#emu_edit_binary_name').value.trim(),
                binary_path_override: $('#emu_edit_binary_path_override').value.trim() || null,
                args_template:        $('#emu_edit_args_template').value,
                description:          $('#emu_edit_description').value.trim() || null,
                is_retroarch:         $('#emu_edit_is_retroarch').checked,
                enabled:              $('#emu_edit_enabled').checked,
            };
            try {
                await fetchJSON(`/api/emulators/${id}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload),
                });
                closeEmuEditModal();
                refreshEmulators();
            } catch (e) {
                alert('Save failed: ' + e.message);
            }
        });
    }

    // ----- Emulators list ----------------------------------------------------

    let _lastEmulators = [];

    async function refreshEmulators() {
        const tbody = $('#emu-tbody');
        try {
            const out = await fetchJSON('/api/emulators');
            _lastEmulators = out.emulators || [];
            if (_lastEmulators.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-muted">No emulators registered.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            for (const e of _lastEmulators) {
                const tr = document.createElement('tr');
                const name = document.createElement('td');
                name.textContent = e.name || '';
                const bin = document.createElement('td');
                const code = document.createElement('code');
                code.textContent = e.binary_name || '';
                bin.appendChild(code);
                const override = document.createElement('td');
                if (e.binary_path_override) {
                    const c = document.createElement('code');
                    c.textContent = e.binary_path_override;
                    c.style.fontSize = '0.8rem';
                    override.appendChild(c);
                } else {
                    override.textContent = '(none)';
                    override.style.color = 'var(--text-muted)';
                }
                const args = document.createElement('td');
                const codeArgs = document.createElement('code');
                codeArgs.textContent = e.args_template || '';
                codeArgs.style.fontSize = '0.8rem';
                args.appendChild(codeArgs);
                const type = document.createElement('td');
                type.textContent = e.is_retroarch ? 'RetroArch' : 'Standalone';
                const enabled = document.createElement('td');
                enabled.textContent = e.enabled ? '✓' : '✗';
                const actions = document.createElement('td');
                const editBtn = document.createElement('button');
                editBtn.className = 'btn btn-sm btn-secondary';
                editBtn.innerHTML = '<span class="btn-icon">✏️</span> Edit';
                editBtn.addEventListener('click', () => openEmuEditModal(e));
                actions.appendChild(editBtn);

                tr.appendChild(name);
                tr.appendChild(bin);
                tr.appendChild(override);
                tr.appendChild(args);
                tr.appendChild(type);
                tr.appendChild(enabled);
                tr.appendChild(actions);
                tbody.appendChild(tr);
            }
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-danger">Failed: ${err.message}</td></tr>`;
        }
    }

    refreshEmulators();
})();
