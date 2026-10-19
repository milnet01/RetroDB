/**
 * PASS-59-91 §4.6 — the game page's Emulator settings panel.
 *
 * Shows the settings RetroDB manages for this game's emulator (DuckStation,
 * PCSX2, RPCS3) and where each value comes from. Editors pick a value for
 * this game, or "Use the system setting" to remove the game's choice.
 * Fullscreen is set per system only (Settings > Emulators). Nothing is
 * written to the emulator's folder until the next Play.
 *
 * Contract: docs/specs/PASS-59-91-zero-setup-play.md §4.6 Routes.
 */
(function () {
    'use strict';

    const LABELS = () => ({
        resolution_scale: t('Resolution scale'),
        aspect_ratio: t('Aspect ratio'),
        fullscreen: t('Fullscreen'),
    });

    function sourceText(source) {
        return {
            game: t('Set for this game'),
            system: t('From the system setting'),
            default: t('RetroDB default'),
            emulator: t('Set inside the emulator; RetroDB leaves it alone'),
        }[source] || '';
    }

    function render(panel, view) {
        const grid = document.getElementById('emuSettingsGrid');
        const note = document.getElementById('emuSettingsNote');
        const canEdit = panel.dataset.canEdit === 'true';
        const gameId = panel.dataset.gameId;
        const labels = LABELS();

        let text = view.supported
            ? t('Applied when you press Play, in the {emulator} settings for this game.',
                {emulator: view.emulator.name})
            : (view.reason || '');
        if (view.candidates && view.candidates.length) {
            text += ' ' + view.candidates.join(', ');
        }
        note.textContent = text;

        grid.replaceChildren(...view.settings.map((s) => {
            const box = document.createElement('div');
            box.className = 'emu-setting';
            const id = `emuSetting-${s.setting}`;
            const label = document.createElement('label');
            label.htmlFor = id;
            label.textContent = labels[s.setting] || s.setting;
            const source = document.createElement('div');
            source.className = 'emu-setting-source';
            source.textContent = sourceText(s.source);

            if (!s.per_game || !canEdit) {
                const value = document.createElement('div');
                value.id = id;
                value.textContent = s.value;
                if (!s.per_game) source.textContent = t('Set per system, in Settings > Emulators');
                box.append(label, value, source);
                return box;
            }

            const select = document.createElement('select');
            select.id = id;
            select.className = 'form-input';
            const inherit = document.createElement('option');
            inherit.value = '';
            inherit.textContent = t('Use the system setting');
            select.appendChild(inherit);
            for (const v of s.values) {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                select.appendChild(opt);
            }
            select.value = s.source === 'game' ? s.value : '';
            select.addEventListener('change', async () => {
                select.disabled = true;
                try {
                    const resp = await fetch(`/api/games/${gameId}/emulator-settings`, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({[s.setting]: select.value || null}),
                    });
                    const data = await resp.json();
                    if (!resp.ok || !data.success) throw new Error(data.error || resp.statusText);
                    render(panel, data.data);
                    showNotification(t('Saved. It applies the next time you press Play.'), 'success');
                } catch (err) {
                    showNotification((err && err.message) || t('Could not save that setting.'), 'error');
                    select.disabled = false;
                }
            });
            box.append(label, select, source);
            return box;
        }));
    }

    document.addEventListener('DOMContentLoaded', async () => {
        const panel = document.getElementById('emuSettingsPanel');
        if (!panel) return;
        try {
            const data = await API.get(`/api/games/${panel.dataset.gameId}/emulator-settings`);
            if (!data.data.settings.length) return;   // not a managed emulator
            render(panel, data.data);
            panel.hidden = false;
        } catch (err) {
            // A game with no emulator set up has nothing to show.
        }
    });
})();
