/**
 * ROM Tools > Bulk AI Fill: the game page's AI Fill on every game of one
 * system, or of all systems, saved straight to the games. The run also shows
 * in the AI Fill toast (toast-controller.js).
 */
(function () {
    'use strict';

    function failMessage(err, fallback) {
        return (err && err.status && err.message) ? err.message : fallback;
    }

    // The bulk fill's switches, remembered in this browser.
    const FILL_SWITCHES_KEY = 'aiFillBulkFields';

    function initFill() {
        const systemSelect = document.getElementById('fillSystem');
        const runBtn = document.getElementById('fillRunBtn');
        const cancelBtn = document.getElementById('fillCancelBtn');
        const countLine = document.getElementById('fillCount');
        const runStatus = document.getElementById('fillRunStatus');
        const switches = [...document.querySelectorAll('#fillSwitches input')];
        const includeDone = document.getElementById('fillIncludeDone');
        const progress = document.getElementById('fillProgress');
        const progressBar = document.getElementById('fillProgressBar');
        let pollTimer = null;
        let count = 0;

        const saved = Storage.get(FILL_SWITCHES_KEY);
        if (Array.isArray(saved)) {
            switches.forEach(box => { box.checked = saved.includes(box.value); });
        }

        function fields() {
            return switches.filter(box => box.checked).map(box => box.value);
        }

        function systemId() {
            return systemSelect.value ? Number(systemSelect.value) : null;
        }

        async function loadCount() {
            const selected = systemSelect.value;
            const chosen = fields();
            if (!chosen.length) {
                count = 0;
                countLine.textContent = t('Turn on at least one field.');
                return;
            }
            countLine.textContent = t('Loading…');
            try {
                const qs = new URLSearchParams({ fields: chosen.join(',') });
                if (selected) qs.set('system_id', selected);
                if (includeDone.checked) qs.set('include_done', '1');
                const data = await API.get(`/api/ai-fill-bulk/count?${qs}`);
                if (systemSelect.value !== selected) return;
                count = data.count;
                countLine.textContent = count
                    ? t('Games to fill: {count}.', { count: count })
                    : t('No game here has those fields empty, or AI Fill has done them all.');
            } catch (err) {
                countLine.textContent = failMessage(err, t('Could not count the games.'));
            }
        }

        function showProgress(percent) {
            progressBar.style.width = `${percent}%`;
            progressBar.dataset.percent = percent;
            progressBar.setAttribute('aria-valuenow', percent);
            progressBar.textContent = `${percent}%`;
        }

        function showRun(status) {
            const running = status.running;
            runBtn.disabled = running;
            cancelBtn.hidden = !running;
            progress.hidden = !(running || status.completed);
            showProgress(status.completed && !status.cancelled && !status.error ? 100 : status.percent);
            if (running) {
                runStatus.textContent = t('Filling game {current} of {total}: {title}. Filled so far: {filled}.',
                    { current: status.processing, total: status.total,
                      title: status.current_game || '', filled: status.success });
            } else if (status.error) {
                runStatus.textContent = t('The run stopped: {error}. Check your AI key with Test saved AI key in Settings > Scraping. Games already filled keep what they got.',
                    { error: status.error });
            } else if (status.completed) {
                runStatus.textContent = t('{state} Games filled: {filled}. Nothing new: {skipped}. No answer: {failed}.', {
                    state: status.cancelled ? t('Stopped.') : t('Done.'),
                    filled: status.success, skipped: status.skipped, failed: status.failed });
            }
            return running;
        }

        let pollMisses = 0;
        async function poll() {
            clearTimeout(pollTimer);
            try {
                const status = await API.get('/api/ai-fill-bulk/status');
                pollMisses = 0;
                if (showRun(status)) {
                    pollTimer = setTimeout(poll, 2000);
                } else if (status.completed) {
                    loadCount();
                }
            } catch (err) {
                // The run goes on without the page: keep asking, more
                // slowly, and give up after several misses (PASS-59-277).
                runStatus.textContent = failMessage(err, t('Could not read the run status.'));
                if (++pollMisses < 10) pollTimer = setTimeout(poll, 5000);
            }
        }

        async function start() {
            runBtn.disabled = true;
            try {
                await API.post('/api/ai-fill-bulk/run', {
                    system_id: systemId(), fields: fields(), include_done: includeDone.checked });
                if (window.UnifiedToastController) {
                    UnifiedToastController.adjustPollingSpeed('ai-fill', true);
                    UnifiedToastController.broadcast('job-started', 'ai-fill');
                }
                poll();
            } catch (err) {
                showNotification(failMessage(err, t('Could not start the run.')), 'error');
                runBtn.disabled = false;
            }
        }

        function switchesChanged() {
            Storage.set(FILL_SWITCHES_KEY, fields());
            loadCount();
        }

        runBtn.addEventListener('click', () => {
            if (!count) {
                showNotification(countLine.textContent, 'info');
                return;
            }
            showConfirm(t('Fill with AI'),
                t('Fill {count} games with AI? Your AI provider charges for each game.', { count: count }),
                start);
        });
        cancelBtn.addEventListener('click', async () => {
            try {
                await API.post('/api/ai-fill-bulk/cancel');
            } catch (err) {
                showNotification(failMessage(err, t('Could not stop the run.')), 'error');
            }
        });
        document.getElementById('fillAllOnBtn').addEventListener('click', () => {
            switches.forEach(box => { box.checked = true; });
            switchesChanged();
        });
        document.getElementById('fillAllOffBtn').addEventListener('click', () => {
            switches.forEach(box => { box.checked = false; });
            switchesChanged();
        });
        switches.forEach(box => box.addEventListener('change', switchesChanged));
        includeDone.addEventListener('change', loadCount);
        systemSelect.addEventListener('change', loadCount);

        loadCount();
        poll();
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (document.getElementById('aiFillBulk')) initFill();
    });
})();
