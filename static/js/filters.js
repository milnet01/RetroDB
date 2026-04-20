/**
 * RetroDB Filtering & Sorting Module
 * Shared filtering functionality for games lists
 * Version: 2.0.0
 *
 * Features:
 * - AlphabetNav: A-Z quick navigation (used by achievements, trophies, etc.)
 *
 * Note: FilterController, SortController, and BulkSelectionController were
 * removed in v2.0.0 — they were unused dead code superseded by
 * AllGamesController (all-games-controller.js) for game list pages.
 */

window.RetroDB = window.RetroDB || {};

// =============================================================================
// ALPHABET NAVIGATION
// =============================================================================

const AlphabetNav = {
    /**
     * Initialize alphabet navigation
     * Scans DOM items to build a letter map and wires up A-Z buttons.
     * @param {Object} config - Configuration options
     * @param {string} config.itemSelector - CSS selector for items (default: '.game-card-wrapper')
     */
    init(config = {}) {
        const nav = document.getElementById('alphabetNav');
        if (!nav) return;

        const buttons = nav.querySelectorAll('.alphabet-btn');
        const itemSelector = config.itemSelector || '.game-card-wrapper';
        const items = document.querySelectorAll(itemSelector);

        // Build letter map
        const letterMap = new Map();
        items.forEach(item => {
            const title = (item.dataset.sortTitle || item.dataset.title || item.dataset.name || '').toUpperCase();
            const firstChar = title.charAt(0);
            const letter = /[A-Z]/.test(firstChar) ? firstChar : '#';

            if (!letterMap.has(letter)) {
                letterMap.set(letter, item);
            }
        });

        // Update button states
        buttons.forEach(btn => {
            const letter = btn.dataset.letter;
            if (letterMap.has(letter)) {
                btn.classList.remove('disabled');
                btn.onclick = () => this.scrollToLetter(letterMap.get(letter));
            } else {
                btn.classList.add('disabled');
                btn.onclick = null;
            }
        });
    },

    /**
     * Scroll to first game starting with letter
     * @param {Element} element - Target element
     */
    scrollToLetter(element) {
        if (!element) return;

        // Account for sticky header
        const headerOffset = 150;
        const elementPosition = element.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

        window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
        });

        // Highlight the element briefly
        element.classList.add('highlight-jump');
        setTimeout(() => {
            element.classList.remove('highlight-jump');
        }, 1500);
    }
};

// =============================================================================
// REGISTER WITH RETRODB NAMESPACE
// =============================================================================

RetroDB.AlphabetNav = AlphabetNav;

// =============================================================================
// EXPORT GLOBALS (backward compatibility)
// =============================================================================

window.AlphabetNav = AlphabetNav;
