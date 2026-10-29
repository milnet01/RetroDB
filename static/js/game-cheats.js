/**
 * PASS-59-155 §4.6 — the game page's Cheats panel.
 *
 * Lists the cheats RetroDB found for this game, one on/off switch each.
 * For the player (RetroDB's RetroArch) a save writes the game's own cheat
 * list, copied in place at the next Play; for DuckStation and PCSX2 it
 * writes straight into the emulator's settings for this game. The panel
 * re-reads those files each time, so a switch flipped inside the emulator
 * shows here. Shown only for the player on a system with cheats, DuckStation
 * and PCSX2.
 *
 * Contract: docs/specs/PASS-59-155-cheats.md §4.6, §4.7.
 */
(function () {
    'use strict';

    const HARDCORE = () => ({
        player: t('A cheat that is on pauses RetroAchievements hardcore mode for that session.'),
        duckstation: t('DuckStation ignores cheats in hardcore mode.'),
        pcsx2: t('PCSX2 ignores cheats in hardcore mode.'),
    });

    // Above this many cheats the panel offers a search box.
    const FILTER_FROM = 12;

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    async function put(panel, body) {
        const resp = await fetch(`/api/games/${panel.dataset.gameId}/cheats`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken()},
            body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error(data.error || resp.statusText);
        return data.data;
    }

    function switchRow(name, checked, disabled, title) {
        const li = document.createElement('li');
        const toggle = document.createElement('label');
        toggle.className = 'toggle-switch';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = checked;
        input.disabled = disabled;
        input.dataset.name = name;
        input.setAttribute('aria-label', name);
        const slider = document.createElement('span');
        slider.className = 'toggle-slider';
        toggle.append(input, slider);
        const label = document.createElement('span');
        label.className = 'cheat-name' + (title ? ' cheat-locked' : '');
        label.textContent = name;
        if (title) li.title = title;
        li.append(toggle, label);
        return li;
    }

    function renderNote(panel, view) {
        const note = document.getElementById('cheatsNote');
        note.replaceChildren();
        if (view.reason) {
            note.append(view.reason);
            if (!view.cheats.length && panel.dataset.settingsUrl) {
                const link = document.createElement('a');
                link.href = `${panel.dataset.settingsUrl}#cheats`;
                link.textContent = t('Get cheats in Settings > Emulators');
                note.append(' ', link);
            }
            return;
        }
        note.textContent = view.emulator === 'player'
            ? t('Switched-on cheats apply the next time you press Play.')
            : t('Saved in the emulator\'s settings for this game. Changes made inside the emulator show here.');
    }

    function renderPicker(panel, view) {
        const picker = document.getElementById('cheatsPicker');
        const select = document.getElementById('cheatsSource');
        const canEdit = panel.dataset.canEdit === 'true';
        picker.hidden = !(view.emulator === 'player' && view.candidates.length > 1);
        if (picker.hidden) return;
        select.replaceChildren(...view.candidates.map((c) => {
            const opt = document.createElement('option');
            opt.value = c.source;
            opt.textContent = c.name;
            return opt;
        }));
        select.value = view.source;
        select.disabled = !canEdit;
        select.onchange = () => {
            const source = select.value;
            select.value = view.source;
            showConfirm(t('Use another cheat list?'),
                t('The switches go back to the new list\'s own settings.'),
                async () => {
                    select.disabled = true;
                    try {
                        render(panel, await put(panel, {source}));
                        showNotification(t('Cheat list changed.'), 'success');
                    } catch (err) {
                        showNotification((err && err.message) || t('Could not change the cheat list.'), 'error');
                        select.disabled = false;
                    }
                });
        };
    }

    function render(panel, view) {
        const list = document.getElementById('cheatsList');
        const canEdit = panel.dataset.canEdit === 'true';
        renderNote(panel, view);
        renderPicker(panel, view);

        const rows = [];
        if (view.always_on) {
            rows.push(switchRow(t('Always on while cheats are on'), true, true,
                t('PCSX2 applies these lines whenever any cheat is on.')));
        }
        for (const c of view.cheats) {
            rows.push(switchRow(c.name, c.enabled, !canEdit || c.locked,
                c.locked ? t('This name holds "=", which the emulator\'s settings cannot hold.') : ''));
        }
        list.replaceChildren(...rows);
        const filter = document.getElementById('cheatsFilter');
        filter.hidden = view.cheats.length <= FILTER_FROM;
        const applyFilter = () => {
            const want = filter.value.trim().toLowerCase();
            for (const li of rows) {
                li.hidden = !!want && !li.textContent.toLowerCase().includes(want);
            }
        };
        filter.oninput = applyFilter;
        applyFilter();
        list.onchange = async (event) => {
            const inputs = [...list.querySelectorAll('input[data-name]')]
                .filter((i) => !i.disabled);
            if (!inputs.includes(event.target)) return;
            const enabled = inputs.filter((i) => i.checked).map((i) => i.dataset.name);
            inputs.forEach((i) => { i.disabled = true; });
            try {
                render(panel, await put(panel, {enabled}));
                showNotification(t('Cheats saved.'), 'success');
            } catch (err) {
                showNotification((err && err.message) || t('Could not save the cheats.'), 'error');
                event.target.checked = !event.target.checked;
                inputs.forEach((i) => { i.disabled = false; });
            }
        };
        document.getElementById('cheatsHardcore').textContent =
            view.cheats.length ? HARDCORE()[view.emulator] || '' : '';
    }

    document.addEventListener('DOMContentLoaded', async () => {
        const panel = document.getElementById('cheatsPanel');
        if (!panel) return;
        try {
            const data = await API.get(`/api/games/${panel.dataset.gameId}/cheats`);
            if (!data.data.emulator) return;   // no cheats for this emulator
            render(panel, data.data);
            panel.hidden = false;
        } catch (err) {
            // A game with no emulator set up has nothing to show.
        }
    });
})();
