// =============================================================================
// RETRODB - Top-of-page launch indicator
// =============================================================================
// Pass 44 — polls /api/launches/active every 5s while the page is foregrounded.
// Shows the running count when non-zero, hidden otherwise.  Click reveals the
// list with kill buttons, and a Next disk button for a RetroArch game started
// from a .m3u disk list.
// =============================================================================

(function () {
    'use strict';

    const ind = document.getElementById('launch-indicator');
    const cnt = document.getElementById('launch-count');
    const status = document.getElementById('launch-status');
    if (!ind || !cnt) return;

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    let timer = null;
    let popover = null;
    let shownCount = null;

    async function refresh() {
        try {
            const rv = await fetch('/api/launches/active');
            if (!rv.ok) return;
            const body = await rv.json();
            const handles = (body && body.launches) || [];
            cnt.textContent = String(handles.length);
            ind.classList.toggle('hidden', handles.length === 0);
            ind.dataset.launches = JSON.stringify(handles);
            announce(handles.length);
        } catch (e) {
            // silent — viewer may lack the view permission, etc.
        }
    }

    // PASS-59-258 — a screen reader hears the count only when it changes,
    // not on each refresh, and not on page load.
    function announce(n) {
        if (status && shownCount !== null && n !== shownCount) {
            status.textContent = n === 0 ? t('No games running')
                : n === 1 ? t('1 game running') : t('{count} games running', {count: n});
        }
        shownCount = n;
    }

    async function nextDisk(token) {
        try {
            const rv = await fetch(`/api/launch/${token}/disk-next`, {
                method: 'POST',
                headers: {'X-CSRF-Token': csrfToken()},
            });
            const body = await rv.json().catch(() => ({}));
            showNotification(body.message || body.error || t('Next disk failed'),
                             rv.ok ? 'success' : 'error');
        } catch (e) {
            showNotification(t('Next disk failed'), 'error');
        }
    }

    async function killLaunch(token) {
        // A refused or failed stop is said; the list refresh below shows
        // whether the game is still running (PASS-59-284).
        try {
            const rv = await fetch(`/api/launch/${token}/kill`, {
                method: 'POST',
                headers: {'X-CSRF-Token': csrfToken()},
            });
            if (!rv.ok) {
                const body = await rv.json().catch(() => ({}));
                showNotification(body.error || t('Could not stop the game'), 'error');
            }
        } catch (e) {
            showNotification(t('Could not stop the game'), 'error');
        }
        // The open list still shows the killed game; close it so the next
        // click rebuilds it from the refreshed list.
        closePopover();
        await refresh();
        // Focus goes back to the indicator, or to the page if it has gone.
        if (ind.classList.contains('hidden')) {
            const main = document.getElementById('main-content');
            if (main) {
                main.setAttribute('tabindex', '-1');
                main.focus();
            }
        } else {
            ind.focus();
        }
    }

    // PASS-59-245 — Esc or a click elsewhere closes the list; Esc returns
    // focus to the indicator.
    function onPopoverKey(e) {
        if (e.key === 'Escape') { closePopover(); ind.focus(); }
    }
    function onOutsideClick(e) {
        if (popover && !popover.contains(e.target) && !ind.contains(e.target)) closePopover();
    }
    function closePopover() {
        if (!popover) return;
        popover.remove();
        popover = null;
        ind.setAttribute('aria-expanded', 'false');
        document.removeEventListener('keydown', onPopoverKey);
        document.removeEventListener('click', onOutsideClick, true);
    }

    function togglePopover() {
        if (popover) {
            closePopover();
            return;
        }
        const handles = JSON.parse(ind.dataset.launches || '[]');
        if (handles.length === 0) return;
        popover = document.createElement('div');
        popover.className = 'launch-indicator-popover';
        popover.id = 'launch-popover';
        popover.setAttribute('role', 'dialog');
        popover.setAttribute('aria-label', t('Now playing'));
        const title = document.createElement('div');
        title.className = 'launch-indicator-popover-title';
        title.textContent = t('Now playing');
        popover.appendChild(title);
        for (const h of handles) {
            const row = document.createElement('div');
            row.className = 'launch-indicator-popover-row';
            const label = document.createElement('span');
            const name = h.title || t('game #{id} (pid {pid})', {id: h.game_id, pid: h.pid});
            label.textContent = name;
            row.appendChild(label);
            if (h.disk_swap) {
                const dbtn = document.createElement('button');
                dbtn.className = 'btn btn-sm btn-secondary';
                dbtn.textContent = t('Next disk');
                dbtn.setAttribute('aria-label', t('Next disk: {game}', {game: name}));
                dbtn.addEventListener('click', () => nextDisk(h.token));
                row.appendChild(dbtn);
            }
            const kbtn = document.createElement('button');
            kbtn.className = 'btn btn-sm btn-danger';
            kbtn.textContent = t('Kill');
            kbtn.setAttribute('aria-label', t('Kill {game}', {game: name}));
            kbtn.addEventListener('click', () => killLaunch(h.token));
            row.appendChild(kbtn);
            popover.appendChild(row);
        }
        document.body.appendChild(popover);
        ind.setAttribute('aria-expanded', 'true');
        popover.querySelector('button').focus();
        document.addEventListener('keydown', onPopoverKey);
        document.addEventListener('click', onOutsideClick, true);
    }

    ind.addEventListener('click', togglePopover);

    function start() {
        if (timer) return;
        refresh();
        timer = setInterval(refresh, 5000);
    }
    function stop() {
        if (timer) clearInterval(timer);
        timer = null;
    }
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stop(); else start();
    });
    start();
})();
