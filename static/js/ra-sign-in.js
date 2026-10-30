// =============================================================================
// RETRODB - Settings > Account: RetroAchievements sign-in
// =============================================================================
// The password goes to /api/retroachievements/sign-in and the box is cleared at
// once. Page-specific JS (not bundled).
// =============================================================================

(function () {
    'use strict';

    const URL = '/api/retroachievements/sign-in';
    const box = document.getElementById('raPlay');
    if (!box) return;
    const el = (id) => document.getElementById(id);
    const password = el('raPlayPassword');
    const note = el('raPlayStatus');
    const hardcore = el('raPlayHardcore');

    // By style, not the hidden attribute: .btn and .path-input-row set display.
    const shown = (id, on) => { el(id).style.display = on ? '' : 'none'; };

    function show(state) {
        shown('raPlayIntro', !state.signed_in);
        shown('raPlayForm', !state.signed_in);
        shown('raPlaySignOut', state.signed_in);
        shown('raPlaySignedIn', state.signed_in);
        shown('raPlayHardcoreRow', state.signed_in);
        el('raPlaySignedIn').textContent = t('Signed in as {name}', {name: state.username});
        hardcore.checked = state.hardcore;
        box.style.display = '';
    }

    async function send(method, url, body) {
        const headers = {'Content-Type': 'application/json'};
        const token = document.querySelector('meta[name="csrf-token"]');
        if (token) headers['X-CSRF-Token'] = token.getAttribute('content');
        const rv = await fetch(url, {method, headers, body: body && JSON.stringify(body)});
        const data = await rv.json();
        if (!rv.ok || !data.success) throw new Error(data.error || rv.statusText);
        return data;
    }

    async function signIn() {
        const value = password.value;
        password.value = '';
        el('raPlaySignIn').disabled = true;
        note.textContent = t('Signing in…');
        try {
            show(await send('POST', URL, {username: el('userRaUsername').value.trim(), password: value}));
            note.textContent = '';
        } catch (e) {
            note.textContent = e.message;
        }
        el('raPlaySignIn').disabled = false;
    }

    el('raPlaySignIn').addEventListener('click', signIn);
    password.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
            ev.preventDefault();
            signIn();
        }
    });
    el('raPlaySignOut').addEventListener('click', async () => {
        try {
            show(await send('DELETE', URL));
            note.textContent = '';
        } catch (e) {
            note.textContent = e.message;
        }
    });
    hardcore.addEventListener('change', async () => {
        try {
            show(await send('PUT', '/api/retroachievements/hardcore', {on: hardcore.checked}));
            note.textContent = t('Saved. It applies the next time you press Play.');
        } catch (e) {
            hardcore.checked = !hardcore.checked;
            note.textContent = t('Save failed: {error}', {error: e.message});
        }
    });

    send('GET', URL).then(show).catch(() => {});
})();
