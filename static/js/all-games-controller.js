/**
 * RetroDB All-Games Controller
 * API-driven game list with infinite scroll.
 * Used by both /games (all games) and /system/<id> (per-system) pages.
 * Version: 2.2.0
 */

const AllGamesController = (function() {
    'use strict';

    // =========================================================================
    // STATE
    // =========================================================================
    let currentPage = 0;
    let totalPages = 1;
    let totalFiltered = 0;
    let loadedCount = 0;
    let isLoading = false;
    let hasMore = true;
    const PER_PAGE = 100;

    // Current filters (sent as query params)
    let filters = {};

    // Exclude filters (sent as not_* query params)
    let excludeFilters = {};

    // Filter modal mode: false = IS (include), true = IS NOT (exclude)
    let filterModalExcludeMode = false;

    // Current filter type open in the modal (for mode toggle callback)
    let currentFilterType = null;

    // Configuration (set via init)
    let cfg = {
        systemId: null,         // Lock to a specific system (null = all systems)
        showSystemBadge: true,  // Show system badge on cards
        pageKey: 'retrodb_all_games_api',  // sessionStorage key for state persistence
    };

    // Letter navigation state (scroll-to, not a filter)
    let activeLetterJump = null;

    // Bulk selection
    let bulkMode = false;
    const selectedGames = new Set();

    // Infinite scroll observer
    let scrollObserver = null;

    // Debounce timer for search
    let searchTimeout = null;

    // AbortController for cancelling stale fetch requests
    let currentFetchController = null;

    // =========================================================================
    // RATING SYSTEM HELPERS
    // =========================================================================

    // Map system key → db_column (API property name)
    const _RATING_COLUMNS = {
        esrb: 'esrb_rating', pegi: 'pegi_rating', cero: 'cero_rating',
        usk: 'usk_rating', acb: 'acb_rating', fpb: 'fpb_rating',
        grac: 'grac_rating', classind: 'classind_rating'
    };

    /**
     * Get the preferred rating for a game, cross-mapping if needed.
     * @param {Object} game - Game object from API
     * @returns {Object|null} {system, value, image, crossmapped} or null
     */
    function _getPreferredRating(game) {
        const pref = window.PREFERRED_RATING_SYSTEM || 'esrb';
        const imgMap = window.RATING_IMAGE_MAP || {};
        const keys = window.RATING_SYSTEM_KEYS || Object.keys(_RATING_COLUMNS);

        // Direct value in preferred system
        const prefCol = _RATING_COLUMNS[pref];
        if (prefCol && game[prefCol]) {
            return {
                system: pref,
                value: game[prefCol],
                image: imgMap[`${pref}:${game[prefCol]}`] || '',
                crossmapped: false
            };
        }

        // Cross-map from any available rating
        const r2t = window.RATING_TO_TIER || {};
        const t2r = window.TIER_TO_RATING || {};
        for (const sysKey of keys) {
            if (sysKey === pref) continue;
            const col = _RATING_COLUMNS[sysKey];
            const val = game[col];
            if (val) {
                const tier = r2t[`${sysKey}:${val}`];
                if (tier !== undefined) {
                    const mapped = t2r[`${pref}:${tier}`];
                    if (mapped) {
                        return {
                            system: pref,
                            value: mapped,
                            image: imgMap[`${pref}:${mapped}`] || '',
                            crossmapped: true
                        };
                    }
                }
            }
        }
        return null;
    }

    /**
     * Get all direct (non-cross-mapped) ratings for a game (admin view).
     * @param {Object} game - Game object from API
     * @returns {Array} Array of {system, value, image} objects
     */
    function _getAllRatings(game) {
        const imgMap = window.RATING_IMAGE_MAP || {};
        const keys = window.RATING_SYSTEM_KEYS || Object.keys(_RATING_COLUMNS);
        const names = window.RATING_SYSTEM_NAMES || {};
        const ratings = [];
        for (const sysKey of keys) {
            const col = _RATING_COLUMNS[sysKey];
            const val = game[col];
            if (val) {
                ratings.push({
                    system: sysKey,
                    value: val,
                    image: imgMap[`${sysKey}:${val}`] || '',
                    name: names[sysKey] || sysKey.toUpperCase()
                });
            }
        }
        return ratings;
    }

    // =========================================================================
    // LETTER NAVIGATION HELPER
    // =========================================================================

    /** Clear any active letter jump (called when other filters change) */
    function clearLetterJump() {
        if (activeLetterJump) {
            activeLetterJump = null;
            delete filters.letter;
            document.querySelectorAll('.alphabet-btn.active').forEach(b => b.classList.remove('active'));
        }
    }

    // =========================================================================
    // INITIALIZATION
    // =========================================================================

    function init(config) {
        config = config || {};
        cfg.systemId = config.systemId || null;
        cfg.showSystemBadge = config.showSystemBadge !== undefined ? config.showSystemBadge : true;
        cfg.pageKey = config.pageKey || 'retrodb_all_games_api';

        // When locked to a system, always include system filter
        if (cfg.systemId) {
            filters.system = cfg.systemId;
        }

        // Init shared controllers from game-list.js
        FanartController.init();
        BackToTopController.init();

        // Delegated event listeners on game grid (replaces per-card inline handlers)
        const grid = document.getElementById('gamesGrid');
        if (grid) {
            // Click → open game detail modal
            grid.addEventListener('click', (e) => {
                if (e.target.closest('.bulk-select-checkbox') || e.target.closest('.meta-clickable')) return;
                const card = e.target.closest('.game-card-new');
                if (card) openGameDetailModal(parseInt(card.dataset.gameId));
            });
            // Mouseover → show fanart (bubbles, so no capture needed)
            grid.addEventListener('mouseover', (e) => {
                const wrapper = e.target.closest && e.target.closest('.game-card-wrapper');
                if (!wrapper) return;
                const fanart = wrapper.dataset.fanart;
                if (fanart && window.showFanart) window.showFanart(fanart);
            });
            // Mouseout → hide fanart only when truly leaving the card
            grid.addEventListener('mouseout', (e) => {
                const wrapper = e.target.closest && e.target.closest('.game-card-wrapper');
                if (!wrapper) return;
                const related = e.relatedTarget;
                if (!related || !wrapper.contains(related)) {
                    if (window.hideFanart) window.hideFanart();
                }
            });
        }

        // Setup search
        const searchInput = document.getElementById('gameSearch');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    clearLetterJump();
                    const val = searchInput.value.trim();
                    if (val) filters.search = val;
                    else delete filters.search;
                    resetAndFetch();
                }, 300);
            });
        }

        // System dropdown (only present on all-games page)
        const sysFilter = document.getElementById('systemFilter');
        if (sysFilter) {
            sysFilter.addEventListener('change', () => {
                clearLetterJump();
                if (sysFilter.value) filters.system = sysFilter.value;
                else delete filters.system;
                resetAndFetch();
            });
        }

        // System type dropdown (only present on all-games page)
        const typeFilter = document.getElementById('systemTypeFilter');
        if (typeFilter) {
            typeFilter.addEventListener('change', () => {
                clearLetterJump();
                if (typeFilter.value) filters.system_type = typeFilter.value;
                else delete filters.system_type;
                resetAndFetch();
            });
        }

        // Alphabet nav
        setupAlphabetNav();

        // Setup infinite scroll
        setupInfiniteScroll();

        // Restore state if available
        restoreState();

        // Load first page
        fetchGames(1, false);
    }

    // =========================================================================
    // DATA FETCHING
    // =========================================================================

    function buildQueryString(page) {
        const params = new URLSearchParams();
        params.set('page', page);
        params.set('per_page', PER_PAGE);
        for (const [k, v] of Object.entries(filters)) {
            if (v !== undefined && v !== null && v !== '') {
                params.set(k, v);
            }
        }
        for (const [k, v] of Object.entries(excludeFilters)) {
            if (v !== undefined && v !== null && v !== '') {
                params.set('not_' + k, v);
            }
        }
        return params.toString();
    }

    async function fetchGames(page, append) {
        // For infinite scroll (append), skip if already loading to prevent duplicate pages
        if (append && isLoading) return;

        // For fresh fetches (non-append), cancel any in-flight request so the
        // new filter/search always takes effect (prevents "stuck" results)
        if (!append && currentFetchController) {
            currentFetchController.abort();
        }

        isLoading = true;
        const controller = new AbortController();
        currentFetchController = controller;

        const loadingEl = document.getElementById('gamesLoading');
        if (!append && loadingEl) loadingEl.style.display = '';

        try {
            const qs = buildQueryString(page);
            const data = await API.get(`/api/games?${qs}`, { signal: controller.signal });

            if (data.error) throw new Error(data.error);

            currentPage = data.page;
            totalPages = data.total_pages;
            totalFiltered = data.total;
            hasMore = data.has_more;

            renderGames(data.games, append);
            loadedCount = append
                ? loadedCount + data.games.length
                : data.games.length;

            updateCounts();

            // Re-observe the trigger for next page
            observeTrigger();
        } catch (err) {
            if (err.name === 'AbortError') return; // Cancelled by newer request
            console.error('Failed to fetch games:', err);
        } finally {
            // Only clear loading state if this is still the active request
            if (currentFetchController === controller) {
                isLoading = false;
                currentFetchController = null;
                if (loadingEl) loadingEl.style.display = 'none';
            }
        }
    }

    function resetAndFetch() {
        currentPage = 0;
        loadedCount = 0;
        hasMore = true;
        const grid = document.getElementById('gamesGrid');
        if (grid) grid.innerHTML = '';
        fetchGames(1, false);
        saveState();
        updateFilterDisplay();
    }

    // =========================================================================
    // RENDERING
    // =========================================================================

    function renderGames(games, append) {
        const grid = document.getElementById('gamesGrid');
        if (!grid) return;

        if (!append) grid.innerHTML = '';

        const fragment = document.createDocumentFragment();
        const newWrappers = [];
        games.forEach(game => {
            const wrapper = renderGameCard(game);
            newWrappers.push(wrapper);
            fragment.appendChild(wrapper);
        });
        grid.appendChild(fragment);

        // Masonry: measure card heights and assign explicit grid positions
        requestAnimationFrame(() => {
            layoutMasonryItems(newWrappers, append);
            // Re-layout after badge images load (they affect card height via wrapping)
            scheduleImageRelayout(newWrappers);
        });
    }

    // Masonry state
    let masonryColumnEnds = [];
    let masonryItemCount = 0;
    let _imageRelayoutTimer = null;
    let _filterBarResizeObserver = null;

    /** Watch for unloaded images in new cards and re-layout masonry when they load */
    function scheduleImageRelayout(wrappers) {
        let pending = 0;
        const onLoad = () => {
            pending--;
            if (pending <= 0) {
                clearTimeout(_imageRelayoutTimer);
                _imageRelayoutTimer = setTimeout(() => window.relayoutMasonry(), 50);
            }
        };
        wrappers.forEach(w => {
            w.querySelectorAll('img').forEach(img => {
                if (!img.complete) {
                    pending++;
                    img.addEventListener('load', onLoad, { once: true });
                    img.addEventListener('error', onLoad, { once: true });
                }
            });
        });
    }

    function layoutMasonryItems(items, append) {
        const grid = document.getElementById('gamesGrid');
        if (!grid || items.length === 0) return;

        const gap = 16;
        const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').length;

        // Reset on fresh render or column count change
        if (!append || masonryColumnEnds.length !== columns) {
            masonryColumnEnds = new Array(columns).fill(1);
            masonryItemCount = 0;

            // Column count changed during append — re-layout all items
            if (append) {
                items = Array.from(grid.querySelectorAll('.game-card-wrapper'));
                masonryItemCount = 0;
            }
        }

        items.forEach(wrapper => {
            const card = wrapper.querySelector('.game-card-new');
            if (!card) return;

            const h = card.getBoundingClientRect().height;
            const span = h > 0 ? Math.ceil(h) + gap : 296;

            const col = masonryItemCount % columns;
            wrapper.style.gridColumn = String(col + 1);
            wrapper.style.gridRowStart = String(masonryColumnEnds[col]);
            wrapper.style.gridRowEnd = String(masonryColumnEnds[col] + span);

            masonryColumnEnds[col] += span;
            masonryItemCount++;
        });
    }

    // Expose a full re-layout function for external use (e.g. after card edits)
    window.relayoutMasonry = function() {
        const grid = document.getElementById('gamesGrid');
        if (!grid) return;
        const allWrappers = Array.from(grid.querySelectorAll('.game-card-wrapper'));
        masonryColumnEnds = [];
        masonryItemCount = 0;
        layoutMasonryItems(allWrappers, false);
    };

    function renderGameCard(game) {
        const prefer3d = window.PREFERRED_BOXART === '3d';
        const use3d = prefer3d && game.boxart_3d;
        const boxartToShow = use3d ? game.boxart_3d : game.boxart;
        const boxartFolder = use3d ? 'boxart_3d' : 'boxart';
        const fallbackBoxart = (use3d && game.boxart) ? game.boxart : '';

        const importSource = game.import_source;
        const isClz = importSource === 'clz';
        const isBonus = game.is_bonus_disc;

        const wrapper = document.createElement('div');
        const wrapperClasses = ['game-card-wrapper'];
        if (importSource) wrapperClasses.push(`${importSource}-import`);
        if (isBonus) wrapperClasses.push('bonus-disc');
        wrapper.className = wrapperClasses.join(' ');
        wrapper.dataset.gameId = game.id;
        wrapper.dataset.systemId = game.system_id;
        wrapper.dataset.systemFolder = game.system_folder || '';
        wrapper.dataset.systemType = game.system_type || '';
        wrapper.dataset.scraped = game.scraped ? '1' : '0';
        wrapper.dataset.clz = isClz ? '1' : '0';
        wrapper.dataset.bonusDisc = isBonus ? '1' : '0';
        wrapper.dataset.title = game.title || '';
        wrapper.dataset.sortTitle = game.sort_title || game.title || '';
        wrapper.dataset.fanart = game.fanart || '';
        wrapper.dataset.ra = game.has_retroachievements ? 'true' : 'false';

        // Boxart HTML
        let boxartHtml;
        if (boxartToShow) {
            const fallbackAttr = fallbackBoxart
                ? ` onerror="this.onerror=null; this.classList.remove('boxart-3d'); this.removeAttribute('srcset'); this.removeAttribute('sizes'); this.src='/static/images/boxart/${esc(fallbackBoxart)}';"`
                : ` onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"`;
            // Pass FU.2 — pre-computed srcset (boxart 160 w / 320 w variants
            // plus the original) shipped from build_game_card(). `sizes`
            // mirrors the card-boxart-section CSS: 100 px on the ≤768 px
            // breakpoint, 135 px above it. Falls through to the legacy
            // single-source img when the field is absent (e.g. card data
            // produced before this pass).
            const srcset = use3d ? game.boxart_3d_srcset : game.boxart_srcset;
            const responsiveAttr = srcset
                ? ` srcset="${esc(srcset)}" sizes="(max-width: 768px) 100px, 135px"`
                : '';
            boxartHtml = `
                <img src="/static/images/${boxartFolder}/${esc(boxartToShow)}"${responsiveAttr}
                     alt="${esc(game.title)}"
                     class="game-boxart-img${use3d ? ' boxart-3d' : ''}"
                     loading="lazy"
                     decoding="async"${fallbackAttr}>
                <div class="game-boxart-placeholder" style="display: none;">
                    <span class="placeholder-icon">&#127918;</span>
                </div>`;
        } else {
            boxartHtml = `<div class="game-boxart-placeholder"><span class="placeholder-icon">&#127918;</span></div>`;
        }

        // Title badges
        let badges = '';
        if (isBonus) badges += '<span class="bonus-badge" title="Bonus/Extra Disc">&#127873;</span>';
        if (game.bonus_count > 0) badges += `<span class="has-bonus-badge" title="Has ${game.bonus_count} bonus disc${game.bonus_count > 1 ? 's' : ''}">&#127873;+</span>`;
        if (isClz) badges += '<img class="import-badge clz-badge" src="/static/images/trophies/clz-games-web.svg" title="CLZ Import (No ROM file)" alt="CLZ">';
        if (importSource === 'steam') badges += '<img class="import-badge steam-badge" src="/static/images/trophies/steam.png" title="Steam Import" alt="Steam">';
        if (importSource === 'xbox') badges += '<img class="import-badge xbox-badge" src="/static/images/trophies/xbox.png" title="Xbox Import" alt="Xbox">';
        if (importSource === 'psn') badges += '<img class="import-badge psn-badge" src="/static/images/trophies/psn.png" title="PSN Import" alt="PlayStation">';
        if (game.has_retroachievements) badges += '<img class="import-badge ra-badge" src="/static/images/trophies/ra.webp" title="Has RetroAchievements" alt="RetroAchievements">';

        // Meta grid
        let metaHtml = '';
        if (game.genre) {
            const firstGenre = game.genre.split(',')[0].trim();
            metaHtml += `<div class="meta-item"><span class="meta-label">Genre</span><span class="meta-value meta-clickable" onclick="event.preventDefault();event.stopPropagation();if(event.shiftKey)AllGamesController.applyExcludeFilterDirect('genre','${escAttr(firstGenre)}');else AllGamesController.applyFilterDirect('genre','${escAttr(firstGenre)}')" title="Click to filter, Shift+click to exclude">${esc(firstGenre)}</span></div>`;
        }
        if (game.franchise) {
            metaHtml += `<div class="meta-item"><span class="meta-label">Series</span><span class="meta-value meta-clickable" onclick="event.preventDefault();event.stopPropagation();if(event.shiftKey)AllGamesController.applyExcludeFilterDirect('franchise','${escAttr(game.franchise)}');else AllGamesController.applyFilterDirect('franchise','${escAttr(game.franchise)}')" title="Click to filter, Shift+click to exclude">${esc(game.franchise.substring(0, 20))}${game.franchise.length > 20 ? '...' : ''}</span></div>`;
        }
        if (game.developer) {
            const firstDev = game.developer.split(',')[0].trim();
            metaHtml += `<div class="meta-item"><span class="meta-label">Developer</span><span class="meta-value meta-clickable" onclick="event.preventDefault();event.stopPropagation();if(event.shiftKey)AllGamesController.applyExcludeFilterDirect('developer','${escAttr(firstDev)}');else AllGamesController.applyFilterDirect('developer','${escAttr(firstDev)}')" title="Click to filter, Shift+click to exclude">${esc(firstDev.substring(0, 20))}${firstDev.length > 20 ? '...' : ''}</span></div>`;
        }
        if (game.publisher) {
            const firstPub = game.publisher.split(',')[0].trim();
            metaHtml += `<div class="meta-item"><span class="meta-label">Publisher</span><span class="meta-value meta-clickable" onclick="event.preventDefault();event.stopPropagation();if(event.shiftKey)AllGamesController.applyExcludeFilterDirect('publisher','${escAttr(firstPub)}');else AllGamesController.applyFilterDirect('publisher','${escAttr(firstPub)}')" title="Click to filter, Shift+click to exclude">${esc(firstPub.substring(0, 20))}${firstPub.length > 20 ? '...' : ''}</span></div>`;
        }
        if (game.release_date) {
            metaHtml += `<div class="meta-item"><span class="meta-label">Year</span><span class="meta-value">${esc(game.release_date.substring(0, 4))}</span></div>`;
        }

        // Rating badges — age ratings first so they group on their own row
        let ratingBadges = '';
        // Age rating badges — admin sees all, users see preferred only
        if (window.IS_ADMIN) {
            const allRatings = _getAllRatings(game);
            for (const r of allRatings) {
                const tooltip = `${r.name}: ${r.value}`;
                if (r.image) {
                    ratingBadges += `<span class="game-badge age-rating-badge" title="${esc(tooltip)}"><img src="/static/images/ratings/${r.image}" alt="${esc(r.value)}" class="age-rating-img"></span>`;
                } else {
                    ratingBadges += `<span class="game-badge age-rating-badge" title="${esc(tooltip)}">${esc(r.name.split(' (')[0])} ${esc(r.value)}</span>`;
                }
            }
        } else {
            const ageRating = _getPreferredRating(game);
            if (ageRating) {
                const sysName = (window.RATING_SYSTEM_NAMES || {})[ageRating.system] || ageRating.system.toUpperCase();
                const tooltip = ageRating.crossmapped ? `${sysName}: ${ageRating.value} (cross-mapped)` : `${sysName}: ${ageRating.value}`;
                if (ageRating.image) {
                    ratingBadges += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${esc(tooltip)}"><img src="/static/images/ratings/${ageRating.image}" alt="${esc(ageRating.value)}" class="age-rating-img"></span>`;
                } else {
                    ratingBadges += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${esc(tooltip)}">${esc(sysName.split(' (')[0])} ${esc(ageRating.value)}</span>`;
                }
            }
        }
        if (game.completion_status && game.completion_status !== 'not_started') {
            const csClass = game.completion_status === '100_percent' ? 'hundred-percent' : game.completion_status.replace(/_/g, '-');
            const csLabels = { in_progress: '&#127918; In Progress', played: '&#128377;&#65039; Played', completed: '&#9989; Completed', '100_percent': '&#127942; 100%' };
            ratingBadges += `<span class="game-badge completion ${csClass}" title="Completion Status">${csLabels[game.completion_status] || ''}</span>`;
        }
        if (game.critic_score) {
            const cs = Math.round(game.critic_score);
            const csClass = cs >= 75 ? 'score-good' : cs >= 50 ? 'score-mixed' : 'score-bad';
            ratingBadges += `<span class="game-badge score-badge critic-score ${csClass}" title="Critic Score (${game.critic_score_count || '?'} reviews)">&#11088; ${cs}</span>`;
        }
        if (game.user_score) {
            const us = Math.round(game.user_score);
            const usClass = us >= 75 ? 'score-good' : us >= 50 ? 'score-mixed' : 'score-bad';
            ratingBadges += `<span class="game-badge score-badge user-score ${usClass}" title="User Score (${game.user_score_count || '?'} ratings)">&#128100; ${us}</span>`;
        }
        if (game.achievement_total > 0 && game.achievement_earned != null) {
            const earned = game.achievement_earned;
            const pct = Math.round((earned / game.achievement_total) * 100);
            const pctClass = pct >= 100 ? 'ach-complete' : pct >= 50 ? 'ach-good' : 'ach-low';
            const srcImages = { ra: '/static/images/trophies/ra.webp', steam: '/static/images/trophies/steam.png', xbox: '/static/images/trophies/xbox.png' };
            const srcLabels = { ra: 'RetroAchievements', steam: 'Steam', xbox: 'Xbox' };
            const src = game.achievement_source || 'ra';
            const iconImg = `<img class="ach-icon" src="${srcImages[src] || srcImages.ra}" alt="${srcLabels[src] || 'Achievements'}">`;
            const label = srcLabels[src] || 'Achievements';
            ratingBadges += `<span class="game-badge achievement-progress ${src} ${pctClass}" title="${label}: ${earned}/${game.achievement_total} (${pct}%)">${iconImg} ${earned}/${game.achievement_total}<span class="ach-bar"><span class="ach-fill" style="width:${pct}%"></span></span></span>`;
        }
        if (game.psn_total > 0 && game.psn_earned != null) {
            const psnPct = game.psn_total > 0 ? Math.round((game.psn_earned / game.psn_total) * 100) : 0;
            const psnClass = psnPct >= 100 ? 'ach-complete' : psnPct >= 50 ? 'ach-good' : 'ach-low';
            ratingBadges += `<span class="game-badge achievement-progress psn ${psnClass}" title="PSN Trophies: ${game.psn_earned}/${game.psn_total} (${psnPct}%)"><img class="ach-icon" src="/static/images/trophies/platinum.png" alt="PSN"> ${game.psn_earned}/${game.psn_total}<span class="ach-bar"><span class="ach-fill" style="width:${psnPct}%"></span></span></span>`;
        }
        if (game.rpcs3_total > 0 && game.rpcs3_earned != null) {
            const rpcs3Pct = Math.round((game.rpcs3_earned / game.rpcs3_total) * 100);
            const rpcs3Class = rpcs3Pct >= 100 ? 'ach-complete' : rpcs3Pct >= 50 ? 'ach-good' : 'ach-low';
            ratingBadges += `<span class="game-badge achievement-progress rpcs3 ${rpcs3Class}" title="RPCS3 Trophies: ${game.rpcs3_earned}/${game.rpcs3_total} (${rpcs3Pct}%)"><img class="ach-icon" src="/static/images/trophies/rpcs3.png" alt="RPCS3"> ${game.rpcs3_earned}/${game.rpcs3_total}<span class="ach-bar"><span class="ach-fill" style="width:${rpcs3Pct}%"></span></span></span>`;
        }

        // Bulk checkbox
        const checkboxDisplay = bulkMode ? 'block' : 'none';
        const isSelected = selectedGames.has(game.id);

        // Card info section — system badge row vs title row layout
        let infoSectionHtml;
        if (cfg.showSystemBadge) {
            // All-games layout: system badge row with badges, then title
            infoSectionHtml = `
                    <div class="system-badge-row">
                        <span class="system-badge ${esc((game.system_folder || '').toLowerCase().replace(/ /g, '-'))}">${esc(game.system_name)}</span>
                        <div class="title-badges">${badges}</div>
                    </div>
                    <h3 class="game-card-title">${esc(game.title)}</h3>`;
        } else {
            // System-games layout: title row with inline badges (no system badge)
            infoSectionHtml = `
                    <div class="title-row">
                        <h3 class="game-card-title">${esc(game.title)}</h3>
                        <div class="title-badges">${badges}</div>
                    </div>`;
        }

        wrapper.innerHTML = `
            <div class="bulk-select-checkbox" style="display: ${checkboxDisplay};">
                <input type="checkbox" class="game-checkbox" data-game-id="${game.id}" ${isSelected ? 'checked' : ''}
                       onclick="event.stopPropagation(); AllGamesController.toggleGameSelection(${game.id})">
            </div>
            <div class="game-card-new glass-card"
                 data-game-id="${game.id}"
                 style="cursor: pointer;">
                <div class="card-glow"></div>
                <div class="card-boxart-section">
                    <div class="game-card-image">${boxartHtml}</div>
                </div>
                <div class="card-info-section">
                    ${infoSectionHtml}
                    <div class="meta-grid">${metaHtml}</div>
                    <div class="rating-badges">${ratingBadges}</div>
                </div>
                <div class="scan-lines"></div>
            </div>`;

        if (isSelected) wrapper.classList.add('selected');

        return wrapper;
    }

    // =========================================================================
    // INFINITE SCROLL
    // =========================================================================

    function setupInfiniteScroll() {
        const trigger = document.getElementById('infiniteScrollTrigger');
        if (!trigger || !('IntersectionObserver' in window)) return;

        scrollObserver = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting && hasMore && !isLoading) {
                fetchGames(currentPage + 1, true);
            }
        }, { rootMargin: '600px' });
    }

    function observeTrigger() {
        const trigger = document.getElementById('infiniteScrollTrigger');
        if (!scrollObserver || !trigger) return;
        scrollObserver.disconnect();
        if (hasMore) {
            scrollObserver.observe(trigger);
        }
    }

    // =========================================================================
    // COUNTS & DISPLAY
    // =========================================================================

    function updateCounts() {
        const visibleEl = document.getElementById('visibleCount');
        const totalEl = document.getElementById('totalFilteredCount');
        if (visibleEl) visibleEl.textContent = formatNumber(loadedCount);
        if (totalEl) totalEl.textContent = formatNumber(totalFiltered);
    }

    // =========================================================================
    // FILTER HANDLERS
    // =========================================================================

    function applyFilterDirect(type, value) {
        clearLetterJump();
        filters[type] = value;
        resetAndFetch();
    }

    function openFilterModal(filterType) {
        const modal = document.getElementById('filterModal');
        const title = document.getElementById('filterModalTitle');
        const optionsEl = document.getElementById('filterOptions');
        if (!modal || !optionsEl) return;

        // Reset mode toggle state
        filterModalExcludeMode = false;
        currentFilterType = filterType;
        modal.classList.remove('exclude-mode');

        const titles = {
            genre: 'Select Genre', franchise: 'Select Series',
            publisher: 'Select Publisher', developer: 'Select Developer',
            modes: 'Select Play Mode', perspective: 'Select Perspective',
            dimension: 'Select Dimension',
            rating: 'Select Rating', source: 'Select Source'
        };
        if (title) title.textContent = titles[filterType] || 'Select Filter';

        // Show/hide mode toggle (not for source)
        const toggleEl = document.getElementById('filterModeToggle');
        if (toggleEl) {
            toggleEl.style.display = (filterType === 'source') ? 'none' : 'flex';
            // Reset toggle button states
            toggleEl.querySelectorAll('.filter-mode-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === 'include');
            });
        }

        // Special: source (include only, no exclude support)
        if (filterType === 'source') {
            optionsEl.innerHTML = `
                <div class="filter-option" onclick="AllGamesController.applyFilter('source','rom')">
                    <span class="filter-option-name">ROM Files</span>
                </div>
                <div class="filter-option" onclick="AllGamesController.applyFilter('source','clz')">
                    <span class="filter-option-name">CLZ Imports</span>
                </div>
                <div class="filter-option" onclick="AllGamesController.applyFilter('source','steam')">
                    <span class="filter-option-name">Steam Imports</span>
                </div>
                <div class="filter-option" onclick="AllGamesController.applyFilter('source','xbox')">
                    <span class="filter-option-name">Xbox Imports</span>
                </div>
                <div class="filter-option" onclick="AllGamesController.applyFilter('source','psn')">
                    <span class="filter-option-name">PSN Imports</span>
                </div>`;
            modal.classList.add('active');
            _activateFilterModalTrap(modal);
            return;
        }

        // Special: rating — show all rating systems with subheadings
        if (filterType === 'rating') {
            const opts = window.FILTER_OPTIONS || {};
            const sysNames = window.RATING_SYSTEM_NAMES || {};
            const keys = window.RATING_SYSTEM_KEYS || Object.keys(_RATING_COLUMNS);
            let html = '';
            for (const sysKey of keys) {
                const items = opts[sysKey] || [];
                if (items.length === 0) continue;
                const label = sysNames[sysKey] || sysKey.toUpperCase();
                html += `<div class="filter-subheading">${esc(label)}</div>`;
                items.forEach(([val, cnt]) => {
                    html += `<div class="filter-option" onclick="AllGamesController.handleFilterOptionClick('rating','${escAttr(val)}')">${esc(val)} <span class="filter-option-count">(${formatNumber(cnt)})</span></div>`;
                });
            }
            optionsEl.innerHTML = html || '<div class="filter-empty">No ratings available</div>';
            modal.classList.add('active');
            _activateFilterModalTrap(modal);
            return;
        }

        // Generic: use FILTER_OPTIONS from server
        const opts = (window.FILTER_OPTIONS || {})[filterType] || [];
        if (opts.length === 0) {
            optionsEl.innerHTML = '<div class="filter-empty">No options available</div>';
        } else {
            optionsEl.innerHTML = opts.map(([val, cnt]) =>
                `<div class="filter-option" onclick="AllGamesController.handleFilterOptionClick('${filterType}','${escAttr(val)}')">
                    <span class="filter-option-name">${esc(val)}</span>
                    <span class="filter-option-count">(${formatNumber(cnt)})</span>
                </div>`
            ).join('');
        }
        modal.classList.add('active');
        _activateFilterModalTrap(modal);
    }

    // Pass 29.3: shared helper so every openFilterModal branch activates
    // the focus trap once, idempotently. Deactivated in closeFilterModal.
    let _filterModalTrapActive = false;
    function _activateFilterModalTrap(modal) {
        if (!window.ModalFocusTrap || _filterModalTrapActive) return;
        ModalFocusTrap.activate(modal, document.activeElement, {
            onEscape: () => closeFilterModal(),
        });
        _filterModalTrapActive = true;
    }

    function closeFilterModal() {
        const modal = document.getElementById('filterModal');
        if (modal) modal.classList.remove('active');
        // Pass 29.3: Deactivate the trap we activated in openFilterModal.
        // Safe to call even if activation never happened — deactivate()
        // pops the top of the stack and no-ops on empty.
        if (window.ModalFocusTrap && _filterModalTrapActive) {
            ModalFocusTrap.deactivate();
            _filterModalTrapActive = false;
        }
    }

    function applyFilter(type, value) {
        clearLetterJump();
        filters[type] = value;
        closeFilterModal();
        resetAndFetch();
    }

    function removeFilter(type) {
        // Don't allow removing the locked system filter
        if (type === 'system' && cfg.systemId) return;

        clearLetterJump();
        delete filters[type];
        // Also reset corresponding UI control
        if (type === 'system') {
            const el = document.getElementById('systemFilter');
            if (el) el.value = '';
        }
        if (type === 'system_type') {
            const el = document.getElementById('systemTypeFilter');
            if (el) el.value = '';
        }
        if (type === 'search') {
            const el = document.getElementById('gameSearch');
            if (el) el.value = '';
        }
        resetAndFetch();
    }

    // =========================================================================
    // EXCLUDE FILTER HANDLERS
    // =========================================================================

    /** Route modal option clicks based on current mode (IS vs IS NOT) */
    function handleFilterOptionClick(type, value) {
        if (filterModalExcludeMode) {
            applyExcludeFilter(type, value);
        } else {
            applyFilter(type, value);
        }
    }

    /** Toggle modal between IS (include) and IS NOT (exclude) mode */
    function setFilterMode(excludeMode) {
        filterModalExcludeMode = excludeMode;
        const modal = document.getElementById('filterModal');
        const toggleEl = document.getElementById('filterModeToggle');
        if (modal) modal.classList.toggle('exclude-mode', excludeMode);
        if (toggleEl) {
            toggleEl.querySelectorAll('.filter-mode-btn').forEach(btn => {
                const isExcludeBtn = btn.dataset.mode === 'exclude';
                btn.classList.toggle('active', excludeMode ? isExcludeBtn : !isExcludeBtn);
            });
        }
    }

    function applyExcludeFilter(type, value) {
        clearLetterJump();
        excludeFilters[type] = value;
        closeFilterModal();
        resetAndFetch();
    }

    function applyExcludeFilterDirect(type, value) {
        clearLetterJump();
        excludeFilters[type] = value;
        resetAndFetch();
    }

    function removeExcludeFilter(type) {
        clearLetterJump();
        delete excludeFilters[type];
        resetAndFetch();
    }

    function clearFilters() {
        // Clear letter navigation
        activeLetterJump = null;

        // Preserve locked system filter
        const lockedSystem = cfg.systemId ? cfg.systemId : null;
        filters = {};
        excludeFilters = {};
        if (lockedSystem) filters.system = lockedSystem;

        const searchInput = document.getElementById('gameSearch');
        if (searchInput) searchInput.value = '';
        const sysFilter = document.getElementById('systemFilter');
        if (sysFilter) sysFilter.value = '';
        const typeFilter = document.getElementById('systemTypeFilter');
        if (typeFilter) typeFilter.value = '';

        // Reset RA and bonus button states
        document.querySelector('.ra-filter-btn')?.classList.remove('active');
        document.querySelector('.bonus-filter-btn')?.classList.remove('active');
        const bonusText = document.getElementById('bonusFilterText');
        if (bonusText) bonusText.textContent = 'Show Bonus';

        // Remove active alphabet button
        document.querySelectorAll('.alphabet-btn.active').forEach(b => b.classList.remove('active'));

        resetAndFetch();
    }

    function toggleRAFilter() {
        clearLetterJump();
        const btn = document.querySelector('.ra-filter-btn');
        if (filters.ra_only === '1') {
            delete filters.ra_only;
            btn?.classList.remove('active');
        } else {
            filters.ra_only = '1';
            btn?.classList.add('active');
        }
        resetAndFetch();
    }

    function toggleBonusDiscFilter() {
        clearLetterJump();
        const btn = document.querySelector('.bonus-filter-btn');
        const textEl = document.getElementById('bonusFilterText');
        if (filters.show_bonus === '1') {
            delete filters.show_bonus;
            btn?.classList.remove('active');
            if (textEl) textEl.textContent = 'Show Bonus';
        } else {
            filters.show_bonus = '1';
            btn?.classList.add('active');
            if (textEl) textEl.textContent = 'Hide Bonus';
        }
        resetAndFetch();
    }

    function updateFilterDisplay() {
        const container = document.getElementById('activeFilters');
        const tags = document.getElementById('activeFilterTags');
        const clearBtn = document.getElementById('clearFiltersBtn');

        // Count meaningful filters (exclude show_bonus, ra_only, letter nav, and locked system which have their own buttons/are implicit)
        const hiddenKeys = ['show_bonus', 'ra_only', 'letter'];
        if (cfg.systemId) hiddenKeys.push('system');
        const displayFilters = Object.entries(filters).filter(
            ([k]) => !hiddenKeys.includes(k)
        );
        const displayExcludeFilters = Object.entries(excludeFilters);
        const hasRA = filters.ra_only === '1';
        const hasBonus = filters.show_bonus === '1';
        const hasAny = displayFilters.length > 0 || displayExcludeFilters.length > 0 || hasRA || hasBonus;

        if (clearBtn) clearBtn.style.display = hasAny ? '' : 'none';

        if (container && tags) {
            if (hasAny) {
                container.style.display = 'flex';

                const icons = {
                    system: '&#128421;&#65039;', system_type: '&#128241;', genre: '&#127917;',
                    franchise: '&#128218;', publisher: '&#127970;', developer: '&#128104;&#8205;&#128187;',
                    modes: '&#128101;', perspective: '&#128065;&#65039;', dimension: '&#128208;',
                    rating: '&#11088;', source: '&#128203;',
                    search: '&#128269;', letter: '&#128289;'
                };

                let html = displayFilters.map(([k, v]) =>
                    `<span class="filter-tag">
                        ${icons[k] || ''} ${esc(String(v))}
                        <span class="filter-tag-remove" onclick="AllGamesController.removeFilter('${k}')">&#215;</span>
                    </span>`
                ).join('');

                // Exclude filter tags (red theme with NOT prefix)
                html += displayExcludeFilters.map(([k, v]) =>
                    `<span class="filter-tag filter-tag-exclude">
                        ${icons[k] || ''} NOT ${esc(String(v))}
                        <span class="filter-tag-remove" onclick="AllGamesController.removeExcludeFilter('${k}')">&#215;</span>
                    </span>`
                ).join('');

                if (hasRA) {
                    html += `<span class="filter-tag ra-tag">&#127942; Has Achievements
                        <span class="filter-tag-remove" onclick="AllGamesController.toggleRAFilter()">&#215;</span></span>`;
                }
                if (hasBonus) {
                    html += `<span class="filter-tag" style="background:rgba(168,85,247,0.15);border-color:#a855f7;color:#a855f7;">
                        &#127873; Showing Bonus Discs
                        <span class="filter-tag-remove" onclick="AllGamesController.toggleBonusDiscFilter()">&#215;</span></span>`;
                }

                tags.innerHTML = html;
            } else {
                container.style.display = 'none';
            }
        }
    }

    // =========================================================================
    // ALPHABET NAV
    // =========================================================================

    function setupAlphabetNav() {
        const nav = document.getElementById('alphabetNav');
        if (!nav) return;

        // Only show alphabet nav when there are enough games to warrant it
        const totalGames = window.TOTAL_GAMES || 0;
        if (totalGames < 30) {
            nav.style.display = 'none';
            return;
        }

        // Position below filter bar — use ResizeObserver to track height changes
        // (e.g. bulk mode toggle, filter tags appearing, window resize)
        const filterBar = document.querySelector('.filter-bar-new');
        if (filterBar && nav) {
            const updateNavTop = () => {
                nav.style.top = filterBar.offsetHeight + 'px';
            };
            requestAnimationFrame(() => {
                requestAnimationFrame(updateNavTop);
            });
            if (typeof ResizeObserver !== 'undefined') {
                if (_filterBarResizeObserver) _filterBarResizeObserver.disconnect();
                _filterBarResizeObserver = new ResizeObserver(updateNavTop);
                _filterBarResizeObserver.observe(filterBar);
            }
        }

        // Determine which letters have games (from server-provided data)
        const available = window.AVAILABLE_LETTERS || [];
        // Normalize: non-alpha first chars map to '#'
        const letterSet = new Set();
        available.forEach(l => {
            if (/^[A-Z]$/i.test(l)) letterSet.add(l.toUpperCase());
            else letterSet.add('#');
        });

        nav.querySelectorAll('.alphabet-btn').forEach(btn => {
            const letter = btn.dataset.letter;
            const hasGames = letterSet.size === 0 || letterSet.has(letter);

            if (hasGames) {
                btn.classList.remove('disabled');
            } else {
                btn.classList.add('disabled');
            }

            btn.addEventListener('click', () => {
                if (btn.classList.contains('disabled')) return;

                // Highlight active button
                nav.querySelectorAll('.alphabet-btn.active').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                activeLetterJump = letter;

                // Try to scroll to the first loaded card matching this letter
                const grid = document.getElementById('gamesGrid');
                if (grid) {
                    const cards = grid.querySelectorAll('.game-card-wrapper');
                    let targetCard = null;

                    for (const card of cards) {
                        const sortTitle = (card.dataset.sortTitle || card.dataset.title || '').toUpperCase();
                        if (!sortTitle) continue;
                        const firstChar = sortTitle.charAt(0);
                        const cardLetter = /[A-Z]/.test(firstChar) ? firstChar : '#';
                        if (cardLetter === letter) {
                            targetCard = card;
                            break;
                        }
                    }

                    if (targetCard) {
                        // Found in DOM — smooth scroll to it
                        const offset = (filterBar ? filterBar.offsetHeight : 0) +
                                       (nav ? nav.offsetHeight : 0) + 20;
                        const targetPos = targetCard.getBoundingClientRect().top +
                                         window.pageYOffset - offset;
                        window.scrollTo({ top: targetPos, behavior: 'smooth' });

                        // Add highlight animation
                        targetCard.classList.add('highlight-jump');
                        targetCard.addEventListener('animationend', () => {
                            targetCard.classList.remove('highlight-jump');
                        }, { once: true });
                        return;
                    }
                }

                // Not in DOM yet — use API letter param as a transparent navigation jump
                filters.letter = letter;
                currentPage = 0;
                loadedCount = 0;
                hasMore = true;
                const gridEl = document.getElementById('gamesGrid');
                if (gridEl) gridEl.innerHTML = '';
                fetchGames(1, false);
                saveState();
                updateFilterDisplay();
            });
        });
    }

    // =========================================================================
    // BULK MODE
    // =========================================================================

    function toggleBulkMode() {
        bulkMode = !bulkMode;

        const btn = document.getElementById('bulkModeBtn');
        const text = document.getElementById('bulkModeText');
        const selectAllBtn = document.getElementById('selectAllBtn');
        const selectUnscrapedBtn = document.getElementById('selectUnscrapedBtn');
        const bulkModeSelector = document.getElementById('bulkModeSelector');
        const scrapeBtn = document.getElementById('bulkScrapeBtn');
        const editBtn = document.getElementById('bulkEditBtn');
        const checkboxes = document.querySelectorAll('.bulk-select-checkbox');

        if (bulkMode) {
            btn?.classList.add('active');
            if (text) text.textContent = 'Cancel';
            checkboxes.forEach(cb => cb.style.display = 'block');
            if (selectAllBtn) selectAllBtn.style.display = 'flex';
            if (selectUnscrapedBtn) selectUnscrapedBtn.style.display = 'flex';
            if (bulkModeSelector) bulkModeSelector.style.display = 'flex';
            if (scrapeBtn) scrapeBtn.style.display = 'flex';
            if (editBtn) editBtn.style.display = 'flex';
        } else {
            btn?.classList.remove('active');
            if (text) text.textContent = 'Select';
            checkboxes.forEach(cb => cb.style.display = 'none');
            if (selectAllBtn) selectAllBtn.style.display = 'none';
            if (selectUnscrapedBtn) selectUnscrapedBtn.style.display = 'none';
            if (bulkModeSelector) bulkModeSelector.style.display = 'none';
            if (scrapeBtn) scrapeBtn.style.display = 'none';
            if (editBtn) editBtn.style.display = 'none';
            selectedGames.clear();
            document.querySelectorAll('.game-card-wrapper.selected').forEach(w => w.classList.remove('selected'));
            document.querySelectorAll('.game-checkbox:checked').forEach(cb => { cb.checked = false; });
            updateSelectedCount();
        }
    }

    function toggleGameSelection(gameId) {
        const wrapper = document.querySelector(`.game-card-wrapper[data-game-id="${gameId}"]`);
        if (!wrapper) return;
        const checkbox = wrapper.querySelector('.game-checkbox');

        if (selectedGames.has(gameId)) {
            selectedGames.delete(gameId);
            wrapper.classList.remove('selected');
            if (checkbox) checkbox.checked = false;
        } else {
            selectedGames.add(gameId);
            wrapper.classList.add('selected');
            if (checkbox) checkbox.checked = true;
        }
        updateSelectedCount();
    }

    async function selectAllVisible() {
        // Use the /api/games/ids endpoint to get ALL IDs matching current filters
        // (not just the ones loaded in the DOM via infinite scroll)
        try {
            const params = new URLSearchParams();
            for (const [k, v] of Object.entries(filters)) {
                if (v !== undefined && v !== null && v !== '') params.set(k, v);
            }
            for (const [k, v] of Object.entries(excludeFilters)) {
                if (v !== undefined && v !== null && v !== '') params.set('not_' + k, v);
            }

            const data = await API.get(`/api/games/ids?${params.toString()}`);

            if (data.ids) {
                // Clear current selection
                selectedGames.clear();
                document.querySelectorAll('.game-card-wrapper.selected').forEach(w => w.classList.remove('selected'));
                document.querySelectorAll('.game-checkbox:checked').forEach(cb => { cb.checked = false; });

                // Add all returned IDs
                data.ids.forEach(id => selectedGames.add(id));

                // Mark loaded cards that are in the selection
                document.querySelectorAll('.game-card-wrapper').forEach(wrapper => {
                    const gid = parseInt(wrapper.dataset.gameId);
                    if (selectedGames.has(gid)) {
                        wrapper.classList.add('selected');
                        const cb = wrapper.querySelector('.game-checkbox');
                        if (cb) cb.checked = true;
                    }
                });

                updateSelectedCount();

                if (typeof showNotification === 'function') {
                    showNotification(`Selected ${data.ids.length} games across all pages`, 'info');
                }
            }
        } catch (err) {
            console.error('Failed to select all:', err);
        }
    }

    async function selectAllUnscraped() {
        // Use the /api/games/ids endpoint to get ALL unscraped IDs matching current filters
        try {
            const params = new URLSearchParams();
            for (const [k, v] of Object.entries(filters)) {
                if (v !== undefined && v !== null && v !== '') params.set(k, v);
            }
            for (const [k, v] of Object.entries(excludeFilters)) {
                if (v !== undefined && v !== null && v !== '') params.set('not_' + k, v);
            }
            params.set('unscraped', '1');

            const data = await API.get(`/api/games/ids?${params.toString()}`);

            if (data.ids) {
                // Clear current selection
                selectedGames.clear();
                document.querySelectorAll('.game-card-wrapper.selected').forEach(w => w.classList.remove('selected'));
                document.querySelectorAll('.game-checkbox:checked').forEach(cb => { cb.checked = false; });

                // Add all returned IDs
                data.ids.forEach(id => selectedGames.add(id));

                // Mark visible cards that are in the selection
                document.querySelectorAll('.game-card-wrapper').forEach(wrapper => {
                    const gid = parseInt(wrapper.dataset.gameId);
                    if (selectedGames.has(gid)) {
                        wrapper.classList.add('selected');
                        const cb = wrapper.querySelector('.game-checkbox');
                        if (cb) cb.checked = true;
                    }
                });

                updateSelectedCount();

                if (typeof showNotification === 'function') {
                    showNotification(`Selected ${data.ids.length} unscraped games across all pages`, 'info');
                }
            }
        } catch (err) {
            console.error('Failed to select all unscraped:', err);
        }
    }

    function updateSelectedCount() {
        const el = document.getElementById('selectedCount');
        if (el) el.textContent = selectedGames.size;
        const editEl = document.getElementById('selectedEditCount');
        if (editEl) editEl.textContent = selectedGames.size;
    }

    function startBulkScrape() {
        if (selectedGames.size === 0) {
            if (typeof showModal === 'function') {
                showModal('No Games Selected', 'Please select at least one game to scrape.');
            }
            return;
        }
        const toggle = document.getElementById('scrapeModeToggle');
        const mode = toggle && toggle.checked ? 'fill_missing' : 'full_rescrape';
        BulkScrapeController.start(Array.from(selectedGames), cfg.systemId || filters.system || null, mode);
    }

    function startBulkEdit() {
        if (selectedGames.size === 0) {
            if (typeof showModal === 'function') {
                showModal('No Games Selected', 'Please select at least one game to edit.');
            }
            return;
        }
        BulkEditController.open(Array.from(selectedGames));
    }

    // =========================================================================
    // STATE PERSISTENCE
    // =========================================================================

    function getStateKey() {
        return cfg.pageKey;
    }

    function saveState() {
        try {
            sessionStorage.setItem(getStateKey(), JSON.stringify({
                filters: filters,
                excludeFilters: excludeFilters,
                scrollY: window.scrollY
            }));
        } catch (e) { /* ignore */ }
    }

    function restoreState() {
        try {
            // Pass 36.5 — route through safeParseJSON so a corrupt entry
            // (DevTools edit, schema drift from a prior build) gets cleared
            // on first read instead of re-throwing every page load.
            const state = safeParseJSON(getStateKey(), null, sessionStorage);
            if (!state) return;

            if (state.filters) {
                filters = state.filters;
                excludeFilters = state.excludeFilters || {};

                // Ensure locked system filter is always present
                if (cfg.systemId) filters.system = cfg.systemId;

                // Restore UI elements
                if (filters.search) {
                    const si = document.getElementById('gameSearch');
                    if (si) si.value = filters.search;
                }
                if (filters.system && !cfg.systemId) {
                    const sf = document.getElementById('systemFilter');
                    if (sf) sf.value = filters.system;
                }
                if (filters.system_type) {
                    const tf = document.getElementById('systemTypeFilter');
                    if (tf) tf.value = filters.system_type;
                }
                if (filters.ra_only === '1') {
                    document.querySelector('.ra-filter-btn')?.classList.add('active');
                }
                if (filters.show_bonus === '1') {
                    document.querySelector('.bonus-filter-btn')?.classList.add('active');
                    const bt = document.getElementById('bonusFilterText');
                    if (bt) bt.textContent = 'Hide Bonus';
                }
                if (filters.letter) {
                    activeLetterJump = filters.letter;
                    const btn = document.querySelector(`.alphabet-btn[data-letter="${filters.letter}"]`);
                    if (btn) btn.classList.add('active');
                }

                updateFilterDisplay();
            }

            // Restore scroll after data loads
            if (state.scrollY) {
                const savedScroll = state.scrollY;
                const tryRestore = () => {
                    if (!isLoading) {
                        setTimeout(() => window.scrollTo(0, savedScroll), 100);
                    } else {
                        setTimeout(tryRestore, 200);
                    }
                };
                setTimeout(tryRestore, 200);
            }
        } catch (e) { /* ignore */ }
    }

    // Save on scroll (debounced) — store reference for cleanup in destroy()
    let scrollSaveTimer;
    function _onScrollSave() {
        clearTimeout(scrollSaveTimer);
        scrollSaveTimer = setTimeout(saveState, 300);
    }
    window.addEventListener('scroll', _onScrollSave, { passive: true });

    // =========================================================================
    // HELPERS
    // =========================================================================

    function esc(str) {
        return escapeHtml(String(str || ''));
    }

    // Pass 36.1 — escAttr interpolates into a SINGLE-QUOTED JS-string
    // literal embedded in a DOUBLE-QUOTED HTML attribute:
    //   `onclick="...applyFilter('${escAttr(title)}')"`.
    // The HTML parser entity-decodes first, then the JS parser sees the
    // result. So a game title containing `'`, `\\`, newline, `<`, or `>`
    // breaks out of the JS string and everything after is executable —
    // the previous `escapeHtml()`-only form was XSS-equivalent for any
    // user-editable text that reached these sinks.
    //
    // Fix: escape EVERYTHING outside a safe alphanumeric/space set to a
    // `\\uHHHH` JS escape. That survives both HTML attribute decoding
    // AND JS string parsing — the decoded bytes are a valid JS escape
    // sequence that yields the original char in-string without any
    // delimiter break. Then HTML-escape the whole thing to protect the
    // outer attribute quote.
    function escAttr(str) {
        const s = String(str || '');
        const jsEscaped = s.replace(/[^a-zA-Z0-9 _.\-]/g, (c) => {
            const code = c.charCodeAt(0);
            if (code < 0x100) {
                return '\\x' + code.toString(16).padStart(2, '0');
            }
            return '\\u' + code.toString(16).padStart(4, '0');
        });
        return escapeHtml(jsEscaped);
    }

    // =========================================================================
    // GLOBAL EXPORTS (for onclick handlers in HTML)
    // =========================================================================

    // Override globals from game-list.js for this page
    window.filterGames = () => resetAndFetch();
    window.openFilterModal = (type) => openFilterModal(type);
    window.closeFilterModal = () => closeFilterModal();
    window.applyFilter = (type, value) => applyFilter(type, value);
    window.applyFilterDirect = (type, value) => applyFilterDirect(type, value);
    window.removeFilter = (type) => removeFilter(type);
    window.setFilterMode = (excludeMode) => setFilterMode(excludeMode);
    window.clearFilters = () => clearFilters();
    window.toggleRAFilter = () => toggleRAFilter();
    window.toggleBonusDiscFilter = () => toggleBonusDiscFilter();
    window.clearSearch = () => {
        clearLetterJump();
        const si = document.getElementById('gameSearch');
        if (si) si.value = '';
        delete filters.search;
        resetAndFetch();
    };

    window.toggleBulkMode = () => toggleBulkMode();
    window.exitBulkMode = () => { if (bulkMode) toggleBulkMode(); };
    window.selectAllVisible = () => selectAllVisible();
    window.selectAllUnscraped = () => selectAllUnscraped();
    window.toggleGameSelection = (id) => toggleGameSelection(id);
    window.startBulkScrape = () => startBulkScrape();
    window.startBulkEdit = () => startBulkEdit();

    // =========================================================================
    // EVENT LISTENERS (non-init)
    // =========================================================================

    // Close filter modal on backdrop click.
    // Pass 29.3: Escape handling is now owned by ModalFocusTrap (activated
    // inside openFilterModal / deactivated inside closeFilterModal), which
    // stacks correctly with any parent modal trap. The standalone document
    // keydown listener from the pre-29.3 implementation has been removed.
    function _onFilterBackdropClick(e) {
        const modal = document.getElementById('filterModal');
        if (e.target === modal) closeFilterModal();
    }
    document.addEventListener('click', _onFilterBackdropClick);

    // =========================================================================
    // PUBLIC API
    // =========================================================================

    function destroy() {
        if (scrollObserver) { scrollObserver.disconnect(); scrollObserver = null; }
        if (_filterBarResizeObserver) { _filterBarResizeObserver.disconnect(); _filterBarResizeObserver = null; }
        if (currentFetchController) { currentFetchController.abort(); currentFetchController = null; }
        clearTimeout(searchTimeout);
        clearTimeout(scrollSaveTimer);
        clearTimeout(_imageRelayoutTimer);
        window.removeEventListener('scroll', _onScrollSave);
        document.removeEventListener('keydown', _onFilterKeydown);
        document.removeEventListener('click', _onFilterBackdropClick);
        selectedGames.clear();
    }

    window.addEventListener('beforeunload', destroy);

    /**
     * Refresh one or more game cards with fresh data from the server.
     * Fetches card-compatible data and fully re-renders each card in-place.
     * @param {number|number[]} gameIds - Single game ID or array of IDs
     */
    async function refreshCards(gameIds) {
        if (!cfg) return; // Controller not initialized
        const ids = Array.isArray(gameIds) ? gameIds : [gameIds];
        if (ids.length === 0) return;

        // Only refresh IDs that have cards on the page
        const visibleIds = ids.filter(id =>
            document.querySelector(`.game-card-wrapper[data-game-id="${id}"]`)
        );
        if (visibleIds.length === 0) return;

        try {
            const data = await API.get(`/api/games/card-data?ids=${visibleIds.join(',')}`);
            if (!data.success || !data.games) return;

            for (const game of data.games) {
                const oldWrapper = document.querySelector(`.game-card-wrapper[data-game-id="${game.id}"]`);
                if (!oldWrapper) continue;

                const newWrapper = renderGameCard(game);

                // Preserve bulk selection state
                if (oldWrapper.classList.contains('selected')) {
                    newWrapper.classList.add('selected');
                }

                // Replace in DOM (click handler is delegated on the grid, no re-attach needed)
                oldWrapper.parentNode.replaceChild(newWrapper, oldWrapper);
            }

            // Re-layout masonry after cards changed
            if (typeof window.relayoutMasonry === 'function') {
                requestAnimationFrame(() => window.relayoutMasonry());
            }
        } catch (e) {
            console.debug('Card refresh failed:', e.message);
        }
    }

    return {
        init,
        applyFilter,
        applyFilterDirect,
        removeFilter,
        handleFilterOptionClick,
        setFilterMode,
        applyExcludeFilter,
        applyExcludeFilterDirect,
        removeExcludeFilter,
        toggleRAFilter,
        toggleBonusDiscFilter,
        toggleGameSelection,
        selectAllUnscraped,
        refreshCards,
        destroy,
    };

})();

window.AllGamesController = AllGamesController;
