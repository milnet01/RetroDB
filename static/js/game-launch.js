// =============================================================================
// RETRODB - Game launch
// =============================================================================
// Pass 42 — wires the ▶ Play button on game_detail.html to
// POST /api/game/<id>/launch.  On 409 (already running), prompts to kill
// the prior instance and relaunch.  Surfaces errors via showNotification.
// =============================================================================

(function () {
    'use strict';

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    async function launchGameImpl(btn) {
        const gid = btn.dataset.gameId;
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-icon">⏳</span> Launching…';

        try {
            const rv = await fetch(`/api/game/${gid}/launch`, {
                method: 'POST',
                headers: {'X-CSRF-Token': csrfToken()},
            });
            const body = await rv.json().catch(() => ({}));

            if (rv.status === 409 && body.existing_token) {
                if (confirm('This game is already running.  Kill the existing process and relaunch?')) {
                    await fetch(`/api/launch/${body.existing_token}/kill`, {
                        method: 'POST',
                        headers: {'X-CSRF-Token': csrfToken()},
                    });
                    // Retry the launch once
                    const rv2 = await fetch(`/api/game/${gid}/launch`, {
                        method: 'POST',
                        headers: {'X-CSRF-Token': csrfToken()},
                    });
                    const body2 = await rv2.json().catch(() => ({}));
                    if (!rv2.ok) throw new Error(body2.error || rv2.statusText);
                    if (typeof showNotification === 'function') {
                        showNotification('Launched (replaced previous instance)', 'success');
                    }
                } else {
                    return;
                }
            } else if (!rv.ok) {
                throw new Error(body.error || rv.statusText);
            } else {
                if (typeof showNotification === 'function') {
                    showNotification('Launched (pid ' + (body.data && body.data.pid) + ')', 'success');
                }
            }
        } catch (e) {
            if (typeof showNotification === 'function') {
                showNotification('Launch failed: ' + e.message, 'error');
            } else {
                alert('Launch failed: ' + e.message);
            }
        } finally {
            btn.disabled = false;
            btn.innerHTML = orig;
        }
    }

    // Expose for the inline onclick attribute on the button.
    window.launchGame = launchGameImpl;
})();
