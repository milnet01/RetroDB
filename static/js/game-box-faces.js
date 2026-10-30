/**
 * PASS-59-142 — import a Slipcase box file onto a game.
 *
 * "Import 3D box", in the edit modal, opens a file picker; the editor picks the .box.json file
 * Slipcase saved together with its pictures (picking the whole folder is
 * fine: only the files the box file names are read). A game that already
 * has faces asks before replacing them. The modal then shows the case and a
 * Remove button, the game page's hint appears, and the record goes to the
 * turnable box in the cover zoom (box-viewer.js, PASS-59-143).
 *
 * Contract: docs/specs/PASS-59-142-box-file-import.md §4.4, §4.5.
 */
(function () {
    'use strict';

    const csrfToken = () => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    };

    async function send(gameId, method, body) {
        const resp = await fetch(`/api/games/${gameId}/box-faces`, {
            method,
            headers: {'X-CSRF-Token': csrfToken()},
            body,
        });
        const data = await resp.json().catch(() => ({}));
        return {status: resp.status, data};
    }

    function showNote(record) {
        if (window.BoxViewer) BoxViewer.setRecord(record);
        const hint = document.getElementById('boxFacesHint');
        if (hint) hint.hidden = !record;
        const status = document.getElementById('boxFacesStatus');
        if (!status) return;
        document.getElementById('boxFacesCase').textContent = record ? record.case.name : '';
        status.hidden = !record;
        const remove = document.getElementById('boxFacesRemoveBtn');
        if (remove) remove.hidden = !record;
    }

    async function upload(gameId, files, replace) {
        const form = new FormData();
        for (const file of files) form.append('files', file, file.name);
        if (replace) form.append('replace', '1');
        const {status, data} = await send(gameId, 'POST', form);
        if (data.success) {
            showNote(data.data.box_faces);
            showNotification(t('3D box imported.'), 'success');
        } else if (status === 409 && data.reason === 'exists') {
            showConfirm(t('Replace the 3D box?'),
                t('This game already has 3D box faces. Replace them with the ones you picked?'),
                () => upload(gameId, files, true));
        } else {
            showNotification(data.error || t('The box file could not be imported.'), 'error');
        }
    }

    function init() {
        const button = document.getElementById('boxFacesImportBtn');
        const input = document.getElementById('boxFacesInput');
        if (button && input) {
            button.addEventListener('click', () => input.click());
            input.addEventListener('change', () => {
                const files = Array.from(input.files);
                input.value = '';  // so picking the same files again still fires
                if (files.length) upload(button.dataset.gameId, files, false);
            });
        }
        const remove = document.getElementById('boxFacesRemoveBtn');
        if (remove) {
            remove.addEventListener('click', () => {
                showConfirm(t('Remove the 3D box?'),
                    t('The imported faces are deleted. Your Slipcase files are not touched.'),
                    async () => {
                        const {data} = await send(remove.dataset.gameId, 'DELETE');
                        if (data.success) {
                            showNote(null);
                            showNotification(t('3D box removed.'), 'success');
                        } else {
                            showNotification(data.error || t('The 3D box could not be removed.'), 'error');
                        }
                    });
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
