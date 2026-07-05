/* =============================================================================
   RETRODB - MAIN JAVASCRIPT
   Interactive functionality for the ROM Library
   ============================================================================= */

window.RetroDB = window.RetroDB || {};

// =============================================================================
// GLOBAL STATE
// =============================================================================

const RetroDBState = {
    currentModal: null,
    screenshotIndex: 0,
    screenshots: [],
};

// Tracked resources for cleanup
let _animationObserver = null;
let _backToTopScrollHandler = null;

// =============================================================================
// GLOBAL ERROR HANDLERS (Pass 42.3)
// =============================================================================
// Surface unhandled errors and unhandled promise rejections to the user via
// the toast system instead of letting them die silently in the console.
// Rate-limited so a feedback loop can't flood the screen.

let _lastErrorToastAt = 0;
const _ERROR_TOAST_INTERVAL_MS = 5000;

function _surfaceError(prefix, detail) {
    if (typeof showNotification !== 'function') return;
    const now = Date.now();
    if (now - _lastErrorToastAt < _ERROR_TOAST_INTERVAL_MS) return;
    _lastErrorToastAt = now;
    try {
        showNotification(`${prefix}: ${detail}`, 'error');
    } catch (_e) { /* swallow — never loop on a toast failure */ }
}

window.addEventListener('error', function(event) {
    // Cross-origin script errors arrive sanitized as "Script error." with no
    // useful detail — nothing actionable to surface, skip.
    const msg = event.message || '';
    if (!msg || msg === 'Script error.') return;
    _surfaceError(t('Unexpected error'), msg);
});

window.addEventListener('unhandledrejection', function(event) {
    const r = event.reason;
    let detail;
    if (r instanceof Error) {
        detail = r.message || r.name || 'unknown error';
    } else if (typeof r === 'string') {
        detail = r;
    } else {
        try { detail = JSON.stringify(r); } catch (_e) { detail = String(r); }
    }
    _surfaceError(t('Unhandled rejection'), detail);
});

// =============================================================================
// DOM READY
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initializeSidebar();
    initializeSearch();
    initializeFilters();
    initializeModals();
    initializeScreenshots();
    initializeAnimations();
    initializeTooltips();
    initializeConfirmDialogs();
    initializeBackToTop();
    initializeImageErrorHandling();

    // Apply themed icons to all [data-themed-icon] elements
    if (typeof getThemedIcon === 'function') {
        document.querySelectorAll('[data-themed-icon]').forEach(el => {
            el.textContent = getThemedIcon(el.dataset.themedIcon);
        });
    }

    // Stack sticky navs and set scroll-margin-top on anchor targets
    if (typeof StickyScroll !== 'undefined') {
        StickyScroll.stackPositions();
        StickyScroll.updateMargins();

        // Re-scroll to hash target after margins are set (browser may
        // have already scrolled before margins existed)
        if (window.location.hash) {
            const hashTarget = document.getElementById(window.location.hash.substring(1));
            if (hashTarget) {
                requestAnimationFrame(() => StickyScroll.to(hashTarget));
            }
        }
    }
});

// =============================================================================
// BACK TO TOP BUTTON
// =============================================================================

function initializeBackToTop() {
    const backToTopBtn = document.getElementById('backToTopBtn');
    if (!backToTopBtn) return;

    // Skip scroll handler if BackToTopController already initialized it (game list pages)
    if (!(window.BackToTopController && BackToTopController._isInit)) {
        // Remove previous handler if re-initialized (e.g. bfcache restore)
        if (_backToTopScrollHandler) {
            window.removeEventListener('scroll', _backToTopScrollHandler);
        }
        let ticking = false;
        _backToTopScrollHandler = function() {
            if (!ticking) {
                window.requestAnimationFrame(function() {
                    if (window.scrollY > 400) {
                        backToTopBtn.classList.add('visible');
                    } else {
                        backToTopBtn.classList.remove('visible');
                    }
                    ticking = false;
                });
                ticking = true;
            }
        };
        window.addEventListener('scroll', _backToTopScrollHandler, { passive: true });
    }

    // Position the button after sidebar loads
    setTimeout(() => {
        if (window.ToastController) {
            ToastController.positionBackToTop();
        }
    }, 100);

    // Reposition on window resize
    window.addEventListener('resize', debounce(function() {
        if (window.ToastController) {
            ToastController.positionBackToTop();
        }
    }, 250), { passive: true });
}

// Global click handler for the back-to-top button. The button lives in
// base.html (every page), so its onclick handler must be in the core bundle —
// game-list.js (games bundle) only loads on game-centric pages. On those pages
// game-list.js reassigns this to BackToTopController.scrollToTop (identical
// behaviour). Without this, non-game pages threw "scrollToTop is not defined".
window.scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' });

// =============================================================================
// DELEGATED IMAGE ERROR HANDLING (FU.1)
// =============================================================================
// CSP-enforcing mode forbids inline `onerror="..."` attributes. Templates
// now mark images with `data-on-error="<action>"` and any action-specific
// attributes; a single document-level capture-phase listener dispatches.
// The handler removes the marker after firing so the fallback's own
// failure can't loop back through here.
//
// Supported actions:
//   hide               — `target.style.display = 'none'` (the no-fallback case).
//   hide-show-next     — also `display:'flex'` on `target.nextElementSibling`
//                        (cover image + adjacent placeholder pattern).
//   hide-show-id       — also `display:'flex'` on the element whose id is
//                        in `data-on-error-target-id`.
//   src                — `target.src = target.dataset.onErrorSrc`
//                        (drop-in default-image replacement).
//   outer-html         — `target.outerHTML = target.dataset.onErrorHtml`
//                        (used for trophy emoji fallbacks).

function initializeImageErrorHandling() {
    document.addEventListener('error', function(event) {
        const target = event.target;
        if (!target || !target.dataset) return;
        const action = target.dataset.onError;
        if (!action) return;

        // Strip the marker first so a fallback that also fails (e.g. the
        // default trophy image was deleted) can't re-enter this handler
        // and loop. `event.preventDefault()` is intentionally not called
        // — other listeners may still want to know an image failed.
        delete target.dataset.onError;

        if (action === 'hide') {
            target.style.display = 'none';
        } else if (action === 'hide-show-next') {
            target.style.display = 'none';
            const sibling = target.nextElementSibling;
            if (sibling) sibling.style.display = 'flex';
        } else if (action === 'hide-show-id') {
            target.style.display = 'none';
            const targetId = target.dataset.onErrorTargetId;
            if (targetId) {
                const placeholder = document.getElementById(targetId);
                if (placeholder) placeholder.style.display = 'flex';
            }
        } else if (action === 'src') {
            const src = target.dataset.onErrorSrc;
            if (src) target.src = src;
        } else if (action === 'outer-html') {
            const html = target.dataset.onErrorHtml;
            if (html) target.outerHTML = html;
        }
    }, /* useCapture */ true);
}

// =============================================================================
// SIDEBAR FUNCTIONALITY
// =============================================================================

function initializeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.querySelector('.sidebar-toggle');
    const mainContent = document.querySelector('.main-content');
    
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            sidebar.classList.toggle('collapsed');
            mainContent.classList.toggle('sidebar-collapsed');
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
            // Reposition toast and back-to-top after sidebar transition completes
            setTimeout(() => {
                if (window.ToastController) {
                    ToastController.positionContainer();
                    ToastController.positionBackToTop();
                }
            }, 300);
        });
    }
    
    // Restore sidebar state
    const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (isCollapsed && sidebar) {
        sidebar.classList.add('collapsed');
        if (mainContent) mainContent.classList.add('sidebar-collapsed');
    }
    
    // Mobile sidebar toggle
    const mobileToggle = document.querySelector('.mobile-menu-toggle');
    if (mobileToggle) {
        mobileToggle.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
    }
    
    // Close sidebar on outside click (mobile)
    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 992) {
            if (sidebar && !sidebar.contains(e.target) && !mobileToggle?.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        }
    });
}

// =============================================================================
// SEARCH FUNCTIONALITY
// =============================================================================

function initializeSearch() {
    // System search
    const systemSearch = document.getElementById('systemSearch');
    if (systemSearch) {
        systemSearch.addEventListener('input', debounce(function(e) {
            filterSystems(e.target.value);
        }, 300));
    }
    
    // Games search
    const gameSearch = document.getElementById('gameSearch');
    if (gameSearch) {
        gameSearch.addEventListener('input', debounce(function(e) {
            filterGames(e.target.value);
        }, 300));
    }
    
    // Global search
    const globalSearch = document.getElementById('globalSearch');
    if (globalSearch) {
        globalSearch.addEventListener('input', debounce(function(e) {
            performGlobalSearch(e.target.value);
        }, 500));
    }
}

function filterSystems(query) {
    const cards = document.querySelectorAll('.system-card');
    const normalizedQuery = query.toLowerCase().trim();
    let visibleCount = 0;
    
    cards.forEach(card => {
        const name = card.querySelector('.system-name')?.textContent.toLowerCase() || '';
        const folder = card.dataset.folder?.toLowerCase() || '';
        
        if (name.includes(normalizedQuery) || folder.includes(normalizedQuery)) {
            card.style.display = '';
            card.style.animation = 'fadeIn 0.3s ease';
            visibleCount++;
        } else {
            card.style.display = 'none';
        }
    });
    
    updateEmptyState('.systems-grid', cards);
    
    // Update visible count
    const countEl = document.getElementById('visibleSystemsCount');
    if (countEl) {
        countEl.textContent = formatNumber(visibleCount);
    }
}

function filterGames(query) {
    const rows = document.querySelectorAll('.games-table tbody tr, .game-card');
    const normalizedQuery = query.toLowerCase().trim();
    let visibleCount = 0;
    
    rows.forEach(row => {
        const title = row.querySelector('.game-row-title, .game-title')?.textContent.toLowerCase() || '';
        const system = row.querySelector('.game-row-system')?.textContent.toLowerCase() || '';
        const genre = row.querySelector('.game-row-genre')?.textContent.toLowerCase() || '';
        const developer = row.dataset.developer?.toLowerCase() || '';
        const publisher = row.dataset.publisher?.toLowerCase() || '';
        
        if (title.includes(normalizedQuery) || 
            system.includes(normalizedQuery) || 
            genre.includes(normalizedQuery) ||
            developer.includes(normalizedQuery) ||
            publisher.includes(normalizedQuery)) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });
    
    updateRowCount(visibleCount);
}

// Pass 29.5: last-in-wins guard for the global search input. Rapid typing
// used to fire parallel fetches; whichever completed last painted the
// results, so a slow response to "Zel" could overwrite a fast response to
// "Zelda". The controller is aborted before issuing each new request.
let _globalSearchController = null;

function performGlobalSearch(query) {
    if (query.length < 2) {
        if (_globalSearchController) {
            _globalSearchController.abort();
            _globalSearchController = null;
        }
        hideSearchResults();
        return;
    }

    if (_globalSearchController) _globalSearchController.abort();
    _globalSearchController = new AbortController();
    const signal = _globalSearchController.signal;

    showSearchLoading();

    API.get(`/api/search?q=${encodeURIComponent(query)}`, { signal })
        .then(data => {
            if (signal.aborted) return;  // a newer request is in flight
            displaySearchResults(data);
        })
        .catch(error => {
            // AbortError just means we were superseded; don't wipe results
            // that the follow-up request may have already painted.
            if (error && error.name === 'AbortError') return;
            console.error('Search error:', error);
            hideSearchResults();
        });
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');
    if (!container) return;
    
    if (!results || results.length === 0) {
        container.innerHTML = `<div class="search-no-results">${escapeHtml(t('No results found'))}</div>`;
    } else {
        container.innerHTML = results.map(result => `
            <a href="${encodeURI(result.url)}" class="search-result-item">
                <span class="search-result-type">${escapeHtml(result.type)}</span>
                <span class="search-result-name">${escapeHtml(result.name)}</span>
            </a>
        `).join('');
    }
    
    container.classList.add('active');
}

function hideSearchResults() {
    const container = document.getElementById('searchResults');
    if (container) {
        container.classList.remove('active');
    }
}

function showSearchLoading() {
    const container = document.getElementById('searchResults');
    if (container) {
        container.innerHTML = `<div class="search-loading"><span class="loading-spinner"></span> ${escapeHtml(t('Searching...'))}</div>`;
        container.classList.add('active');
    }
}

// =============================================================================
// FILTER FUNCTIONALITY
// =============================================================================

function initializeFilters() {
    // Sort select
    const sortSelect = document.getElementById('sortSelect');
    if (sortSelect) {
        sortSelect.addEventListener('change', function() {
            sortItems(this.value);
        });
    }
    
    // System filter
    const systemFilter = document.getElementById('systemFilter');
    if (systemFilter) {
        systemFilter.addEventListener('change', function() {
            filterBySystem(this.value);
        });
    }
    
    // Metadata filter
    const metadataFilter = document.getElementById('metadataFilter');
    if (metadataFilter) {
        metadataFilter.addEventListener('change', function() {
            filterByMetadata(this.value);
        });
    }
}

function sortItems(sortBy) {
    const container = document.querySelector('.systems-grid, .games-table tbody');
    if (!container) return;
    
    const items = Array.from(container.children);
    
    items.sort((a, b) => {
        let aValue, bValue;
        
        switch (sortBy) {
            case 'name-asc':
                aValue = getItemName(a).toLowerCase();
                bValue = getItemName(b).toLowerCase();
                return aValue.localeCompare(bValue);
            case 'name-desc':
                aValue = getItemName(a).toLowerCase();
                bValue = getItemName(b).toLowerCase();
                return bValue.localeCompare(aValue);
            case 'count-asc':
                aValue = parseInt(getItemCount(a)) || 0;
                bValue = parseInt(getItemCount(b)) || 0;
                return aValue - bValue;
            case 'count-desc':
                aValue = parseInt(getItemCount(a)) || 0;
                bValue = parseInt(getItemCount(b)) || 0;
                return bValue - aValue;
            case 'year-asc':
                aValue = getItemYear(a) || '9999';
                bValue = getItemYear(b) || '9999';
                return aValue.localeCompare(bValue);
            case 'year-desc':
                aValue = getItemYear(a) || '0000';
                bValue = getItemYear(b) || '0000';
                return bValue.localeCompare(aValue);
            default:
                return 0;
        }
    });
    
    items.forEach(item => container.appendChild(item));
}

function getItemName(item) {
    return item.querySelector('.system-name, .game-row-title, .game-title')?.textContent || '';
}

function getItemCount(item) {
    const countText = item.querySelector('.system-info')?.textContent || '0';
    return countText.match(/\d+/)?.[0] || '0';
}

