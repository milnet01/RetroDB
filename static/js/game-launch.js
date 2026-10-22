// =============================================================================
// RETRODB - Game launch
// =============================================================================
// Pass 44 — wires the ▶ Play button on game_detail.html, and on library and
// system-page cards (PASS-59-91), to POST /api/game/<id>/launch.
// On 409 (already running), prompts to kill
// the prior instance and relaunch.  Surfaces errors via showNotification.
// PASS-59-81 §4.5 — a 202 with `installing` means the player's core is
// downloading: poll the core job, then send the launch again once.
// =============================================================================

(function () {
    'use strict';

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    // A library card's Play button is icon-only (PASS-59-91 §4.5).
    function busyLabel(btn, text) {
        btn.title = text;
        btn.innerHTML = btn.classList.contains('card-play-btn')
            ? '⏳'
            : '<span class="btn-icon">⏳</span> ' + escapeHtml(text);
    }

    // Wait for the core job to finish `core`; its error message, or null.
    async function waitForCore(core) {
        for (;;) {
            await sleep(1500);
            const rv = await fetch('/api/player/cores/status');
            const st = ((await rv.json().catch(() => ({}))).data) || {};
            const pending = st.running && (st.current_item === core
                || (st.queued || []).includes(core));
            if (!pending) return (st.errors || {})[core] || null;
        }
    }

    async function launchGameImpl(btn, afterInstall = false) {
        const gid = btn.dataset.gameId;
        const orig = btn.innerHTML;
        const origTitle = btn.title;
        btn.disabled = true;
        busyLabel(btn, t('Launching…'));

        try {
            const rv = await fetch(`/api/game/${gid}/launch`, {
                method: 'POST',
                headers: {'X-CSRF-Token': csrfToken()},
            });
            const body = await rv.json().catch(() => ({}));

            if (rv.status === 409 && body.existing_token) {
                if (confirm(t('This game is already running.  Kill the existing process and relaunch?'))) {
                    // Pass 48.4 — check the kill succeeded before retrying. A
                    // failed kill (process unkillable, token expired) otherwise
                    // surfaces as a second confusing "already running" 409.
                    const killRv = await fetch(`/api/launch/${body.existing_token}/kill`, {
                        method: 'POST',
                        headers: {'X-CSRF-Token': csrfToken()},
                    });
                    if (!killRv.ok) {
                        const killBody = await killRv.json().catch(() => ({}));
                        throw new Error(killBody.error || t('Could not stop the running instance.'));
                    }
                    // Retry the launch once
                    const rv2 = await fetch(`/api/game/${gid}/launch`, {
                        method: 'POST',
                        headers: {'X-CSRF-Token': csrfToken()},
                    });
                    const body2 = await rv2.json().catch(() => ({}));
                    if (!rv2.ok) throw new Error(body2.error || rv2.statusText);
                    if (typeof showNotification === 'function') {
                        showNotification(t('Launched (replaced previous instance)'), 'success');
                    }
                } else {
                    return;
                }
            } else if (!rv.ok) {
                throw new Error(body.error || rv.statusText);
            } else if (body.installing) {
                const inst = body.installing;
                if (afterInstall) throw new Error(t('The core installed but the game still cannot start.'));
                const msg = t('Downloading the {system} core…', {system: inst.system});
                busyLabel(btn, msg);
                if (typeof showNotification === 'function') {
                    showNotification(inst.bytes ? `${msg} (${formatBytes(inst.bytes)})` : msg, 'info');
                }
                if (await waitForCore(inst.core)) {
                    throw new Error(t('Could not download the {system} core. Check the internet connection and try again.', {system: inst.system}));
                }
                await launchGameImpl(btn, true);
            } else {
                if (typeof showNotification === 'function') {
                    showNotification(t('Launched (pid {pid})', {pid: body.data && body.data.pid}), 'success');
                }
            }
        } catch (e) {
            if (typeof showNotification === 'function') {
                showNotification(t('Launch failed: {error}', {error: e.message}), 'error');
            } else {
                alert(t('Launch failed: {error}', {error: e.message}));
            }
        } finally {
            btn.disabled = false;
            btn.innerHTML = orig;
            btn.title = origTitle;
        }
    }

    // Expose for the inline onclick attribute on the button.
    window.launchGame = launchGameImpl;
})();
