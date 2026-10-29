/**
 * RetroDB - Self-updater page code (PASS-59-169)
 *
 * Settings > System > Updates ([data-update-card]) and the admin dashboard
 * banner ([data-update-banner]). Talks to /api/updates/*; release notes come
 * from GitHub and are only ever set as text.
 * Contract: docs/specs/PASS-59-169-self-updater.md.
 */
(function () {
    'use strict';

    const REASONS = {
        git: () => t('This copy of RetroDB is a git checkout. Update it with git pull.'),
        managed: () => t('RetroDB is run by a process manager here. Download the release and install it yourself.'),
        no_asset: () => t('This release has no download for this computer yet.'),
        busy: () => t('An update is already being downloaded.'),
        not_ready: () => t('Download the update first.'),
        not_available: () => t('No newer version is available.'),
        start_failed: () => t('The update could not be started. See logs/update.log.'),
    };

    // Spelled out: tests/test_pass59_frontend.py matches every call to a route.
    const ACTION_URLS = {
        check: '/api/updates/check',
        download: '/api/updates/download',
    };

    function reasonText(code) {
        return (REASONS[code] || (() => t('This update cannot be installed here.')))();
    }

    function show(el, on) { if (el) el.hidden = !on; }

    function formatDate(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return isNaN(d) ? '' : d.toLocaleDateString();
    }

    // ---------------------------------------------------------------------
    // Dashboard banner
    // ---------------------------------------------------------------------

    function renderBanner(banner, st) {
        if (!st.available || !st.latest) return;
        banner.querySelector('[data-update-banner-text]').textContent =
            t('RetroDB {version} is available.', { version: st.latest.version });
        show(banner, true);
    }

    // ---------------------------------------------------------------------
    // Settings card
    // ---------------------------------------------------------------------

    function Card(root) {
        this.root = root;
        this.q = sel => root.querySelector(sel);
        this.pollTimer = null;
        root.addEventListener('click', e => {
            const btn = e.target.closest('[data-update-action]');
            if (btn) this.act(btn.dataset.updateAction, btn);
        });
        const auto = this.q('[data-update-auto]');
        if (auto) auto.addEventListener('change', () => this.saveAuto(auto));
    }

    Card.prototype.render = function (st) {
        const q = this.q;
        this.current = st.current;
        const latest = st.latest;
        let summary = '';
        if (st.available && latest) {
            summary = t('Version {version} is available.', { version: latest.version });
        } else if (st.check_error && !latest) {
            summary = t('Could not check for updates.');
        } else if (st.checked_at) {
            summary = t('You have the latest version.');
        }
        q('[data-update-summary]').textContent = summary;

        const release = q('[data-update-release]');
        show(release, !!(st.available && latest));
        if (st.available && latest) {
            const date = formatDate(latest.published_at);
            q('[data-update-title]').textContent = date
                ? t('What is new in {version} ({date})', { version: latest.version, date })
                : t('What is new in {version}', { version: latest.version });
            q('[data-update-notes]').textContent = latest.notes || '';
            const link = q('[data-update-link]');
            if (latest.url) link.href = latest.url;
            show(link, !!latest.url);
        }

        const job = st.job || {};
        const busy = job.state === 'downloading' || job.state === 'installing';
        const note = q('[data-update-note]');
        let noteText = '';
        if (st.available && !st.can_install && st.reason) noteText = reasonText(st.reason);
        if (job.state === 'error' && job.error) {
            noteText = t('The download failed: {error}', { error: job.error });
        }
        if (job.state === 'ready') noteText = t('The update is downloaded and checked.');
        note.textContent = noteText;
        show(note, !!noteText);

        show(q('[data-update-progress]'), job.state === 'downloading');
        if (job.state === 'downloading') {
            const pct = job.total_bytes ? Math.min(100, Math.round(job.done_bytes * 100 / job.total_bytes)) : 0;
            q('[data-update-bar]').style.width = pct + '%';
        }

        show(q('[data-update-action="download"]'),
             st.available && st.can_install && !busy && job.state !== 'ready');
        show(q('[data-update-action="install"]'), job.state === 'ready');
        q('[data-update-action="check"]').disabled = busy;

        this.renderResult(st.last_result);

        clearTimeout(this.pollTimer);
        if (job.state === 'downloading') {
            this.pollTimer = setTimeout(() => this.refresh(), 1000);
        }
    };

    Card.prototype.renderResult = function (result) {
        const box = this.q('[data-update-result]');
        box.replaceChildren();
        if (!result) { show(box, false); return; }
        const text = document.createElement('span');
        if (result.result === 'updated') {
            text.textContent = t('Updated from {from} to {to}.',
                { from: result.from_version, to: result.to_version });
            box.className = 'update-result update-result-ok';
        } else {
            text.textContent = t('The update to {to} did not work, so RetroDB went back to {from}. Reason: {reason}',
                { to: result.to_version, from: result.from_version, reason: result.reason || '?' });
            box.className = 'update-result update-result-failed';
        }
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'btn btn-sm btn-secondary';
        close.textContent = t('OK');
        close.addEventListener('click', async () => {
            try { await API.post('/api/updates/dismiss'); } catch (_) { /* shown again next time */ }
            show(box, false);
        });
        box.append(text, ' ', close);
        show(box, true);
    };

    Card.prototype.refresh = async function () {
        try {
            this.render(await API.get('/api/updates/status'));
        } catch (err) {
            showNotification(t('Could not check for updates.'), 'error');
        }
    };

    Card.prototype.act = async function (action, btn) {
        if (action === 'install') {
            showConfirm(t('Install update'),
                t('RetroDB will back up its database, install the update and restart. Anyone using it will be disconnected for a minute or two.'),
                () => this.install(btn));
            return;
        }
        btn.disabled = true;
        try {
            const st = await API.post(ACTION_URLS[action]);
            this.render(st);
        } catch (err) {
            const reason = err && err.data && err.data.reason;
            showNotification(reason ? reasonText(reason) : t('Could not check for updates.'), 'error');
        } finally {
            btn.disabled = false;
        }
    };

    Card.prototype.install = async function (btn) {
        btn.disabled = true;
        try {
            await API.post('/api/updates/install');
        } catch (err) {
            const reason = err && err.data && err.data.reason;
            showNotification(reasonText(reason), 'error');
            btn.disabled = false;
            return;
        }
        waitForRestart(this.current);
    };

    Card.prototype.saveAuto = async function (box) {
        try {
            await API.post('/api/settings', { update_check_auto: box.checked });
        } catch (err) {
            box.checked = !box.checked;
            showNotification(t('Failed to save settings'), 'error');
        }
    };

    // ---------------------------------------------------------------------
    // After Install: wait for the server to go away and come back
    // ---------------------------------------------------------------------

    function waitForRestart(current) {
        const overlay = document.createElement('div');
        overlay.className = 'update-overlay';
        const msg = document.createElement('p');
        msg.textContent = t('Installing the update and restarting RetroDB…');
        overlay.append(msg);
        document.body.append(overlay);

        const started = Date.now();
        let wentDown = false;
        const tick = async () => {
            try {
                const r = await fetch('/health', { cache: 'no-store' });
                // Back up: after an outage, or already on another version
                // (a restart quicker than one poll).
                const version = r.ok ? (await r.json()).version : null;
                if (r.ok && (wentDown || (version && version !== current))) {
                    window.location.reload();
                    return;
                }
                if (!r.ok) wentDown = true;
            } catch (_) {
                wentDown = true;
            }
            if (Date.now() - started > 8 * 60 * 1000) {
                msg.textContent = t('RetroDB has not come back yet. See logs/update.log, then reload this page.');
                return;
            }
            setTimeout(tick, 2000);
        };
        setTimeout(tick, 2000);
    }

    // ---------------------------------------------------------------------

    async function init() {
        const card = document.querySelector('[data-update-card]');
        const banner = document.querySelector('[data-update-banner]');
        if (!card && !banner) return;
        let st;
        try {
            st = await API.get('/api/updates/status');
        } catch (_) {
            return;
        }
        if (banner) renderBanner(banner, st);
        if (card) new Card(card).render(st);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
