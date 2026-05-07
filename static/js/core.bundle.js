(function(){
/**
 * RetroDB Shared Utilities Module
 * Common functions used across all pages
 * Version: 1.16.0
 */

window.RetroDB = window.RetroDB || {};

/**
 * Debounce function to limit execution rate
 * @param {Function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {Function} - Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function to limit execution frequency
 * @param {Function} func - Function to throttle
 * @param {number} limit - Minimum time between calls in ms
 * @returns {Function} - Throttled function
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * Format bytes to human readable string
 * @param {number} bytes - Size in bytes
 * @param {number} decimals - Decimal places
 * @returns {string} - Formatted string
 */
function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return '0 Bytes';

    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];

    const i = Math.floor(Math.log(bytes) / Math.log(k));

    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

/**
 * Format number with spaces as thousand separators (e.g., 12573 → 12 573)
 * @param {number} num - Number to format
 * @returns {string} - Formatted string
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/**
 * Format a ratio as "X / Y" with proper number formatting
 * @param {number} numerator
 * @param {number} denominator
 * @returns {string} - Formatted ratio string
 */
function formatRatio(numerator, denominator) {
    return `${formatNumber(numerator)} / ${formatNumber(denominator)}`;
}

/**
 * Escape HTML entities
 * @param {string} text - Text to escape
 * @returns {string} - Escaped text
 */
function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

/**
 * Pass 29.4 — safely parse a localStorage value as JSON.
 *
 * A corrupted or tampered value (bad quotes, truncated string, attacker-
 * modified content) previously threw in JSON.parse and bubbled to the page
 * load, breaking the whole script. This helper returns the fallback value
 * in that case and removes the poison entry so the page recovers on next
 * reload.
 *
 * @param {string} key - localStorage key
 * @param {*} fallback - Value to return when parse fails or key is missing
 * @returns {*} parsed value, or `fallback` on any failure
 */
function safeParseJSON(key, fallback, storage) {
    const store = storage || localStorage;
    let raw;
    try {
        raw = store.getItem(key);
    } catch (e) {
        return fallback;
    }
    if (raw === null || raw === undefined) return fallback;
    try {
        return JSON.parse(raw);
    } catch (e) {
        console.warn(`safeParseJSON: could not parse ${key}, removing poison entry`, e);
        try { store.removeItem(key); } catch (_) { /* ignore */ }
        return fallback;
    }
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @returns {Promise<boolean>} - Success status
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (err) {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand('copy');
            document.body.removeChild(textArea);
            return true;
        } catch (e) {
            document.body.removeChild(textArea);
            return false;
        }
    }
}

const Storage = {
    /**
     * Get item from localStorage with optional default
     * @param {string} key - Storage key
     * @param {*} defaultValue - Default if not found
     * @returns {*} - Stored value or default
     */
    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            if (item === null) return defaultValue;
            return JSON.parse(item);
        } catch (e) {
            console.warn(`Error reading localStorage key "${key}":`, e);
            return defaultValue;
        }
    },

    /**
     * Set item in localStorage
     * @param {string} key - Storage key
     * @param {*} value - Value to store
     * @returns {boolean} - Success status
     */
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.warn(`Error writing localStorage key "${key}":`, e);
            return false;
        }
    },

    /**
     * Remove item from localStorage
     * @param {string} key - Storage key
     */
    remove(key) {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.warn(`Error removing localStorage key "${key}":`, e);
        }
    },

    /**
     * Clear all RetroDB localStorage items.
     *
     * Pass 36.9 — prior prefix list was `retrodb/bulkScrape/sidebar` only,
     * so Storage.clearAll() lied — it left behind the RetroAchievements
     * operations queue, toast completion flags, and the legacy
     * raSyncQueue. Settings → "Clear local storage" is a support
     * diagnostic; skipping half the keys makes bug reports harder. Keep
     * this list in sync with every key pattern introduced below.
     */
    clearAll() {
        const PREFIXES = [
            'retrodb',
            'bulkScrape',
            'sidebar',
            'raOperationsQueue',
            'raSyncQueue',
            'toast_completion_',
        ];
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (!key) continue;
            for (const prefix of PREFIXES) {
                if (key.startsWith(prefix)) {
                    keysToRemove.push(key);
                    break;
                }
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));
    }
};

const _API_DEFAULT_TIMEOUT_MS = 30000;

function _withTimeout(opts) {
    if (opts && opts.signal) {
        return { opts, cleanup: null };  // caller controls cancellation
    }
    const ac = new AbortController();
    const t = setTimeout(() => ac.abort(), _API_DEFAULT_TIMEOUT_MS);
    return {
        opts: Object.assign({}, opts, { signal: ac.signal }),
        cleanup: () => clearTimeout(t),
    };
}

const API = {
    /**
     * Make a GET request
     * @param {string} url - API endpoint
     * @param {Object} options - Fetch options (pass `signal` to opt out of default 30s timeout)
     * @returns {Promise<Object>} - Response data
     */
    async get(url, options = {}) {
        const { opts, cleanup } = _withTimeout(options);
        try {
            const response = await fetch(url, {
                method: 'GET',
                ...opts
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API GET error:', error);
            throw error;
        } finally {
            if (cleanup) cleanup();
        }
    },

    /**
     * Make a POST request
     * @param {string} url - API endpoint
     * @param {Object} data - Request body
     * @param {Object} options - Fetch options (pass `signal` to opt out of default 30s timeout)
     * @returns {Promise<Object>} - Response data
     */
    async post(url, data = {}, options = {}) {
        const { opts, cleanup } = _withTimeout(options);
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...opts.headers
                },
                body: JSON.stringify(data),
                ...opts
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API POST error:', error);
            throw error;
        } finally {
            if (cleanup) cleanup();
        }
    },

    /**
     * Make a POST request with FormData
     * @param {string} url - API endpoint
     * @param {FormData} formData - Form data
     * @returns {Promise<Object>} - Response data
     */
    async postForm(url, formData) {
        const { opts, cleanup } = _withTimeout({});
        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData,
                signal: opts.signal,
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API POST form error:', error);
            throw error;
        } finally {
            if (cleanup) cleanup();
        }
    }
};

