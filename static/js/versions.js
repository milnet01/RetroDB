/**
 * PASS-59-106 — regional versions of a game.
 *
 * Two pages use this file:
 *   - the game page's Versions section (#versionsSection): unlink this
 *     version, or search the same system and link another;
 *   - ROM Tools > Regional Versions (#versionsReview): review RetroDB's
 *     suggested groups and link them, or mark them "not versions".
 *
 * Contract: docs/specs/PASS-59-106-regional-versions.md §4.4 and §4.5.
 */
(function () {
    'use strict';

    function failMessage(err, fallback) {
        return (err && err.status && err.message) ? err.message : fallback;
    }

    // =========================================================================
    // GAME PAGE
    // =========================================================================

    function initGamePage(section) {
        const gameId = Number(section.dataset.gameId);
        const systemId = section.dataset.systemId;

        const unlinkBtn = document.getElementById('versionUnlinkBtn');
        if (unlinkBtn) {
            unlinkBtn.addEventListener('click', async () => {
                unlinkBtn.disabled = true;
                try {
                    await API.post(`/api/versions/unlink/${gameId}`);
                    showNotification(t('Version unlinked.'), 'success');
                    window.location.reload();
                } catch (err) {
                    showNotification(failMessage(err, t('Could not unlink this version.')), 'error');
                    unlinkBtn.disabled = false;
                }
            });
        }

        // PASS-59-107 — ask the AI how the versions differ.
        const aiBtn = document.getElementById('versionAiBtn');
        if (aiBtn) {
            aiBtn.addEventListener('click', async () => {
                aiBtn.disabled = true;
                aiBtn.setAttribute('aria-busy', 'true');
                showNotification(t('Asking the AI. This can take up to a minute.'), 'info');
                try {
                    const data = await API.post(`/api/versions/ai-summary/${gameId}`);
                    const list = document.getElementById('versionsAiList');
                    list.replaceChildren(...data.summary.differences.map(d => {
                        const li = document.createElement('li');
                        li.textContent = d;
                        return li;
                    }));
                    document.getElementById('versionsAiNone').hidden = data.summary.differences.length > 0;
                    document.getElementById('versionsAiSummary').hidden = false;
                    aiBtn.textContent = '🤖 ' + t('Write again with AI');
                    showNotification(t('Summary written.'), 'success');
                } catch (err) {
                    showNotification(failMessage(err, t('Could not write the summary.')), 'error');
                } finally {
                    aiBtn.disabled = false;
                    aiBtn.removeAttribute('aria-busy');
                }
            });
        }

        const input = document.getElementById('versionLinkSearch');
        const results = document.getElementById('versionLinkResults');
        if (!input || !results) return;

        const search = debounce(async () => {
            const term = input.value.trim();
            if (term.length < 2) {
                results.hidden = true;
                results.innerHTML = '';
                return;
            }
            try {
                const qs = new URLSearchParams({ system: systemId, search: term, per_page: 20 });
                const data = await API.get(`/api/games?${qs}`);
                renderCandidates(data.games.filter(g => g.id !== gameId));
            } catch (err) {
                showNotification(failMessage(err, t('Search failed.')), 'error');
            }
        }, 300);

        function renderCandidates(games) {
            results.innerHTML = '';
            if (!games.length) {
                const li = document.createElement('li');
                li.textContent = t('No matching games on this system.');
                results.appendChild(li);
            }
            for (const game of games) {
                const li = document.createElement('li');
                const label = document.createElement('span');
                label.textContent = game.version_count > 1
                    ? t('{title} ({count} versions)', { title: game.title, count: game.version_count })
                    : game.title;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-primary btn-sm';
                btn.textContent = t('Link');
                btn.addEventListener('click', () => linkWith(game.id, btn));
                li.append(label, btn);
                results.appendChild(li);
            }
            results.hidden = false;
        }

        async function linkWith(otherId, btn) {
            btn.disabled = true;
            try {
                await API.post('/api/versions/link', { game_ids: [gameId, otherId] });
                showNotification(t('Versions linked.'), 'success');
                window.location.reload();
            } catch (err) {
                showNotification(failMessage(err, t('Could not link these versions.')), 'error');
                btn.disabled = false;
            }
        }

        input.addEventListener('input', search);
    }

    // =========================================================================
    // REVIEW PAGE
    // =========================================================================

    const SIGNAL_LABELS = {
        igdb_id: () => t('Same IGDB game'),
        screenscraper_id: () => t('Same ScreenScraper game'),
        title: () => t('Same title, different region'),
        alternate_title: () => t('Regional name matches'),
    };

    function initReviewPage(root) {
        const list = document.getElementById('versionSuggestions');
        const status = document.getElementById('versionSuggestionsStatus');
        const systemSelect = document.getElementById('versionSystem');
        const findBtn = document.getElementById('versionFindBtn');

        async function load() {
            findBtn.disabled = true;
            status.textContent = t('Looking for versions…');
            list.innerHTML = '';
            try {
                const qs = new URLSearchParams(systemSelect.value ? { system_id: systemSelect.value } : {});
                const data = await API.get(`/api/versions/suggestions?${qs}`);
                status.textContent = data.suggestions.length
                    ? t('{count} suggested groups. Untick any game that does not belong, then link.', { count: data.suggestions.length })
                    : t('No suggestions. Run Backfill Alternate Titles in Maintenance to find more.');
                data.suggestions.forEach(s => list.appendChild(renderSuggestion(s)));
            } catch (err) {
                status.textContent = failMessage(err, t('Could not load suggestions.'));
            } finally {
                findBtn.disabled = false;
            }
        }

        function renderSuggestion(suggestion) {
            const card = document.createElement('li');
            card.className = 'card version-suggestion';

            const signals = document.createElement('div');
            signals.className = 'version-signals';
            for (const s of suggestion.signals) {
                const chip = document.createElement('span');
                chip.className = 'version-signal';
                chip.textContent = (SIGNAL_LABELS[s] || (() => s))();
                signals.appendChild(chip);
            }

            const games = document.createElement('ul');
            games.className = 'version-suggestion-games';
            for (const game of suggestion.games) {
                const li = document.createElement('li');
                const label = document.createElement('label');
                const box = document.createElement('input');
                box.type = 'checkbox';
                box.checked = true;
                box.value = game.id;
                const link = document.createElement('a');
                link.href = `/game/${game.id}`;
                link.textContent = game.title;
                const file = document.createElement('span');
                file.className = 'version-file';
                file.textContent = game.rom_file;
                label.append(box, ' ', link, ' ', file);
                li.appendChild(label);
                games.appendChild(li);
            }

            const actions = document.createElement('div');
            actions.className = 'version-suggestion-actions';
            const linkBtn = document.createElement('button');
            linkBtn.type = 'button';
            linkBtn.className = 'btn btn-primary btn-sm';
            linkBtn.textContent = t('Link ticked games');
            const rejectBtn = document.createElement('button');
            rejectBtn.type = 'button';
            rejectBtn.className = 'btn btn-secondary btn-sm';
            rejectBtn.textContent = t('Not versions');
            actions.append(linkBtn, rejectBtn);

            const ticked = () => [...games.querySelectorAll('input:checked')].map(b => Number(b.value));
            const act = async (url, ids, done, fail) => {
                if (ids.length < 2) {
                    showNotification(t('Tick at least two games.'), 'warning');
                    return;
                }
                linkBtn.disabled = rejectBtn.disabled = true;
                try {
                    await API.post(url, { game_ids: ids });
                    showNotification(done, 'success');
                    card.remove();
                } catch (err) {
                    showNotification(failMessage(err, fail), 'error');
                    linkBtn.disabled = rejectBtn.disabled = false;
                }
            };
            linkBtn.addEventListener('click', () => act('/api/versions/link', ticked(),
                t('Versions linked.'), t('Could not link these versions.')));
            rejectBtn.addEventListener('click', () => act('/api/versions/reject',
                suggestion.games.map(g => g.id),
                t('Marked as not versions.'), t('Could not save that.')));

            card.append(signals, games, actions);
            return card;
        }

        findBtn.addEventListener('click', load);
    }

    document.addEventListener('DOMContentLoaded', () => {
        const section = document.getElementById('versionsSection');
        if (section) initGamePage(section);
        const review = document.getElementById('versionsReview');
        if (review) initReviewPage(review);
    });
})();
