/**
 * PASS-59-227 — ROM Tools > MAME Names: starts the job and shows its progress.
 * The chosen file paths are remembered in this browser.
 */
(function () {
    'use strict';

    const FIELDS = { list_path: 'mameListPath', extra_list_path: 'mameExtraListPath', category_path: 'mameCategoryPath' };
    const PATHS_KEY = 'mameNamesPaths';

    document.addEventListener('DOMContentLoaded', () => {
        const runBtn = document.getElementById('mameRunBtn');
        const cancelBtn = document.getElementById('mameCancelBtn');
        const statusLine = document.getElementById('mameStatus');
        if (!runBtn) return;

        const saved = Storage.get(PATHS_KEY) || {};
        Object.entries(FIELDS).forEach(([key, id]) => {
            document.getElementById(id).value = saved[key] || '';
        });

        function show(status) {
            runBtn.disabled = status.running;
            cancelBtn.hidden = !status.running;
            if (status.running) {
                statusLine.textContent = status.reading
                    ? t('Reading the lists. This can take a few minutes.')
                    : t('Naming game {current} of {total}.', { current: status.current, total: status.total });
            } else if (status.error) {
                statusLine.textContent = t('That stopped: {error}', { error: status.error });
            } else if (status.completed) {
                statusLine.textContent = t('{state} Games named: {named}. Games changed: {updated}. Not in the lists: {missing}.', {
                    state: status.cancelled ? t('Stopped.') : t('Done.'),
                    named: status.named, updated: status.updated, missing: status.not_listed });
            }
            return status.running;
        }

        let pollMisses = 0;
        async function poll() {
            try {
                const status = await API.get('/api/mame-names/status');
                pollMisses = 0;
                if (show(status)) setTimeout(poll, 2000);
            } catch (err) {
                // The job goes on without the page: keep asking, more
                // slowly; after several misses, let the user try again.
                statusLine.textContent = t('Could not read the run status.');
                if (++pollMisses < 10) setTimeout(poll, 5000);
                else runBtn.disabled = false;
            }
        }

        runBtn.addEventListener('click', async () => {
            const body = {};
            Object.entries(FIELDS).forEach(([key, id]) => {
                body[key] = document.getElementById(id).value.trim();
            });
            Storage.set(PATHS_KEY, body);
            runBtn.disabled = true;
            try {
                await API.post('/api/mame-names/start', body);
                poll();
            } catch (err) {
                showNotification((err && err.status && err.message) || t('Could not start the run.'), 'error');
                runBtn.disabled = false;
            }
        });
        cancelBtn.addEventListener('click', () => {
            API.post('/api/mame-names/cancel').catch(() => {
                showNotification(t('Could not stop the run.'), 'error');
            });
        });
        poll();
    });
})();