const Notifications = {
    container: null,        // polite (success/info/warning)
    assertiveContainer: null,  // Pass 36.10 — errors announced immediately

    timeouts: {
        success: 3,
        info: 3,
        warning: 5,
        error: 8
    },

    /**
     * Initialize notification containers and load settings.
     *
     * Pass 36.10 — WCAG 4.1.3 Status Messages: warning/info/success should
     * be announced at idle (`aria-live="polite"`), but errors and
     * critical alerts need `aria-live="assertive"` so a screen-reader
     * user hears them mid-utterance. One container can't carry both
     * severities — split into two regions and route by notification type.
     */
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'notification-container';
            this.container.className = 'notification-container';
            this.container.setAttribute('role', 'status');
            this.container.setAttribute('aria-live', 'polite');
            this.container.setAttribute('aria-atomic', 'false');
            document.body.appendChild(this.container);
        }
        if (!this.assertiveContainer) {
            this.assertiveContainer = document.createElement('div');
            this.assertiveContainer.id = 'notification-container-assertive';
            this.assertiveContainer.className = 'notification-container';
            this.assertiveContainer.setAttribute('role', 'alert');
            this.assertiveContainer.setAttribute('aria-live', 'assertive');
            this.assertiveContainer.setAttribute('aria-atomic', 'false');
            document.body.appendChild(this.assertiveContainer);
        }
        if (window.NOTIFICATION_TIMEOUTS) {
            this.timeouts = { ...this.timeouts, ...window.NOTIFICATION_TIMEOUTS };
        }
    },

    _containerFor(type) {
        return type === 'error' ? this.assertiveContainer : this.container;
    },

    /**
     * Get duration for a notification type
     * @param {string} type - Notification type
     * @param {number} customDuration - Custom duration (if provided)
     * @returns {number} Duration in ms
     */
    getDuration(type, customDuration) {
        if (customDuration !== undefined) {
            return customDuration;
        }
        const timeoutSeconds = this.timeouts[type] || this.timeouts.info || 3;
        return timeoutSeconds * 1000;
    },

    /**
     * Show a notification
     * @param {string} message - Notification message
     * @param {string} type - Type (success, error, warning, info)
     * @param {number} duration - Duration in ms (optional, uses settings if not provided)
     */
    show(message, type = 'info', duration) {
        this.init();

        const actualDuration = this.getDuration(type, duration);

        const container = this._containerFor(type);

        const MAX_NOTIFICATIONS = 8;
        const existing = container.querySelectorAll('.notification');
        if (existing.length >= MAX_NOTIFICATIONS) {
            for (let i = 0; i <= existing.length - MAX_NOTIFICATIONS; i++) {
                existing[i].remove();
            }
        }

        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;

        const fallbackIcons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
        const icon = typeof getThemedIcon === 'function'
            ? getThemedIcon(type, fallbackIcons[type])
            : (fallbackIcons[type] || fallbackIcons.info);

        notification.innerHTML = `
            <span class="notification-icon">${icon}</span>
            <span class="notification-message">${escapeHtml(message)}</span>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;

        container.appendChild(notification);

        requestAnimationFrame(() => {
            notification.classList.add('show');
        });

        if (actualDuration > 0) {
            setTimeout(() => {
                notification.classList.remove('show');
                setTimeout(() => notification.remove(), 300);
            }, actualDuration);
        }

        return notification;
    },

    success(message, duration) {
        return this.show(message, 'success', duration);
    },

    error(message, duration) {
        return this.show(message, 'error', duration);
    },

    warning(message, duration) {
        return this.show(message, 'warning', duration);
    },

    info(message, duration) {
        return this.show(message, 'info', duration);
    }
};

function showNotification(message, type = 'info', duration) {
    return Notifications.show(message, type, duration);
}

const LoadingState = {
    /**
     * Show loading overlay
     * @param {string} message - Loading message
     * @returns {HTMLElement} - Loading element
     */
    show(message = 'Loading...') {
        let overlay = document.getElementById('loading-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'loading-overlay';
            overlay.className = 'loading-overlay';
            overlay.setAttribute('role', 'status');
            overlay.setAttribute('aria-live', 'polite');
            overlay.setAttribute('aria-busy', 'true');
            overlay.innerHTML = `
                <div class="loading-content">
                    <div class="loading-spinner"></div>
                    <span class="loading-text">${escapeHtml(message)}</span>
                </div>
            `;
            document.body.appendChild(overlay);
        } else {
            overlay.querySelector('.loading-text').textContent = message;
        }
        overlay.classList.add('active');
        return overlay;
    },

    /**
     * Hide loading overlay
     */
    hide() {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
    },

    /**
     * Update loading message
     * @param {string} message - New message
     */
    update(message) {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.querySelector('.loading-text').textContent = message;
        }
    }
};

function _buildElement(tag, attrs) {
    const el = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
        if (key === 'className') {
            el.className = value;
        } else if (key === 'dataset') {
            Object.entries(value).forEach(([k, v]) => { el.dataset[k] = v; });
        } else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.slice(2).toLowerCase(), value);
        } else {
            el.setAttribute(key, value);
        }
    });
    return el;
}

const DOM = {
    /**
     * Query selector shorthand
     * @param {string} selector - CSS selector
     * @param {Element} context - Parent element
     * @returns {Element|null}
     */
    $(selector, context = document) {
        return context.querySelector(selector);
    },

    /**
     * Query selector all shorthand
     * @param {string} selector - CSS selector
     * @param {Element} context - Parent element
     * @returns {NodeList}
     */
    $$(selector, context = document) {
        return context.querySelectorAll(selector);
    },

    /**
     * Create element with attributes. String `content` is assigned as
     * `textContent` (safe) — call `DOM.createHTML(tag, attrs, html)` for
     * explicit innerHTML when the caller has already sanitized the string.
     *
     * Pass 36.7 — the old form treated string content as innerHTML, giving
     * every future caller an easy XSS footgun baked into the API.
     *
     * @param {string} tag - Tag name
     * @param {Object} attrs - Attributes
     * @param {string|Element|Element[]} content - Inner content (text for strings)
     * @returns {Element}
     */
    create(tag, attrs = {}, content = '') {
        const el = _buildElement(tag, attrs);
        if (content !== null && content !== undefined && content !== '') {
            if (typeof content === 'string') {
                el.textContent = content;
            } else if (Array.isArray(content)) {
                content.forEach((c) => el.appendChild(c));
            } else {
                el.appendChild(content);
            }
        }
        return el;
    },

    /**
     * Create element and assign pre-sanitized HTML to innerHTML. Use only
     * when the caller has escaped every user-controlled interpolation.
     *
     * @param {string} tag - Tag name
     * @param {Object} attrs - Attributes
     * @param {string} html - Pre-escaped inner HTML
     * @returns {Element}
     */
    createHTML(tag, attrs = {}, html = '') {
        const el = _buildElement(tag, attrs);
        if (html) el.innerHTML = html;
        return el;
    },

    /**
     * Toggle element visibility
     * @param {Element|string} el - Element or selector
     * @param {boolean} show - Show or hide
     */
    toggle(el, show) {
        const element = typeof el === 'string' ? document.querySelector(el) : el;
        if (element) {
            element.style.display = show ? '' : 'none';
        }
    },

    /**
     * Add event listener with delegation
     * @param {Element} parent - Parent element
     * @param {string} event - Event type
     * @param {string} selector - Child selector
     * @param {Function} handler - Event handler
     */
    delegate(parent, event, selector, handler) {
        parent.addEventListener(event, function(e) {
            const target = e.target.closest(selector);
            if (target && parent.contains(target)) {
                handler.call(target, e, target);
            }
        });
    }
};

const DateUtils = {
    _tz: 'UTC',

    /**
     * Set the user's timezone for all formatting methods
     * @param {string} tz - IANA timezone name (e.g., 'America/New_York')
     */
    setTimezone(tz) {
        this._tz = tz || 'UTC';
    },

    /**
     * Format date to YYYY-MM-DD in user's timezone
     * @param {Date|string} date - Date to format
     * @returns {string}
     */
    formatDate(date) {
        const d = new Date(date);
        if (isNaN(d)) return '';
        return d.toLocaleDateString('sv-SE', { timeZone: this._tz });
    },

    /**
     * Format date to YYYY-MM-DD HH:MM:SS in user's timezone
     * @param {Date|string} date - Date to format
     * @returns {string}
     */
    formatDateTime(date) {
        const d = new Date(date);
        if (isNaN(d)) return '';
        const datePart = d.toLocaleDateString('sv-SE', { timeZone: this._tz });
        const timePart = d.toLocaleTimeString('en-GB', { timeZone: this._tz, hour12: false });
        return `${datePart} ${timePart}`;
    },

    /**
     * Format date to YYYY-MM-DD HH:MM in user's timezone
     * @param {Date|string} date - Date to format
     * @returns {string}
     */
    formatShort(date) {
        const d = new Date(date);
        if (isNaN(d)) return '';
        const datePart = d.toLocaleDateString('sv-SE', { timeZone: this._tz });
        const timePart = d.toLocaleTimeString('en-GB', { timeZone: this._tz, hour12: false, hour: '2-digit', minute: '2-digit' });
        return `${datePart} ${timePart}`;
    },

    /**
     * Format date to readable string in user's timezone
     * @param {Date|string} date - Date to format
     * @returns {string}
     */
    formatReadable(date) {
        const d = new Date(date);
        if (isNaN(d)) return '';
        return d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            timeZone: this._tz
        });
    },

    /**
     * Get relative time (e.g., "2 hours ago")
     * @param {Date|string} date - Date to compare
     * @returns {string}
     */
    relative(date) {
        const d = new Date(date);
        if (isNaN(d)) return '';

        const now = new Date();
        const diff = now - d;
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 30) return this.formatReadable(date);
        if (days > 0) return `${days} day${days > 1 ? 's' : ''} ago`;
        if (hours > 0) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        if (minutes > 0) return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;
        return 'Just now';
    }
};

const StickyScroll = {
    /**
     * Calculate the total height of stacked sticky navigation elements
     * that will be pinned above a given target when scrolled into view.
     * Uses each element's CSS `top` value + offsetHeight to correctly
     * handle overlapping or stacked sticky elements.
     * @param {HTMLElement} [targetEl] - Target element (counts all sticky navs if omitted)
     * @returns {number} Total sticky header height in pixels
     */
    getStickyOffset(targetEl) {
        let maxBottom = 0;

        document.querySelectorAll('[data-sticky-nav]').forEach(nav => {
            if (!nav.offsetHeight) return;

            if (targetEl) {
                const pos = nav.compareDocumentPosition(targetEl);
                if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) return;

                const scopeId = nav.dataset.stickyScope;
                if (scopeId) {
                    const scope = document.getElementById(scopeId);
                    if (scope && !scope.contains(targetEl)) return;
                }
            }

            const stickyTop = parseFloat(getComputedStyle(nav).top) || 0;
            const stuckBottom = stickyTop + nav.offsetHeight;
            maxBottom = Math.max(maxBottom, stuckBottom);
        });

        return maxBottom;
    },

    /**
     * Smooth scroll to a target element, automatically accounting for
     * all stacked sticky navigation headers on the page.
     * @param {string|HTMLElement} target - Element ID string or DOM element
     * @param {number} [padding=20] - Extra pixels of breathing room below sticky headers
     */
    to(target, padding = 20) {
        const el = typeof target === 'string' ? document.getElementById(target) : target;
        if (!el) return;

        const offset = this.getStickyOffset(el);
        const elementTop = el.getBoundingClientRect().top + window.pageYOffset;

        window.scrollTo({
            top: elementTop - offset - padding,
            behavior: 'smooth'
        });
    },

    /**
     * Dynamically set CSS `top` values on all visible [data-sticky-nav]
     * elements so they stack without overlapping.  Processes elements in
     * document order: the first gets top:0, each subsequent one sits
     * directly below the previous.
     * Call on DOMContentLoaded and after tab/panel switches.
     */
    stackPositions() {
        let runningTop = 0;

        document.querySelectorAll('[data-sticky-nav]').forEach(nav => {
            if (!nav.offsetHeight) return;

            nav.style.top = runningTop + 'px';
            runningTop += nav.offsetHeight;
        });
    },

    /**
     * Set scroll-margin-top on all elements targeted by sticky nav anchor
     * links, so native browser anchor navigation (URL hash, back/forward)
     * also respects sticky header heights.
     * Call on DOMContentLoaded and optionally on window resize.
     * @param {number} [padding=20] - Extra pixels of breathing room
     */
    updateMargins(padding = 20) {
        const processed = new Set();

        document.querySelectorAll('[data-sticky-nav] a[href^="#"]').forEach(link => {
            const id = link.getAttribute('href')?.substring(1);
            if (!id || processed.has(id)) return;
            processed.add(id);

            const target = document.getElementById(id);
            if (target) {
                const offset = this.getStickyOffset(target);
                target.style.scrollMarginTop = (offset + padding) + 'px';
            }
        });
    }
};

const _FOCUSABLE_SELECTOR = [
    'a[href]:not([disabled])',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

function _isTypingTarget(target) {
    if (!target || !target.tagName) return false;
    const tag = target.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    if (target.isContentEditable) return true;
    return false;
}

const ModalFocusTrap = {
    _stack: [],  // stack of { modalEl, triggerEl, keyHandler, onEscape }

    /**
     * Activate a focus trap on the given modal element.
     * @param {HTMLElement} modalEl - the dialog root (the visible container)
     * @param {HTMLElement} [triggerEl] - element to restore focus to on close
     * @param {Object} [opts]
     * @param {Function} [opts.onEscape] - called when Escape is pressed (default: noop)
     * @param {Function} [opts.onArrowLeft] - called when ArrowLeft is pressed (Pass 36.8)
     * @param {Function} [opts.onArrowRight] - called when ArrowRight is pressed (Pass 36.8)
     * @param {boolean}  [opts.autoFocus=true] - focus the first focusable on activate
     */
    activate(modalEl, triggerEl, opts = {}) {
        if (!modalEl) return;
        const onEscape = opts.onEscape || null;
        const onArrowLeft = opts.onArrowLeft || null;
        const onArrowRight = opts.onArrowRight || null;
        const autoFocus = opts.autoFocus !== false;

        const keyHandler = (e) => {
            if (e.key === 'Escape' && onEscape) {
                e.preventDefault();
                e.stopPropagation();
                onEscape();
                return;
            }
            if (e.key === 'ArrowLeft' && onArrowLeft && !_isTypingTarget(e.target)) {
                e.preventDefault();
                onArrowLeft();
                return;
            }
            if (e.key === 'ArrowRight' && onArrowRight && !_isTypingTarget(e.target)) {
                e.preventDefault();
                onArrowRight();
                return;
            }
            if (e.key !== 'Tab') return;

            const focusables = Array.from(modalEl.querySelectorAll(_FOCUSABLE_SELECTOR))
                .filter(el => el.offsetParent !== null || el === document.activeElement);
            if (focusables.length === 0) {
                e.preventDefault();
                return;
            }
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            const active = document.activeElement;

            if (e.shiftKey && active === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && active === last) {
                e.preventDefault();
                first.focus();
            } else if (!modalEl.contains(active)) {
                e.preventDefault();
                first.focus();
            }
        };

        document.addEventListener('keydown', keyHandler, true);
        this._stack.push({ modalEl, triggerEl: triggerEl || document.activeElement, keyHandler, onEscape });

        if (autoFocus) {
            requestAnimationFrame(() => {
                const first = modalEl.querySelector(_FOCUSABLE_SELECTOR);
                if (first) first.focus();
                else if (modalEl.hasAttribute('tabindex') === false) {
                    modalEl.setAttribute('tabindex', '-1');
                    modalEl.focus();
                }
            });
        }
    },

    /**
     * Deactivate the top-most focus trap and restore focus to its trigger.
     */
    deactivate() {
        const entry = this._stack.pop();
        if (!entry) return;
        document.removeEventListener('keydown', entry.keyHandler, true);
        if (entry.triggerEl && typeof entry.triggerEl.focus === 'function') {
            try { entry.triggerEl.focus(); } catch (e) { /* element removed from DOM */ }
        }
    },

    /**
     * Deactivate all active focus traps. Call on SPA-style navigation.
     */
    deactivateAll() {
        while (this._stack.length > 0) this.deactivate();
    },

    /**
     * Pass 45.17 — auto-attach the focus trap to a modal whose `.active`
     * class toggles open/closed. Useful for modals where the open/close
     * functions are not in our control (or where threading the trap
     * through every call site would be more error-prone than the
     * MutationObserver). Idempotent: a second autoAttach() on the same
     * element is a no-op.
     *
     * @param {HTMLElement} modalEl - the modal root (the element that
     *     toggles `.active`).
     * @param {Object} [opts]
     * @param {Function} [opts.onEscape] - escape handler.
     * @param {string}   [opts.contentSelector] - CSS selector for the
     *     focus-trap target inside modalEl (defaults to `.modal-content`
     *     or `.custom-modal-content`, falling back to modalEl itself).
     */
    autoAttach(modalEl, opts = {}) {
        if (!modalEl || modalEl._focusTrapObserver) return;
        const onEscape = opts.onEscape || null;
        const contentSelector = opts.contentSelector || null;

        const _resolveTarget = () => {
            if (contentSelector) {
                return modalEl.querySelector(contentSelector) || modalEl;
            }
            return (modalEl.querySelector('.modal-content') ||
                    modalEl.querySelector('.custom-modal-content') ||
                    modalEl);
        };

        const obs = new MutationObserver(mutations => {
            for (const m of mutations) {
                if (m.attributeName !== 'class') continue;
                const isActive = modalEl.classList.contains('active');
                if (isActive && !modalEl._focusTrapActive) {
                    modalEl._focusTrapActive = true;
                    ModalFocusTrap.activate(
                        _resolveTarget(),
                        document.activeElement,
                        { onEscape: onEscape },
                    );
                } else if (!isActive && modalEl._focusTrapActive) {
                    modalEl._focusTrapActive = false;
                    ModalFocusTrap.deactivate();
                }
            }
        });
        obs.observe(modalEl, { attributes: true, attributeFilter: ['class'] });
        modalEl._focusTrapObserver = obs;
    },
};

RetroDB.debounce = debounce;
RetroDB.throttle = throttle;
RetroDB.formatBytes = formatBytes;
RetroDB.formatNumber = formatNumber;
RetroDB.formatRatio = formatRatio;
RetroDB.escapeHtml = escapeHtml;
RetroDB.copyToClipboard = copyToClipboard;
RetroDB.Storage = Storage;
RetroDB.API = API;
RetroDB.Notifications = Notifications;
RetroDB.showNotification = showNotification;
RetroDB.LoadingState = LoadingState;
RetroDB.DOM = DOM;
RetroDB.DateUtils = DateUtils;
RetroDB.StickyScroll = StickyScroll;
RetroDB.ModalFocusTrap = ModalFocusTrap;

window.debounce = debounce;
window.throttle = throttle;
window.formatBytes = formatBytes;
window.formatNumber = formatNumber;
window.formatRatio = formatRatio;
window.escapeHtml = escapeHtml;
window.safeParseJSON = safeParseJSON;
window.copyToClipboard = copyToClipboard;
window.Storage = Storage;
window.API = API;
window.Notifications = Notifications;
window.showNotification = showNotification;
window.LoadingState = LoadingState;
window.DOM = DOM;
window.DateUtils = DateUtils;
window.StickyScroll = StickyScroll;
window.ModalFocusTrap = ModalFocusTrap;

})();

(function(){
/**
 * RetroDB Unified Toast Controller
 * Handles all toast notifications: Bulk Scrape, RA Sync, RA Refresh, PSN Refresh
 * Version: 1.21.0
 *
 * Polling strategy (v1.21.0):
 *   - On page load: one-time burst poll of all endpoints to detect in-progress jobs
 *   - Active jobs: 2s polling until complete
 *   - No idle polling — cross-tab events use BroadcastChannel
 *   - Tab re-focus: burst poll to catch anything missed while hidden
 */

window.RetroDB = window.RetroDB || {};

const ToastTypes = {
    BULK_SCRAPE: {
        id: 'bulk-scrape',
        name: 'Bulk Scrape',
        icon: '⏳',
        activeColor: '#4cc9f0',     // Cyan
        queuedColor: '#3a9fc2',      // Darker cyan
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    RA_SYNC: {
        id: 'ra-sync',
        name: 'RA Sync',
        icon: '🏆',
        activeColor: '#f59e0b',      // Orange
        queuedColor: '#c47d09',      // Darker orange
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    RA_REFRESH: {
        id: 'ra-refresh',
        name: 'RA Refresh',
        icon: '🔄',
        activeColor: '#a855f7',      // Purple
        queuedColor: '#8b46d4',      // Darker purple
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    PSN_REFRESH: {
        id: 'psn-refresh',
        name: 'PSN Refresh',
        icon: '🏆',
        activeColor: '#0070d1',      // PlayStation blue
        queuedColor: '#00439c',      // Darker PS blue
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    },
    IMAGE_RESIZE: {
        id: 'image-resize',
        name: 'Image Resize',
        icon: '🖼️',
        activeColor: '#22c55e',      // Green
        queuedColor: '#16a34a',      // Darker green
        completedColor: '#22c55e',   // Green
        pausedColor: '#f59e0b'       // Orange
    }
};

const ThemeIcons = {
    cyberpunk: {
        'bulk-scrape': '⏳', 'ra-sync': '🏆', 'ra-refresh': '🔄',
        'psn-refresh': '🏆', 'image-resize': '🖼️',
        paused: '⏸️', resume: '▶️', complete: '✅', queued: '📋',
        cancelled: '❌', background: '🔽',
        success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️',
        'stat-success': '✅', 'stat-failed': '❌', 'stat-skipped': '⏭️',
        starting: '⏳', running: '⏳', cancel: '❌', save: '✅',
        loading: '🔄'
    },
    matrix: {
        'bulk-scrape': '⟩⟩', 'ra-sync': '◈', 'ra-refresh': '⟳',
        'psn-refresh': '◈', 'image-resize': '⊞',
        paused: '▮▮', resume: '▶', complete: '✓', queued: '≡',
        cancelled: '✗', background: '▼',
        success: '✓', error: '✗', warning: '▲', info: '◆',
        'stat-success': '✓', 'stat-failed': '✗', 'stat-skipped': '▷',
        starting: '▶', running: '▶', cancel: '✗', save: '✓',
        loading: '⟳'
    },
    amber: {
        'bulk-scrape': '►', 'ra-sync': '★', 'ra-refresh': '↻',
        'psn-refresh': '★', 'image-resize': '▦',
        paused: '‖', resume: '►', complete: '●', queued: '░',
        cancelled: '■', background: '▾',
        success: '●', error: '■', warning: '▲', info: '◦',
        'stat-success': '●', 'stat-failed': '■', 'stat-skipped': '▻',
        starting: '►', running: '►', cancel: '■', save: '●',
        loading: '↻'
    },
    ocean: {
        'bulk-scrape': '≋', 'ra-sync': '⚓', 'ra-refresh': '↺',
        'psn-refresh': '⚓', 'image-resize': '◇',
        paused: '∿', resume: '▶', complete: '◉', queued: '⊕',
        cancelled: '⊘', background: '▿',
        success: '◉', error: '⊘', warning: '◈', info: '◎',
        'stat-success': '◉', 'stat-failed': '⊘', 'stat-skipped': '▹',
        starting: '≋', running: '≋', cancel: '⊘', save: '◉',
        loading: '↺'
    },
    christian: {
        'bulk-scrape': '✦', 'ra-sync': '☩', 'ra-refresh': '❋',
        'psn-refresh': '☩', 'image-resize': '✥',
        paused: '◆', resume: '▶', complete: '✧', queued: '⚜',
        cancelled: '✘', background: '▽',
        success: '✧', error: '✘', warning: '◈', info: '✦',
        'stat-success': '✧', 'stat-failed': '✘', 'stat-skipped': '▸',
        starting: '✦', running: '✦', cancel: '✘', save: '✧',
        loading: '❋'
    },
    bladerunner: {
        'bulk-scrape': '▸▸', 'ra-sync': '◆', 'ra-refresh': '⟲',
        'psn-refresh': '◆', 'image-resize': '⬡',
        paused: '▪▪', resume: '▶', complete: '◉', queued: '▫',
        cancelled: '✕', background: '▾',
        success: '◉', error: '✕', warning: '◈', info: '◇',
        'stat-success': '◉', 'stat-failed': '✕', 'stat-skipped': '▹',
        starting: '▸▸', running: '▸▸', cancel: '✕', save: '◉',
        loading: '⟲'
    },
    elite: {
        'bulk-scrape': '>>>', 'ra-sync': '*', 'ra-refresh': '~',
        'psn-refresh': '*', 'image-resize': '#',
        paused: '||', resume: '>', complete: 'OK', queued: '...',
        cancelled: 'X', background: 'v',
        success: 'OK', error: 'X', warning: '!', info: '>',
        'stat-success': 'OK', 'stat-failed': 'X', 'stat-skipped': '-',
        starting: '>>>', running: '>>>', cancel: 'X', save: 'OK',
        loading: '~'
    }
};

/**
 * Get a themed icon by key.
 * @param {string} key - Icon key (job type, state, or notification type)
 * @param {string} [fallback] - Fallback if key not found
 * @returns {string} Themed icon character(s)
 */
function getThemedIcon(key, fallback) {
    const theme = document.documentElement.getAttribute('data-theme') || 'cyberpunk';
    const icons = ThemeIcons[theme] || ThemeIcons.cyberpunk;
    return icons[key] || fallback || ThemeIcons.cyberpunk[key] || key;
}

const UnifiedToastController = {
    container: null,
    activeToasts: new Map(),  // Map of jobId -> toast element
    pollingIntervals: new Map(),  // Map of type -> interval
    pollingEndpoints: new Map(),  // Map of type -> endpoint URL
    activeOperations: new Map(),  // Map of type -> boolean (is running)
    pollCallbacks: new Map(),     // Map of type -> callback fn (external consumers of poll data)
    _pollAbortControllers: new Map(),  // Map of type -> AbortController (cancel in-flight fetches)
    _initialized: false,          // Guard against duplicate init
    _resizeHandler: null,         // Stored for cleanup
    _visibilityHandler: null,     // Stored for cleanup
    _broadcastChannel: null,      // BroadcastChannel for cross-tab communication
    activePollIntervalMs: 2000,   // 2 seconds when operation is active

    /**
     * Initialize the toast controller
     */
    init() {
        if (this._initialized) return;  // Prevent duplicate initialization
        this._initialized = true;
        this.createContainer();
        this.cleanupOldCompletionKeys();
        this.setupBroadcastChannel();
        this.startPolling();
        this.restoreSavedState();
        this.setupVisibilityHandler();
    },

    /**
     * Clean up old completion tracking keys from localStorage
     * Keeps only keys from the last hour
     */
    cleanupOldCompletionKeys() {
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith('toast_completion_')) {
                const match = key.match(/_(\d{10,})$/);
                if (match) {
                    const timestamp = parseInt(match[1], 10);
                    const hourAgo = Math.floor(Date.now() / 1000) - 3600;
                    if (timestamp < hourAgo) {
                        keysToRemove.push(key);
                    }
                }
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));
    },

    /**
     * Set up BroadcastChannel for cross-tab communication.
     * Messages: job-started, job-completed, job-cancelled
     */
    setupBroadcastChannel() {
        try {
            this._broadcastChannel = new BroadcastChannel('retrodb-jobs');
            this._broadcastChannel.onmessage = (event) => {
                this._handleBroadcast(event.data);
            };
        } catch (e) {
            console.debug('BroadcastChannel not available:', e.message);
        }
    },

    /**
     * Broadcast a job event to all other tabs.
     * @param {string} event - Event type: 'job-started', 'job-completed', 'job-cancelled'
     * @param {string} jobType - Operation type (e.g. 'bulk-scrape', 'ra-sync')
     * @param {Object} [data] - Optional status data to include
     */
    broadcast(event, jobType, data) {
        if (!this._broadcastChannel) return;
        try {
            this._broadcastChannel.postMessage({ event, jobType, data: data || {} });
        } catch (e) {
        }
    },

    /**
     * Handle an incoming broadcast from another tab.
     */
    _handleBroadcast(msg) {
        if (!msg || !msg.event || !msg.jobType) return;
        const { event, jobType, data } = msg;

        switch (event) {
            case 'job-started': {
                this.activeOperations.set(jobType, true);
                const config = this.getTypeConfig(jobType);
                if (config && data && !this.activeToasts.has(`active-${jobType}`)) {
                    this.showActiveToast(jobType, config, data);
                }
                this._startActivePolling(jobType);
                break;
            }
            case 'job-completed': {
                this.activeOperations.set(jobType, false);
                const endpoint = this.pollingEndpoints.get(jobType);
                if (endpoint) {
                    this.pollStatus(jobType, endpoint);
                }
                break;
            }
            case 'job-cancelled': {
                this.activeOperations.set(jobType, false);
                this.hideActiveToast(jobType);
                this._stopTypePolling(jobType);
                break;
            }
        }
    },

    /**
     * Handle tab visibility changes - pause polling when hidden
     */
    setupVisibilityHandler() {
        if (this._visibilityHandlerSet) return;
        this._visibilityHandlerSet = true;
        this._visibilityHandler = () => {
            if (document.hidden) {
                this.stopAllPolling();
            } else {
                this._burstPollAll();
                for (const [type, isActive] of this.activeOperations) {
                    if (isActive && !this.pollingIntervals.has(type)) {
                        this._startActivePolling(type);
                    }
                }
            }
        };
        document.addEventListener('visibilitychange', this._visibilityHandler);
    },

    /**
     * Stop all polling intervals and abort in-flight requests
     */
    stopAllPolling() {
        for (const [type, intervalId] of this.pollingIntervals) {
            clearInterval(intervalId);
        }
        this.pollingIntervals.clear();
        for (const [type, ac] of this._pollAbortControllers) {
            ac.abort();
        }
        this._pollAbortControllers.clear();
    },

    /**
     * Create the unified toast container
     */
    createContainer() {
        const existingContainers = document.querySelectorAll('.unified-toast-container, #unifiedToastContainer');
        if (existingContainers.length > 1) {
            console.warn(`Found ${existingContainers.length} toast containers, cleaning up...`);
            for (let i = 1; i < existingContainers.length; i++) {
                existingContainers[i].remove();
            }
        }

        if (document.getElementById('unifiedToastContainer')) {
            this.container = document.getElementById('unifiedToastContainer');
            this.positionContainer();
            this.positionBackToTop();
            return;
        }

        this.container = document.createElement('div');
        this.container.id = 'unifiedToastContainer';
        this.container.className = 'unified-toast-container';
        document.body.appendChild(this.container);

        this.container.addEventListener('click', (e) => {
            const target = e.target.closest('[data-toast-action]');
            if (!target) return;
            const action = target.dataset.toastAction;
            const type = target.dataset.toastType;
            if (action === 'navigate') {
                this.navigateTo(type, target.dataset.toastReturnUrl || '');
                return;
            }
            e.stopPropagation();
            if (action === 'pause') {
                this.togglePause(type);
            } else if (action === 'cancel') {
                this.cancel(type);
            } else if (action === 'cancel-ra-queued') {
                const raType = target.dataset.raType;
                const raSystemIdRaw = target.dataset.raSystemId;
                const raSystemId = raSystemIdRaw === '' ? null : Number(raSystemIdRaw);
                this.cancelRAQueued(raType, Number.isFinite(raSystemId) ? raSystemId : null);
            }
        });

        this.positionContainer();
        this.positionBackToTop();

        if (!this._containerListenersSet) {
            this._containerListenersSet = true;

            window.addEventListener('load', () => {
                this.positionContainer();
                this.positionBackToTop();
            });

            setTimeout(() => {
                this.positionContainer();
                this.positionBackToTop();
            }, 500);

            let resizeTimer;
            this._resizeHandler = () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => {
                    this.positionContainer();
                    this.positionBackToTop();
                }, 150);
            };
            window.addEventListener('resize', this._resizeHandler, { passive: true });
        }
    },

    /**
     * Position the toast container based on actual content wrapper position.
     * Toast sits to the LEFT of content with a 25px gap between toast right edge and content left edge.
     * Dynamically adjusts toast width to fit the available space.
     */
    positionContainer() {
        const contentWrapper = document.querySelector('.content-wrapper');
        if (!contentWrapper) {
            if (!this._positionRetryCount) this._positionRetryCount = 0;
            if (this._positionRetryCount < 10) {
                this._positionRetryCount++;
                setTimeout(() => this.positionContainer(), 100);
            }
            return;
        }

        if (!this.container) return;

        this._positionRetryCount = 0;

        const contentRect = contentWrapper.getBoundingClientRect();
        const gap = 25;
        const maxToastWidth = 360;
        const minToastWidth = 260;

        const sidebar = document.querySelector('.sidebar');
        const sidebarRight = sidebar ? sidebar.getBoundingClientRect().right : 260;
        const sidebarGap = 10;  // Minimum gap from sidebar
        const minLeft = sidebarRight + sidebarGap;

        const availableSpace = contentRect.left - minLeft - gap;

        let toastWidth = Math.min(maxToastWidth, Math.max(minToastWidth, availableSpace));

        let leftPos = contentRect.left - toastWidth - gap;

        if (leftPos < minLeft) {
            leftPos = minLeft;
            const fitWidth = contentRect.left - leftPos - gap;
            toastWidth = Math.max(minToastWidth, Math.min(maxToastWidth, fitWidth));
        }

        this.container.style.setProperty('left', leftPos + 'px', 'important');
        this.container.style.setProperty('width', toastWidth + 'px', 'important');

        this.container.querySelectorAll('.unified-toast').forEach(t => {
            t.style.width = toastWidth + 'px';
        });

        this._currentToastWidth = toastWidth;
    },

    /**
     * Position the Back to Top button 25px to the right of the content wrapper's right edge.
     * Falls back to right: 20px if it would go off-screen.
     */
    positionBackToTop() {
        const btn = document.getElementById('backToTopBtn');
        if (!btn) return;

        const contentWrapper = document.querySelector('.content-wrapper');
        if (!contentWrapper) return;

        const contentRect = contentWrapper.getBoundingClientRect();
        const gap = 25;
        const btnSize = 50;

        const leftPos = contentRect.right + gap;

        if (leftPos + btnSize > window.innerWidth - 10) {
            btn.style.left = 'auto';
            btn.style.right = '20px';
        } else {
            btn.style.right = 'auto';
            btn.style.left = leftPos + 'px';
        }
    },

    /**
     * Register endpoints and run a one-time burst poll to detect in-progress jobs.
     * No idle polling is started — only active jobs get polled.
     */
    startPolling() {
        this.pollingEndpoints.set('bulk-scrape', '/api/bulk-scrape-job/status');
        this.pollingEndpoints.set('ra-sync', '/api/achievements/sync-status');
        this.pollingEndpoints.set('ra-refresh', '/api/refresh-retroachievements/status');
        this.pollingEndpoints.set('psn-refresh', '/api/psn/bulk-refresh/status');
        this.pollingEndpoints.set('image-resize', '/api/maintenance/image-resize/status');

        this.activeOperations.set('bulk-scrape', false);
        this.activeOperations.set('ra-sync', false);
        this.activeOperations.set('ra-refresh', false);
        this.activeOperations.set('psn-refresh', false);
        this.activeOperations.set('image-resize', false);

        this._burstPollAll();
    },

    /**
     * Burst poll all endpoints once (no recurring interval).
     * If a job is found active, starts active polling for that type.
     */
    _burstPollAll() {
        for (const [type, endpoint] of this.pollingEndpoints) {
            this.pollStatus(type, endpoint);
        }
    },

    /**
     * Start active (2s) polling for a specific type.
     * @param {string} type - Operation type
     */
    _startActivePolling(type) {
        if (this.pollingIntervals.has(type)) {
            clearInterval(this.pollingIntervals.get(type));
        }
        const endpoint = this.pollingEndpoints.get(type);
        if (!endpoint) return;

        const intervalId = setInterval(() => {
            this.pollStatus(type, endpoint);
        }, this.activePollIntervalMs);
        this.pollingIntervals.set(type, intervalId);
    },

    /**
     * Stop polling for a specific type.
     */
    _stopTypePolling(type) {
        const intervalId = this.pollingIntervals.get(type);
        if (intervalId) {
            clearInterval(intervalId);
            this.pollingIntervals.delete(type);
        }
    },

    /**
     * Adjust polling speed for a specific type based on whether it's active.
     * When isActive is true, ensures active (2s) polling is running.
     * When false, stops polling for this type.
     */
    adjustPollingSpeed(type, isActive) {
        this.activeOperations.set(type, isActive);
        if (isActive) {
            this._startActivePolling(type);
        } else {
            this._stopTypePolling(type);
        }
    },

    /**
     * Immediately poll all types so toasts appear without waiting.
     * Polls twice (now + 2s) to handle the race where a just-started job
     * hasn't registered with its status endpoint yet on the first poll.
     */
    pollAllNow() {
        this._burstPollAll();
        setTimeout(() => {
            this._burstPollAll();
        }, 2000);
    },

    /**
     * Register a callback to receive poll data for a type.
     * This makes the toast controller the single poller — the callback
     * receives the same data the toast uses, so both stay perfectly in sync.
     * Also switches to a faster poll rate while a callback is registered.
     */
    registerPollCallback(type, callback) {
        this.pollCallbacks.set(type, callback);
        const endpoint = this.pollingEndpoints.get(type);
        if (endpoint) {
            this._stopTypePolling(type);
            this.pollStatus(type, endpoint);
            this.pollingIntervals.set(type, setInterval(() => {
                this.pollStatus(type, endpoint);
            }, 1500));
        }
    },

    /**
     * Unregister a poll callback and revert to normal polling speed
     */
    unregisterPollCallback(type) {
        this.pollCallbacks.delete(type);
        const isActive = this.activeOperations.get(type) || false;
        if (isActive) {
            this._startActivePolling(type);
        } else {
            this._stopTypePolling(type);
        }
    },

    /**
     * Poll status for a specific type
     */
    async pollStatus(type, endpoint) {
        try {
            const prevAbort = this._pollAbortControllers.get(type);
            if (prevAbort) prevAbort.abort();

            const ac = new AbortController();
            this._pollAbortControllers.set(type, ac);

            const data = await API.get(endpoint, { signal: ac.signal });
            this._pollAbortControllers.delete(type);

            if (data.success === false) return;

            this.updateToasts(type, data);

            const isActive = data.running && !data.completed;
            const wasActive = this.activeOperations.get(type) || false;
            const hasToast = this.activeToasts.has(`active-${type}`);

            if (isActive && (!wasActive || !this.pollingIntervals.has(type))) {
                this._startActivePolling(type);
            } else if (!isActive && wasActive && data.completed) {
                this._stopTypePolling(type);
                this.broadcast('job-completed', type, data);
            } else if (!isActive && wasActive && !data.completed && hasToast) {
                this._stopTypePolling(type);
                const endpoint2 = this.pollingEndpoints.get(type);
                if (endpoint2) {
                    this.pollingIntervals.set(type, setInterval(() => {
                        this.pollStatus(type, endpoint2);
                    }, 5000));
                }
            } else if (!isActive && wasActive) {
                this._stopTypePolling(type);
                this.broadcast('job-completed', type, data);
            } else if (!isActive && !this.pollCallbacks.has(type) && !hasToast) {
                this._stopTypePolling(type);
            }

            const callback = this.pollCallbacks.get(type);
            if (callback) callback(data);

        } catch (e) {
            if (e.name === 'AbortError') return;  // Expected when aborting stale requests
            console.debug(`Toast poll error for ${type}:`, e.message || e);
        }
    },

    /**
     * Update toasts based on status data
     * Creates active toasts if an operation is running but no toast exists (self-healing).
     * Toast removal is handled by completion or explicit cancel.
     */
    updateToasts(type, data) {
        const typeConfig = this.getTypeConfig(type);
        if (!typeConfig) return;

        const isActive = data.running && !data.completed;

        this.activeOperations.set(type, isActive);

        const toastId = `active-${type}`;
        const existingToast = this.activeToasts.get(toastId);

        if (isActive && !existingToast) {
            this.showActiveToast(type, typeConfig, data);
        } else if (existingToast && (isActive || data.completed)) {
            this.updateActiveToastContent(existingToast, type, typeConfig, data);
        }

        if (data.completed && existingToast) {
            this.handleCompletion(type, data);
        }

        if (data.completed && !existingToast) {
            const completionKey = `toast_completion_${type}_${data.job_id || data.start_time || Date.now()}`;
            if (!localStorage.getItem(completionKey)) {
                localStorage.setItem(completionKey, 'true');
                if (data.error) {
                    showNotification(`${typeConfig.name} failed: ${data.error}`, 'error');
                } else if (data.cancelled) {
                    showNotification(`${typeConfig.name} cancelled`, 'warning');
                } else {
                    const total = data.success || data.processed || 0;
                    showNotification(`${typeConfig.name} completed (${total} processed)`, 'success');
                }
            }
        }

        if (type === 'bulk-scrape' && data.queue) {
            this.updateQueuedToasts(type, data.queue);
        }

        if (type === 'ra-sync' && !isActive && !existingToast) {
            const raRefreshToast = this.activeToasts.get('active-ra-refresh');
            if (!raRefreshToast) {
                const queue = safeParseJSON('raOperationsQueue', []);
                if (queue.length > 0 && !this._triggeringRAQueue) {
                    this.triggerNextRAOperationFromQueue();
                }
            }
        }
    },

    /**
     * Trigger the next RA operation from the unified queue
     * Queue can contain both 'sync' and 'refresh' operations
     */
    triggerNextRAOperationFromQueue() {
        const queue = safeParseJSON('raOperationsQueue', []);
        if (queue.length === 0) {
            this._triggeringRAQueue = false;
            return;
        }

        if (this._triggeringRAQueue) return;
        this._triggeringRAQueue = true;

        const syncToast = this.activeToasts.get('active-ra-sync');
        const refreshToast = this.activeToasts.get('active-ra-refresh');
        if (syncToast || refreshToast) {
            console.debug('RA operation already active, not triggering queue');
            this._triggeringRAQueue = false;
            return;
        }

        const next = queue[0];

        if (!next || !next.type) {
            console.error('Invalid queue item:', next);
            const newQueue = queue.slice(1);
            localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
            this._triggeringRAQueue = false;
            return;
        }

        let endpoint;
        if (next.type === 'sync') {
            endpoint = `/api/achievements/sync-system/${next.systemId}`;
        } else if (next.type === 'refresh') {
            endpoint = next.systemId
                ? `/api/refresh-retroachievements/${next.systemId}`
                : '/api/refresh-retroachievements';
        } else {
            console.error('Unknown RA operation type:', next.type);
            const newQueue = queue.slice(1);
            localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));
            this._triggeringRAQueue = false;
            return;
        }

        console.debug(`Triggering queued RA ${next.type} for ${next.systemName}`);

        API.post(endpoint)
            .then(result => {
                if (result.success && !result.queued) {
                    this.removeRAQueuedToast(next);

                    const updatedQueue = safeParseJSON('raOperationsQueue', []);
                    const newQueue = updatedQueue.slice(1); // Remove first item
                    localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));

                    this.updateRAQueuePositions();

                    const initialData = {
                        running: true,
                        completed: false,
                        current_system: next.systemName,
                        current_game: 'Starting...',
                        total: next.gameCount || 0,
                        current: 0,
                        percent: 0,
                        paused: false
                    };

                    if (next.type === 'sync') {
                        this.showActiveToast('ra-sync', ToastTypes.RA_SYNC, initialData);
                        this.adjustPollingSpeed('ra-sync', true);
                        this.broadcast('job-started', 'ra-sync', initialData);
                    } else {
                        this.showActiveToast('ra-refresh', ToastTypes.RA_REFRESH, initialData);
                        this.adjustPollingSpeed('ra-refresh', true);
                        this.broadcast('job-started', 'ra-refresh', initialData);
                    }
                } else if (result.queued) {
                    console.debug(`RA ${next.type} still queued - another operation is running`);
                } else {
                    console.error(`Failed to start queued RA ${next.type}:`, result.error);
                }
            })
            .catch(e => {
                console.error(`Error starting queued RA ${next.type}:`, e);
            })
            .finally(() => {
                setTimeout(() => {
                    this._triggeringRAQueue = false;
                }, 2000);
            });
    },

    triggerNextRASyncFromQueue() {
        this.triggerNextRAOperationFromQueue();
    },

    /**
     * Add an RA operation to the unified queue (sync or refresh)
     */
    addRAOperationToQueue(item) {
        if (!this.container) {
            this.createContainer();
        }

        const toastId = item.type === 'sync'
            ? `queued-ra-sync-${item.systemId}`
            : `queued-ra-refresh-${item.systemId || 'all'}`;

        if (this.activeToasts.has(toastId)) {
            return;
        }

        const queue = safeParseJSON('raOperationsQueue', []);
        const position = queue.findIndex(q =>
            q.type === item.type &&
            (q.systemId || 'all') === (item.systemId || 'all')
        ) + 1;

        const toast = this.createRAQueuedToast(item, position || queue.length);
        this.activeToasts.set(toastId, toast);
        this.container.appendChild(toast);
    },

    addRASyncQueuedToast(item) {
        item.type = 'sync';
        this.addRAOperationToQueue(item);
    },

    /**
     * Remove a queued RA operation toast
     */
    removeRAQueuedToast(item) {
        const toastId = item.type === 'sync'
            ? `queued-ra-sync-${item.systemId}`
            : `queued-ra-refresh-${item.systemId || 'all'}`;
        const toast = this.activeToasts.get(toastId);
        if (toast) {
            toast.remove();
            this.activeToasts.delete(toastId);
        }
    },

    removeRASyncQueuedToast(systemId) {
        this.removeRAQueuedToast({ type: 'sync', systemId });
    },

    /**
     * Update queue position numbers for unified queue
     */
    updateRAQueuePositions() {
        const queue = safeParseJSON('raOperationsQueue', []);
        queue.forEach((item, index) => {
            const toastId = item.type === 'sync'
                ? `queued-ra-sync-${item.systemId}`
                : `queued-ra-refresh-${item.systemId || 'all'}`;
            const toast = this.activeToasts.get(toastId);
            if (toast) {
                const posEl = toast.querySelector('.queue-position');
                if (posEl) posEl.textContent = `#${index + 1}`;
            }
        });
    },

    updateQueuePositions() {
        this.updateRAQueuePositions();
    },

    /**
     * Restore RA queued toasts from localStorage (called on page load only)
     */
    restoreRAQueuedToasts() {
        const queue = safeParseJSON('raOperationsQueue', []);
        if (queue.length === 0) return;

        if (!this.container) {
            this.createContainer();
        }

        queue.forEach((item, index) => {
            const toastId = item.type === 'sync'
                ? `queued-ra-sync-${item.systemId}`
                : `queued-ra-refresh-${item.systemId || 'all'}`;

            if (this.activeToasts.has(toastId)) return;

            const toast = this.createRAQueuedToast(item, index + 1);
            this.activeToasts.set(toastId, toast);
            this.container.appendChild(toast);
        });
    },

    restoreRASyncQueuedToasts() {
        this.restoreRAQueuedToasts();
    },

    /**
     * Create a queued toast for any RA operation (sync or refresh)
     */
    createRAQueuedToast(item, position) {
        const config = item.type === 'sync' ? ToastTypes.RA_SYNC : ToastTypes.RA_REFRESH;
        const toast = document.createElement('div');
        toast.className = `unified-toast queued-toast ra-${item.type}-queued-toast`;
        toast.dataset.priority = '10';
        toast.style.order = 90;
        toast.style.setProperty('--toast-color', config.queuedColor);

        const title = item.type === 'sync'
            ? `🔄 Sync: ${this.escapeHtml(item.systemName)}`
            : `🏆 Refresh: ${this.escapeHtml(item.systemName || 'All Systems')}`;

        const raType = item.type === 'sync' ? 'sync' : 'refresh';
        const raSystemId = item.systemId == null ? '' : String(item.systemId);

        toast.innerHTML = `
            <div class="toast-content">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon(item.type === 'sync' ? 'ra-sync' : 'ra-refresh', 'queued')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${title}</div>
                        <div class="toast-subtitle"><span class="queue-position">#${position}</span> in queue${item.gameCount ? ` • ${this.fmtNum(item.gameCount)} games` : ''}</div>
                    </div>
                </div>
                <div class="toast-controls">
                    <button class="toast-btn cancel" data-toast-action="cancel-ra-queued" data-ra-type="${this.escapeHtml(raType)}" data-ra-system-id="${this.escapeHtml(raSystemId)}" title="Remove from queue">
                        ✕
                    </button>
                </div>
            </div>
        `;

        return toast;
    },

    createRASyncQueuedToast(item, position) {
        item.type = 'sync';
        return this.createRAQueuedToast(item, position);
    },

    /**
     * Cancel a queued RA operation
     */
    cancelRAQueued(type, systemId) {
        const queue = safeParseJSON('raOperationsQueue', []);
        const newQueue = queue.filter(q => !(q.type === type && (q.systemId || null) === systemId));
        localStorage.setItem('raOperationsQueue', JSON.stringify(newQueue));

        this.removeRAQueuedToast({ type, systemId });

        this.updateRAQueuePositions();
    },

    cancelRASyncQueued(systemId) {
        this.cancelRAQueued('sync', systemId);
    },

    /**
     * Get type configuration
     */
    getTypeConfig(type) {
        switch(type) {
            case 'bulk-scrape': return ToastTypes.BULK_SCRAPE;
            case 'ra-sync': return ToastTypes.RA_SYNC;
            case 'ra-refresh': return ToastTypes.RA_REFRESH;
            case 'psn-refresh': return ToastTypes.PSN_REFRESH;
            case 'image-resize': return ToastTypes.IMAGE_RESIZE;
            default: return null;
        }
    },

    /**
     * Show or update an active toast
     */
    showActiveToast(type, config, data) {
        const toastId = `active-${type}`;
        let toast = this.activeToasts.get(toastId);

        if (!toast) {
            toast = this.createActiveToast(type, config, data);
            this.activeToasts.set(toastId, toast);
            this.container.appendChild(toast);
            if (this.activeToasts.size === 1) {
                this.positionContainer();
            }
        }

        this.updateActiveToastContent(toast, type, config, data);
    },

    /**
     * Create an active toast element
     */
    createActiveToast(type, config, data) {
        const toast = document.createElement('div');
        toast.className = `unified-toast active-toast ${type}-toast`;
        toast.dataset.type = type;
        const priority = type === 'bulk-scrape' ? '100' : (type === 'ra-sync' ? '101' : (type === 'ra-refresh' ? '102' : (type === 'image-resize' ? '104' : '103')));
        toast.dataset.priority = priority;
        toast.style.order = 100 - parseInt(priority);

        const borderColor = data.paused ? config.pausedColor : config.activeColor;
        toast.style.setProperty('--toast-color', borderColor);

        toast.innerHTML = this.getActiveToastHTML(type, config, data);

        return toast;
    },

    /**
     * Get HTML for active toast
     */
    getActiveToastHTML(type, config, data) {
        const isPaused = data.paused;
        const percent = data.percent || 0;
        const total = data.total || 0;
        const current = type === 'bulk-scrape' ? (data.processing || 1) : (data.current || 0);

        let currentItem;
        if (type === 'image-resize') {
            currentItem = data.current_file || 'Processing...';
        } else if (type === 'ra-refresh' || type === 'psn-refresh') {
            currentItem = data.current_game || 'Processing...';
        } else {
            currentItem = data.current_game || data.current_system || 'Processing...';
        }

        const fmt = (n) => this.fmtNum(n);
        const si = { s: getThemedIcon('stat-success'), f: getThemedIcon('stat-failed'), k: getThemedIcon('stat-skipped') };
        let statsHTML = '';
        if (type === 'bulk-scrape') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'ra-refresh') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${getThemedIcon('ra-sync')} <span class="stat-value" data-stat="success">${fmt(data.success)}</span> found</span>
                </div>
            `;
        } else if (type === 'psn-refresh') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'ra-sync') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">${si.s} <span class="stat-value" data-stat="success">${fmt(data.success)}</span></span>
                    <span class="stat failed">${si.f} <span class="stat-value" data-stat="failed">${fmt(data.failed)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        } else if (type === 'image-resize') {
            statsHTML = `
                <div class="toast-stats">
                    <span class="stat success">⬆️ <span class="stat-value" data-stat="upscaled">${fmt(data.upscaled)}</span></span>
                    <span class="stat failed">⬇️ <span class="stat-value" data-stat="downscaled">${fmt(data.downscaled)}</span></span>
                    <span class="stat skipped">${si.k} <span class="stat-value" data-stat="skipped">${fmt(data.skipped)}</span></span>
                </div>
            `;
        }

        let systemNameValue = '';
        if (type === 'bulk-scrape' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-sync' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-refresh' && data.current_system) {
            systemNameValue = data.current_system;
        } else if (type === 'image-resize' && data.current_type) {
            systemNameValue = data.current_type;
        }
        const systemNameHTML = systemNameValue
            ? `<div class="toast-system-name" data-system-name>${this.escapeHtml(systemNameValue)}</div>`
            : '';

        const npwrHTML = (type === 'psn-refresh' && data.current_npwr)
            ? `<div class="toast-system-name" data-npwr>${this.escapeHtml(data.current_npwr)}</div>`
            : '';

        return `
            <div class="toast-content">
                <div class="toast-main" data-toast-action="navigate" data-toast-type="${this.escapeHtml(type)}" data-toast-return-url="${this.escapeHtml(data.return_url || '')}">
                    <div class="toast-icon ${isPaused ? 'paused' : ''}">${isPaused ? getThemedIcon(type, 'paused') : getThemedIcon(type)}</div>
                    <div class="toast-info">
                        <div class="toast-title ${isPaused ? 'paused' : ''}">${config.name} ${isPaused ? '(Paused)' : 'Running'}</div>
                        ${systemNameHTML}
                        <div class="toast-subtitle" data-subtitle>${this.escapeHtml(currentItem)}</div>
                        ${npwrHTML}
                        <div class="toast-progress-bar">
                            <div class="toast-progress-fill" data-progress style="width: ${percent}%"></div>
                        </div>
                        <div class="toast-progress-text">
                            <span data-current>${fmt(current)}</span> / <span data-total>${fmt(total)}</span> (<span data-percent>${percent}</span>%)
                        </div>
                        ${statsHTML}
                    </div>
                </div>
                <div class="toast-controls">
                    ${type === 'bulk-scrape' || type === 'psn-refresh' ? `
                    <button class="toast-btn pause" data-toast-action="pause" data-toast-type="${this.escapeHtml(type)}" title="${isPaused ? 'Resume' : 'Pause'}">
                        <span data-pause-icon>${isPaused ? '▶️' : '⏸️'}</span>
                    </button>
                    ` : ''}
                    <button class="toast-btn cancel" data-toast-action="cancel" data-toast-type="${this.escapeHtml(type)}" title="Cancel">
                        ✕
                    </button>
                </div>
            </div>
        `;
    },

    /**
     * Update active toast content
     */
    updateActiveToastContent(toast, type, config, data) {
        const stateSignature = `${type}-${data.paused}-${data.completed}-${data.percent}-${data.current}-${data.total}-${data.current_game || ''}-${data.current_system || ''}-${data.system_name || ''}-${data.current_file || ''}-${data.current_type || ''}-${data.current_npwr || ''}-${data.success}-${data.failed}-${data.skipped}-${data.upscaled || 0}-${data.downscaled || 0}`;
        if (toast.dataset.lastState === stateSignature) {
            return;  // Skip update - nothing changed
        }
        toast.dataset.lastState = stateSignature;

        const isPaused = data.paused;
        const percent = data.percent || 0;
        const total = data.total || 0;
        const current = type === 'bulk-scrape' ? (data.processing || 1) : (data.current || 0);

        let currentItem;
        if (type === 'image-resize') {
            currentItem = data.current_file || 'Processing...';
        } else if (type === 'ra-refresh' || type === 'psn-refresh') {
            currentItem = data.current_game || 'Processing...';
        } else {
            currentItem = data.current_game || data.current_system || 'Processing...';
        }

        const isComplete = data.completed;
        const borderColor = isComplete ? config.completedColor : (isPaused ? config.pausedColor : config.activeColor);
        toast.style.setProperty('--toast-color', borderColor);

        const icon = toast.querySelector('.toast-icon');
        if (icon) {
            icon.textContent = isComplete ? getThemedIcon(type, 'complete') : (isPaused ? getThemedIcon(type, 'paused') : getThemedIcon(type));
            icon.classList.toggle('paused', isPaused);
        }

        const title = toast.querySelector('.toast-title');
        if (title) {
            const statusText = isComplete ? 'Complete' : (isPaused ? '(Paused)' : 'Running');
            title.textContent = `${config.name} ${statusText}`;
            title.classList.toggle('paused', isPaused);
        }

        let systemNameEl = toast.querySelector('[data-system-name]');
        let systemNameValue = '';
        if (type === 'bulk-scrape' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-sync' && data.system_name) {
            systemNameValue = data.system_name;
        } else if (type === 'ra-refresh' && data.current_system) {
            systemNameValue = data.current_system;
        } else if (type === 'image-resize' && data.current_type) {
            systemNameValue = data.current_type;
        }
        if (systemNameValue) {
            if (systemNameEl) {
                systemNameEl.textContent = systemNameValue;
            } else {
                const titleEl = toast.querySelector('.toast-title');
                if (titleEl) {
                    const nameDiv = document.createElement('div');
                    nameDiv.className = 'toast-system-name';
                    nameDiv.setAttribute('data-system-name', '');
                    nameDiv.textContent = systemNameValue;
                    titleEl.insertAdjacentElement('afterend', nameDiv);
                }
            }
        }

        const subtitle = toast.querySelector('[data-subtitle]');
        if (subtitle) subtitle.textContent = currentItem;

        if (type === 'psn-refresh') {
            let npwrEl = toast.querySelector('[data-npwr]');
            if (data.current_npwr) {
                if (npwrEl) {
                    npwrEl.textContent = data.current_npwr;
                } else if (subtitle) {
                    const npwrDiv = document.createElement('div');
                    npwrDiv.className = 'toast-system-name';
                    npwrDiv.setAttribute('data-npwr', '');
                    npwrDiv.textContent = data.current_npwr;
                    subtitle.insertAdjacentElement('afterend', npwrDiv);
                }
            } else if (npwrEl) {
                npwrEl.remove();
            }
        }

        const progressFill = toast.querySelector('[data-progress]');
        if (progressFill) progressFill.style.width = `${percent}%`;

        const currentEl = toast.querySelector('[data-current]');
        if (currentEl) currentEl.textContent = this.fmtNum(current);

        const totalEl = toast.querySelector('[data-total]');
        if (totalEl) totalEl.textContent = this.fmtNum(total);

        const percentEl = toast.querySelector('[data-percent]');
        if (percentEl) percentEl.textContent = percent;

        if (type === 'bulk-scrape' || type === 'ra-sync' || type === 'ra-refresh' || type === 'psn-refresh') {
            const successEl = toast.querySelector('[data-stat="success"]');
            if (successEl) successEl.textContent = this.fmtNum(data.success);
        }

        if (type === 'bulk-scrape' || type === 'ra-sync' || type === 'psn-refresh') {
            const failedEl = toast.querySelector('[data-stat="failed"]');
            if (failedEl) failedEl.textContent = this.fmtNum(data.failed);

            const skippedEl = toast.querySelector('[data-stat="skipped"]');
            if (skippedEl) skippedEl.textContent = this.fmtNum(data.skipped);
        }

        if (type === 'image-resize') {
            const upscaledEl = toast.querySelector('[data-stat="upscaled"]');
            if (upscaledEl) upscaledEl.textContent = this.fmtNum(data.upscaled);

            const downscaledEl = toast.querySelector('[data-stat="downscaled"]');
            if (downscaledEl) downscaledEl.textContent = this.fmtNum(data.downscaled);

            const skippedEl = toast.querySelector('[data-stat="skipped"]');
            if (skippedEl) skippedEl.textContent = this.fmtNum(data.skipped);
        }

        const pauseIcon = toast.querySelector('[data-pause-icon]');
        if (pauseIcon) pauseIcon.textContent = isPaused ? '▶️' : '⏸️';

        const pauseBtn = toast.querySelector('.toast-btn.pause');
        if (pauseBtn) {
            pauseBtn.title = isPaused ? 'Resume' : 'Pause';
            pauseBtn.classList.toggle('is-paused', isPaused);
        }
    },

    /**
     * Hide active toast
     */
    hideActiveToast(type) {
        const toastId = `active-${type}`;
        const toast = this.activeToasts.get(toastId);
        if (toast) {
            toast.remove();
            this.activeToasts.delete(toastId);
        }
    },

    /**
     * Handle completion - removes toast and processes queue
     * This is the ONLY place that removes active toasts (besides cancel)
     */
    handleCompletion(type, data) {
        const completionKey = `toast_completion_${type}_${data.job_id || data.start_time || Date.now()}`;
        if (localStorage.getItem(completionKey)) {
            return;  // Already handled
        }
        localStorage.setItem(completionKey, 'true');

        console.debug(`Handling completion for ${type}`, data.job_id);

        setTimeout(() => {
            this.hideActiveToast(type);

            if (type === 'ra-sync' || type === 'ra-refresh') {
                setTimeout(() => {
                    const queue = safeParseJSON('raOperationsQueue', []);
                    const syncToast = this.activeToasts.get('active-ra-sync');
                    const refreshToast = this.activeToasts.get('active-ra-refresh');

                    if (queue.length > 0 && !this._triggeringRAQueue && !syncToast && !refreshToast) {
                        console.debug(`Queue has ${queue.length} items, triggering next`);
                        this.triggerNextRAOperationFromQueue();
                    }
                }, 1000);
            }
        }, 2000);
    },

    /**
     * Update queued toasts
     */
    updateQueuedToasts(type, queue) {
        const queueSignature = JSON.stringify(queue.map(j => j.job_id));
        const signatureKey = `_lastQueueSig_${type}`;
        if (this[signatureKey] === queueSignature) {
            return;  // No changes, skip all DOM operations
        }
        this[signatureKey] = queueSignature;

        const queueJobIds = new Set(queue.map(j => j.job_id));

        this.activeToasts.forEach((toast, toastId) => {
            if (toastId.startsWith(`queued-${type}-`)) {
                const jobId = toastId.replace(`queued-${type}-`, '');
                if (!queueJobIds.has(jobId)) {
                    toast.remove();
                    this.activeToasts.delete(toastId);
                }
            }
        });

        queue.forEach((job, index) => {
            const toastId = `queued-${type}-${job.job_id}`;
            let toast = this.activeToasts.get(toastId);

            if (!toast) {
                toast = this.createQueuedToast(type, job, index + 1);
                this.activeToasts.set(toastId, toast);
                this.container.appendChild(toast);
            } else {
                const posEl = toast.querySelector('.queue-position');
                if (posEl && posEl.textContent !== `#${index + 1}`) {
                    posEl.textContent = `#${index + 1}`;
                }
            }
        });

    },

    /**
     * Create a queued toast
     */
    createQueuedToast(type, job, position) {
        const config = this.getTypeConfig(type);
        const toast = document.createElement('div');
        toast.className = `unified-toast queued-toast ${type}-queued-toast`;
        toast.dataset.type = type;
        toast.dataset.jobId = job.job_id;
        toast.dataset.priority = '10';  // Queued toasts above active (lower priority = higher in stack)
        toast.style.order = 90;
        toast.style.setProperty('--toast-color', config.queuedColor);

        const subtitleText = job.system_name || 'Multi-System';
        toast.innerHTML = `
            <div class="toast-content queued">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon(type, 'queued')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${this.escapeHtml(config.name)} Queued (#${position})</div>
                        <div class="toast-subtitle">${this.escapeHtml(subtitleText)}</div>
                        <div class="toast-meta">${this.fmtNum(job.total)} games</div>
                    </div>
                </div>
                <div class="toast-controls">
                    <button class="toast-btn cancel" data-cancel-queued title="Remove from queue">
                        ✕
                    </button>
                </div>
            </div>
        `;

        const cancelBtn = toast.querySelector('[data-cancel-queued]');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                UnifiedToastController.cancelQueued(type, job.job_id);
            });
        }

        return toast;
    },

    /**
     * Toggle pause for an operation
     */
    async togglePause(type) {
        try {
            let endpoint;
            switch(type) {
                case 'bulk-scrape':
                    const status = await API.get('/api/bulk-scrape-job/status');
                    endpoint = status.paused ? '/api/bulk-scrape-job/resume' : '/api/bulk-scrape-job/pause';
                    break;
                case 'ra-sync':
                    endpoint = '/api/ra-sync/toggle-pause';
                    break;
                case 'ra-refresh':
                    endpoint = '/api/ra-refresh/toggle-pause';
                    break;
                case 'psn-refresh':
                    const psnStatus = await API.get('/api/psn/bulk-refresh/status');
                    endpoint = psnStatus.paused ? '/api/psn/bulk-refresh/resume' : '/api/psn/bulk-refresh/pause';
                    break;
            }

            if (endpoint) {
                await API.post(endpoint);
            }
        } catch (e) {
            console.error(`Error toggling pause for ${type}:`, e);
        }
    },

    /**
     * Cancel an operation
     */
    cancel(type) {
        const config = this.getTypeConfig(type);
        if (typeof showConfirm === 'function') {
            showConfirm(`⚠️ Cancel ${config.name}`, `Are you sure you want to cancel?`, async () => {
                await this.performCancel(type);
            });
        } else {
            this.performCancel(type);
        }
    },

    /**
     * Perform cancellation
     */
    async performCancel(type) {
        try {
            let endpoint;
            switch(type) {
                case 'bulk-scrape':
                    endpoint = '/api/bulk-scrape-job/cancel';
                    break;
                case 'ra-sync':
                    endpoint = '/api/achievements/sync-cancel';
                    break;
                case 'ra-refresh':
                    endpoint = '/api/refresh-retroachievements/cancel';
                    break;
                case 'psn-refresh':
                    endpoint = '/api/psn/bulk-refresh/cancel';
                    break;
                case 'image-resize':
                    endpoint = '/api/maintenance/image-resize/cancel';
                    break;
            }

            if (endpoint) {
                await API.post(endpoint);
                this.hideActiveToast(type);
                this._stopTypePolling(type);
                this.activeOperations.set(type, false);
                this.broadcast('job-cancelled', type);
            }
        } catch (e) {
            console.error(`Error cancelling ${type}:`, e);
        }
    },

    /**
     * Cancel a queued job
     */
    async cancelQueued(type, jobId) {
        try {
            if (type === 'bulk-scrape') {
                await API.post(`/api/bulk-scrape-job/cancel-queued/${jobId}`);

                const toastId = `queued-${type}-${jobId}`;
                const toast = this.activeToasts.get(toastId);
                if (toast) {
                    toast.remove();
                    this.activeToasts.delete(toastId);
                }
            }
        } catch (e) {
            console.error(`Error cancelling queued job ${jobId}:`, e);
        }
    },

    /**
     * Navigate to the appropriate page.
     *
     * Pass 41.12.B — open-redirect guard. The `returnUrl` argument flows
     * from `localStorage.getItem('bulkScrapeReturnUrl')` and similar
     * sources. localStorage is writable from any same-origin script, so
     * an XSS payload (or a stale value left by a malicious extension)
     * could land an attacker-controlled absolute URL here. Without
     * validation, `window.location.href = 'https://evil.example/...'`
     * would fire on the user's next toast click. Accept only:
     *   (a) same-origin paths starting with `/` (e.g. `/all-games`)
     *   (b) absolute URLs whose parsed origin matches the current page
     */
    navigateTo(type, returnUrl) {
        if (type === 'bulk-scrape') {
            localStorage.setItem('showBulkScrapeModal', 'true');
        }

        if (returnUrl && window.location.pathname !== returnUrl) {
            if (UnifiedToastController._isSafeReturnUrl(returnUrl)) {
                window.location.href = returnUrl;
            } else {
                console.warn('navigateTo: rejecting unsafe returnUrl', returnUrl);
            }
        } else if (type === 'ra-sync' || type === 'ra-refresh') {
            window.location.href = '/achievements';
        } else if (type === 'psn-refresh') {
            window.location.href = '/psn-trophies';
        }
    },

    /**
     * Pass 41.12.B — Validate that a navigation target is same-origin.
     */
    _isSafeReturnUrl(url) {
        if (typeof url !== 'string' || !url) return false;
        if (url.startsWith('/') && !url.startsWith('//')) return true;
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.origin === window.location.origin &&
                   (parsed.protocol === 'http:' || parsed.protocol === 'https:');
        } catch (e) {
            return false;
        }
    },

    /**
     * Restore saved toast state on page load
     */
    restoreSavedState() {
        localStorage.removeItem('bulkScrapeJustStarted');
        localStorage.removeItem('bulkScrapeToastState');

        this.migrateOldQueue();

        this.restoreRAQueuedToasts();
    },

    /**
     * Migrate old raSyncQueue to unified raOperationsQueue
     */
    migrateOldQueue() {
        const oldItems = safeParseJSON('raSyncQueue', null);
        if (Array.isArray(oldItems) && oldItems.length > 0) {
            const unifiedQueue = safeParseJSON('raOperationsQueue', []);
            oldItems.forEach(item => {
                if (!item.type) item.type = 'sync';
                if (!unifiedQueue.find(q => q.type === 'sync' && q.systemId === item.systemId)) {
                    unifiedQueue.push(item);
                }
            });
            try {
                localStorage.setItem('raOperationsQueue', JSON.stringify(unifiedQueue));
            } catch (e) {
                console.warn('Could not write migrated raOperationsQueue:', e);
            }
        }
        try { localStorage.removeItem('raSyncQueue'); } catch (_) { /* ignore */ }
    },

    /**
     * Format a number with thin-space thousands separators (delegates to global formatNumber)
     */
    fmtNum(n) {
        return typeof formatNumber === 'function' ? formatNumber(n || 0) : String(n || 0);
    },

    /**
     * Escape HTML
     */
    escapeHtml(text) {
        return window.escapeHtml ? window.escapeHtml(text) : (text || '');
    },

    /**
     * Cleanup - call on page unload
     */
    cleanup() {
        this.pollingIntervals.forEach(interval => clearInterval(interval));
        this.pollingIntervals.clear();
        this._pollAbortControllers.forEach(ac => ac.abort());
        this._pollAbortControllers.clear();
        if (this._broadcastChannel) {
            this._broadcastChannel.close();
            this._broadcastChannel = null;
        }
        if (this._resizeHandler) {
            window.removeEventListener('resize', this._resizeHandler);
            this._resizeHandler = null;
        }
        if (this._visibilityHandler) {
            document.removeEventListener('visibilitychange', this._visibilityHandler);
            this._visibilityHandler = null;
        }
        this.activeToasts.clear();
        this.pollCallbacks.clear();
        this.activeOperations.clear();
        this._initialized = false;
        this._containerListenersSet = false;
        this._visibilityHandlerSet = false;
    }
};

