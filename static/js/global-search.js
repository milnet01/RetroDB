/**
 * Global search (PASS-53-1) — the sidebar search box on every page.
 *
 * Typing two or more characters lists matching systems (name or folder,
 * matched in the browser against /api/systems, fetched once) and up to
 * GAME_LIMIT games from /api/games?search=. The list is an ARIA combobox:
 * Up/Down move, Enter opens, Escape closes. "See all results" opens the
 * Library with the same search (all-games-controller.js reads ?q=).
 */
(function () {
    'use strict';

    const MIN_CHARS = 2;
    const GAME_LIMIT = 8;
    const SYSTEM_LIMIT = 4;
    const DEBOUNCE_MS = 250;

    let input, list, status;
    let systemsPromise = null;
    let pending = null;      // AbortController of the in-flight game query
    let timer = null;
    let activeIndex = -1;

    function loadSystems() {
        if (!systemsPromise) {
            systemsPromise = API.get('/api/systems')
                .then(r => (r && r.systems) || [])
                .catch(() => { systemsPromise = null; return []; });
        }
        return systemsPromise;
    }

    function matchSystems(systems, q) {
        const needle = q.toLowerCase();
        return systems.filter(s =>
            (s.name || '').toLowerCase().includes(needle) ||
            (s.folder || '').toLowerCase().includes(needle)
        ).slice(0, SYSTEM_LIMIT);
    }

    function options() {
        return Array.from(list.querySelectorAll('[role="option"]'));
    }

    function setActive(index) {
        const opts = options();
        opts.forEach(o => o.setAttribute('aria-selected', 'false'));
        activeIndex = opts.length ? (index + opts.length) % opts.length : -1;
        if (activeIndex >= 0) {
            const opt = opts[activeIndex];
            opt.setAttribute('aria-selected', 'true');
            input.setAttribute('aria-activedescendant', opt.id);
            opt.scrollIntoView({ block: 'nearest' });
        } else {
            input.removeAttribute('aria-activedescendant');
        }
    }

    function open() {
        list.hidden = false;
        input.setAttribute('aria-expanded', 'true');
    }

    function close() {
        list.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
        activeIndex = -1;
    }

    function libraryUrl(q) {
        return '/games?q=' + encodeURIComponent(q);
    }

    function optionHtml(id, href, label, meta, thumb) {
        return `<a role="option" id="${id}" aria-selected="false" class="global-search-option" href="${escapeHtml(href)}">`
            + (thumb !== undefined ? `<span class="global-search-thumb">${thumb}</span>` : '')
            + `<span class="global-search-text"><span class="global-search-label">${escapeHtml(label)}</span>`
            + (meta ? `<span class="global-search-meta">${escapeHtml(meta)}</span>` : '')
            + '</span></a>';
    }

    function render(q, systems, games, total) {
        let html = '';
        let n = 0;
        if (systems.length) {
            html += `<div class="global-search-group" role="presentation">${escapeHtml(t('Systems'))}</div>`;
            for (const s of systems) {
                html += optionHtml(`gs-opt-${n++}`, `/system/${s.id}`, s.name, '');
            }
        }
        if (games.length) {
            html += `<div class="global-search-group" role="presentation">${escapeHtml(t('Games'))}</div>`;
            for (const g of games) {
                const img = g.boxart
                    ? `<img src="/static/images/boxart/${escapeHtml(g.boxart)}" alt="" loading="lazy" data-on-error="hide">`
                    : '';
                html += optionHtml(`gs-opt-${n++}`, `/game/${g.id}`, g.title, g.system_name, img);
            }
            html += optionHtml(`gs-opt-${n++}`, libraryUrl(q),
                t('See all {n} results', { n: formatNumber(total) }), '');
        }
        if (!n) {
            html = `<div class="global-search-empty" role="presentation">${escapeHtml(t('No games or systems match'))}</div>`;
        }
        list.innerHTML = html;
        status.textContent = n
            ? t('{n} results', { n: formatNumber(total + systems.length) })
            : t('No games or systems match');
        activeIndex = -1;
        open();
    }

    async function search(q) {
        if (pending) pending.abort();
        pending = new AbortController();
        const signal = pending.signal;
        try {
            const [systems, data] = await Promise.all([
                loadSystems(),
                API.get(`/api/games?search=${encodeURIComponent(q)}&per_page=${GAME_LIMIT}`, { signal }),
            ]);
            if (signal.aborted || input.value.trim() !== q) return;
            render(q, matchSystems(systems, q), (data && data.games) || [], (data && data.total) || 0);
        } catch (err) {
            if (signal.aborted) return;
            list.innerHTML = `<div class="global-search-empty" role="presentation">${escapeHtml(t('Search failed. Try again.'))}</div>`;
            open();
        }
    }

    function onInput() {
        clearTimeout(timer);
        const q = input.value.trim();
        if (q.length < MIN_CHARS) {
            if (pending) pending.abort();
            close();
            return;
        }
        timer = setTimeout(() => search(q), DEBOUNCE_MS);
    }

    function onKeydown(e) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            if (list.hidden) {
                if (list.innerHTML) open();
                return;
            }
            e.preventDefault();
            setActive(activeIndex + (e.key === 'ArrowDown' ? 1 : -1));
        } else if (e.key === 'Enter') {
            const q = input.value.trim();
            const opt = activeIndex >= 0 ? options()[activeIndex] : null;
            if (opt) {
                e.preventDefault();
                window.location.href = opt.getAttribute('href');
            } else if (q.length >= MIN_CHARS) {
                e.preventDefault();
                window.location.href = libraryUrl(q);
            }
        } else if (e.key === 'Escape') {
            if (!list.hidden) {
                // Keep the global Escape handler from also closing a modal.
                e.stopPropagation();
                close();
            } else if (input.value) {
                input.value = '';
            } else {
                input.blur();
            }
        }
    }

    function init() {
        input = document.getElementById('globalSearch');
        list = document.getElementById('globalSearchList');
        status = document.getElementById('globalSearchStatus');
        if (!input || !list || !status) return;
        input.addEventListener('input', onInput);
        input.addEventListener('keydown', onKeydown);
        input.addEventListener('focus', () => {
            if (list.innerHTML && input.value.trim().length >= MIN_CHARS) open();
        });
        // Close when focus or a click lands outside the search.
        document.addEventListener('pointerdown', (e) => {
            if (!e.target.closest('.global-search')) close();
        });
        input.closest('.global-search').addEventListener('focusout', (e) => {
            if (!e.relatedTarget || !e.relatedTarget.closest('.global-search')) close();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
