// =============================================================================
// RETRODB - Top-of-page launch indicator
// =============================================================================
// Pass 42 — polls /api/launches/active every 5s while the page is foregrounded.
// Shows the running count when non-zero, hidden otherwise.  Click reveals the
// list with kill buttons.
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

    async function killLaunch(token) {
        await fetch(`/api/launch/${token}/kill`, {
            method: 'POST',
            headers: {'X-CSRF-Token': csrfToken()},
        });
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
        title.textContent = 'Now playing';
        popover.appendChild(title);
        for (const h of handles) {
            const row = document.createElement('div');
            row.className = 'launch-indicator-popover-row';
            const label = document.createElement('span');
            label.textContent = `game #${h.game_id} (pid ${h.pid})`;
            const kbtn = document.createElement('button');
            kbtn.className = 'btn btn-sm btn-danger';
            kbtn.textContent = 'Kill';
            kbtn.addEventListener('click', () => killLaunch(h.token));
            row.appendChild(label);
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