function goToBulkScrape() {
    UnifiedToastController.navigateTo('bulk-scrape', localStorage.getItem('bulkScrapeReturnUrl') || '/all-games');
}

function toggleToastPause() {
    UnifiedToastController.togglePause('bulk-scrape');
}

function cancelFromToast() {
    UnifiedToastController.cancel('bulk-scrape');
}

function cancelRASync() {
    UnifiedToastController.cancel('ra-sync');
}

document.addEventListener('DOMContentLoaded', () => {
    UnifiedToastController.init();
});

window.addEventListener('beforeunload', () => {
    UnifiedToastController.cleanup();
});

RetroDB.UnifiedToastController = UnifiedToastController;
RetroDB.ToastController = UnifiedToastController;
RetroDB.ToastTypes = ToastTypes;
RetroDB.ThemeIcons = ThemeIcons;
RetroDB.getThemedIcon = getThemedIcon;

window.UnifiedToastController = UnifiedToastController;
window.ToastController = UnifiedToastController;
window.ToastTypes = ToastTypes;
window.ThemeIcons = ThemeIcons;
window.getThemedIcon = getThemedIcon;

})();

(function(){
/* =============================================================================
   RETRODB - MAIN JAVASCRIPT
   Interactive functionality for the ROM Library
   ============================================================================= */

window.RetroDB = window.RetroDB || {};

const RetroDBState = {
    currentModal: null,
    screenshotIndex: 0,
    screenshots: [],
};

let _animationObserver = null;
let _backToTopScrollHandler = null;

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
    const msg = event.message || '';
    if (!msg || msg === 'Script error.') return;
    _surfaceError('Unexpected error', msg);
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
    _surfaceError('Unhandled rejection', detail);
});

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

    if (typeof getThemedIcon === 'function') {
        document.querySelectorAll('[data-themed-icon]').forEach(el => {
            el.textContent = getThemedIcon(el.dataset.themedIcon);
        });
    }

    if (typeof StickyScroll !== 'undefined') {
        StickyScroll.stackPositions();
        StickyScroll.updateMargins();

        if (window.location.hash) {
            const hashTarget = document.getElementById(window.location.hash.substring(1));
            if (hashTarget) {
                requestAnimationFrame(() => StickyScroll.to(hashTarget));
            }
        }
    }
});

