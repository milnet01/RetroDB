/**
 * PASS-59-148 — read a game's PDF manual on the game page.
 *
 * The Manual button opens #manualReaderModal (templates/_modals/
 * manual_reader_modal.html). Pages turn with a page-flip — none under
 * reduced motion — by the arrow buttons, the arrow / Page keys, Home / End,
 * or a swipe. A ctrl-, shift- or middle-click still opens the raw PDF in a
 * new tab, and so does the link in the reader's header.
 *
 * PDF.js (pdfjs-dist 6.4.299, Apache-2.0) is vendored in
 * static/js/vendor/pdfjs/ and imported on first open: build/pdf.min.mjs and
 * pdf.worker.min.mjs, cmaps/, standard_fonts/, and the two JavaScript image
 * decoders from wasm/. It runs under the page's CSP: those decoders are used
 * instead of the .wasm ones (useWasm: false), so the CSP needs no
 * 'wasm-unsafe-eval'. To update, `npm pack pdfjs-dist@<version>` and copy
 * the same files over.
 */
(function () {
    'use strict';

    const CACHE_PAGES = 6;      // rendered pages kept for quick turns back
    const SWIPE_PX = 50;
    const TURN_MS = 600;        // must cover the CSS flip animation

    const state = {
        modal: null, stage: null, label: null, prev: null, next: null,
        pdfjs: null, task: null, doc: null,
        page: 1, pages: 0, turning: false,
        cache: new Map(),       // page number -> canvas
        cacheKey: '',           // stage size the cached canvases fit
        swipeX: null,
    };

    function reducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    function absolute(url) {
        return new URL(url, window.location.href).href;
    }

    async function loadPdfjs() {
        if (!state.pdfjs) {
            const ds = state.modal.dataset;
            state.pdfjs = await import(ds.pdfjsUrl);
            state.pdfjs.GlobalWorkerOptions.workerSrc = absolute(ds.workerUrl);
        }
        return state.pdfjs;
    }

    function setMessage(text) {
        state.stage.replaceChildren();
        const p = document.createElement('p');
        p.className = 'manual-reader-message';
        p.textContent = text;
        state.stage.appendChild(p);
    }

    function updateControls() {
        state.label.textContent = state.pages
            ? `${t('Page:')} ${state.page} / ${state.pages}` : '';
        state.prev.disabled = !state.pages || state.page <= 1;
        state.next.disabled = !state.pages || state.page >= state.pages;
    }

    // A canvas holding page `num`, scaled to fit the stage and drawn at the
    // screen's pixel density. Cached until the stage changes size.
    async function renderPage(num) {
        const box = state.stage.getBoundingClientRect();
        const key = `${Math.round(box.width)}x${Math.round(box.height)}`;
        if (key !== state.cacheKey) {
            state.cache.clear();
            state.cacheKey = key;
        }
        if (state.cache.has(num)) return state.cache.get(num);

        const page = await state.doc.getPage(num);
        const base = page.getViewport({ scale: 1 });
        const fit = Math.min(box.width / base.width, box.height / base.height);
        const dpr = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale: fit * dpr });
        const canvas = document.createElement('canvas');
        canvas.className = 'manual-reader-sheet';
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
        canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;
        await page.render({ canvas, viewport }).promise;

        state.cache.set(num, canvas);
        if (state.cache.size > CACHE_PAGES) {
            const far = [...state.cache.keys()].sort(
                (a, b) => Math.abs(b - state.page) - Math.abs(a - state.page))[0];
            state.cache.delete(far);
        }
        return canvas;
    }

    function prerender(num) {
        if (num >= 1 && num <= state.pages) renderPage(num).catch(() => {});
    }

    function wait(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // Show page `num`. Forward, the current sheet turns away over its left
    // edge and uncovers the next; back, the earlier sheet turns in over it.
    async function show(num) {
        if (state.turning || !state.doc || num < 1 || num > state.pages) return;
        state.turning = true;
        try {
            const doc = state.doc;
            const incoming = await renderPage(num);
            if (doc !== state.doc) return;     // closed while rendering
            const outgoing = state.stage.querySelector('.manual-reader-sheet');
            const animate = outgoing && outgoing !== incoming && !reducedMotion();
            const forward = num > state.page;
            state.page = num;
            updateControls();

            if (!animate) {
                state.stage.replaceChildren(incoming);
            } else {
                incoming.classList.remove('turn-out', 'turn-in');
                if (forward) {
                    state.stage.insertBefore(incoming, outgoing);
                    outgoing.classList.add('turn-out');
                } else {
                    incoming.classList.add('turn-in');
                    state.stage.appendChild(incoming);
                }
                await wait(TURN_MS);
                outgoing.classList.remove('turn-out');
                incoming.classList.remove('turn-in');
                if (doc === state.doc) state.stage.replaceChildren(incoming);
            }
            prerender(num + 1);
            prerender(num - 1);
        } catch (err) {
            console.error('Manual reader: could not draw page', num, err);
            setMessage(t('Could not show this page of the manual.'));
        } finally {
            state.turning = false;
        }
    }

    function turn(step) {
        show(state.page + step);
    }

    async function open(url) {
        state.modal.classList.add('active');
        state.page = 1;
        state.pages = 0;
        updateControls();
        setMessage(t('Loading the manual…'));
        try {
            const pdfjs = await loadPdfjs();
            const vendor = absolute(state.modal.dataset.vendorUrl);
            state.task = pdfjs.getDocument({
                url: absolute(url),
                useWasm: false,
                wasmUrl: `${vendor}wasm/`,
                cMapUrl: `${vendor}cmaps/`,
                standardFontDataUrl: `${vendor}standard_fonts/`,
            });
            const doc = await state.task.promise;
            if (!state.modal.classList.contains('active')) {
                doc.destroy();
                return;
            }
            state.doc = doc;
            state.pages = doc.numPages;
            state.stage.replaceChildren();
            state.stage.focus();
            await show(1);
        } catch (err) {
            if (!state.modal.classList.contains('active')) return;
            console.error('Manual reader: could not open', url, err);
            setMessage(t('Could not open this manual. Use "Open PDF in a new tab" instead.'));
        }
    }

    function close() {
        state.modal.classList.remove('active');
        if (state.task) state.task.destroy();
        state.task = null;
        state.doc = null;
        state.pages = 0;
        state.cache.clear();
        state.cacheKey = '';
        state.stage.replaceChildren();
    }

    // The Manual button: an ordinary click opens the reader; a modified or
    // middle click keeps the link's own new-tab behaviour.
    function openFromLink(link, event) {
        if (!state.modal) return;
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        open(link.href);
    }

    function onKey(event) {
        const keys = {
            ArrowRight: () => turn(1), PageDown: () => turn(1),
            ArrowLeft: () => turn(-1), PageUp: () => turn(-1),
            Home: () => show(1), End: () => show(state.pages),
        };
        if (!state.doc || !keys[event.key]) return;
        event.preventDefault();
        keys[event.key]();
    }

    function init() {
        state.modal = document.getElementById('manualReaderModal');
        if (!state.modal) return;
        state.stage = document.getElementById('manualReaderStage');
        state.label = document.getElementById('manualReaderPage');
        state.prev = document.getElementById('manualReaderPrev');
        state.next = document.getElementById('manualReaderNext');

        state.modal.addEventListener('keydown', onKey);
        state.stage.addEventListener('pointerdown', e => { state.swipeX = e.clientX; });
        state.stage.addEventListener('pointerup', e => {
            if (state.swipeX === null) return;
            const dx = e.clientX - state.swipeX;
            state.swipeX = null;
            if (Math.abs(dx) >= SWIPE_PX) turn(dx < 0 ? 1 : -1);
        });
        // A new size re-fits the page without a turn; renderPage empties
        // the cache when the stage size changes.
        window.addEventListener('resize', debounce(async () => {
            if (!state.doc || state.turning) return;
            const doc = state.doc;
            const sheet = await renderPage(state.page).catch(() => null);
            if (sheet && doc === state.doc) state.stage.replaceChildren(sheet);
        }, 250));
    }

    window.ManualReader = { open, close, turn, openFromLink };
    window.closeManualReader = close;
    document.addEventListener('DOMContentLoaded', init);
})();
