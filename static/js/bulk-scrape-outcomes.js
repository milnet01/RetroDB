/**
 * The games the latest bulk scrape failed or skipped, with the reason
 * (PASS-59-338). The server keeps the list until a fresh bulk scrape starts
 * (services/jobs/bulk_scrape.py, table bulk_scrape_outcomes), so this card
 * comes back after a reload or a restart until the person closes it.
 *
 * Used by the Bulk Scraping window (bulk-scrape.js showResults) and, on every
 * page, by a card beside the job cards once a run ends.
 */
const BulkScrapeOutcomes = {
    CARD_ID: 'bulkOutcomesCard',

    /** One sentence per reason the server records (OUTCOME_REASONS). */
    reasonText(reason) {
        const texts = {
            not_found: t('The game is no longer in the library'),
            cooldown: t('Bulk scraped in the last 24 hours'),
            all_filled: t('Every field is already filled'),
            no_results: t('No source found the game'),
            no_match: t('No result was close enough to pass the match filter'),
            source_limit: t('A source had reached its limit; the next bulk scrape asks again'),
            no_updates: t('Found, but there was nothing new to add'),
            error: t('An error stopped the scrape'),
        };
        return texts[reason] || reason;
    },

    _item(game) {
        const name = escapeHtml(game.title || t('Game {id}', {id: game.game_id}));
        const link = game.game_id ? `<a href="/game/${encodeURIComponent(game.game_id)}">${name}</a>` : name;
        const detail = game.detail ? `: ${escapeHtml(game.detail)}` : '';
        return `<li>${link} <span class="bulk-outcome-reason">${escapeHtml(this.reasonText(game.reason))}${detail}</span></li>`;
    },

    /** HTML for the list: failed games open, skipped ones under a closed heading. */
    render(games) {
        const failed = games.filter(g => g.outcome === 'failed');
        const skipped = games.filter(g => g.outcome === 'skipped');
        let html = '';
        if (failed.length) {
            html += `<h3 class="bulk-outcomes-heading">${escapeHtml(t('Failed ({count})', {count: formatNumber(failed.length)}))}</h3>`
                + `<ul class="bulk-outcomes-list">${failed.map(g => this._item(g)).join('')}</ul>`;
        }
        if (skipped.length) {
            html += `<details class="bulk-outcomes-skipped"><summary>${escapeHtml(t('Skipped ({count})', {count: formatNumber(skipped.length)}))}</summary>`
                + `<ul class="bulk-outcomes-list">${skipped.map(g => this._item(g)).join('')}</ul></details>`;
        }
        return `<div class="bulk-outcomes">${html}</div>`;
    },

    async _games() {
        const reply = await API.get('/api/bulk-scrape-job/outcomes');
        return (reply && reply.games) || [];
    },

    /** Fill an element (the Bulk Scraping window's) with the list. */
    async fillInto(el) {
        if (!el) return;
        try {
            const games = await this._games();
            el.innerHTML = games.length ? this.render(games) : '';
            el.hidden = !games.length;
        } catch (e) {
            el.hidden = true;
        }
    },

    /** The list in a dialog, from the card. */
    async open() {
        try {
            const games = await this._games();
            showModal(t('Games the bulk scrape failed or skipped'), this.render(games),
                      null, false, null, {allowHtml: true});
        } catch (e) {
            showNotification(t('Could not load the list of games.'), 'error');
        }
    },

    _dismissKey(summary) {
        return `bulk_outcomes_closed_${summary.job_id}`;
    },

    close() {
        const card = document.getElementById(this.CARD_ID);
        if (card && card.dataset.key) localStorage.setItem(card.dataset.key, '1');
        if (card) card.remove();
    },

    /** Show, update or remove the card from a bulk scrape status reply. */
    showFor(status) {
        const old = document.getElementById(this.CARD_ID);
        const summary = status && status.outcomes;
        const count = summary ? summary.failed + summary.skipped : 0;
        const busy = status && status.running && !status.completed;
        if (busy || !count || localStorage.getItem(this._dismissKey(summary))) {
            if (old) old.remove();
            return;
        }
        UnifiedToastController.createContainer();
        const card = old || document.createElement('div');
        card.id = this.CARD_ID;
        card.className = 'unified-toast bulk-outcomes-card';
        card.dataset.key = this._dismissKey(summary);
        card.style.setProperty('--toast-color', summary.failed ? 'var(--neon-orange)' : 'var(--neon-green)');
        const text = t('Bulk scrape finished: {failed} failed, {skipped} skipped',
                       {failed: formatNumber(summary.failed), skipped: formatNumber(summary.skipped)});
        card.innerHTML = `
            <div class="toast-content">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon('complete')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${escapeHtml(text)}</div>
                        <button type="button" class="btn btn-xs btn-secondary" data-on-click="BulkScrapeOutcomes.open">${escapeHtml(t('Show the games'))}</button>
                    </div>
                </div>
                <div class="toast-controls">
                    <button type="button" class="toast-btn cancel" data-on-click="BulkScrapeOutcomes.close" title="${escapeHtml(t('Close'))}" aria-label="${escapeHtml(t('Close'))}">✕</button>
                </div>
            </div>`;
        if (!old) UnifiedToastController.container.appendChild(card);
    },

    /** Ask the server once; used on page load and when a run ends. */
    async refresh() {
        if (document.body.dataset.signedIn !== 'true') return;  // the sign-in page
        try {
            this.showFor(await API.get('/api/bulk-scrape-job/status'));
        } catch (e) {
            // Not signed in, or the server is restarting: no card.
        }
    },
};

window.BulkScrapeOutcomes = BulkScrapeOutcomes;
document.addEventListener('DOMContentLoaded', () => BulkScrapeOutcomes.refresh());