function initializeBackToTop() {
    const backToTopBtn = document.getElementById('backToTopBtn');
    if (!backToTopBtn) return;

    if (!(window.BackToTopController && BackToTopController._isInit)) {
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

    setTimeout(() => {
        if (window.ToastController) {
            ToastController.positionBackToTop();
        }
    }, 100);

    window.addEventListener('resize', debounce(function() {
        if (window.ToastController) {
            ToastController.positionBackToTop();
        }
    }, 250), { passive: true });
}

function initializeSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.querySelector('.sidebar-toggle');
    const mainContent = document.querySelector('.main-content');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', function() {
            sidebar.classList.toggle('collapsed');
            mainContent.classList.toggle('sidebar-collapsed');
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
            setTimeout(() => {
                if (window.ToastController) {
                    ToastController.positionContainer();
                    ToastController.positionBackToTop();
                }
            }, 300);
        });
    }

    const isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (isCollapsed && sidebar) {
        sidebar.classList.add('collapsed');
        if (mainContent) mainContent.classList.add('sidebar-collapsed');
    }

    const mobileToggle = document.querySelector('.mobile-menu-toggle');
    if (mobileToggle) {
        mobileToggle.addEventListener('click', function() {
            sidebar.classList.toggle('open');
        });
    }

    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 992) {
            if (sidebar && !sidebar.contains(e.target) && !mobileToggle?.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        }
    });
}

