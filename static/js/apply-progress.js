// =============================================================================
// RETRODB - Apply Metadata progress gauge
// =============================================================================
// PASS-59-108 — the game page's Search Metadata apply runs in the background
// (POST /api/game/<id>/apply-metadata) and this file polls
// GET /api/apply-metadata/<task> into a ring gauge with the percentage in its
// centre and the current step beneath. At 100% the page reloads, where the
// server's flashed message reports what was filled. A failure closes the
// overlay and shows the error as a toast.
// =============================================================================

(function () {
    'use strict';

    const POLL_MS = 400;
    const RADIUS = 52;
    const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    // t() takes string literals only (docs/specs/i18n.md §6), so each label
    // is spelled out rather than built from the media kind.
    function stepText(step) {
        switch (step.kind) {
            case 'fetch': return t('Fetching from {source}…', {source: step.source});
            case 'search': return t('Searching {source}…', {source: step.source});
            case 'ai': return t('Asking AI…');
            case 'process': return t('Processing images…');
            case 'save': return t('Saving to the database…');
            case 'achievements': return t('Checking RetroAchievements…');
            case 'download':
                switch (step.media) {
                    case 'boxart': return t('Downloading box art…');
                    case 'boxart_3d': return t('Downloading 3D box art…');
                    case 'fanart': return t('Downloading fan art…');
                    case 'screenshot': return t('Downloading screenshots…');
                    case 'video': return t('Downloading video…');
                    case 'manual': return t('Downloading manual…');
                    default: return t('Downloading media…');
                }
            default: return t('Starting…');
        }
    }

    function overlay() {
        let el = document.getElementById('applyingOverlay');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'applyingOverlay';
        el.className = 'applying-overlay';
        el.innerHTML = `
            <div class="applying-content">
                <div class="applying-gauge" role="progressbar" aria-valuemin="0"
                     aria-valuemax="100" aria-valuenow="0"
                     aria-label="${escapeHtml(t('Applying Metadata'))}">
                    <svg viewBox="0 0 120 120" aria-hidden="true">
                        <circle class="applying-gauge-track" cx="60" cy="60" r="${RADIUS}"></circle>
                        <circle class="applying-gauge-fill" cx="60" cy="60" r="${RADIUS}"
                                stroke-dasharray="${CIRCUMFERENCE}"
                                stroke-dashoffset="${CIRCUMFERENCE}"></circle>
                    </svg>
                    <span class="applying-gauge-percent">0%</span>
                </div>
                <div class="applying-text">${escapeHtml(t('Applying Metadata'))}</div>
                <div class="applying-subtext" aria-live="polite"></div>
            </div>
        `;
        document.body.appendChild(el);
        return el;
    }

    function render(el, percent, step) {
        const pct = Math.max(0, Math.min(100, percent));
        el.querySelector('.applying-gauge-fill')
            .setAttribute('stroke-dashoffset', CIRCUMFERENCE * (1 - pct / 100));
        el.querySelector('.applying-gauge').setAttribute('aria-valuenow', pct);
        el.querySelector('.applying-gauge-percent').textContent = pct + '%';
        el.querySelector('.applying-subtext').textContent = stepText(step);
    }

    function fail(el, message) {
        el.classList.remove('active');
        showNotification(message || t('Could not apply metadata.'), 'error');
    }

    // One apply at a time: a second run would poll into the same gauge.
    let running = false;

    async function run(gameId, gameSource, secondarySelections) {
        if (running) return;
        running = true;
        try {
            await start(gameId, gameSource, secondarySelections);
        } finally {
            running = false;
        }
    }

    async function start(gameId, gameSource, secondarySelections) {
        const el = overlay();
        render(el, 0, {kind: 'start'});
        el.classList.add('active');

        let taskId;
        try {
            const rv = await fetch(`/api/game/${gameId}/apply-metadata`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
                body: JSON.stringify({
                    game_source: gameSource,
                    secondary_selections: secondarySelections,
                }),
            });
            const body = await rv.json().catch(() => ({}));
            if (!rv.ok || !body.success) return fail(el, body.error);
            taskId = body.task_id;
        } catch (e) {
            console.error('Apply metadata start failed:', e);
            return fail(el);
        }

        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
        for (;;) {
            await sleep(POLL_MS);
            let body;
            try {
                const rv = await fetch(`/api/apply-metadata/${taskId}`);
                body = await rv.json().catch(() => ({}));
                if (!rv.ok || !body.success) return fail(el, body.error);
            } catch (e) {
                console.error('Apply metadata poll failed:', e);
                return fail(el);
            }
            render(el, body.percent, body.step);
            if (!body.finished) continue;
            if (!body.applied) return fail(el, body.error);
            // A GET of the same page, so a reload never re-submits a form.
            window.location.assign(window.location.pathname + window.location.search);
            return;
        }
    }

    window.ApplyProgress = {run};
})();
