/**
 * PASS-59-159 — ROM Tools > Official Names.
 *
 * Starts the AI run that proposes each game's official name, shows its
 * progress, and lists the proposals to accept or reject.
 *
 * Contract: docs/specs/PASS-59-159-official-names.md §4.5.
 */
(function () {
    'use strict';

    // CLDR codes the run stores for the old name's region.
    const REGION_LABELS = {
        US: () => t('USA'),
        150: () => t('Europe'),
        JP: () => t('Japan'),
        '001': () => t('World'),
    };

    function failMessage(err, fallback) {
        return (err && err.status && err.message) ? err.message : fallback;
    }

    function init() {
        const systemSelect = document.getElementById('namesSystem');
        const runBtn = document.getElementById('namesRunBtn');
        const cancelBtn = document.getElementById('namesCancelBtn');
        const runStatus = document.getElementById('namesRunStatus');
        const listStatus = document.getElementById('namesListStatus');
        const actions = document.getElementById('namesActions');
        const list = document.getElementById('namesList');
        let pollTimer = null;

        function systemId() {
            return systemSelect.value ? Number(systemSelect.value) : null;
        }

        async function loadProposals() {
            listStatus.textContent = t('Loading…');
            const selected = systemSelect.value;
            try {
                const qs = new URLSearchParams(selected ? { system_id: selected } : {});
                const data = await API.get(`/api/official-names/proposals?${qs}`);
                // The system changed while this loaded; its own load follows.
                if (systemSelect.value !== selected) return;
                list.replaceChildren(...data.proposals.map(renderRow));
                actions.hidden = data.proposals.length === 0;
                listStatus.textContent = data.proposals.length
                    ? t('Suggested names waiting: {count}. Untick any you do not want, then accept.', { count: data.proposals.length })
                    : t('No suggested names waiting. Press Ask the AI to look for some.');
            } catch (err) {
                listStatus.textContent = failMessage(err, t('Could not load the suggested names.'));
            }
        }

        function renderRow(p) {
            const li = document.createElement('li');
            const label = document.createElement('label');
            const box = document.createElement('input');
            box.type = 'checkbox';
            box.checked = true;
            box.value = p.game_id;

            const change = document.createElement('span');
            change.className = 'names-change';
            const oldName = document.createElement('span');
            oldName.textContent = p.old_title;
            const newName = document.createElement('span');
            newName.className = 'names-new';
            newName.textContent = p.proposed_title;
            const meta = document.createElement('span');
            meta.className = 'names-meta';
            const region = p.old_title_region
                ? (REGION_LABELS[p.old_title_region] || (() => p.old_title_region))()
                : t('unknown');
            meta.textContent = t('{system} · {file} · old name from: {region}',
                { system: p.system_name, file: p.rom_file, region: region });
            change.append(oldName, ' → ', newName, meta);

            label.append(box, change);
            li.appendChild(label);
            return li;
        }

        function ticked() {
            return [...list.querySelectorAll('input:checked')].map(b => Number(b.value));
        }

        async function act(url, done, fail) {
            const ids = ticked();
            if (!ids.length) {
                showNotification(t('Tick at least one name.'), 'warning');
                return;
            }
            actions.querySelectorAll('button').forEach(b => { b.disabled = true; });
            try {
                const data = await API.post(url, { game_ids: ids });
                showNotification(done(data), 'success');
                await loadProposals();
            } catch (err) {
                showNotification(failMessage(err, fail), 'error');
            } finally {
                actions.querySelectorAll('button').forEach(b => { b.disabled = false; });
            }
        }

        function showRun(status) {
            const running = status.running;
            runBtn.disabled = running;
            cancelBtn.hidden = !running;
            if (running) {
                runStatus.textContent = t('Asking the AI: game {current} of {total}. Names suggested: {proposals}. {system}',
                    { current: status.current, total: status.total, proposals: status.proposals,
                      system: status.current_system || '' });
            } else if (status.error) {
                runStatus.textContent = t('The run stopped: {error}. Names already suggested are kept.', { error: status.error });
            } else if (status.completed) {
                runStatus.textContent = status.cancelled
                    ? t('Stopped. Names suggested: {proposals}.', { proposals: status.proposals })
                    : t('Done. Games asked: {total}. Names suggested: {proposals}.',
                        { proposals: status.proposals, total: status.total });
            }
            return running;
        }

        async function poll() {
            clearTimeout(pollTimer);
            try {
                const data = await API.get('/api/official-names/status');
                if (showRun(data.status)) {
                    pollTimer = setTimeout(poll, 2000);
                } else if (data.status.completed) {
                    await loadProposals();
                }
            } catch (err) {
                runStatus.textContent = failMessage(err, t('Could not read the run status.'));
            }
        }

        runBtn.addEventListener('click', async () => {
            runBtn.disabled = true;
            try {
                await API.post('/api/official-names/run', { system_id: systemId() });
                poll();
            } catch (err) {
                showNotification(failMessage(err, t('Could not start the run.')), 'error');
                runBtn.disabled = false;
            }
        });
        cancelBtn.addEventListener('click', async () => {
            try {
                await API.post('/api/official-names/cancel');
            } catch (err) {
                showNotification(failMessage(err, t('Could not stop the run.')), 'error');
            }
        });
        document.getElementById('namesAcceptBtn').addEventListener('click', () => act(
            '/api/official-names/accept',
            d => d.skipped
                ? t('Names changed: {accepted}. Skipped because their title changed since: {skipped}.',
                    { accepted: d.accepted, skipped: d.skipped })
                : t('Names changed: {accepted}.', { accepted: d.accepted }),
            t('Could not accept these names.')));
        document.getElementById('namesRejectBtn').addEventListener('click', () => act(
            '/api/official-names/reject',
            d => t('Names rejected: {rejected}. They will not be suggested again.', { rejected: d.rejected }),
            t('Could not reject these names.')));
        document.getElementById('namesTickAllBtn').addEventListener('click', () => {
            list.querySelectorAll('input').forEach(b => { b.checked = true; });
        });
        document.getElementById('namesTickNoneBtn').addEventListener('click', () => {
            list.querySelectorAll('input').forEach(b => { b.checked = false; });
        });
        systemSelect.addEventListener('change', loadProposals);

        loadProposals();
        poll();
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (document.getElementById('officialNamesReview')) init();
    });
})();