function getItemYear(item) {
    return item.querySelector('.game-row-year')?.textContent?.trim() || 
           item.dataset.year || '';
}

function filterBySystem(systemId) {
    const rows = document.querySelectorAll('.games-table tbody tr, .game-card');
    let visibleCount = 0;
    
    rows.forEach(row => {
        if (!systemId || row.dataset.systemId === systemId) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });
    
    updateRowCount(visibleCount);
}

function filterByMetadata(status) {
    const rows = document.querySelectorAll('.games-table tbody tr, .game-card');
    let visibleCount = 0;
    
    rows.forEach(row => {
        const hasMetadata = row.dataset.scraped === '1';
        
        if (!status) {
            row.style.display = '';
            visibleCount++;
        } else if (status === 'complete' && hasMetadata) {
            row.style.display = '';
            visibleCount++;
        } else if (status === 'missing' && !hasMetadata) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });
    
    updateRowCount(visibleCount);
}

function updateRowCount(count) {
    const countElement = document.getElementById('visibleCount');
    if (countElement) {
        const val = count !== undefined ? count :
            document.querySelectorAll('.games-table tbody tr:not([style*="display: none"]), .game-card:not([style*="display: none"])').length;
        countElement.textContent = formatNumber(val);
    }
}

function updateEmptyState(containerSelector, items) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    
    const visibleItems = Array.from(items).filter(item => item.style.display !== 'none');
    
    let emptyState = container.querySelector('.empty-state');
    
    if (visibleItems.length === 0) {
        if (!emptyState) {
            emptyState = document.createElement('div');
            emptyState.className = 'empty-state';
            emptyState.innerHTML = `
                <div class="empty-state-icon">🔍</div>
                <div class="empty-state-title">${escapeHtml(t('No results found'))}</div>
                <div class="empty-state-text">${escapeHtml(t('Try adjusting your search or filters'))}</div>
            `;
            container.appendChild(emptyState);
        }
        emptyState.style.display = '';
    } else if (emptyState) {
        emptyState.style.display = 'none';
    }
}

// =============================================================================
// MODAL FUNCTIONALITY
// =============================================================================

function initializeModals() {
    // Note: Escape key handling is done by KeyboardShortcuts.closeAnyModal()
    // and game-modals.js — no duplicate keydown listener needed here.

    // Close modal on backdrop click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeScreenshotModal();
            }
        });
    });

    // Modal close buttons
    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', closeScreenshotModal);
    });
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
        RetroDBState.currentModal = modal;
        document.body.style.overflow = 'hidden';
    }
}

function closeScreenshotModal() {
    if (RetroDBState.currentModal) {
        RetroDBState.currentModal.classList.remove('active');
        RetroDBState.currentModal = null;
        document.body.style.overflow = '';
        // Pass 29.3: match the activate in openScreenshotModal so the
        // focus trap stack stays balanced. deactivate() no-ops when
        // there's nothing to pop.
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    }
}

// =============================================================================
// SCREENSHOT GALLERY
// =============================================================================

function initializeScreenshots() {
    // Use event delegation so indices are always computed from current DOM state
    const container = document.getElementById('screenshotsRow');
    if (container) {
        container.addEventListener('click', function(e) {
            // Ignore clicks on the delete button
            if (e.target.closest('.screenshot-delete-btn')) return;
            const thumb = e.target.closest('.screenshot-thumb');
            if (!thumb) return;
            // Compute index from current DOM order
            const currentThumbs = Array.from(container.querySelectorAll('.screenshot-thumb'));
            const index = currentThumbs.indexOf(thumb);
            if (index >= 0) {
                // Rebuild screenshots array from current DOM
                RetroDBState.screenshots = currentThumbs.map(t => t.querySelector('img')?.src || '');
                openScreenshotModal(index);
            }
        });
    }

    // Collect initial screenshots
    const screenshotItems = document.querySelectorAll('.screenshot-thumb');
    RetroDBState.screenshots = Array.from(screenshotItems).map(item => {
        return item.querySelector('img')?.src || '';
    });

    // Navigation arrows
    document.querySelector('.modal-nav.prev')?.addEventListener('click', function(e) {
        e.stopPropagation();
        navigateScreenshots(-1);
    });
    
    document.querySelector('.modal-nav.next')?.addEventListener('click', function(e) {
        e.stopPropagation();
        navigateScreenshots(1);
    });
    
    // Pass 36.8 — arrow-key navigation now routes through the
    // ModalFocusTrap activated in openScreenshotModal (see below). That
    // removed the standalone document-level keydown handler formerly here.
}

function openScreenshotModal(index) {
    RetroDBState.screenshotIndex = index;
    updateScreenshotDisplay();
    openModal('screenshotModal');
    // Pass 29.3: activate ModalFocusTrap so Tab stays inside the modal and
    // Escape routes through the trap's onEscape (closes this modal without
    // collapsing any parent modal beneath). KeyboardShortcuts.closeAnyModal
    // retains its global Escape semantics for pages that don't open via
    // openScreenshotModal.
    const modal = document.getElementById('screenshotModal');
    if (window.ModalFocusTrap && modal) {
        ModalFocusTrap.activate(modal, document.activeElement, {
            onEscape: () => closeScreenshotModal(),
            // Pass 36.8 — arrows consolidated here; removed separate
            // document-level keydown handler that used currentModal probe.
            onArrowLeft: () => navigateScreenshots(-1),
            onArrowRight: () => navigateScreenshots(1),
        });
    }
}

function navigateScreenshots(direction) {
    const newIndex = RetroDBState.screenshotIndex + direction;

    if (newIndex >= 0 && newIndex < RetroDBState.screenshots.length) {
        RetroDBState.screenshotIndex = newIndex;
        updateScreenshotDisplay();
    }
}

function updateScreenshotDisplay() {
    const modalImg = document.getElementById('modalImage');
    const counter = document.getElementById('modalCounter');

    if (modalImg && RetroDBState.screenshots[RetroDBState.screenshotIndex]) {
        modalImg.src = RetroDBState.screenshots[RetroDBState.screenshotIndex];
    }

    if (counter) {
        counter.textContent = `${RetroDBState.screenshotIndex + 1} / ${RetroDBState.screenshots.length}`;
    }

    // Update nav button states
    const prevBtn = document.querySelector('.modal-nav.prev');
    const nextBtn = document.querySelector('.modal-nav.next');

    if (prevBtn) {
        prevBtn.disabled = RetroDBState.screenshotIndex === 0;
        prevBtn.style.opacity = RetroDBState.screenshotIndex === 0 ? '0.3' : '1';
    }

    if (nextBtn) {
        nextBtn.disabled = RetroDBState.screenshotIndex === RetroDBState.screenshots.length - 1;
        nextBtn.style.opacity = RetroDBState.screenshotIndex === RetroDBState.screenshots.length - 1 ? '0.3' : '1';
    }
}

// =============================================================================
// ANIMATIONS
// =============================================================================

function initializeAnimations() {
    // Disconnect previous observer if re-initialized (e.g. bfcache restore)
    if (_animationObserver) {
        _animationObserver.disconnect();
        _animationObserver = null;
    }

    // Intersection Observer for scroll animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    _animationObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate-in');
                _animationObserver.unobserve(entry.target);
            }
        });
    }, observerOptions);

    // Observe elements
    document.querySelectorAll('.animate-on-scroll').forEach(el => {
        _animationObserver.observe(el);
    });
    
    // Add staggered animation to cards
    const cards = document.querySelectorAll('.system-card, .stat-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.05}s`;
        card.classList.add('animate-fade-up');
    });
}

