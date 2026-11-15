/**
 * PASS-59-307 — search the help manual.
 *
 * Typing in #helpSearch hides every part of the manual that does not hold all
 * the words typed, and highlights them in what stays. A "part" is a section's
 * title, its text before the first sub-heading, or one sub-heading (h3/h4) with
 * the text under it. A section whose title matches stays whole.
 *
 * Matching ignores case and accents ("configuracao" finds "configuração"),
 * so it works the same in every language's manual. Highlighting uses the CSS
 * Custom Highlight API, which changes no markup; where a browser lacks it the
 * filter still works, unhighlighted.
 */
(function () {
    'use strict';

    const HIDDEN = 'help-search-hidden';
    const MIN_LENGTH = 2;

    // Fold one string for matching: lower case, accents removed.
    function fold(s) {
        return s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
    }

    // Fold a text node's text, keeping where each folded character came from,
    // so a match in the folded text maps back to a range in the original.
    function foldWithMap(text) {
        let folded = '';
        const map = [];
        for (let i = 0; i < text.length; i++) {
            const f = fold(text[i]);
            for (let j = 0; j < f.length; j++) {
                folded += f[j];
                map.push(i);
            }
        }
        return { folded, map };
    }

    // Split a section's body into parts, each starting at an h3 or h4. An h4
    // part remembers the h3 above it, so the h3 shows with a matching h4.
    function splitParts(body) {
        const parts = [];
        let current = { heading: null, parent: null, nodes: [] };
        let lastH3 = null;
        parts.push(current);
        for (const el of body.children) {
            if (el.tagName === 'H3' || el.tagName === 'H4') {
                current = { heading: el, parent: el.tagName === 'H4' ? lastH3 : null, nodes: [el] };
                if (el.tagName === 'H3') lastH3 = current;
                parts.push(current);
            } else {
                current.nodes.push(el);
            }
        }
        for (const p of parts) {
            p.text = fold(p.nodes.map(n => n.textContent).join(' '));
        }
        return parts.filter(p => p.nodes.length);
    }

    function init() {
        const input = document.getElementById('helpSearch');
        const status = document.getElementById('helpSearchStatus');
        if (!input || !status) return;

        // Each nav link hides when its target does. Some point at a heading
        // inside a section rather than at the section itself.
        const links = Array.from(document.querySelectorAll('.help-nav a[href^="#"]'))
            .map(a => ({ a, target: document.getElementById(a.getAttribute('href').slice(1)) }))
            .filter(l => l.target);

        const sections = Array.from(document.querySelectorAll('.help-section')).map(section => {
            const title = section.querySelector('.card-title');
            const body = section.querySelector('.card-body');
            return {
                section, body,
                title: fold(title ? title.textContent : ''),
                parts: body ? splitParts(body) : [],
            };
        });
        const canHighlight = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight === 'function';

        function setHidden(el, hidden) {
            if (el) el.classList.toggle(HIDDEN, hidden);
        }

        function highlight(words) {
            if (!canHighlight) return;
            CSS.highlights.delete('help-search');
            if (!words.length) return;
            const ranges = [];
            for (const s of sections) {
                if (s.section.classList.contains(HIDDEN)) continue;
                const walker = document.createTreeWalker(s.section, NodeFilter.SHOW_TEXT);
                for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                    if (node.parentElement.closest('.' + HIDDEN)) continue;
                    const { folded, map } = foldWithMap(node.data);
                    for (const w of words) {
                        let at = folded.indexOf(w);
                        while (at !== -1) {
                            const range = new Range();
                            range.setStart(node, map[at]);
                            range.setEnd(node, map[at + w.length - 1] + 1);
                            ranges.push(range);
                            at = folded.indexOf(w, at + w.length);
                        }
                    }
                }
            }
            CSS.highlights.set('help-search', new Highlight(...ranges));
        }

        function run() {
            const query = fold(input.value.trim());
            const words = query.length >= MIN_LENGTH ? query.split(/\s+/).filter(Boolean) : [];
            const has = text => words.every(w => text.includes(w));
            let found = 0;
            for (const s of sections) {
                const whole = !words.length || has(s.title);
                let any = whole;
                for (const p of s.parts) p.show = whole || has(p.text);
                for (const p of s.parts) {
                    if (p.show && p.parent) p.parent.show = true;
                }
                for (const p of s.parts) {
                    any = any || p.show;
                    // A heading shown only as a matching h4's parent hides its own text.
                    const ownMatch = whole || has(p.text);
                    p.nodes.forEach((n, i) => setHidden(n, !(p.show && (ownMatch || i === 0))));
                }
                setHidden(s.section, !any);
                if (any) found++;
            }
            for (const l of links) setHidden(l.a, !!l.target.closest('.' + HIDDEN));
            highlight(words);
            if (!words.length) {
                status.textContent = '';
            } else if (found) {
                status.textContent = t('Sections found: {count}', { count: found });
            } else {
                status.textContent = t('Nothing in the manual matches "{query}".', { query: input.value.trim() });
            }
        }

        input.addEventListener('input', debounce(run, 150));
        input.addEventListener('keydown', e => {
            if (e.key === 'Escape' && input.value) {
                e.preventDefault();
                e.stopPropagation();
                input.value = '';
                run();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                run();
                const first = sections.find(s => !s.section.classList.contains(HIDDEN));
                if (first && input.value.trim()) {
                    StickyScroll.to(first.section);
                }
            }
        });
        // A search box cleared with its own × button fires "search", not "input".
        input.addEventListener('search', run);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
