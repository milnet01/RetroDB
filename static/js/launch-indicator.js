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
    if (!ind || !cnt) return;

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    let timer = null;
    let popover = null;

    async function refresh() {
        try {
            const rv = await fetch('/api/launches/active');
            if (!rv.ok) return;
            const body = await rv.json();
            const handles = (body && body.launches) || [];
            cnt.textContent = String(handles.length);
            ind.classList.toggle('hidden', handles.length === 0);
            ind.dataset.launches = JSON.stringify(handles);
        } catch (e) {
            // silent — viewer may lack the view permission, etc.
        }
    }

    async function nextDisk(token) {
        const rv = await fetch(`/api/launch/${token}/disk-next`, {
            method: 'POST',
            headers: {'X-CSRF-Token': csrfToken()},
        });
        const body = await rv.json().catch(() => ({}));
        showNotification(body.message || body.error || t('Next disk failed'),
                         rv.ok ? 'success' : 'error');
    }

    async function killLaunch(token) {
        await fetch(`/api/launch/${token}/kill`, {
            method: 'POST',
            headers: {'X-CSRF-Token': csrfToken()},
        }).catch(() => {});
        // The open list still shows the killed game; close it so the next
        // click rebuilds it from the refreshed list.
        if (popover) { popover.remove(); popover = null; }
        await refresh();
    }

    function togglePopover() {
        if (popover) {
            popover.remove();
            popover = null;
            return;
        }
        const handles = JSON.parse(ind.dataset.launches || '[]');
        if (handles.length === 0) return;
        popover = document.createElement('div');
        popover.className = 'launch-indicator-popover';
        const title = document.createElement('div');
        title.className = 'launch-indicator-popover-title';
        title.textContent = t('Now playing');
        popover.appendChild(title);
        for (const h of handles) {
            const row = document.createElement('div');
            row.className = 'launch-indicator-popover-row';
            const label = document.createElement('span');
            label.textContent = h.title || `game #${h.game_id} (pid ${h.pid})`;
            row.appendChild(label);
            if (h.disk_swap) {
                const dbtn = document.createElement('button');
                dbtn.className = 'btn btn-sm btn-secondary';
                dbtn.textContent = t('Next disk');
                dbtn.addEventListener('click', () => nextDisk(h.token));
                row.appendChild(dbtn);
            }
            const kbtn = document.createElement('button');
            kbtn.className = 'btn btn-sm btn-danger';
            kbtn.textContent = t('Kill');
            kbtn.addEventListener('click', () => killLaunch(h.token));
            row.appendChild(kbtn);
            popover.appendChild(row);
        }
        document.body.appendChild(popover);
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
