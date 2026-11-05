// =============================================================================
// RETRODB - Game launch
// =============================================================================
// Pass 44 — wires the ▶ Play button on game_detail.html, and on library and
// system-page cards (PASS-59-91), to POST /api/game/<id>/launch.
// On 409 (already running), prompts to kill
// the prior instance and relaunch.  Surfaces errors via showNotification.
// PASS-59-81 §4.5 — a 202 with `installing` means the player's core is
// downloading: poll the core job, then send the launch again once.
// PASS-59-228 — a full-screen play screen covers the page while it starts.
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
    // PASS-59-244: an error page is no answer, not "done"; five in a row, or
    // a download past CORE_WAIT_MS (RetroArch itself is large), give up. The
    // caller shows its own message, so these reasons are for the log only.
    const CORE_POLL_MS = 1500;
    const CORE_WAIT_MS = 30 * 60 * 1000;
    async function waitForCore(core) {
        let failures = 0;
        for (let waited = 0; waited < CORE_WAIT_MS; waited += CORE_POLL_MS) {
            await sleep(CORE_POLL_MS);
            const rv = await fetch('/api/player/cores/status').catch(() => null);
            const body = rv && rv.ok ? await rv.json().catch(() => null) : null;
            if (!body) {
                if (++failures >= 5) return 'no answer from RetroDB';
                continue;
            }
            failures = 0;
            const st = body.data || {};
            const pending = st.running && (st.current_item === core
                || (st.queued || []).includes(core));
            if (!pending) return (st.errors || {})[core] || null;
        }
        return 'the download took too long';
    }

    // PASS-59-228 — the play screen: the game's logo, large, on its background
    // art (its title when it has no logo) while the game starts. It closes when
    // the game's window takes focus from the browser, on Esc or a click, when
    // the launch fails or the game quits, or SCREEN_MAX_MS after the start: a
    // game started from another device's browser never takes that one's focus.
    const SCREEN_MAX_MS = 15000;
    const STATUS_POLL_MS = 1000;
    let screen = null;

    function closeScreen() {
        if (!screen) return;
        const s = screen;
        screen = null;
        clearTimeout(s.timer);
        clearInterval(s.poll);
        window.removeEventListener('blur', closeScreen);
        document.removeEventListener('keydown', s.onKey, true);
        s.el.remove();
        if (s.trigger && s.trigger.isConnected) s.trigger.focus({preventScroll: true});
    }

    function openScreen(btn) {
        closeScreen();
        const d = btn.dataset;
        const title = d.gameTitle || '';
        const el = document.createElement('div');
        el.className = 'play-screen';
        el.tabIndex = -1;
        el.setAttribute('role', 'dialog');
        el.setAttribute('aria-modal', 'true');
        el.setAttribute('aria-label', t('Starting {title}', {title}));
        if (d.fanart) {
            el.style.backgroundImage = `url("/static/images/fanart/${encodeURIComponent(d.fanart)}")`;
        }
        const art = d.logo ? document.createElement('img') : document.createElement('h1');
        if (d.logo) {
            art.src = `/static/images/game_logos/${encodeURIComponent(d.logo)}`;
            art.alt = title;
            art.className = 'play-screen-logo';
        } else {
            art.textContent = title;
            art.className = 'play-screen-title';
        }
        const status = document.createElement('p');
        status.className = 'play-screen-status';
        status.setAttribute('aria-live', 'polite');
        status.textContent = t('Starting…');
        el.append(art, status);
        el.addEventListener('click', closeScreen);
        // Esc closes it; Tab stays on it, since it covers the page (PASS-59-245).
        const onKey = (e) => {
            if (e.key === 'Escape') { e.preventDefault(); closeScreen(); }
            else if (e.key === 'Tab') { e.preventDefault(); el.focus({preventScroll: true}); }
        };
        document.addEventListener('keydown', onKey, true);
        document.body.appendChild(el);
        el.focus({preventScroll: true});
        screen = {el, status, onKey, trigger: btn, timer: null, poll: null};
    }

    function screenStatus(text) {
        if (screen) screen.status.textContent = text;
    }

    // The game started: close on focus loss, when it quits, or at the limit.
    function screenStarted(token) {
        if (!screen) return;
        const s = screen;
        window.addEventListener('blur', closeScreen);
        s.timer = setTimeout(closeScreen, SCREEN_MAX_MS);
        if (!token) return;
        s.poll = setInterval(async () => {
            const rv = await fetch(`/api/launch/${token}/status`).catch(() => null);
            const st = rv && rv.ok ? ((await rv.json().catch(() => ({}))).data || {}) : {};
            if (screen === s && st.state !== 'running') closeScreen();
        }, STATUS_POLL_MS);
    }

    async function launchGameImpl(btn, afterInstall = false) {
        const gid = btn.dataset.gameId;
        const orig = btn.innerHTML;
        const origTitle = btn.title;
        btn.disabled = true;
        busyLabel(btn, t('Launching…'));
        if (!afterInstall) openScreen(btn);

        try {
            const rv = await fetch(`/api/game/${gid}/launch`, {
                method: 'POST',
                headers: {'X-CSRF-Token': csrfToken()},
            });
            const body = await rv.json().catch(() => ({}));

            if (rv.status === 409 && body.existing_token) {
                closeScreen();
                const relaunch = await new Promise((resolve) => showConfirm(
                    t('Confirm Action'),
                    t('This game is already running.  Kill the existing process and relaunch?'),
                    () => resolve(true), () => resolve(false)));
                if (relaunch) {
                    openScreen(btn);
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
                    screenStarted(body2.data && body2.data.token);
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
                screenStatus(msg);
                if (typeof showNotification === 'function') {
                    showNotification(inst.bytes ? `${msg} (${formatBytes(inst.bytes)})` : msg, 'info');
                }
                if (await waitForCore(inst.core)) {
                    throw new Error(t('Could not download the {system} core. Check the internet connection and try again.', {system: inst.system}));
                }
                await launchGameImpl(btn, true);
            } else {
                screenStarted(body.data && body.data.token);
                if (typeof showNotification === 'function') {
                    showNotification(t('Launched (pid {pid})', {pid: body.data && body.data.pid}), 'success');
                }
            }
        } catch (e) {
            closeScreen();
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
