// =============================================================================
// RETRODB - Settings → Emulators page
// =============================================================================
// Pass 42 — wires the RetroArch auto-detect button, lists emulators in the
// registry, and lists per-system mappings.  No bundled — page-specific JS.
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

    // ----- Emulators list ----------------------------------------------------

    async function refreshEmulators() {
        const tbody = $('#emu-tbody');
        try {
            const out = await fetchJSON('/api/emulators');
            if (!out.emulators || out.emulators.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-muted">No emulators registered.</td></tr>';
                return;
            }
            tbody.innerHTML = '';
            for (const e of out.emulators) {
                const tr = document.createElement('tr');
                const name = document.createElement('td');
                name.textContent = e.name || '';
                const bin = document.createElement('td');
                const code = document.createElement('code');
                code.textContent = e.binary_name || '';
                bin.appendChild(code);
                const args = document.createElement('td');
                const codeArgs = document.createElement('code');
                codeArgs.textContent = e.args_template || '';
                args.appendChild(codeArgs);
                const type = document.createElement('td');
                type.textContent = e.is_retroarch ? 'RetroArch' : 'Standalone';
                const enabled = document.createElement('td');
                enabled.textContent = e.enabled ? '✓' : '✗';

                tr.appendChild(name);
                tr.appendChild(bin);
                tr.appendChild(args);
                tr.appendChild(type);
                tr.appendChild(enabled);
                tbody.appendChild(tr);
            }
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="5" class="text-danger">Failed: ${err.message}</td></tr>`;
        }
    }

    refreshEmulators();
})();