// =============================================================================
// TOOLTIPS
// =============================================================================

function initializeTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(el => {
        el.addEventListener('mouseenter', showTooltip);
        el.addEventListener('mouseleave', hideTooltip);
    });
}

function showTooltip(e) {
    const text = e.target.dataset.tooltip;
    if (!text) return;

    // Remove any existing tooltip to prevent leak on rapid hover
    if (e.target._tooltip) {
        e.target._tooltip.remove();
        delete e.target._tooltip;
    }

    const tooltip = document.createElement('div');
    tooltip.className = 'tooltip';
    tooltip.textContent = text;
    document.body.appendChild(tooltip);
    
    const rect = e.target.getBoundingClientRect();
    tooltip.style.top = `${rect.top - tooltip.offsetHeight - 8}px`;
    tooltip.style.left = `${rect.left + (rect.width - tooltip.offsetWidth) / 2}px`;
    
    requestAnimationFrame(() => tooltip.classList.add('active'));
    
    e.target._tooltip = tooltip;
}

function hideTooltip(e) {
    if (e.target._tooltip) {
        e.target._tooltip.remove();
        delete e.target._tooltip;
    }
}

// =============================================================================
// CONFIRM DIALOGS
// =============================================================================

function initializeConfirmDialogs() {
    document.querySelectorAll('[data-confirm]').forEach(el => {
        el.addEventListener('click', function(e) {
            e.preventDefault();
            const message = this.dataset.confirm;
            const target = this;
            showConfirm(t('⚠️ Confirm'), message, () => {
                // Re-trigger the action without the confirm listener
                target.removeAttribute('data-confirm');
                target.click();
                target.setAttribute('data-confirm', message);
            });
        });
    });
}

// Specific confirm for reset
function confirmReset(form) {
    if (window.event) window.event.preventDefault();
    showConfirm(t('🗑️ Reset Metadata'), t('Are you sure you want to reset all metadata for this game? This will delete boxart and screenshots.'), () => {
        form.submit();
    });
    return false;
}

// =============================================================================
// API FUNCTIONS
// =============================================================================

