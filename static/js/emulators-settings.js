// =============================================================================
// RETRODB - Settings → Emulators page
// =============================================================================
// Pass 44 — wires the RetroArch auto-detect button, lists emulators in the
// registry, and lists per-system mappings.  Page-specific JS (not bundled).
//
// Pass 44.1 — adds: AppImage scanner (POST /api/settings/emulators/detect
// with apply=true|false), per-row Edit button → emuEditModal, save via
// PUT /api/emulators/<id>.
//
// PASS-59-91 stage 2 — the Emulator folders list (the editable form of the
// emulator_scan_paths setting; adding one scans with apply=true) and the
// per-system mapping table, filled from GET /api/system_emulators.
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
            statusLine.textContent = t('Detecting…');
            try {
                const out = await fetchJSON(
                    '/api/settings/retroarch/detect?validate=true',
                    {method: 'POST'}
                );
                $('#ra-binary').value = out.binary.path || '';
                $('#ra-cores-dir').value = out.cores_dir.path || '';
                const bv = out.binary.version || out.binary.error || '';
                const cn = out.cores_dir.core_count
                    ? `${out.cores_dir.core_count} cores`
                    : (out.cores_dir.error || '');
                statusLine.textContent = `${bv} · ${cn}`;
            } catch (e) {
                statusLine.textContent = t('Detect failed: {error}', {error: e.message});
            }
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            statusLine.textContent = t('Saving…');
            try {
                await fetchJSON('/api/settings', {
                    method: 'POST',
                    body: JSON.stringify({
                        retroarch_binary:    $('#ra-binary').value.trim(),
                        retroarch_cores_dir: $('#ra-cores-dir').value.trim(),
                    }),
                });
                statusLine.textContent = t('Saved.');
            } catch (e) {
                statusLine.textContent = t('Save failed: {error}', {error: e.message});
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
            emuDetectResults.innerHTML = '<span class="text-muted">' + escapeHtml(t('No emulator AppImages found in the scan paths.')) + '</span>';
            emuApplyBtn.disabled = true;
            return;
        }
        const wrap = document.createElement('table');
        wrap.className = 'data-table';
        wrap.innerHTML = '<thead><tr><th>' + escapeHtml(t('Emulator')) + '</th><th>'
        + escapeHtml(t('Detected path')) + '</th><th>' + escapeHtml(t('Systems'))
        + '</th><th>' + escapeHtml(t('Currently set'))
        + '</th><th>' + escapeHtml(t('Will change?')) + '</th></tr></thead>';
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
            const systems = document.createElement('td');
            systems.textContent = (s.systems || []).join(', ');
            const cur = document.createElement('td');
            cur.textContent = s.current_override || '(not set)';
            cur.style.color = 'var(--text-muted)';
            const chg = document.createElement('td');
            chg.textContent = s.would_change ? 'Yes' : 'No (already set)';
            chg.style.color = s.would_change ? 'var(--neon-green)' : 'var(--text-muted)';
            tr.appendChild(name);
            tr.appendChild(path);
            tr.appendChild(systems);
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
            emuDetectStatus.textContent = t('Scanning…');
            emuDetectResults.innerHTML = '';
            emuApplyBtn.disabled = true;
            try {
                const out = await fetchJSON('/api/settings/emulators/detect', {method: 'POST'});
                emuDetectStatus.textContent = `Scanned ${(out.scanned_paths || []).length} paths · found ${out.found_count || 0} matches.`;
                renderSuggestions(out.suggestions);
            } catch (e) {
                emuDetectStatus.textContent = t('Scan failed: {error}', {error: e.message});
            }
        });
    }

    // Scan with apply=true: set each found emulator's path and wire it to
    // its systems. Also run when a folder is added.
    async function applyScan() {
        emuApplyBtn.disabled = true;
        emuDetectStatus.textContent = t('Applying…');
        try {
            const out = await fetchJSON('/api/settings/emulators/detect?apply=true', {method: 'POST'});
            emuDetectStatus.textContent = `Applied ${(out.applied || []).length} update(s).`;
            renderSuggestions(out.suggestions);
            refreshEmulators();
            refreshMappings();
        } catch (e) {
            emuDetectStatus.textContent = t('Apply failed: {error}', {error: e.message});
            emuApplyBtn.disabled = false;
        }
    }

    if (emuApplyBtn) {
        emuApplyBtn.addEventListener('click', applyScan);
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
                alert(t('Save failed: {error}', {error: e.message}));
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
                tbody.innerHTML = '<tr><td colspan="7" class="text-muted">' + escapeHtml(t('No emulators registered.')) + '</td></tr>';
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
                    override.textContent = t('(none)');
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
                editBtn.innerHTML = '<span class="btn-icon">✏️</span> ' + escapeHtml(t('Edit'));
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

    // ----- PASS-59-91 — Emulator folders ------------------------------------

    const folderList = $('#emu-folders');
    const folderInput = $('#emu-folder-input');
    let folders = folderList
        ? (folderList.dataset.paths || '').split(':').map(p => p.trim()).filter(Boolean)
        : [];

    // A remove button asks once more on the button itself; this page loads
    // no confirm modal.
    function armedClick(btn, action) {
        const label = btn.textContent;
        btn.addEventListener('click', () => {
            if (btn.dataset.armed) {
                action();
                return;
            }
            btn.dataset.armed = '1';
            btn.textContent = t('Click again to remove');
            setTimeout(() => {
                delete btn.dataset.armed;
                btn.textContent = label;
            }, 6000);
        });
    }

    function renderFolders() {
        folderList.innerHTML = '';
        if (folders.length === 0) {
            const li = document.createElement('li');
            li.className = 'text-muted';
            li.textContent = t('No folders yet.');
            folderList.appendChild(li);
            return;
        }
        for (const folder of folders) {
            const li = document.createElement('li');
            const code = document.createElement('code');
            code.textContent = folder;
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-secondary';
            btn.textContent = t('Remove');
            armedClick(btn, () => saveFolders(folders.filter(f => f !== folder), false));
            li.appendChild(code);
            li.appendChild(btn);
            folderList.appendChild(li);
        }
    }

    async function saveFolders(next, scan) {
        emuDetectStatus.textContent = t('Saving…');
        try {
            await fetchJSON('/api/settings', {
                method: 'POST',
                body: JSON.stringify({emulator_scan_paths: next.join(':')}),
            });
        } catch (e) {
            emuDetectStatus.textContent = t('Save failed: {error}', {error: e.message});
            return;
        }
        folders = next;
        renderFolders();
        emuDetectStatus.textContent = t('Saved.');
        if (scan) applyScan();
    }

    const folderAddBtn = $('#emu-folder-add');
    if (folderAddBtn) {
        const add = () => {
            const folder = folderInput.value.trim();
            if (!folder || folder.includes(':')) {
                emuDetectStatus.textContent = t('Enter one folder path.');
                return;
            }
            folderInput.value = '';
            if (folders.includes(folder)) {
                applyScan();
                return;
            }
            saveFolders(folders.concat([folder]), true);
        };
        folderAddBtn.addEventListener('click', add);
        folderInput.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') add();
        });
        renderFolders();
    }

    // ----- PASS-59-91 — Per-system mapping ----------------------------------

    function biosText(bios) {
        if (!bios || bios.state === 'unknown') return t('Unknown');
        if (bios.state === 'ok') return t('OK');
        return t('Missing: {files}', {files: bios.missing.join(', ')});
    }

    async function refreshMappings() {
        const body = $('#mapping-body');
        if (!body) return;
        let mappings;
        try {
            mappings = (await fetchJSON('/api/system_emulators')).mappings || [];
        } catch (e) {
            body.textContent = t('Failed: {error}', {error: e.message});
            return;
        }
        if (mappings.length === 0) {
            body.innerHTML = '<span class="text-muted">'
                + escapeHtml(t('No mappings yet. Add an emulator folder above.')) + '</span>';
            return;
        }
        const table = document.createElement('table');
        table.className = 'data-table';
        table.innerHTML = '<thead><tr><th>' + escapeHtml(t('System')) + '</th><th>'
            + escapeHtml(t('Emulator')) + '</th><th>' + escapeHtml(t('Default'))
            + '</th><th>' + escapeHtml(t('Works')) + '</th><th>' + escapeHtml(t('BIOS'))
            + '</th><th></th></tr></thead>';
        const tbody = document.createElement('tbody');
        for (const m of mappings) {
            const tr = document.createElement('tr');
            const cells = [m.system_name, m.emulator_name || '?'].map((text) => {
                const td = document.createElement('td');
                td.textContent = text;
                return td;
            });
            const def = document.createElement('td');
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = `default-${m.system_id}`;
            radio.checked = !!m.is_default;
            radio.setAttribute('aria-label',
                t('Default emulator for {system}', {system: m.system_name}));
            radio.addEventListener('change', async () => {
                try {
                    await fetchJSON('/api/system_emulators', {
                        method: 'POST',
                        body: JSON.stringify({
                            system_id: m.system_id,
                            emulator_id: m.emulator_id,
                            is_default: true,
                            retroarch_core: m.retroarch_core,
                            extra_args: m.extra_args,
                        }),
                    });
                } catch (e) {
                    body.prepend(document.createTextNode(
                        t('Save failed: {error}', {error: e.message})));
                }
                refreshMappings();
            });
            def.appendChild(radio);
            const works = document.createElement('td');
            works.textContent = m.resolves ? t('Yes') : t('No');
            works.style.color = m.resolves ? 'var(--neon-green)' : 'var(--text-muted)';
            const bios = document.createElement('td');
            bios.textContent = biosText(m.bios);
            if (m.bios && m.bios.state === 'missing') bios.className = 'text-danger';
            const actions = document.createElement('td');
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-secondary';
            btn.textContent = t('Remove');
            armedClick(btn, async () => {
                try {
                    await fetchJSON(`/api/system_emulators/${m.id}`, {method: 'DELETE'});
                } catch (e) {
                    btn.textContent = t('Failed: {error}', {error: e.message});
                    return;
                }
                refreshMappings();
            });
            actions.appendChild(btn);
            for (const td of [...cells, def, works, bios, actions]) tr.appendChild(td);
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        const wrap = document.createElement('div');
        wrap.style.overflowX = 'auto';
        wrap.appendChild(table);
        body.innerHTML = '';
        body.appendChild(wrap);
    }

    refreshEmulators();
    refreshMappings();
})();