function initializeSearch() {
    const systemSearch = document.getElementById('systemSearch');
    if (systemSearch) {
        systemSearch.addEventListener('input', debounce(function(e) {
            filterSystems(e.target.value);
        }, 300));
    }

    const gameSearch = document.getElementById('gameSearch');
    if (gameSearch) {
        gameSearch.addEventListener('input', debounce(function(e) {
            filterGames(e.target.value);
        }, 300));
    }

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
            if (error && error.name === 'AbortError') return;
            console.error('Search error:', error);
            hideSearchResults();
        });
}

function displaySearchResults(results) {
    const container = document.getElementById('searchResults');
    if (!container) return;

    if (!results || results.length === 0) {
        container.innerHTML = '<div class="search-no-results">No results found</div>';
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
        container.innerHTML = '<div class="search-loading"><span class="loading-spinner"></span> Searching...</div>';
        container.classList.add('active');
    }
}

function initializeFilters() {
    const sortSelect = document.getElementById('sortSelect');
    if (sortSelect) {
        sortSelect.addEventListener('change', function() {
            sortItems(this.value);
        });
    }

    const systemFilter = document.getElementById('systemFilter');
    if (systemFilter) {
        systemFilter.addEventListener('change', function() {
            filterBySystem(this.value);
        });
    }

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
                <div class="empty-state-title">No results found</div>
                <div class="empty-state-text">Try adjusting your search or filters</div>
            `;
            container.appendChild(emptyState);
        }
        emptyState.style.display = '';
    } else if (emptyState) {
        emptyState.style.display = 'none';
    }
}

function initializeModals() {

    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeScreenshotModal();
            }
        });
    });

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
        if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
    }
}

function initializeScreenshots() {
    const container = document.getElementById('screenshotsRow');
    if (container) {
        container.addEventListener('click', function(e) {
            if (e.target.closest('.screenshot-delete-btn')) return;
            const thumb = e.target.closest('.screenshot-thumb');
            if (!thumb) return;
            const currentThumbs = Array.from(container.querySelectorAll('.screenshot-thumb'));
            const index = currentThumbs.indexOf(thumb);
            if (index >= 0) {
                RetroDBState.screenshots = currentThumbs.map(t => t.querySelector('img')?.src || '');
                openScreenshotModal(index);
            }
        });
    }

    const screenshotItems = document.querySelectorAll('.screenshot-thumb');
    RetroDBState.screenshots = Array.from(screenshotItems).map(item => {
        return item.querySelector('img')?.src || '';
    });

    document.querySelector('.modal-nav.prev')?.addEventListener('click', function(e) {
        e.stopPropagation();
        navigateScreenshots(-1);
    });

    document.querySelector('.modal-nav.next')?.addEventListener('click', function(e) {
        e.stopPropagation();
        navigateScreenshots(1);
    });

}

function openScreenshotModal(index) {
    RetroDBState.screenshotIndex = index;
    updateScreenshotDisplay();
    openModal('screenshotModal');
    const modal = document.getElementById('screenshotModal');
    if (window.ModalFocusTrap && modal) {
        ModalFocusTrap.activate(modal, document.activeElement, {
            onEscape: () => closeScreenshotModal(),
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

function initializeAnimations() {
    if (_animationObserver) {
        _animationObserver.disconnect();
        _animationObserver = null;
    }

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

    document.querySelectorAll('.animate-on-scroll').forEach(el => {
        _animationObserver.observe(el);
    });

    const cards = document.querySelectorAll('.system-card, .stat-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.05}s`;
        card.classList.add('animate-fade-up');
    });
}

function initializeTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(el => {
        el.addEventListener('mouseenter', showTooltip);
        el.addEventListener('mouseleave', hideTooltip);
    });
}

function showTooltip(e) {
    const text = e.target.dataset.tooltip;
    if (!text) return;

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

function initializeConfirmDialogs() {
    document.querySelectorAll('[data-confirm]').forEach(el => {
        el.addEventListener('click', function(e) {
            e.preventDefault();
            const message = this.dataset.confirm;
            const target = this;
            showConfirm('⚠️ Confirm', message, () => {
                target.removeAttribute('data-confirm');
                target.click();
                target.setAttribute('data-confirm', message);
            });
        });
    });
}

function confirmReset(form) {
    if (window.event) window.event.preventDefault();
    showConfirm('🗑️ Reset Metadata', 'Are you sure you want to reset all metadata for this game? This will delete boxart and screenshots.', () => {
        form.submit();
    });
    return false;
}

async function scanLibrary() {
    const btn = document.getElementById('scanLibraryBtn');
    if (!btn) return;

    const originalText = btn.innerHTML;

    btn.innerHTML = '<span class="loading-spinner"></span> Scanning...';
    btn.disabled = true;

    try {
        const data = await API.post('/api/scan');

        if (data.success) {
            showNotification('Library scan complete! Found ' + (data.new_games || 0) + ' new games.', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showNotification(data.error || 'Scan failed', 'error');
        }
    } catch (error) {
        showNotification('Error scanning library: ' + error.message, 'error');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

async function restartServer() {
    showConfirm(
        '🔄 Restart Server',
        'Are you sure you want to restart the server?',
        async function() {
            showNotification('Restarting server...', 'info');

            try {
                await API.post('/api/restart');

                setTimeout(() => {
                    checkServerStatus();
                }, 3000);
            } catch (error) {
                setTimeout(() => {
                    checkServerStatus();
                }, 3000);
            }
        }
    );
}

async function checkServerStatus() {
    const maxAttempts = 10;
    let attempts = 0;

    const checkStatus = async () => {
        try {
            await API.get('/api/status');
            showNotification('Server restarted successfully!', 'success');
            setTimeout(() => location.reload(), 1000);
            return true;
        } catch (error) {
        }

        attempts++;
        if (attempts < maxAttempts) {
            setTimeout(checkStatus, 1000);
        } else {
            showNotification('Could not reconnect to server. Please refresh manually.', 'error');
        }
    };

    checkStatus();
}

async function cleanMissingRoms() {
    showConfirm(
        '🧹 Clean Missing ROMs',
        'This will remove database entries for ROM files that no longer exist on disk. This cannot be undone. Continue?',
        async function() {
            const btn = document.getElementById('cleanMissingBtn');
            const resultDiv = document.getElementById('cleanMissingResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="btn-icon">⏳</span> Scanning...';
            }

            try {
                const data = await API.post('/api/clean-missing-roms');

                if (data.success) {
                    showNotification(`Removed ${formatNumber(data.removed)} games with missing ROMs`, 'success');

                    if (resultDiv) {
                        if (data.removed > 0) {
                            let html = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(239, 68, 68, 0.1);">`;
                            html += `<strong style="color: var(--danger-red);">Removed ${formatNumber(data.removed)} games:</strong>`;
                            html += `<ul style="margin-top: var(--spacing-sm); font-size: 0.9rem;">`;
                            for (const game of data.removed_games) {
                                html += `<li>${escapeHtml(game.title)}</li>`;
                            }
                            if (data.removed > 50) {
                                html += `<li>... and ${formatNumber(data.removed - 50)} more</li>`;
                            }
                            html += `</ul></div>`;
                            resultDiv.innerHTML = html;
                        } else {
                            resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                                <strong style="color: var(--primary-cyan);">✓ All ROMs accounted for!</strong>
                                <p style="margin-top: var(--spacing-xs);">No missing ROM files found.</p>
                            </div>`;
                        }
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || 'Failed to clean missing ROMs', 'error');
                }
            } catch (error) {
                console.error('Error cleaning missing ROMs:', error);
                showNotification('Failed to clean missing ROMs', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">🧹</span> Clean Missing ROMs';
                }
            }
        },
        {danger: true}
    );
}

async function clearClzImports() {
    showConfirm(
        '📋 Clear CLZ Imports',
        'This will remove ALL games imported via CLZ Games Import from the database. This cannot be undone. Continue?',
        async function() {
            const btn = document.getElementById('clearClzBtn');
            const resultDiv = document.getElementById('clearClzResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="btn-icon">⏳</span> Removing...';
            }

            try {
                const data = await API.post('/api/clear-clz-imports');

                if (data.success) {
                    showNotification(`Removed ${formatNumber(data.removed)} CLZ Import games`, 'success');

                    if (resultDiv) {
                        if (data.removed > 0) {
                            let html = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(239, 68, 68, 0.1);">`;
                            html += `<strong style="color: var(--danger-red);">Removed ${formatNumber(data.removed)} CLZ Import games:</strong>`;
                            html += `<ul style="margin-top: var(--spacing-sm); font-size: 0.9rem;">`;
                            for (const game of data.removed_games) {
                                html += `<li>${escapeHtml(game.title)}</li>`;
                            }
                            if (data.removed > 50) {
                                html += `<li>... and ${formatNumber(data.removed - 50)} more</li>`;
                            }
                            html += `</ul></div>`;
                            resultDiv.innerHTML = html;
                        } else {
                            resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                                <strong style="color: var(--primary-cyan);">✓ No CLZ Import games found</strong>
                            </div>`;
                        }
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || 'Failed to clear CLZ imports', 'error');
                }
            } catch (error) {
                console.error('Error clearing CLZ imports:', error);
                showNotification('Failed to clear CLZ imports', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">📋</span> Clear CLZ Imports';
                }
            }
        },
        {danger: true}
    );
}

async function refreshRetroAchievements() {
    showConfirm(
        '🏆 Refresh RetroAchievements',
        'This will scan all games and update their RetroAchievements status. This may take several minutes for large collections. Continue?',
        async function() {
            const btn = document.getElementById('refreshRABtn');
            const resultDiv = document.getElementById('refreshRAResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="btn-icon">⏳</span> Starting...';
            }

            try {
                const data = await API.post('/api/refresh-retroachievements');

                if (data.success) {
                    if (data.queued) {
                        const queue = safeParseJSON('raOperationsQueue', []);

                        if (!queue.find(q => q.type === 'refresh' && q.systemId === null)) {
                            const newItem = {
                                type: 'refresh',
                                systemId: null,
                                systemName: 'All Systems',
                                timestamp: Date.now()
                            };
                            queue.push(newItem);
                            localStorage.setItem('raOperationsQueue', JSON.stringify(queue));

                            if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                                UnifiedToastController.addRAOperationToQueue(newItem);
                                UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                            }
                        }

                        if (btn) {
                            btn.innerHTML = '<span class="btn-icon">📋</span> Queued';
                        }

                        showNotification('Added to queue - will start when current operation completes', 'info');
                        return;
                    }

                    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                        const initialData = {
                            running: true,
                            completed: false,
                            current_system: 'Starting...',
                            current_game: 'Initializing...',
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

                    if (btn) {
                        btn.innerHTML = '<span class="btn-icon">⏳</span> Running...';
                    }
                } else {
                    showNotification(data.error || 'Failed to start RetroAchievements refresh', 'error');
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<span class="btn-icon">🏆</span> Refresh RetroAchievements';
                    }
                }
            } catch (error) {
                console.error('Error starting RetroAchievements refresh:', error);
                showNotification('Failed to start RetroAchievements refresh', 'error');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">🏆</span> Refresh RetroAchievements';
                }
            }
        }
    );
}

function cancelRARefresh() {
    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.cancel) {
        UnifiedToastController.cancel('ra-refresh');
    }
}

async function clearRAData() {
    const systemSelect = document.getElementById('clearRASystemSelect');
    const systemId = systemSelect ? systemSelect.value : 'all';
    const systemName = systemSelect && systemId !== 'all'
        ? systemSelect.options[systemSelect.selectedIndex].text
        : 'all systems';

    const confirmMsg = systemId === 'all'
        ? 'This will clear ALL RetroAchievements game IDs and progress data from your database. You will need to run "Refresh RetroAchievements" again afterwards to re-scan your games. Continue?'
        : `This will clear RetroAchievements game IDs and progress data for "${systemName}". Continue?`;

    showConfirm(
        '🗑️ Clear RetroAchievements Data',
        confirmMsg,
        async function() {
            const btn = document.getElementById('clearRABtn');
            const resultDiv = document.getElementById('clearRAResult');

            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="btn-icon">⏳</span> Clearing...';
            }

            try {
                const endpoint = systemId === 'all'
                    ? '/api/clear-ra-data'
                    : `/api/clear-ra-data/${systemId}`;

                const data = await API.post(endpoint);

                if (data.success) {
                    const msg = systemId === 'all'
                        ? `Cleared RA data for ${formatNumber(data.cleared)} games`
                        : `Cleared RA data for ${formatNumber(data.cleared)} games in ${systemName}`;
                    showNotification(msg, 'success');

                    if (resultDiv) {
                        resultDiv.innerHTML = `<div class="glass-panel" style="padding: var(--spacing-md); background: rgba(76, 201, 240, 0.1);">
                            <strong style="color: var(--primary-cyan);">✓ RA Data Cleared</strong>
                            <p style="margin-top: var(--spacing-xs);">Cleared RetroAchievements data for ${formatNumber(data.cleared)} games. Run "Refresh RetroAchievements" to re-scan with updated matching.</p>
                        </div>`;
                        resultDiv.style.display = 'block';
                    }
                } else {
                    showNotification(data.error || 'Failed to clear RA data', 'error');
                }
            } catch (error) {
                console.error('Error clearing RA data:', error);
                showNotification('Failed to clear RA data', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<span class="btn-icon">🗑️</span> Clear RA Data';
                }
            }
        },
        {danger: true}
    );
}

async function searchGame(gameId, title) {
    const resultsContainer = document.getElementById('searchResults');
    const searchBtn = document.getElementById('searchBtn');

    if (!resultsContainer || !searchBtn) return;

    const originalText = searchBtn.innerHTML;
    searchBtn.innerHTML = '<span class="loading-spinner"></span> Searching...';
    searchBtn.disabled = true;

    try {
        const data = await API.post('/api/games/search', { game_id: gameId, title: title });

        if (data.results && data.results.length > 0) {
            displayScraperResults(data.results, gameId);
        } else {
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔍</div>
                    <div class="empty-state-title">No results found</div>
                    <div class="empty-state-text">Try modifying the search title</div>
                </div>
            `;
        }
    } catch (error) {
        resultsContainer.innerHTML = `
            <div class="alert alert-error">
                Error searching: ${error.message}
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
                        ${result.score ? `<span>Score: ${result.score.toFixed(1)}</span>` : ''}
                    </div>
                    ${altChips ? `<div class="search-result-alts"><span class="search-result-alts-label">Also known as:</span> ${altChips}</div>` : ''}
                </div>
                <form method="POST" style="margin: 0;">
                    <input type="hidden" name="action" value="apply">
                    <input type="hidden" name="game_source" value="${result.source}_${result.id}">
                    <button type="submit" class="btn btn-success btn-sm">
                        Apply
                    </button>
                </form>
            </div>
        `;
    }).join('');
}

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

const KeyboardShortcuts = {
    enabled: true,
    pendingKey: null,
    pendingTimeout: null,

    shortcuts: {
        'g d': { action: () => window.location.href = '/dashboard', description: 'Go to Dashboard', category: 'Navigation' },
        'g s': { action: () => window.location.href = '/systems', description: 'Go to Systems', category: 'Navigation' },
        'g l': { action: () => window.location.href = '/games', description: 'Go to Library', category: 'Navigation' },
        'g a': { action: () => window.location.href = '/analytics', description: 'Go to Analytics', category: 'Navigation' },
        'g t': { action: () => window.location.href = '/settings', description: 'Go to Settings', category: 'Navigation' },
        'g h': { action: () => window.location.href = '/help', description: 'Go to Help', category: 'Navigation' },
        'g c': { action: () => window.location.href = '/changelog', description: 'Go to Changelog', category: 'Navigation' },

        '/': { action: () => focusSearch(), description: 'Focus search box', category: 'Actions' },
        '?': { action: () => showShortcutsModal(), description: 'Show keyboard shortcuts', category: 'Actions' },
        'Escape': { action: () => closeAnyModal(), description: 'Close modal / cancel', category: 'Actions' },
    },

    gameShortcuts: {
        'e': { action: () => { if (typeof openEditModal === 'function') openEditModal(); }, description: 'Edit game', category: 'Game Page' },
        's': { action: () => { if (typeof openScrapeModal === 'function') openScrapeModal(); }, description: 'Scrape game', category: 'Game Page' },
    },

    init() {
        document.addEventListener('keydown', (e) => this.handleKeydown(e));
    },

    handleKeydown(e) {
        if (this.isTyping(e)) return;

        if (!this.enabled) return;

        const key = e.key;

        if (key === 'Escape') {
            closeAnyModal();
            return;
        }

        if (this.pendingKey) {
            const combo = `${this.pendingKey} ${key}`;
            if (this.shortcuts[combo]) {
                e.preventDefault();
                this.shortcuts[combo].action();
            }
            this.clearPending();
            return;
        }

        if (key === 'g') {
            e.preventDefault();
            this.pendingKey = 'g';
            this.showPendingIndicator('g + ...');
            this.pendingTimeout = setTimeout(() => this.clearPending(), 1500);
            return;
        }

        if (this.shortcuts[key]) {
            e.preventDefault();
            this.shortcuts[key].action();
            return;
        }

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
    const searchIds = ['gameSearch', 'systemSearch', 'globalSearch', 'searchInput'];
    for (const id of searchIds) {
        const input = document.getElementById(id);
        if (input) {
            input.focus();
            input.select();
            return;
        }
    }
    const searchInput = document.querySelector('.search-input, input[type="search"]');
    if (searchInput) {
        searchInput.focus();
        searchInput.select();
    }
}

function closeAnyModal() {
    if (RetroDBState.currentModal) {
        closeScreenshotModal();
    }
    document.querySelectorAll('.modal.active, .modal-overlay.active, .custom-modal.active').forEach(modal => {
        modal.classList.remove('active');
    });
    if (typeof closeModal === 'function') {
        try { closeModal(); } catch (e) {}
    }
}

const _SHORTCUT_KEY_LABELS = {
    'Escape': 'Esc',
    'ArrowLeft': '←',
    'ArrowRight': '→',
    'ArrowUp': '↑',
    'ArrowDown': '↓',
};

function _renderShortcutKeys(combo) {
    return combo.split(' ').map(k => {
        const label = _SHORTCUT_KEY_LABELS[k] || k;
        return `<kbd>${escapeHtml(label)}</kbd>`;
    }).join(' ');
}

function _buildShortcutsBody() {
    const buckets = new Map();
    const addEntry = (combo, meta) => {
        const cat = meta.category || 'Other';
        if (!buckets.has(cat)) buckets.set(cat, []);
        buckets.get(cat).push({ combo, description: meta.description });
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
                    <h3 id="shortcutsModalTitle">⌨️ Keyboard Shortcuts</h3>
                    <button class="custom-modal-close" onclick="closeShortcutsModal()" aria-label="Close keyboard shortcuts">×</button>
                </div>
                <div class="custom-modal-body" id="shortcutsModalBody">${body}</div>
            </div>
        `;
        modal.onclick = (e) => { if (e.target === modal) closeShortcutsModal(); };
        document.body.appendChild(modal);

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

document.addEventListener('DOMContentLoaded', () => KeyboardShortcuts.init());

function trackGameView(gameId) {
    if (!gameId) return;
    API.post(`/api/game/${gameId}/track-view`)
        .catch(e => console.warn('View tracking failed:', e));
}

document.addEventListener('DOMContentLoaded', () => {
    const match = window.location.pathname.match(/\/game\/(\d+)/);
    if (match) {
        trackGameView(match[1]);
    }
});

function updateCompletionStatus(gameId, status) {
    API.post(`/api/game/${gameId}/completion`, { status: status })
        .then(data => {
            if (data.success) {
                showNotification('Completion status updated', 'success');
            } else {
            showNotification('Failed to update status: ' + data.error, 'error');
        }
    })
    .catch(e => showNotification('Error updating status', 'error'));
}

RetroDB.scanLibrary = scanLibrary;
RetroDB.restartServer = restartServer;
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

window.scanLibrary = scanLibrary;
window.restartServer = restartServer;
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

window.addEventListener('beforeunload', function() {
    if (_animationObserver) { _animationObserver.disconnect(); _animationObserver = null; }
    if (_backToTopScrollHandler) { window.removeEventListener('scroll', _backToTopScrollHandler); _backToTopScrollHandler = null; }
    if (window.BackToTopController && BackToTopController.destroy) BackToTopController.destroy();
});

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

})();