async function scanLibrary() {
    const btn = document.getElementById('scanLibraryBtn');
    if (!btn) return;

    const originalText = btn.innerHTML;

    btn.innerHTML = `<span class="loading-spinner"></span> ${escapeHtml(t('Scanning...'))}`;
    btn.disabled = true;

    // v3.6.5 — Use raw fetch so the response body (which carries the
    // "ROM path not configured" remediation message on 4xx) reaches the
    // user instead of being swallowed by API.post's throw-on-!ok wrapper.
    try {
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        });
        let data = null;
        try { data = await response.json(); } catch (_) { /* non-JSON body */ }

        if (response.ok && data && data.success) {
            showNotification(t('Library scan complete! Found {n} new games.', {n: data.new_games || 0}), 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            const msg = (data && data.error) || t('Scan failed (HTTP {status})', {status: response.status});
            showNotification(msg, 'error');
        }
    } catch (error) {
        showNotification(t('Error scanning library: {error}', {error: error.message}), 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function restartServer() {
    showConfirm(
        t('🔄 Restart Server'),
        t('Are you sure you want to restart the server?'),
        async function() {
            showNotification(t('Restarting server...'), 'info');
            
            try {
                await API.post('/api/restart');

                // Wait and try to reconnect
                setTimeout(() => {
                    checkServerStatus();
                }, 3000);
            } catch (error) {
                // Expected - server is restarting
                setTimeout(() => {
                    checkServerStatus();
                }, 3000);
            }
        }
    );
}

async function shutdownServer() {
    showConfirm(
        t('🛑 Shut Down Server'),
        t('Are you sure you want to shut down the server? You will need to start it again manually.'),
        async function() {
            showNotification(t('Shutting down server...'), 'info');

            try {
                await API.post('/api/shutdown');
            } catch (error) {
                // Expected — the connection drops as the server exits.
            }

            // Do NOT poll to reconnect: the server is going down for good.
            showNotification(t('Server stopped. You can close this tab.'), 'success');
        }
    );
}

async function checkServerStatus() {
    const maxAttempts = 10;
    let attempts = 0;
    
    const checkStatus = async () => {
        try {
            await API.get('/api/status');
            showNotification(t('Server restarted successfully!'), 'success');
            setTimeout(() => location.reload(), 1000);
            return true;
        } catch (error) {
            // Server not ready yet
        }
        
        attempts++;
        if (attempts < maxAttempts) {
            setTimeout(checkStatus, 1000);
        } else {
            showNotification(t('Could not reconnect to server. Please refresh manually.'), 'error');
        }
    };
    
    checkStatus();
}

async function cleanMissingRoms() {
    showConfirm(
        t('🧹 Clean Missing ROMs'),
        t('This will remove database entries for ROM files that no longer exist on disk. This cannot be undone. Continue?'),
        async function() {
            const btn = document.getElementById('cleanMissingBtn');
            const resultDiv = document.getElementById('cleanMissingResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<span class="btn-icon">⏳</span> ${escapeHtml(t('Scanning...'))}`;
            }

            try {
                const data = await API.post('/api/clean-missing-roms');

                if (data.success) {
                    showNotification(t('Removed {n} games with missing ROMs', {n: formatNumber(data.removed)}), 'success');

                    if (resultDiv) {
                        if (data.removed > 0) {
                            let html = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(239, 68, 68, 0.1);">`;
                            html += `<strong style="color: var(--danger-red);">${escapeHtml(t('Removed {n} games:', {n: formatNumber(data.removed)}))}</strong>`;
                            html += `<ul style="margin-top: var(--spacing-sm); font-size: 0.9rem;">`;
                            for (const game of data.removed_games) {
                                html += `<li>${escapeHtml(game.title)}</li>`;
                            }
                            if (data.removed > 50) {
                                html += `<li>${escapeHtml(t('... and {n} more', {n: formatNumber(data.removed - 50)}))}</li>`;
                            }
                            html += `</ul></div>`;
                            resultDiv.innerHTML = html;
                        } else {
                            resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                                <strong style="color: var(--primary-cyan);">✓ ${escapeHtml(t('All ROMs accounted for!'))}</strong>
                                <p style="margin-top: var(--spacing-xs);">${escapeHtml(t('No missing ROM files found.'))}</p>
                            </div>`;
                        }
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || t('Failed to clean missing ROMs'), 'error');
                }
            } catch (error) {
                console.error('Error cleaning missing ROMs:', error);
                showNotification(t('Failed to clean missing ROMs'), 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<span class="btn-icon">🧹</span> ${escapeHtml(t('Clean Missing ROMs'))}`;
                }
            }
        },
        {danger: true}
    );
}

async function clearClzImports() {
    showConfirm(
        t('📋 Clear CLZ Imports'),
        t('This will remove ALL games imported via CLZ Games Import from the database. This cannot be undone. Continue?'),
        async function() {
            const btn = document.getElementById('clearClzBtn');
            const resultDiv = document.getElementById('clearClzResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<span class="btn-icon">⏳</span> ${escapeHtml(t('Removing...'))}`;
            }

            try {
                const data = await API.post('/api/clear-clz-imports');

                if (data.success) {
                    showNotification(t('Removed {n} CLZ Import games', {n: formatNumber(data.removed)}), 'success');

                    if (resultDiv) {
                        if (data.removed > 0) {
                            let html = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(239, 68, 68, 0.1);">`;
                            html += `<strong style="color: var(--danger-red);">${escapeHtml(t('Removed {n} CLZ Import games:', {n: formatNumber(data.removed)}))}</strong>`;
                            html += `<ul style="margin-top: var(--spacing-sm); font-size: 0.9rem;">`;
                            for (const game of data.removed_games) {
                                html += `<li>${escapeHtml(game.title)}</li>`;
                            }
                            if (data.removed > 50) {
                                html += `<li>${escapeHtml(t('... and {n} more', {n: formatNumber(data.removed - 50)}))}</li>`;
                            }
                            html += `</ul></div>`;
                            resultDiv.innerHTML = html;
                        } else {
                            resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                                <strong style="color: var(--primary-cyan);">✓ ${escapeHtml(t('No CLZ Import games found'))}</strong>
                            </div>`;
                        }
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || t('Failed to clear CLZ imports'), 'error');
                }
            } catch (error) {
                console.error('Error clearing CLZ imports:', error);
                showNotification(t('Failed to clear CLZ imports'), 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<span class="btn-icon">📋</span> ${escapeHtml(t('Clear CLZ Imports'))}`;
                }
            }
        },
        {danger: true}
    );
}

async function refreshRetroAchievements() {
    showConfirm(
        t('🏆 Refresh RetroAchievements'),
        t('This will scan all games and update their RetroAchievements status. This may take several minutes for large collections. Continue?'),
        async function() {
            const btn = document.getElementById('refreshRABtn');
            const resultDiv = document.getElementById('refreshRAResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<span class="btn-icon">⏳</span> ${escapeHtml(t('Starting...'))}`;
            }
            
            try {
                // Start the background job
                const data = await API.post('/api/refresh-retroachievements');

                if (data.success) {
                    // Check if operation was queued (blocked by another RA operation)
                    if (data.queued) {
                        // Add to unified queue
                        const queue = safeParseJSON('raOperationsQueue', []);
                        
                        // Don't add duplicates
                        if (!queue.find(q => q.type === 'refresh' && q.systemId === null)) {
                            const newItem = {
                                type: 'refresh',
                                systemId: null,
                                systemName: 'All Systems',
                                timestamp: Date.now()
                            };
                            queue.push(newItem);
                            localStorage.setItem('raOperationsQueue', JSON.stringify(queue));
                            
                            // Add queued toast
                            if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                                UnifiedToastController.addRAOperationToQueue(newItem);
                                UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                            }
                        }
                        
                        // Update button to show queued state
                        if (btn) {
                            btn.innerHTML = `<span class="btn-icon">📋</span> ${escapeHtml(t('Queued'))}`;
                        }

                        showNotification(t('Added to queue - will start when current operation completes'), 'info');
                        return;
                    }
                    
                    // Create active toast immediately using UnifiedToastController
                    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                        const initialData = {
                            running: true,
                            completed: false,
                            current_system: t('Starting...'),
                            current_game: t('Initializing...'),
                            total: 0,
                            current: 0,
                            processed: 0,
                            success: 0,
                            failed: 0,
                            percent: 0,
                            paused: false
                        };
                        UnifiedToastController.showActiveToast('ra-refresh', UnifiedToastController.getTypeConfig('ra-refresh'), initialData);
                        UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                        UnifiedToastController.broadcast('job-started', 'ra-refresh', initialData);
                    }

                    // Update button to show running state
                    if (btn) {
                        btn.innerHTML = `<span class="btn-icon">⏳</span> ${escapeHtml(t('Running...'))}`;
                    }
                } else {
                    showNotification(data.error || t('Failed to start RetroAchievements refresh'), 'error');
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = `<span class="btn-icon">🏆</span> ${escapeHtml(t('Refresh RetroAchievements'))}`;
                    }
                }
            } catch (error) {
                console.error('Error starting RetroAchievements refresh:', error);
                showNotification(t('Failed to start RetroAchievements refresh'), 'error');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<span class="btn-icon">🏆</span> ${escapeHtml(t('Refresh RetroAchievements'))}`;
                }
            }
        }
    );
}

// RA Refresh is now handled by UnifiedToastController
// Old toast functions removed in v1.18.35

// Wrapper for cancel - uses UnifiedToastController
function cancelRARefresh() {
    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.cancel) {
        UnifiedToastController.cancel('ra-refresh');
    }
}

async function clearRAData() {
    // Check if system dropdown exists and get value
    const systemSelect = document.getElementById('clearRASystemSelect');
    const systemId = systemSelect ? systemSelect.value : 'all';
    const systemName = systemSelect && systemId !== 'all' 
        ? systemSelect.options[systemSelect.selectedIndex].text 
        : 'all systems';
    
    const confirmMsg = systemId === 'all'
        ? t('This will clear ALL RetroAchievements game IDs and progress data from your database. You will need to run "Refresh RetroAchievements" again afterwards to re-scan your games. Continue?')
        : t('This will clear RetroAchievements game IDs and progress data for "{system}". Continue?', {system: systemName});

    showConfirm(
        t('🗑️ Clear RetroAchievements Data'),
        confirmMsg,
        async function() {
            const btn = document.getElementById('clearRABtn');
            const resultDiv = document.getElementById('clearRAResult');
            
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = `<span class="btn-icon">⏳</span> ${escapeHtml(t('Clearing...'))}`;
            }

            try {
                // Use system-specific or all endpoint
                const endpoint = systemId === 'all'
                    ? '/api/clear-ra-data'
                    : `/api/clear-ra-data/${systemId}`;

                const data = await API.post(endpoint);

                if (data.success) {
                    const msg = systemId === 'all'
                        ? t('Cleared RA data for {n} games', {n: formatNumber(data.cleared)})
                        : t('Cleared RA data for {n} games in {system}', {n: formatNumber(data.cleared), system: systemName});
                    showNotification(msg, 'success');

                    if (resultDiv) {
                        resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                            <strong style="color: var(--primary-cyan);">✓ ${escapeHtml(t('RA Data Cleared'))}</strong>
                            <p style="margin-top: var(--spacing-xs);">${escapeHtml(t('Cleared RetroAchievements data for {n} games. Run "Refresh RetroAchievements" to re-scan with updated matching.', {n: formatNumber(data.cleared)}))}</p>
                        </div>`;
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || t('Failed to clear RA data'), 'error');
                }
            } catch (error) {
                console.error('Error clearing RA data:', error);
                showNotification(t('Failed to clear RA data'), 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = `<span class="btn-icon">🗑️</span> ${escapeHtml(t('Clear RA Data'))}`;
                }
            }
        },
        {danger: true}
    );
}

// =============================================================================
// SCRAPER FUNCTIONS
// =============================================================================

async function searchGame(gameId, title) {
    const resultsContainer = document.getElementById('searchResults');
    const searchBtn = document.getElementById('searchBtn');
    
    if (!resultsContainer || !searchBtn) return;
    
    const originalText = searchBtn.innerHTML;
    searchBtn.innerHTML = `<span class="loading-spinner"></span> ${escapeHtml(t('Searching...'))}`;
    searchBtn.disabled = true;
    
    try {
        const data = await API.post('/api/games/search', { game_id: gameId, title: title });

        if (data.results && data.results.length > 0) {
            displayScraperResults(data.results, gameId);
        } else {
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔍</div>
                    <div class="empty-state-title">${escapeHtml(t('No results found'))}</div>
                    <div class="empty-state-text">${escapeHtml(t('Try modifying the search title'))}</div>
                </div>
            `;
        }
    } catch (error) {
        resultsContainer.innerHTML = `
            <div class="alert alert-error">
                ${escapeHtml(t('Error searching: {error}', {error: error.message}))}
            </div>
        `;
    } finally {
        searchBtn.innerHTML = originalText;
        searchBtn.disabled = false;
    }
}

function displayScraperResults(results, gameId) {
    const container = document.getElementById('searchResults');
    if (!container) return;

    container.innerHTML = results.map(result => {
        const alts = Array.isArray(result.alternate_titles) ? result.alternate_titles : [];
        const primaryLower = (result.name || '').trim().toLowerCase();
        const altChips = alts
            .filter(a => a && a.title && a.title.trim().toLowerCase() !== primaryLower)
            .slice(0, 6)
            .map(a => `
                <span class="alt-title-chip">
                    ${a.region ? `<span class="alt-title-region">${escapeHtml(a.region)}</span>` : ''}
                    <span class="alt-title-text">${escapeHtml(a.title)}</span>
                </span>
            `).join('');

        return `
            <div class="search-result">
                <div class="search-result-info">
                    <h4>${escapeHtml(result.name)}</h4>
                    <div class="search-result-meta">
                        <span class="source-badge ${result.source}">${result.source.toUpperCase()}</span>
                        ${result.release_date ? `<span>${result.release_date.substring(0, 4)}</span>` : ''}
                        ${result.score ? `<span>${escapeHtml(t('Score: {score}', {score: result.score.toFixed(1)}))}</span>` : ''}
                    </div>
                    ${altChips ? `<div class="search-result-alts"><span class="search-result-alts-label">${escapeHtml(t('Also known as:'))}</span> ${altChips}</div>` : ''}
                </div>
                <form method="POST" style="margin: 0;">
                    <input type="hidden" name="action" value="apply">
                    <input type="hidden" name="game_source" value="${result.source}_${result.id}">
                    <button type="submit" class="btn btn-success btn-sm">
                        ${escapeHtml(t('Apply'))}
                    </button>
                </form>
            </div>
        `;
    }).join('');
}

// =============================================================================
// CSS ANIMATIONS (added via JS for dynamic elements)
// =============================================================================

const styleSheet = document.createElement('style');
styleSheet.textContent = `
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    
    @keyframes fadeUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .animate-fade-up {
        animation: fadeUp 0.5s ease forwards;
        opacity: 0;
    }
    
    .animate-in {
        animation: fadeUp 0.5s ease forwards;
    }
    
    .tooltip {
        position: fixed;
        background: var(--bg-lighter, #212b38);
        color: var(--text-primary, #e8eaed);
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 0.85rem;
        z-index: 10001;
        opacity: 0;
        transform: translateY(4px);
        transition: all 0.2s ease;
        pointer-events: none;
        border: 1px solid var(--card-border, #2a3542);
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.5);
    }
    
    .tooltip.active {
        opacity: 1;
        transform: translateY(0);
    }
    
    .notification-container {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 10002;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    
    .notification {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        background: var(--card-bg, #141a23);
        border: 1px solid var(--card-border, #2a3542);
        border-radius: 8px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.5);
        opacity: 0;
        transform: translateX(100%);
        transition: all 0.3s ease;
        min-width: 280px;
    }
    
    .notification.active {
        opacity: 1;
        transform: translateX(0);
    }
    
    .notification-success {
        border-color: #00e676;
        background: linear-gradient(90deg, rgba(0, 230, 118, 0.1) 0%, var(--card-bg, #141a23) 100%);
    }
    
    .notification-success .notification-icon {
        color: #00e676;
    }
    
    .notification-error {
        border-color: #ff5252;
        background: linear-gradient(90deg, rgba(255, 82, 82, 0.1) 0%, var(--card-bg, #141a23) 100%);
    }
    
    .notification-error .notification-icon {
        color: #ff5252;
    }
    
    .notification-warning {
        border-color: #ffab00;
        background: linear-gradient(90deg, rgba(255, 171, 0, 0.1) 0%, var(--card-bg, #141a23) 100%);
    }
    
    .notification-warning .notification-icon {
        color: #ffab00;
    }
    
    .notification-info {
        border-color: #4cc9f0;
        background: linear-gradient(90deg, rgba(76, 201, 240, 0.1) 0%, var(--card-bg, #141a23) 100%);
    }
    
    .notification-info .notification-icon {
        color: #4cc9f0;
    }
    
    .notification-icon {
        font-size: 1.2rem;
        font-weight: bold;
    }
    
    .notification-message {
        flex: 1;
        color: var(--text-primary, #e8eaed);
    }
    
    .notification-close {
        background: none;
        border: none;
        color: var(--text-muted, #5f6368);
        cursor: pointer;
        font-size: 1.2rem;
        padding: 0;
        line-height: 1;
    }
    
    .notification-close:hover {
        color: var(--text-primary, #e8eaed);
    }
`;
document.head.appendChild(styleSheet);

// =============================================================================
// KEYBOARD SHORTCUTS SYSTEM
// =============================================================================

const KeyboardShortcuts = {
    enabled: true,
    pendingKey: null,
    pendingTimeout: null,
    
    shortcuts: {
        // Navigation shortcuts (g + key)
        'g d': { action: () => window.location.href = '/dashboard', description: 'Go to Dashboard', category: 'Navigation' },
        'g s': { action: () => window.location.href = '/systems', description: 'Go to Systems', category: 'Navigation' },
        'g l': { action: () => window.location.href = '/games', description: 'Go to Library', category: 'Navigation' },
        'g a': { action: () => window.location.href = '/analytics', description: 'Go to Analytics', category: 'Navigation' },
        'g t': { action: () => window.location.href = '/settings', description: 'Go to Settings', category: 'Navigation' },
        'g h': { action: () => window.location.href = '/help', description: 'Go to Help', category: 'Navigation' },
        'g c': { action: () => window.location.href = '/changelog', description: 'Go to Changelog', category: 'Navigation' },

        // Single key shortcuts
        '/': { action: () => focusSearch(), description: 'Focus search box', category: 'Actions' },
        '?': { action: () => showShortcutsModal(), description: 'Show keyboard shortcuts', category: 'Actions' },
        'Escape': { action: () => closeAnyModal(), description: 'Close modal / cancel', category: 'Actions' },
    },

    // Game page shortcuts (only active on game detail pages)
    gameShortcuts: {
        'e': { action: () => { if (typeof openEditModal === 'function') openEditModal(); }, description: 'Edit game', category: 'Game Page' },
        's': { action: () => { if (typeof openScrapeModal === 'function') openScrapeModal(); }, description: 'Scrape game', category: 'Game Page' },
    },
    
    init() {
        document.addEventListener('keydown', (e) => this.handleKeydown(e));
        // Keyboard shortcuts ready
    },
    
    handleKeydown(e) {
        // Ignore if typing in an input field
        if (this.isTyping(e)) return;
        
        // Ignore if disabled
        if (!this.enabled) return;
        
        const key = e.key;
        
        // Handle Escape specially - always works
        if (key === 'Escape') {
            closeAnyModal();
            return;
        }
        
        // Handle pending key (for two-key shortcuts like g+d)
        if (this.pendingKey) {
            const combo = `${this.pendingKey} ${key}`;
            if (this.shortcuts[combo]) {
                e.preventDefault();
                this.shortcuts[combo].action();
            }
            this.clearPending();
            return;
        }
        
        // Check for first key of two-key combo
        if (key === 'g') {
            e.preventDefault();
            this.pendingKey = 'g';
            this.showPendingIndicator('g + ...');
            this.pendingTimeout = setTimeout(() => this.clearPending(), 1500);
            return;
        }
        
        // Check single key shortcuts
        if (this.shortcuts[key]) {
            e.preventDefault();
            this.shortcuts[key].action();
            return;
        }
        
        // Check game page shortcuts
        if (window.location.pathname.includes('/game/')) {
            if (this.gameShortcuts[key]) {
                e.preventDefault();
                this.gameShortcuts[key].action();
                return;
            }
        }
    },
    
    isTyping(e) {
        const target = e.target;
        const tagName = target.tagName.toLowerCase();
        return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
    },
    
    clearPending() {
        this.pendingKey = null;
        if (this.pendingTimeout) {
            clearTimeout(this.pendingTimeout);
            this.pendingTimeout = null;
        }
        this.hidePendingIndicator();
    },
    
    showPendingIndicator(text) {
        let indicator = document.getElementById('shortcut-pending');
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.id = 'shortcut-pending';
            indicator.style.cssText = `
                position: fixed;
                bottom: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: var(--card-bg, #141a23);
                border: 1px solid var(--primary-cyan, #4cc9f0);
                border-radius: 8px;
                padding: 8px 16px;
                color: var(--primary-cyan, #4cc9f0);
                font-family: var(--font-mono, monospace);
                font-size: 14px;
                z-index: 10001;
                box-shadow: 0 0 20px rgba(76, 201, 240, 0.3);
            `;
            document.body.appendChild(indicator);
        }
        indicator.textContent = text;
        indicator.style.display = 'block';
    },
    
    hidePendingIndicator() {
        const indicator = document.getElementById('shortcut-pending');
        if (indicator) indicator.style.display = 'none';
    }
};

function focusSearch() {
    // Try various search input IDs
    const searchIds = ['gameSearch', 'systemSearch', 'globalSearch', 'searchInput'];
    for (const id of searchIds) {
        const input = document.getElementById(id);
        if (input) {
            input.focus();
            input.select();
            return;
        }
    }
    // Try by class
    const searchInput = document.querySelector('.search-input, input[type="search"]');
    if (searchInput) {
        searchInput.focus();
        searchInput.select();
    }
}

function closeAnyModal() {
    // Close screenshot modal if active (resets body overflow and state tracking)
    if (RetroDBState.currentModal) {
        closeScreenshotModal();
    }
    // Close various modal types
    document.querySelectorAll('.modal.active, .modal-overlay.active, .custom-modal.active').forEach(modal => {
        modal.classList.remove('active');
    });
    // Try closeModal function if exists
    if (typeof closeModal === 'function') {
        try { closeModal(); } catch (e) {}
    }
}

// Friendly labels for keys that don't render well as a single character.
const _SHORTCUT_KEY_LABELS = {
    'Escape': 'Esc',
    'ArrowLeft': '←',
    'ArrowRight': '→',
    'ArrowUp': '↑',
    'ArrowDown': '↓',
};

function _renderShortcutKeys(combo) {
    // "g d" → "<kbd>g</kbd> <kbd>d</kbd>", "Escape" → "<kbd>Esc</kbd>"
    return combo.split(' ').map(k => {
        const label = _SHORTCUT_KEY_LABELS[k] || k;
        return `<kbd>${escapeHtml(label)}</kbd>`;
    }).join(' ');
}

function _buildShortcutsBody() {
    // Collect all shortcuts into category-grouped buckets, drawing from the
    // single source of truth (KeyboardShortcuts.shortcuts + .gameShortcuts).
    const buckets = new Map();
    const addEntry = (combo, meta) => {
        const cat = t(meta.category || 'Other');
        if (!buckets.has(cat)) buckets.set(cat, []);
        buckets.get(cat).push({ combo, description: t(meta.description) });
    };
    Object.entries(KeyboardShortcuts.shortcuts).forEach(([k, v]) => addEntry(k, v));
    Object.entries(KeyboardShortcuts.gameShortcuts).forEach(([k, v]) => addEntry(k, v));

    const sections = [];
    for (const [category, entries] of buckets) {
        const rows = entries.map(e =>
            `<div class="shortcut-row">${_renderShortcutKeys(e.combo)} <span>${escapeHtml(e.description)}</span></div>`
        ).join('');
        sections.push(
            `<div style="margin-bottom: 1.5rem;">
                <h4 style="color: var(--primary-cyan); margin-bottom: 0.75rem; font-size: 0.9rem;">${escapeHtml(category.toUpperCase())}</h4>
                <div class="shortcut-list">${rows}</div>
            </div>`
        );
    }
    return sections.join('');
}

function showShortcutsModal() {
    let modal = document.getElementById('shortcuts-modal');
    const body = _buildShortcutsBody();
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'shortcuts-modal';
        modal.className = 'custom-modal';
        modal.innerHTML = `
            <div class="custom-modal-content" style="max-width: 600px;" role="dialog" aria-modal="true" aria-labelledby="shortcutsModalTitle">
                <div class="custom-modal-header">
                    <h3 id="shortcutsModalTitle">⌨️ ${escapeHtml(t('Keyboard Shortcuts'))}</h3>
                    <button class="custom-modal-close" onclick="closeShortcutsModal()" aria-label="${escapeHtml(t('Close keyboard shortcuts'))}">×</button>
                </div>
                <div class="custom-modal-body" id="shortcutsModalBody">${body}</div>
            </div>
        `;
        modal.onclick = (e) => { if (e.target === modal) closeShortcutsModal(); };
        document.body.appendChild(modal);

        // Add styles for shortcuts modal
        const style = document.createElement('style');
        style.textContent = `
            .shortcut-list { display: flex; flex-direction: column; gap: 8px; }
            .shortcut-row { display: flex; align-items: center; gap: 8px; }
            .shortcut-row kbd {
                display: inline-block;
                min-width: 24px;
                padding: 4px 8px;
                background: var(--bg-lighter, #212b38);
                border: 1px solid var(--card-border, #2a3542);
                border-radius: 4px;
                font-family: var(--font-mono, monospace);
                font-size: 0.85rem;
                color: var(--primary-cyan, #4cc9f0);
                text-align: center;
            }
            .shortcut-row span { color: var(--text-secondary, #9aa0a6); margin-left: 8px; }
        `;
        document.head.appendChild(style);
    } else {
        // Refresh — shortcuts object may have been extended since last open.
        document.getElementById('shortcutsModalBody').innerHTML = body;
    }
    modal.classList.add('active');
    if (window.ModalFocusTrap) {
        ModalFocusTrap.activate(modal.querySelector('.custom-modal-content'),
                                document.activeElement,
                                { onEscape: closeShortcutsModal });
    }
}

function closeShortcutsModal() {
    const modal = document.getElementById('shortcuts-modal');
    if (modal) modal.classList.remove('active');
    if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
}

// Initialize keyboard shortcuts
document.addEventListener('DOMContentLoaded', () => KeyboardShortcuts.init());

// =============================================================================
// RECENTLY VIEWED TRACKING
// =============================================================================

function trackGameView(gameId) {
    if (!gameId) return;
    API.post(`/api/game/${gameId}/track-view`)
        .catch(e => console.warn('View tracking failed:', e));
}

// Auto-track if on a game page
document.addEventListener('DOMContentLoaded', () => {
    const match = window.location.pathname.match(/\/game\/(\d+)/);
    if (match) {
        trackGameView(match[1]);
    }
});

// =============================================================================
// COMPLETION STATUS HANDLING
// =============================================================================

function updateCompletionStatus(gameId, status) {
    API.post(`/api/game/${gameId}/completion`, { status: status })
        .then(data => {
            if (data.success) {
                showNotification(t('Completion status updated'), 'success');
            } else {
            showNotification(t('Failed to update status: {error}', {error: data.error}), 'error');
        }
    })
    .catch(e => showNotification(t('Error updating status'), 'error'));
}

// =============================================================================
// REGISTER WITH RETRODB NAMESPACE
// =============================================================================

RetroDB.scanLibrary = scanLibrary;
RetroDB.restartServer = restartServer;
RetroDB.shutdownServer = shutdownServer;
RetroDB.cleanMissingRoms = cleanMissingRoms;
RetroDB.clearClzImports = clearClzImports;
RetroDB.refreshRetroAchievements = refreshRetroAchievements;
RetroDB.cancelRARefresh = cancelRARefresh;
RetroDB.clearRAData = clearRAData;
RetroDB.confirmReset = confirmReset;
RetroDB.openModal = openModal;
RetroDB.closeScreenshotModal = closeScreenshotModal;
RetroDB.filterSystems = filterSystems;
RetroDB.filterGames = filterGames;
RetroDB.sortItems = sortItems;
RetroDB.KeyboardShortcuts = KeyboardShortcuts;
RetroDB.updateCompletionStatus = updateCompletionStatus;
RetroDB.trackGameView = trackGameView;
RetroDB.showShortcutsModal = showShortcutsModal;
RetroDB.closeShortcutsModal = closeShortcutsModal;

// =============================================================================
// EXPORT FOR GLOBAL ACCESS (backward compatibility)
// =============================================================================

window.scanLibrary = scanLibrary;
window.restartServer = restartServer;
window.shutdownServer = shutdownServer;
window.cleanMissingRoms = cleanMissingRoms;
window.clearClzImports = clearClzImports;
window.refreshRetroAchievements = refreshRetroAchievements;
window.cancelRARefresh = cancelRARefresh;
window.clearRAData = clearRAData;
window.confirmReset = confirmReset;
window.openModal = openModal;
window.closeScreenshotModal = closeScreenshotModal;
window.filterSystems = filterSystems;
window.filterGames = filterGames;
window.sortItems = sortItems;
window.KeyboardShortcuts = KeyboardShortcuts;
window.updateCompletionStatus = updateCompletionStatus;
window.trackGameView = trackGameView;
window.showShortcutsModal = showShortcutsModal;
window.closeShortcutsModal = closeShortcutsModal;

// =============================================================================
// CLEANUP ON PAGE UNLOAD
// =============================================================================

window.addEventListener('beforeunload', function() {
    if (_animationObserver) { _animationObserver.disconnect(); _animationObserver = null; }
    if (_backToTopScrollHandler) { window.removeEventListener('scroll', _backToTopScrollHandler); _backToTopScrollHandler = null; }
    if (window.BackToTopController && BackToTopController.destroy) BackToTopController.destroy();
});


// =============================================================================
// PASS 45.16 — aria-current="page" auto-sync for tab-style navs
// =============================================================================
// WCAG 2.4.3 (Focus Order) requires aria-current on the link representing the
// current location/view. The sidebar already gets this via the `nav_active`
// macro in base.html (Pass 41.13.A). Tab/subnav components that toggle .active
// from JS need a separate pin: every container marked `data-tabbar` gets a
// MutationObserver that mirrors `.active` ↔ `aria-current="page"` on its
// descendant <a> / <button> elements.
//
// Why a MutationObserver instead of refactoring every toggle site: the existing
// JS lives in 11+ templates and 2 bundled JS files. Touching all of them risks
// regressions; observing the class change makes the contract a one-time wiring.
// =============================================================================

function _syncAriaCurrent(container) {
    const items = container.querySelectorAll('a, button');
    items.forEach(item => {
        if (item.classList.contains('active')) {
            item.setAttribute('aria-current', 'page');
        } else if (item.hasAttribute('aria-current')) {
            item.removeAttribute('aria-current');
        }
    });
}

const _ariaCurrentObservers = [];

function _setupTabbarAriaCurrent() {
    // Tear down any previous observers (defensive — DOMContentLoaded should
    // only fire once but page-lifecycle teardown could re-bind).
    _ariaCurrentObservers.forEach(o => o.disconnect());
    _ariaCurrentObservers.length = 0;

    document.querySelectorAll('[data-tabbar]').forEach(bar => {
        _syncAriaCurrent(bar);
        const obs = new MutationObserver(mutations => {
            for (const m of mutations) {
                if (m.attributeName === 'class') {
                    _syncAriaCurrent(bar);
                    return;
                }
            }
        });
        obs.observe(bar, {
            subtree: true,
            attributes: true,
            attributeFilter: ['class'],
        });
        _ariaCurrentObservers.push(obs);
    });
}

document.addEventListener('DOMContentLoaded', _setupTabbarAriaCurrent);

window.addEventListener('beforeunload', function() {
    _ariaCurrentObservers.forEach(o => o.disconnect());
    _ariaCurrentObservers.length = 0;
});


// =============================================================================
// PASS 45.17 — auto-attach ModalFocusTrap to opt-in modals
// =============================================================================
// WCAG 2.1.2 (No Keyboard Trap, inverted — i.e. focus must be trapped inside
// modals so Tab doesn't escape to the page underneath). The pre-Pass-45.17
// audit found ~20 dialogs missing the focus trap. Threading the trap through
// every open path is brittle (each modal has its own open function in its own
// JS file); this auto-attach pattern lets a template opt in by adding
// `data-focus-trap` to the modal root, with the trap mounted by a
// MutationObserver that watches the `.active` class.
//
// Modals that already wire ModalFocusTrap.activate() manually (e.g.
// gameDetailModal, gameEditModal, customModal, queueManagerModal,
// folderBrowserModal, filter modal, bulk-edit/scrape modals, museum
// lightboxes) are left alone — adding `data-focus-trap` to them would
// double-attach. The opt-in attribute is the contract.
// =============================================================================

function _setupAutoFocusTraps() {
    if (!window.ModalFocusTrap) return;
    document.querySelectorAll('[data-focus-trap]').forEach(modalEl => {
        const onEscapeFn = modalEl.getAttribute('data-focus-trap-onescape');
        let onEscape = null;
        if (onEscapeFn && typeof window[onEscapeFn] === 'function') {
            onEscape = window[onEscapeFn];
        }
        const contentSelector = modalEl.getAttribute('data-focus-trap-content') || null;
        ModalFocusTrap.autoAttach(modalEl, {
            onEscape: onEscape,
            contentSelector: contentSelector,
        });
    });
}

document.addEventListener('DOMContentLoaded', _setupAutoFocusTraps);
