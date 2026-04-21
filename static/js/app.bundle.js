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
    return text.replace(/[&<>"']/g, m => map[m]);
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
     * Clear all RetroDB localStorage items
     */
    clearAll() {
        const retroDbKeys = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && (key.startsWith('retrodb') || key.startsWith('bulkScrape') || key.startsWith('sidebar'))) {
                retroDbKeys.push(key);
            }
        }
        retroDbKeys.forEach(key => localStorage.removeItem(key));
    }
};

const API = {
    /**
     * Make a GET request
     * @param {string} url - API endpoint
     * @param {Object} options - Fetch options
     * @returns {Promise<Object>} - Response data
     */
    async get(url, options = {}) {
        try {
            const response = await fetch(url, {
                method: 'GET',
                ...options
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API GET error:', error);
            throw error;
        }
    },

    /**
     * Make a POST request
     * @param {string} url - API endpoint
     * @param {Object} data - Request body
     * @param {Object} options - Fetch options
     * @returns {Promise<Object>} - Response data
     */
    async post(url, data = {}, options = {}) {
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                body: JSON.stringify(data),
                ...options
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API POST error:', error);
            throw error;
        }
    },

    /**
     * Make a POST request with FormData
     * @param {string} url - API endpoint
     * @param {FormData} formData - Form data
     * @returns {Promise<Object>} - Response data
     */
    async postForm(url, formData) {
        try {
            const response = await fetch(url, {
                method: 'POST',
                body: formData
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API POST form error:', error);
            throw error;
        }
    }
};

const Notifications = {
    container: null,

    timeouts: {
        success: 3,
        info: 3,
        warning: 5,
        error: 8
    },

    /**
     * Initialize notification container and load settings
     */
    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'notification-container';
            this.container.className = 'notification-container';
            document.body.appendChild(this.container);
        }
        if (window.NOTIFICATION_TIMEOUTS) {
            this.timeouts = { ...this.timeouts, ...window.NOTIFICATION_TIMEOUTS };
        }
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

        const MAX_NOTIFICATIONS = 8;
        const existing = this.container.querySelectorAll('.notification');
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

        this.container.appendChild(notification);

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
     * Create element with attributes
     * @param {string} tag - Tag name
     * @param {Object} attrs - Attributes
     * @param {string|Element} content - Inner content
     * @returns {Element}
     */
    create(tag, attrs = {}, content = '') {
        const el = document.createElement(tag);
        Object.entries(attrs).forEach(([key, value]) => {
            if (key === 'className') {
                el.className = value;
            } else if (key === 'dataset') {
                Object.entries(value).forEach(([k, v]) => {
                    el.dataset[k] = v;
                });
            } else if (key.startsWith('on') && typeof value === 'function') {
                el.addEventListener(key.slice(2).toLowerCase(), value);
            } else {
                el.setAttribute(key, value);
            }
        });
        if (content) {
            if (typeof content === 'string') {
                el.innerHTML = content;
            } else {
                el.appendChild(content);
            }
        }
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

window.debounce = debounce;
window.throttle = throttle;
window.formatBytes = formatBytes;
window.formatNumber = formatNumber;
window.formatRatio = formatRatio;
window.escapeHtml = escapeHtml;
window.copyToClipboard = copyToClipboard;
window.Storage = Storage;
window.API = API;
window.Notifications = Notifications;
window.showNotification = showNotification;
window.LoadingState = LoadingState;
window.DOM = DOM;
window.DateUtils = DateUtils;
window.StickyScroll = StickyScroll;

})();

(function(){
/**
 * RetroDB Page Lifecycle & Cleanup Manager
 * Handles memory leak prevention, event listener cleanup, and page state management
 * Version: 1.19.0
 */

window.RetroDB = window.RetroDB || {};

const PageLifecycle = (function() {
    'use strict';

    const eventListeners = [];
    const intervals = [];
    const timeouts = [];
    const observers = [];
    const abortControllers = [];

    let pageState = null;
    let pageKey = null;

    /**
     * Add an event listener with automatic cleanup tracking
     * @param {Element|Window|Document} target - Event target
     * @param {string} type - Event type
     * @param {Function} handler - Event handler
     * @param {Object} options - Event listener options
     * @returns {Function} - Removal function
     */
    function addEventListener(target, type, handler, options = {}) {
        if (!target || typeof target.addEventListener !== 'function') {
            console.warn('Invalid target for addEventListener');
            return () => {};
        }

        target.addEventListener(type, handler, options);

        const entry = { target, type, handler, options };
        eventListeners.push(entry);

        return () => removeEventListener(entry);
    }

    function removeEventListener(entry) {
        const { target, type, handler, options } = entry;
        target.removeEventListener(type, handler, options);

        const index = eventListeners.indexOf(entry);
        if (index > -1) {
            eventListeners.splice(index, 1);
        }
    }

    /**
     * Set an interval with automatic cleanup tracking
     */
    function setInterval(callback, delay) {
        const id = window.setInterval(callback, delay);
        intervals.push(id);
        return id;
    }

    function clearInterval(id) {
        window.clearInterval(id);
        const index = intervals.indexOf(id);
        if (index > -1) {
            intervals.splice(index, 1);
        }
    }

    /**
     * Set a timeout with automatic cleanup tracking
     */
    function setTimeout(callback, delay) {
        const id = window.setTimeout(() => {
            const index = timeouts.indexOf(id);
            if (index > -1) {
                timeouts.splice(index, 1);
            }
            callback();
        }, delay);
        timeouts.push(id);
        return id;
    }

    function clearTimeout(id) {
        window.clearTimeout(id);
        const index = timeouts.indexOf(id);
        if (index > -1) {
            timeouts.splice(index, 1);
        }
    }

    /**
     * Create a MutationObserver with automatic cleanup tracking
     */
    function createObserver(callback) {
        const observer = new MutationObserver(callback);
        observers.push(observer);
        return observer;
    }

    function disconnectObserver(observer) {
        observer.disconnect();
        const index = observers.indexOf(observer);
        if (index > -1) {
            observers.splice(index, 1);
        }
    }

    /**
     * Create an AbortController for fetch requests with cleanup tracking
     */
    function createAbortController() {
        const controller = new AbortController();
        abortControllers.push(controller);
        return controller;
    }

    function removeAbortController(controller) {
        const index = abortControllers.indexOf(controller);
        if (index > -1) {
            abortControllers.splice(index, 1);
        }
    }

    /**
     * Initialize page state tracking
     * @param {string} key - Unique key for this page's state
     */
    function initPageState(key) {
        pageKey = key;

        try {
            const saved = sessionStorage.getItem(pageKey);
            if (saved) {
                pageState = JSON.parse(saved);
            }
        } catch (e) {
            console.warn('Failed to restore page state:', e);
        }

        return pageState;
    }

    /**
     * Save current page state
     */
    function savePageState(state) {
        pageState = { ...pageState, ...state };

        if (pageKey) {
            try {
                sessionStorage.setItem(pageKey, JSON.stringify(pageState));
            } catch (e) {
                console.warn('Failed to save page state:', e);
            }
        }
    }

    /**
     * Get current page state
     */
    function getPageState() {
        return pageState;
    }

    /**
     * Clear page state
     */
    function clearPageState() {
        pageState = null;
        if (pageKey) {
            sessionStorage.removeItem(pageKey);
        }
    }

    /**
     * Save current scroll position
     */
    function saveScrollPosition() {
        savePageState({ scrollY: window.scrollY });
    }

    /**
     * Restore saved scroll position
     * @param {number} delay - Delay before restoring (for DOM rendering)
     */
    function restoreScrollPosition(delay = 100) {
        const state = getPageState();
        if (state && typeof state.scrollY === 'number') {
            window.setTimeout(() => {
                window.scrollTo(0, state.scrollY);
            }, delay);
        }
    }

    const debounceTimeouts = new Map();

    /**
     * Debounce function with automatic cleanup
     */
    function debounce(key, func, wait) {
        return function(...args) {
            const existing = debounceTimeouts.get(key);
            if (existing) {
                window.clearTimeout(existing);
            }

            const timeout = window.setTimeout(() => {
                debounceTimeouts.delete(key);
                func.apply(this, args);
            }, wait);

            debounceTimeouts.set(key, timeout);
        };
    }

    /**
     * Clean up all tracked resources
     */
    function cleanup() {
        eventListeners.forEach(entry => {
            try {
                entry.target.removeEventListener(entry.type, entry.handler, entry.options);
            } catch (e) { /* Ignore errors during cleanup */ }
        });
        eventListeners.length = 0;

        intervals.forEach(id => window.clearInterval(id));
        intervals.length = 0;

        timeouts.forEach(id => window.clearTimeout(id));
        timeouts.length = 0;

        observers.forEach(obs => {
            try { obs.disconnect(); } catch (e) { /* Ignore */ }
        });
        observers.length = 0;

        abortControllers.forEach(ctrl => {
            try { ctrl.abort(); } catch (e) { /* Ignore */ }
        });
        abortControllers.length = 0;

        debounceTimeouts.forEach(id => window.clearTimeout(id));
        debounceTimeouts.clear();

        if (typeof DOMCache !== 'undefined' && DOMCache.clear) {
            DOMCache.clear();
        }
    }

    /**
     * Register cleanup on page unload
     */
    function registerUnloadCleanup() {
        window.addEventListener('beforeunload', cleanup);

        window.addEventListener('pagehide', (event) => {
            if (event.persisted) {
                saveScrollPosition();
            } else {
                cleanup();
            }
        });

        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                restoreScrollPosition(0);
            }
        });
    }

    if (typeof document !== 'undefined') {
        registerUnloadCleanup();
    }

    return {
        addEventListener,
        removeEventListener: (entry) => removeEventListener(entry),

        setInterval,
        clearInterval,
        setTimeout,
        clearTimeout,

        createObserver,
        disconnectObserver,

        createAbortController,
        removeAbortController,

        initPageState,
        savePageState,
        getPageState,
        clearPageState,
        saveScrollPosition,
        restoreScrollPosition,

        debounce,

        cleanup,
        registerUnloadCleanup
    };
})();

RetroDB.PageLifecycle = PageLifecycle;
window.PageLifecycle = PageLifecycle;

const DOMCache = (function() {
    'use strict';

    const cache = new Map();
    const MAX_CACHE_SIZE = 500;  // Prevent unbounded growth

    /** Evict oldest entries if cache exceeds max size */
    function _evictIfNeeded() {
        if (cache.size <= MAX_CACHE_SIZE) return;
        const excess = cache.size - MAX_CACHE_SIZE + 50;  // Evict 50 at a time
        let removed = 0;
        for (const key of cache.keys()) {
            if (removed >= excess) break;
            cache.delete(key);
            removed++;
        }
    }

    /**
     * Get element by ID with caching
     */
    function getById(id) {
        if (cache.has(id)) return cache.get(id);
        const el = document.getElementById(id);
        if (el) {
            cache.set(id, el);
            _evictIfNeeded();
        }
        return el;
    }

    /**
     * Get elements by selector with caching
     */
    function query(selector) {
        if (cache.has(selector)) return cache.get(selector);
        const el = document.querySelector(selector);
        if (el) {
            cache.set(selector, el);
            _evictIfNeeded();
        }
        return el;
    }

    /**
     * Get all elements by selector with caching
     */
    function queryAll(selector) {
        const key = `all:${selector}`;
        const cached = cache.get(key);
        if (cached !== undefined) return cached;
        const els = document.querySelectorAll(selector);
        cache.set(key, els);
        _evictIfNeeded();
        return els;
    }

    /**
     * Invalidate cache entry
     */
    function invalidate(key) {
        cache.delete(key);
    }

    /**
     * Clear entire cache
     */
    function clear() {
        cache.clear();
    }

    return {
        getById,
        query,
        queryAll,
        invalidate,
        clear
    };
})();

RetroDB.DOMCache = DOMCache;
window.DOMCache = DOMCache;

})();

(function(){
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

        const letterMap = new Map();
        items.forEach(item => {
            const title = (item.dataset.sortTitle || item.dataset.title || item.dataset.name || '').toUpperCase();
            const firstChar = title.charAt(0);
            const letter = /[A-Z]/.test(firstChar) ? firstChar : '#';

            if (!letterMap.has(letter)) {
                letterMap.set(letter, item);
            }
        });

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

        const headerOffset = 150;
        const elementPosition = element.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

        window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
        });

        element.classList.add('highlight-jump');
        setTimeout(() => {
            element.classList.remove('highlight-jump');
        }, 1500);
    }
};

RetroDB.AlphabetNav = AlphabetNav;

window.AlphabetNav = AlphabetNav;

})();

(function(){
/**
 * RetroDB Bulk Scrape Module
 * Shared JavaScript for bulk scraping functionality
 * Used by games.html and all_games.html
 */

window.RetroDB = window.RetroDB || {};

const BulkScrapeController = {
    pollingInterval: null,  // Flag: true when registered with toast controller's shared poller

    /**
     * Initialize bulk scrape UI elements
     * @returns {Object} DOM element references
     */
    getElements() {
        return {
            modal: document.getElementById('bulkScrapeModal'),
            currentGame: document.getElementById('bulkCurrentGame'),
            status: document.getElementById('bulkStatus'),
            results: document.getElementById('bulkResults'),
            resultsLive: document.getElementById('bulkResultsLive'),
            footer: document.getElementById('bulkFooter'),
            closeBtn: document.getElementById('bulkCloseBtn'),
            controlsRow: document.getElementById('bulkControlsRow'),
            backgroundBtn: document.getElementById('bulkBackgroundBtn'),
            progressFill: document.getElementById('bulkProgressFill'),
            progress: document.getElementById('bulkProgress'),
            total: document.getElementById('bulkTotal'),
            successLive: document.getElementById('bulkSuccessCountLive'),
            failedLive: document.getElementById('bulkFailedCountLive'),
            skippedLive: document.getElementById('bulkSkippedCountLive'),
            successFinal: document.getElementById('bulkSuccessCount'),
            failedFinal: document.getElementById('bulkFailedCount'),
            skippedFinal: document.getElementById('bulkSkippedCount'),
            pauseBtn: document.getElementById('bulkPauseBtn'),
            pauseIcon: document.getElementById('bulkPauseBtnIcon'),
            pauseText: document.getElementById('bulkPauseBtnText')
        };
    },

    /**
     * Reset the modal UI to initial state
     * @param {number} totalGames - Total number of games to scrape
     * @param {string|null} firstGame - Title of the first game (for immediate feedback)
     */
    resetUI(totalGames, firstGame = null) {
        const el = this.getElements();

        el.modal.classList.add('active');
        el.total.textContent = formatNumber(totalGames);
        el.progress.textContent = '1';  // Show 1/x immediately (we're about to scrape game 1)
        el.progressFill.style.setProperty('--progress', '0%');
        el.successLive.textContent = '0';
        el.failedLive.textContent = '0';
        el.skippedLive.textContent = '0';
        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ paused: '⏸️', resume: '▶️', cancelled: '❌', 'stat-success': '✅', 'stat-failed': '❌', 'stat-skipped': '⏭️' }[k] || k);
        el.pauseIcon.textContent = _ti('paused');
        el.pauseText.textContent = 'Pause';
        el.pauseBtn.classList.remove('btn-success');
        el.pauseBtn.classList.add('btn-warning');

        el.currentGame.textContent = firstGame || 'Starting...';
        el.status.textContent = firstGame ? `Scraped 0/${formatNumber(totalGames)} - 0%` : 'Initializing bulk scrape...';
        el.results.style.display = 'none';
        el.resultsLive.style.display = 'flex';
        el.footer.style.display = 'none';
        if (el.closeBtn) el.closeBtn.style.display = 'none';
        if (el.backgroundBtn) el.backgroundBtn.style.display = 'inline-flex';
        el.controlsRow.style.display = 'flex';
    },

    /**
     * Start a bulk scrape job
     * @param {Array<number>} gameIds - Array of game IDs to scrape
     * @param {number|null} systemId - Optional system ID (for games.html)
     * @param {string} scrapeMode - 'fill_missing' or 'full_rescrape'
     */
    async start(gameIds, systemId = null, scrapeMode = 'fill_missing') {
        if (gameIds.length === 0) {
            const _wi = typeof getThemedIcon === 'function' ? getThemedIcon('warning') : '⚠️';
            showModal(`${_wi} No Games Selected`, 'Please select at least one game to scrape.');
            return;
        }

        const returnUrl = window.location.href;

        try {
            const payload = {
                game_ids: gameIds,
                return_url: returnUrl,
                scrape_mode: scrapeMode
            };
            if (systemId) payload.system_id = systemId;

            const response = await fetch('/api/bulk-scrape-job/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (data.success) {
                if (data.queued) {
                    const _qi = typeof getThemedIcon === 'function' ? getThemedIcon('queued') : '📋';
                    showModal(`${_qi} Queued`, `Your bulk scrape has been queued (position ${data.queue_position}). It will start automatically when the current scrape finishes.`);

                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }
                } else {
                    this.resetUI(gameIds.length, data.first_game);
                    this.startPolling();

                    if (typeof exitBulkMode === 'function') {
                        exitBulkMode();
                    } else if (typeof toggleBulkMode === 'function') {
                        const bulkModeBtn = document.getElementById('bulkModeBtn');
                        if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                            toggleBulkMode();
                        }
                    }

                    if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                        const initialData = {
                            running: true,
                            completed: false,
                            job_id: data.job_id,
                            current_game: data.first_game || 'Starting...',
                            system_name: data.system_name || null,
                            total: gameIds.length,
                            current: 0,
                            processed: 0,
                            success: 0,
                            failed: 0,
                            skipped: 0,
                            percent: 0,
                            paused: false
                        };
                        UnifiedToastController.showActiveToast('bulk-scrape', UnifiedToastController.getTypeConfig('bulk-scrape'), initialData);
                        UnifiedToastController.adjustPollingSpeed('bulk-scrape', true);
                        UnifiedToastController.broadcast('job-started', 'bulk-scrape', initialData);
                    }
                }
            } else {
                if (data.error && data.error.includes('already')) {
                    showNotification(data.error, 'warning');
                } else {
                    const _ei2 = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
                    showModal(`${_ei2} Error`, data.error || 'Failed to start bulk scrape');
                }
            }
        } catch (error) {
            console.error('Error starting bulk scrape:', error);
            const _ei3 = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
            showModal(`${_ei3} Error`, 'Network error starting bulk scrape');
        }
    },

    /**
     * Handle poll data received from the toast controller (single shared poller)
     */
    _refreshedCardIds: new Set(),
    _MAX_REFRESHED_IDS: 500,  // Prevent unbounded growth during long scrapes

    handlePollData(data) {
        const el = this.getElements();
        const isModalOpen = el.modal && el.modal.classList.contains('active');

        if (!data.running && !data.completed) {
            this.stopPolling();
            return;
        }

        if (isModalOpen) {
            this.updateUI(data);
        }

        if (data.recently_scraped_ids && data.recently_scraped_ids.length > 0 &&
            typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
            const newIds = data.recently_scraped_ids.filter(id => !this._refreshedCardIds.has(id));
            if (newIds.length > 0) {
                newIds.forEach(id => this._refreshedCardIds.add(id));
                if (this._refreshedCardIds.size > this._MAX_REFRESHED_IDS) {
                    const it = this._refreshedCardIds.values();
                    for (let i = 0; i < 100; i++) it.next();
                    const keep = [];
                    let v = it.next();
                    while (!v.done) { keep.push(v.value); v = it.next(); }
                    this._refreshedCardIds = new Set(keep);
                }
                AllGamesController.refreshCards(newIds);
            }
        }

        if (data.completed) {
            this._refreshedCardIds.clear();
            this.stopPolling();
            if (isModalOpen) {
                this.showResults(data);
            }
        }
    },

    /**
     * Update modal UI with current status
     * @param {Object} data - Status data from backend
     */
    updateUI(data) {
        const el = this.getElements();

        el.currentGame.textContent = data.current_game || 'Processing...';
        el.progress.textContent = formatNumber(data.processing || 1);
        el.total.textContent = formatNumber(data.total || 0);
        el.successLive.textContent = formatNumber(data.success || 0);
        el.failedLive.textContent = formatNumber(data.failed || 0);
        el.skippedLive.textContent = formatNumber(data.skipped || 0);

        const percent = data.percent || 0;
        el.progressFill.style.setProperty('--progress', percent + '%');

        const processed = data.processed || 0;

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ paused: '⏸️', resume: '▶️', cancelled: '❌' }[k] || k);
        if (data.paused) {
            el.status.textContent = `${_ti('paused')} Paused - Click Resume to continue`;
            el.pauseIcon.textContent = _ti('resume');
            el.pauseText.textContent = 'Resume';
            el.pauseBtn.classList.remove('btn-warning');
            el.pauseBtn.classList.add('btn-success');
        } else if (data.cancelled) {
            el.status.textContent = `${_ti('cancelled')} Cancelled`;
        } else {
            el.status.textContent = `Scraped ${formatNumber(processed)} / ${formatNumber(data.total)} - ${percent}%`;
            el.pauseIcon.textContent = _ti('paused');
            el.pauseText.textContent = 'Pause';
            el.pauseBtn.classList.remove('btn-success');
            el.pauseBtn.classList.add('btn-warning');
        }
    },

    /**
     * Show final results
     * @param {Object} data - Final status data
     */
    showResults(data) {
        const el = this.getElements();

        const finalPercent = data.cancelled ? (data.percent || 0) : 100;
        el.progressFill.style.setProperty('--progress', finalPercent + '%');
        el.progress.textContent = formatNumber(data.processed || data.total || 0);
        el.total.textContent = formatNumber(data.total || 0);

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ cancelled: '❌' }[k] || k);
        if (data.cancelled) {
            el.status.textContent = `${_ti('cancelled')} Cancelled by user`;
        } else {
            el.status.textContent = 'Bulk scraping complete!';
            el.currentGame.textContent = 'Done';
        }

        el.successFinal.textContent = formatNumber(data.success || 0);
        el.failedFinal.textContent = formatNumber(data.failed || 0);
        el.skippedFinal.textContent = formatNumber(data.skipped || 0);

        el.results.style.display = 'flex';
        el.resultsLive.style.display = 'none';
        el.footer.style.display = 'flex';
        el.controlsRow.style.display = 'none';
        if (el.closeBtn) el.closeBtn.style.display = 'block';
        if (el.backgroundBtn) el.backgroundBtn.style.display = 'none';
    },

    /**
     * Start polling for status updates
     */
    startPolling() {
        if (!this.pollingInterval) {
            if (typeof UnifiedToastController !== 'undefined') {
                UnifiedToastController.registerPollCallback('bulk-scrape', (data) => this.handlePollData(data));
            }
            this.pollingInterval = true;  // Flag that we're registered
        }
    },

    /**
     * Stop receiving poll updates
     */
    stopPolling() {
        if (this.pollingInterval) {
            this.pollingInterval = null;
            if (typeof UnifiedToastController !== 'undefined') {
                UnifiedToastController.unregisterPollCallback('bulk-scrape');
            }
        }
    },

    /**
     * Toggle pause/resume via backend API
     */
    async togglePause() {
        try {
            const response = await fetch('/api/bulk-scrape-job/status');
            const statusData = await response.json();

            const endpoint = statusData.paused
                ? '/api/bulk-scrape-job/resume'
                : '/api/bulk-scrape-job/pause';

            const actionResponse = await fetch(endpoint, { method: 'POST' });
            const data = await actionResponse.json();

            if (data.success) {
                if (typeof UnifiedToastController !== 'undefined') {
                    UnifiedToastController.pollStatus('bulk-scrape', '/api/bulk-scrape-job/status');
                }
            }
        } catch (e) {
            console.error('Error toggling pause:', e);
        }
    },

    /**
     * Cancel bulk scrape via backend API
     */
    cancel() {
        const _wi2 = typeof getThemedIcon === 'function' ? getThemedIcon('warning') : '⚠️';
        showConfirm(`${_wi2} Cancel Bulk Scrape`, 'Are you sure you want to cancel the bulk scrape?', async () => {
            try {
                const response = await fetch('/api/bulk-scrape-job/cancel', { method: 'POST' });
                const data = await response.json();

                if (data.success) {
                    if (typeof UnifiedToastController !== 'undefined') {
                        UnifiedToastController.pollStatus('bulk-scrape', '/api/bulk-scrape-job/status');
                    }
                }
            } catch (e) {
                console.error('Error cancelling bulk scrape:', e);
            }
        });
    },

    /**
     * Run scrape in background (close modal)
     */
    runInBackground() {
        const el = this.getElements();

        this.stopPolling();

        if (el.modal) {
            el.modal.classList.remove('active');
        }

        if (typeof UnifiedToastController !== 'undefined') {
            UnifiedToastController.adjustPollingSpeed('bulk-scrape', true);
        }

        if (typeof exitBulkMode === 'function') {
            exitBulkMode();
        } else if (typeof toggleBulkMode === 'function') {
            const bulkModeBtn = document.getElementById('bulkModeBtn');
            if (bulkModeBtn && bulkModeBtn.classList.contains('active')) {
                toggleBulkMode();
            }
        }
    },

    /**
     * Close the modal
     */
    closeModal() {
        this.getElements().modal.classList.remove('active');
        this.stopPolling();
    },

    /**
     * Check for running job on page load and resume if needed
     */
    async checkOnLoad() {
        if (localStorage.getItem('showBulkScrapeModal') === 'true') {
            localStorage.removeItem('showBulkScrapeModal');

            try {
                const response = await fetch('/api/bulk-scrape-job/status');
                const data = await response.json();

                if (data.success && data.running && !data.completed) {
                    const el = this.getElements();
                    if (el.modal) {
                        el.modal.classList.add('active');
                        this.startPolling();
                        this.updateUI(data);
                    }
                }
            } catch (e) {
                console.error('Error checking bulk scrape status:', e);
            }
        }

    }
};

RetroDB.BulkScrapeController = BulkScrapeController;
window.BulkScrapeController = BulkScrapeController;

window.toggleBulkPause = function() {
    BulkScrapeController.togglePause();
};

window.cancelBulkScrape = function() {
    BulkScrapeController.cancel();
};

window.runInBackground = function() {
    BulkScrapeController.runInBackground();
};

window.closeBulkScrapeModal = function() {
    BulkScrapeController.closeModal();
};

document.addEventListener('DOMContentLoaded', () => {
    BulkScrapeController.checkOnLoad();
});

})();

(function(){
/**
 * RetroDB Bulk Edit Controller
 * Handles bulk editing of game fields from game list pages.
 * Version: 2.4.0
 */

window.RetroDB = window.RetroDB || {};

const BulkEditController = (function() {
    'use strict';

    let gameIds = [];
    let _abortController = null;

    const APPENDABLE_FIELDS = ['genre', 'publisher', 'developer', 'franchise', 'region', 'game_structure'];

    /**
     * Open the bulk edit modal with the given game IDs
     * @param {number[]} ids - Array of game IDs to edit
     */
    async function open(ids) {
        if (!ids || ids.length === 0) {
            showModal('No Games Selected', 'Please select at least one game to edit.');
            return;
        }

        gameIds = ids;

        if (_abortController) _abortController.abort();
        _abortController = new AbortController();

        const modal = document.getElementById('bulkEditModal');
        if (!modal) return;

        modal.querySelectorAll('select[data-field]').forEach(sel => { sel.value = ''; });
        modal.querySelectorAll('input[data-field]').forEach(inp => { inp.value = ''; });
        modal.querySelectorAll('.bulk-append-toggle').forEach(toggle => { toggle.checked = false; });

        const countEl = document.getElementById('bulkEditCount');
        if (countEl) countEl.textContent = formatNumber(ids.length);

        await Promise.all([
            loadGameStructureOptions(),
            loadGenreOptions(),
            loadPerspectiveOptions(),
            loadDimensionOptions()
        ]);

        modal.classList.add('active');
    }

    /**
     * Load game_structure dropdown options from API
     */
    async function loadGameStructureOptions() {
        const select = document.getElementById('bulkEditGameStructure');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const resp = await fetch('/api/dropdown-options/game_structure', {
                signal: _abortController ? _abortController.signal : undefined
            });
            const data = await resp.json();

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load game structure options:', err);
        }
    }

    /**
     * Load perspective dropdown options from API
     */
    async function loadPerspectiveOptions() {
        const select = document.getElementById('bulkEditPerspective');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const resp = await fetch('/api/dropdown-options/perspective', {
                signal: _abortController ? _abortController.signal : undefined
            });
            const data = await resp.json();

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load perspective options:', err);
        }
    }

    /**
     * Load dimension dropdown options from API
     */
    async function loadDimensionOptions() {
        const select = document.getElementById('bulkEditDimension');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const resp = await fetch('/api/dropdown-options/dimension', {
                signal: _abortController ? _abortController.signal : undefined
            });
            const data = await resp.json();

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load dimension options:', err);
        }
    }

    /**
     * Load genre dropdown options from API
     */
    async function loadGenreOptions() {
        const select = document.getElementById('bulkEditGenre');
        if (!select) return;

        select.innerHTML = '<option value="">-- Don\'t change --</option>';

        try {
            const resp = await fetch('/api/dropdown-options/genre', {
                signal: _abortController ? _abortController.signal : undefined
            });
            const data = await resp.json();

            if (data.success && data.options) {
                data.options.forEach(opt => {
                    const option = document.createElement('option');
                    option.value = opt.value;
                    option.textContent = opt.value;
                    select.appendChild(option);
                });
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('Failed to load genre options:', err);
        }
    }

    /**
     * Collect changed fields from the form
     * @returns {Object} - Object with field names and their new values
     */
    function collectChanges() {
        const modal = document.getElementById('bulkEditModal');
        if (!modal) return {};

        const changes = {};

        modal.querySelectorAll('select[data-field]').forEach(sel => {
            if (sel.value !== '') {
                changes[sel.dataset.field] = sel.value;
            }
        });

        modal.querySelectorAll('input[data-field]').forEach(inp => {
            if (inp.value.trim() !== '') {
                changes[inp.dataset.field] = inp.value.trim();
            }
        });

        return changes;
    }

    /**
     * Collect append modes for applicable fields
     * @returns {Object} - Object mapping field names to 'append' or 'replace'
     */
    function collectAppendModes() {
        const modes = {};
        document.querySelectorAll('.bulk-append-toggle').forEach(toggle => {
            const field = toggle.dataset.field;
            if (field && APPENDABLE_FIELDS.includes(field)) {
                modes[field] = toggle.checked ? 'append' : 'replace';
            }
        });
        return modes;
    }

    /**
     * Apply bulk edit changes
     */
    function apply() {
        const fields = collectChanges();

        if (Object.keys(fields).length === 0) {
            showModal('No Changes', 'Please change at least one field before applying.');
            return;
        }

        const fieldNames = Object.keys(fields).map(f => f.replace(/_/g, ' ')).join(', ');
        const msg = `Update ${formatNumber(gameIds.length)} game${gameIds.length !== 1 ? 's' : ''}?\n\nFields: ${fieldNames}`;

        showConfirm('Confirm Bulk Edit', msg, async function() {
            await sendBulkEdit(fields);
        });
    }

    /**
     * Send bulk edit request to the API
     * @param {Object} fields - Fields to update
     */
    async function sendBulkEdit(fields) {
        const applyBtn = document.getElementById('bulkEditApplyBtn');
        if (applyBtn) {
            applyBtn.disabled = true;
            applyBtn.textContent = 'Applying...';
        }

        try {
            const appendModes = collectAppendModes();

            const fieldModes = {};
            for (const field of Object.keys(fields)) {
                if (appendModes[field]) {
                    fieldModes[field] = appendModes[field];
                }
            }

            const resp = await fetch('/api/games/bulk-edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    game_ids: gameIds,
                    fields: fields,
                    field_modes: fieldModes
                })
            });

            const data = await resp.json();

            if (data.success) {
                close();
                showNotification(`Successfully updated ${formatNumber(data.updated)} games`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showModal('Error', data.error || 'Unknown error occurred.');
            }
        } catch (err) {
            console.error('Bulk edit error:', err);
            showModal('Error', 'Failed to apply bulk edit. Check console for details.');
        } finally {
            if (applyBtn) {
                applyBtn.disabled = false;
                applyBtn.textContent = 'Apply Changes';
            }
        }
    }

    /**
     * Close the bulk edit modal
     */
    function close() {
        const modal = document.getElementById('bulkEditModal');
        if (modal) modal.classList.remove('active');
        gameIds = [];
        if (_abortController) {
            _abortController.abort();
            _abortController = null;
        }
    }

    window.closeBulkEditModal = close;

    return {
        open,
        apply,
        close
    };
})();

RetroDB.BulkEditController = BulkEditController;
window.BulkEditController = BulkEditController;

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

            const response = await fetch(endpoint, { signal: ac.signal });
            this._pollAbortControllers.delete(type);

            if (!response.ok) return; // 404, 500, etc.

            const data = await response.json();

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
                const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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

        fetch(endpoint, { method: 'POST' })
            .then(r => r.json())
            .then(result => {
                if (result.success && !result.queued) {
                    this.removeRAQueuedToast(next);

                    const updatedQueue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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

        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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

        const cancelCall = item.type === 'sync'
            ? `UnifiedToastController.cancelRAQueued('sync', ${item.systemId})`
            : `UnifiedToastController.cancelRAQueued('refresh', ${item.systemId || 'null'})`;

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
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); ${cancelCall}" title="Remove from queue">
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
        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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
                <div class="toast-main" onclick="UnifiedToastController.navigateTo('${type}', '${data.return_url || ''}')">
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
                    <button class="toast-btn pause" onclick="event.stopPropagation(); UnifiedToastController.togglePause('${type}')" title="${isPaused ? 'Resume' : 'Pause'}">
                        <span data-pause-icon>${isPaused ? '▶️' : '⏸️'}</span>
                    </button>
                    ` : ''}
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); UnifiedToastController.cancel('${type}')" title="Cancel">
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
                    const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');
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

        toast.innerHTML = `
            <div class="toast-content queued">
                <div class="toast-main">
                    <div class="toast-icon">${getThemedIcon(type, 'queued')}</div>
                    <div class="toast-info">
                        <div class="toast-title">${config.name} Queued (#${position})</div>
                        <div class="toast-subtitle">${job.system_name || 'Multi-System'}</div>
                        <div class="toast-meta">${this.fmtNum(job.total)} games</div>
                    </div>
                </div>
                <div class="toast-controls">
                    <button class="toast-btn cancel" onclick="event.stopPropagation(); UnifiedToastController.cancelQueued('${type}', '${job.job_id}')" title="Remove from queue">
                        ✕
                    </button>
                </div>
            </div>
        `;

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
                    const statusResp = await fetch('/api/bulk-scrape-job/status');
                    const status = await statusResp.json();
                    endpoint = status.paused ? '/api/bulk-scrape-job/resume' : '/api/bulk-scrape-job/pause';
                    break;
                case 'ra-sync':
                    endpoint = '/api/ra-sync/toggle-pause';
                    break;
                case 'ra-refresh':
                    endpoint = '/api/ra-refresh/toggle-pause';
                    break;
                case 'psn-refresh':
                    const psnResp = await fetch('/api/psn/bulk-refresh/status');
                    const psnStatus = await psnResp.json();
                    endpoint = psnStatus.paused ? '/api/psn/bulk-refresh/resume' : '/api/psn/bulk-refresh/pause';
                    break;
            }

            if (endpoint) {
                await fetch(endpoint, { method: 'POST' });
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
                await fetch(endpoint, { method: 'POST' });
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
                await fetch(`/api/bulk-scrape-job/cancel-queued/${jobId}`, { method: 'POST' });

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
     * Navigate to the appropriate page
     */
    navigateTo(type, returnUrl) {
        if (type === 'bulk-scrape') {
            localStorage.setItem('showBulkScrapeModal', 'true');
        }

        if (returnUrl && window.location.pathname !== returnUrl) {
            window.location.href = returnUrl;
        } else if (type === 'ra-sync' || type === 'ra-refresh') {
            window.location.href = '/achievements';
        } else if (type === 'psn-refresh') {
            window.location.href = '/psn-trophies';
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
        const oldQueue = localStorage.getItem('raSyncQueue');
        if (oldQueue) {
            try {
                const oldItems = JSON.parse(oldQueue);
                if (oldItems.length > 0) {
                    const unifiedQueue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');

                    oldItems.forEach(item => {
                        if (!item.type) item.type = 'sync';
                        if (!unifiedQueue.find(q => q.type === 'sync' && q.systemId === item.systemId)) {
                            unifiedQueue.push(item);
                        }
                    });

                    localStorage.setItem('raOperationsQueue', JSON.stringify(unifiedQueue));
                }
            } catch (e) {
                console.error('Error migrating old queue:', e);
            }
            localStorage.removeItem('raSyncQueue');
        }
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
/**
 * RetroDB Game List Module
 * Shared controllers used by game list pages.
 * Version: 2.1.0
 *
 * Features:
 * - FanartController: Hover-triggered fanart background display
 * - BackToTopController: Scroll-based back-to-top button
 * - RARefreshController: RetroAchievements data refresh for systems
 *
 * Note: SearchController, GameBulkSelection, FilterModalController,
 * GameFilterEngine, PageStateController, GameAlphabetNav, and GameListPage
 * were removed in v2.0.0 — they were unused dead code fully superseded by
 * AllGamesController (all-games-controller.js) for game list pages.
 */

window.RetroDB = window.RetroDB || {};

const FanartController = {
    element: null,
    timeout: null,

    /**
     * Initialize fanart controller
     */
    init() {
        this.element = document.getElementById('fanartBg');
    },

    /**
     * Show fanart background
     * @param {string} fanartPath - Path to fanart image
     */
    show(fanartPath) {
        if (!fanartPath || !this.element) return;
        clearTimeout(this.timeout);
        this.element.style.backgroundImage = `url('/static/images/fanart/${fanartPath}')`;
        this.element.classList.add('active');
    },

    /**
     * Hide fanart background with delay
     */
    hide() {
        if (!this.element) return;
        this.timeout = setTimeout(() => {
            this.element.classList.remove('active');
        }, 300);
    }
};

window.showFanart = (path) => FanartController.show(path);
window.hideFanart = () => FanartController.hide();

const BackToTopController = {
    button: null,
    scrollThreshold: 400,
    _scrollHandler: null,

    /**
     * Initialize back to top button
     */
    init() {
        this.button = document.getElementById('backToTopBtn');
        if (!this.button) return;

        this._scrollHandler = throttle(() => {
            this.updateVisibility();
        }, 100);
        window.addEventListener('scroll', this._scrollHandler, { passive: true });

        this.updateVisibility();

        this._isInit = true;
    },

    /**
     * Update button visibility based on scroll position
     */
    updateVisibility() {
        if (!this.button) return;

        if (window.scrollY > this.scrollThreshold) {
            this.button.classList.add('visible');
        } else {
            this.button.classList.remove('visible');
        }
    },

    /**
     * Scroll to top of page
     */
    scrollToTop() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    /**
     * Clean up event listeners
     */
    destroy() {
        if (this._scrollHandler) {
            window.removeEventListener('scroll', this._scrollHandler);
            this._scrollHandler = null;
        }
    }
};

window.scrollToTop = () => BackToTopController.scrollToTop();

const RARefreshController = {
    /**
     * Refresh RetroAchievements for a system
     * @param {number} systemId - System ID
     * @param {string} systemName - System name for display
     */
    async refreshForSystem(systemId, systemName) {
        const btn = document.getElementById('refreshRABtn');
        if (!btn) return;

        const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ starting: '\u23F3', queued: '\uD83D\uDCCB', running: '\u23F3', error: '\u274C' }[k] || k);
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="filter-icon">${_ti('starting')}</span> Starting...`;
        btn.disabled = true;

        try {
            const response = await fetch(`/api/refresh-retroachievements/${systemId}`, {
                method: 'POST'
            });
            const data = await response.json();

            if (data.success) {
                if (data.queued) {
                    const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');

                    if (!queue.find(q => q.type === 'refresh' && q.systemId === systemId)) {
                        const newItem = {
                            type: 'refresh',
                            systemId: systemId,
                            systemName: systemName || 'Unknown System',
                            gameCount: data.game_count,
                            timestamp: Date.now()
                        };
                        queue.push(newItem);
                        localStorage.setItem('raOperationsQueue', JSON.stringify(queue));

                        if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.addRAOperationToQueue) {
                            UnifiedToastController.addRAOperationToQueue(newItem);
                            UnifiedToastController.adjustPollingSpeed('ra-refresh', true);
                        }
                    }

                    btn.innerHTML = `<span class="filter-icon">${_ti('queued')}</span> Queued`;
                    if (typeof showNotification !== 'undefined') {
                        showNotification('Added to queue - will start when current operation completes', 'info');
                    }
                    return;
                }

                if (typeof UnifiedToastController !== 'undefined' && UnifiedToastController.showActiveToast) {
                    const initialData = {
                        running: true,
                        completed: false,
                        current_system: systemName || 'Unknown System',
                        current_game: 'Starting...',
                        total: data.game_count || 0,
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

                btn.innerHTML = `<span class="filter-icon">${_ti('running')}</span> Running...`;
                if (typeof showNotification !== 'undefined') {
                    showNotification(`Refreshing RA for ${systemName || 'system'}...`, 'info');
                }
            } else {
                if (typeof showModal !== 'undefined') {
                    showModal(`${_ti('error')} Error`, data.error || 'Unknown error');
                }
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        } catch (err) {
            if (typeof showModal !== 'undefined') {
                showModal(`${_ti('error')} Error`, 'Error refreshing RetroAchievements: ' + err.message);
            }
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
};

window.refreshRAForSystem = (systemId, systemName) => RARefreshController.refreshForSystem(systemId, systemName);

RetroDB.FanartController = FanartController;
RetroDB.BackToTopController = BackToTopController;
RetroDB.RARefreshController = RARefreshController;

window.FanartController = FanartController;
window.BackToTopController = BackToTopController;
window.RARefreshController = RARefreshController;

window.addEventListener('beforeunload', () => {
    if (FanartController.timeout) {
        clearTimeout(FanartController.timeout);
        FanartController.timeout = null;
    }
    BackToTopController.destroy();
});

})();

(function(){
/**
 * RetroDB Game Modals Module
 * Handles Game Detail Modal and Game Edit Modal functionality
 * Extracted from base.html for better maintainability
 * Version: 1.22.0
 */

window.RetroDB = window.RetroDB || {};

/** Rating system column mapping */
const _MODAL_RATING_COLS = {
    esrb: 'esrb_rating', pegi: 'pegi_rating', cero: 'cero_rating',
    usk: 'usk_rating', acb: 'acb_rating', fpb: 'fpb_rating',
    grac: 'grac_rating', classind: 'classind_rating'
};

/**
 * Get ALL ratings present on a game (for admin view).
 * @param {Object} game - Game data from API
 * @returns {Array} [{system, value, image, name}, ...]
 */
function _getAllRatingsFromGame(game) {
    const imgMap = window.RATING_IMAGE_MAP || {};
    const keys = window.RATING_SYSTEM_KEYS || Object.keys(_MODAL_RATING_COLS);
    const names = window.RATING_SYSTEM_NAMES || {};
    const ratings = [];
    for (const sysKey of keys) {
        const col = _MODAL_RATING_COLS[sysKey];
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

/**
 * Get the preferred rating for a game, cross-mapping if needed.
 * Uses global RATING_IMAGE_MAP, RATING_TO_TIER, TIER_TO_RATING, RATING_SYSTEM_NAMES.
 * @param {Object} game - Game data from API
 * @returns {Object|null} {value, image, label, crossmapped} or null
 */
function _getPreferredRatingFromGame(game) {
    const pref = window.PREFERRED_RATING_SYSTEM || 'esrb';
    const imgMap = window.RATING_IMAGE_MAP || {};
    const sysNames = window.RATING_SYSTEM_NAMES || {};
    const keys = window.RATING_SYSTEM_KEYS || Object.keys(_MODAL_RATING_COLS);
    const label = sysNames[pref] || pref.toUpperCase();

    const prefCol = _MODAL_RATING_COLS[pref];
    if (prefCol && game[prefCol]) {
        return { value: game[prefCol], image: imgMap[`${pref}:${game[prefCol]}`] || '', label, crossmapped: false };
    }

    const r2t = window.RATING_TO_TIER || {};
    const t2r = window.TIER_TO_RATING || {};
    for (const sysKey of keys) {
        if (sysKey === pref) continue;
        const col = _MODAL_RATING_COLS[sysKey];
        const val = game[col];
        if (val) {
            const tier = r2t[`${sysKey}:${val}`];
            if (tier !== undefined) {
                const mapped = t2r[`${pref}:${tier}`];
                if (mapped) {
                    return { value: mapped, image: imgMap[`${pref}:${mapped}`] || '', label, crossmapped: true };
                }
            }
        }
    }
    return null;
}

/** Build age-rating badge HTML (admin sees all, users see preferred only) */
function _buildAgeRatingBadgesHtml(game) {
    let html = '';
    if (window.IS_ADMIN) {
        const allRatings = _getAllRatingsFromGame(game);
        for (const r of allRatings) {
            const tooltip = `${r.name}: ${r.value}`;
            if (r.image) {
                html += `<span class="game-badge age-rating-badge" title="${escapeHtml(tooltip)}"><img src="/static/images/ratings/${r.image}" alt="${escapeHtml(r.value)}" class="age-rating-img"></span>`;
            } else {
                html += `<span class="game-badge age-rating-badge" title="${escapeHtml(tooltip)}">${escapeHtml(r.name.split(' (')[0])} ${escapeHtml(r.value)}</span>`;
            }
        }
    } else {
        const ageRating = _getPreferredRatingFromGame(game);
        if (ageRating) {
            const tooltip = ageRating.crossmapped ? `${ageRating.label}: ${ageRating.value} (cross-mapped)` : `${ageRating.label}: ${ageRating.value}`;
            if (ageRating.image) {
                html += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${escapeHtml(tooltip)}"><img src="/static/images/ratings/${ageRating.image}" alt="${escapeHtml(ageRating.value)}" class="age-rating-img"></span>`;
            } else {
                html += `<span class="game-badge age-rating-badge${ageRating.crossmapped ? ' crossmapped' : ''}" title="${escapeHtml(tooltip)}">${escapeHtml(ageRating.label.split(' (')[0])} ${escapeHtml(ageRating.value)}</span>`;
            }
        }
    }
    return html;
}

/**
 * Build a game detail URL with the appropriate ?from= breadcrumb param
 * based on the current page path.
 */
function gameDetailUrl(gameId) {
    const path = window.location.pathname;
    let from = '';
    if (path === '/games') from = 'library';
    else if (path.startsWith('/reports')) from = 'rom_reports';
    else if (path.startsWith('/achievements')) from = 'achievements';
    return `/game/${gameId}` + (from ? `?from=${from}` : '');
}

const GameDetailModal = {
    cache: new Map(),
    currentId: null,
    maxCacheSize: 50,
    _screenshots: [],
    _screenshotIndex: 0,

    /**
     * Open the game detail modal
     * @param {number} gameId - The game ID to display
     */
    open(gameId) {
        this.currentId = gameId;
        const modal = document.getElementById('gameDetailModal');
        const loading = document.getElementById('gameDetailLoading');
        const content = document.getElementById('gameDetailContent');

        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        loading.style.display = 'flex';
        content.style.display = 'none';

        if (this.cache.has(gameId)) {
            this.populate(this.cache.get(gameId));
            return;
        }

        fetch(`/api/game/${gameId}/detail`)
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    this.cache.set(gameId, data.game);
                    if (this.cache.size > this.maxCacheSize) {
                        const firstKey = this.cache.keys().next().value;
                        this.cache.delete(firstKey);
                    }
                    this.populate(data.game);
                } else {
                    this.showError(data.error || 'Failed to load game');
                }
            })
            .catch(err => this.showError('Network error'));
    },

    /**
     * Populate the detail modal with game data
     * @param {Object} game - The game data object
     */
    populate(game) {
        const loading = document.getElementById('gameDetailLoading');
        const content = document.getElementById('gameDetailContent');

        document.getElementById('gdmTitle').textContent = game.title;
        document.getElementById('gdmSystem').textContent = game.system_name;

        const yearEl = document.getElementById('gdmYear');
        if (game.release_date) {
            yearEl.textContent = game.release_date.substring(0, 4);
            yearEl.style.display = '';
        } else {
            yearEl.style.display = 'none';
        }

        const playersEl = document.getElementById('gdmPlayers');
        if (game.players) {
            playersEl.textContent = `${game.players} Player${game.players > 1 ? 's' : ''}`;
            playersEl.style.display = '';
        } else {
            playersEl.style.display = 'none';
        }

        const boxart = document.getElementById('gdmBoxart');
        if (game.boxart) {
            boxart.src = `/static/images/boxart/${game.boxart}`;
            boxart.style.display = 'block';
        } else {
            boxart.style.display = 'none';
        }

        const desc = game.description || 'No description available.';
        document.getElementById('gdmDescription').textContent =
            desc.length > 300 ? desc.substring(0, 300) + '...' : desc;

        document.getElementById('gdmDeveloper').textContent = game.developer || '-';
        document.getElementById('gdmPublisher').textContent = game.publisher || '-';
        document.getElementById('gdmGenre').textContent = game.genre || '-';
        document.getElementById('gdmFranchise').textContent = game.franchise || '-';

        const ratingsEl = document.getElementById('gdmRatings');
        let ratingsHtml = _buildAgeRatingBadgesHtml(game);
        if (game.critic_score) {
            const scoreClass = game.critic_score >= 75 ? 'score-good' : (game.critic_score >= 50 ? 'score-mixed' : 'score-bad');
            ratingsHtml += `<span class="game-badge score-badge ${scoreClass}">⭐ ${Math.round(game.critic_score)}</span>`;
        }
        if (game.user_score) {
            const userScoreClass = game.user_score >= 75 ? 'score-good' : (game.user_score >= 50 ? 'score-mixed' : 'score-bad');
            ratingsHtml += `<span class="game-badge score-badge user-score ${userScoreClass}">👤 ${Math.round(game.user_score)}</span>`;
        }
        ratingsEl.innerHTML = ratingsHtml;

        const completionEl = document.getElementById('gdmCompletion');
        if (game.completion_status && game.completion_status !== 'not_started') {
            const completionLabels = {
                'in_progress': 'In Progress',
                'played': 'Played',
                'completed': 'Completed',
                '100_percent': '100%'
            };
            const label = completionLabels[game.completion_status] || game.completion_status;
            completionEl.innerHTML = `<span class="completion-badge status-${game.completion_status}">${label}</span>`;
            completionEl.style.display = 'block';
        } else {
            completionEl.style.display = 'none';
        }

        const raEl = document.getElementById('gdmAchievements');
        let achHtml = '';

        if (game.achievement_total > 0 && game.achievement_earned != null) {
            const earned = game.achievement_earned;
            const pct = Math.round((earned / game.achievement_total) * 100);
            const pctClass = pct >= 100 ? 'ach-complete' : pct >= 50 ? 'ach-good' : 'ach-low';
            const srcImages = { ra: '/static/images/trophies/ra.webp', steam: '/static/images/trophies/steam.png', xbox: '/static/images/trophies/xbox.png' };
            const srcLabels = { ra: 'RetroAchievements', steam: 'Steam', xbox: 'Xbox' };
            const src = game.achievement_source || 'ra';
            const iconImg = `<img class="ach-icon" src="${srcImages[src] || srcImages.ra}" alt="${srcLabels[src] || 'Achievements'}">`;
            const label = srcLabels[src] || 'Achievements';
            achHtml += `<span class="game-badge achievement-progress ${src} ${pctClass}" title="${label}: ${earned}/${game.achievement_total} (${pct}%)">${iconImg} ${earned}/${game.achievement_total}<span class="ach-bar"><span class="ach-fill" style="width:${pct}%"></span></span></span>`;
        } else if (game.has_retroachievements && game.ra_achievement_count) {
            achHtml += `<span class="ra-badge-modal">${getThemedIcon('ra-sync', '🏆')} ${formatNumber(game.ra_achievement_count)} Achievements</span>`;
        }

        if (game.psn_total > 0 && game.psn_earned != null) {
            const psnPct = Math.round((game.psn_earned / game.psn_total) * 100);
            const psnClass = psnPct >= 100 ? 'ach-complete' : psnPct >= 50 ? 'ach-good' : 'ach-low';
            achHtml += `<span class="game-badge achievement-progress psn ${psnClass}" title="PSN Trophies: ${game.psn_earned}/${game.psn_total} (${psnPct}%)"><img class="ach-icon" src="/static/images/trophies/platinum.png" alt="PSN"> ${game.psn_earned}/${game.psn_total}<span class="ach-bar"><span class="ach-fill" style="width:${psnPct}%"></span></span></span>`;
        }

        if (game.rpcs3_total > 0 && game.rpcs3_earned != null) {
            const rpcs3Pct = Math.round((game.rpcs3_earned / game.rpcs3_total) * 100);
            const rpcs3Class = rpcs3Pct >= 100 ? 'ach-complete' : rpcs3Pct >= 50 ? 'ach-good' : 'ach-low';
            achHtml += `<span class="game-badge achievement-progress rpcs3 ${rpcs3Class}" title="RPCS3 Trophies: ${game.rpcs3_earned}/${game.rpcs3_total} (${rpcs3Pct}%)"><img class="ach-icon" src="/static/images/trophies/rpcs3.png" alt="RPCS3"> ${game.rpcs3_earned}/${game.rpcs3_total}<span class="ach-bar"><span class="ach-fill" style="width:${rpcs3Pct}%"></span></span></span>`;
        }

        if (achHtml) {
            raEl.innerHTML = achHtml;
            raEl.style.display = 'flex';
        } else {
            raEl.style.display = 'none';
        }

        const ssEl = document.getElementById('gdmScreenshots');
        if (game.screenshots && game.screenshots.length > 0) {
            this._screenshots = game.screenshots.map(s =>
                `/static/images/screenshots/${encodeURIComponent(s)}`
            );
            ssEl.innerHTML = this._screenshots.map((src, i) =>
                `<img src="${src}" alt="" class="gdm-screenshot" data-index="${i}" loading="lazy">`
            ).join('');
            ssEl.style.display = 'flex';

            if (!ssEl._delegated) {
                ssEl.addEventListener('click', (e) => {
                    const img = e.target.closest('.gdm-screenshot');
                    if (img && img.dataset.index != null) {
                        this.openLightbox(parseInt(img.dataset.index));
                    }
                });
                ssEl._delegated = true;
            }
        } else {
            this._screenshots = [];
            ssEl.style.display = 'none';
        }

        const videoEl = document.getElementById('gdmVideo');
        const videoPlayer = document.getElementById('gdmVideoPlayer');
        if (game.video && videoEl && videoPlayer) {
            const ext = game.video.split('.').pop();
            videoPlayer.innerHTML = `<source src="/static/videos/${encodeURIComponent(game.video)}" type="video/${ext}">`;
            videoPlayer.load();
            videoEl.style.display = 'block';
        } else if (videoEl) {
            videoEl.style.display = 'none';
            if (videoPlayer) {
                videoPlayer.pause();
                videoPlayer.innerHTML = '';
            }
        }

        document.getElementById('gdmViewFull').href = gameDetailUrl(game.id);

        const aiFillBtn = document.getElementById('gdmAiFill');
        if (aiFillBtn) {
            aiFillBtn.style.display = window.AI_SCRAPER_ENABLED ? '' : 'none';
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    },

    /**
     * Show an error message in the modal
     * @param {string} message - The error message
     */
    showError(message) {
        document.getElementById('gameDetailLoading').innerHTML =
            `<p style="color: var(--neon-red);">${escapeHtml(message)}</p>
             <button class="btn btn-secondary" onclick="closeGameDetailModal()">Close</button>`;
    },

    /**
     * Open the screenshot lightbox at a given index
     * @param {number} index - Screenshot index
     */
    openLightbox(index) {
        this._screenshotIndex = index;
        this._updateLightbox();
        const lb = document.getElementById('gdmScreenshotLightbox');
        if (lb) lb.classList.add('active');
    },

    /**
     * Close the screenshot lightbox
     */
    closeLightbox() {
        const lb = document.getElementById('gdmScreenshotLightbox');
        if (lb) lb.classList.remove('active');
    },

    /**
     * Navigate screenshots in the lightbox
     * @param {number} direction - -1 for prev, 1 for next
     */
    navigateScreenshot(direction) {
        const newIndex = this._screenshotIndex + direction;
        if (newIndex >= 0 && newIndex < this._screenshots.length) {
            this._screenshotIndex = newIndex;
            this._updateLightbox();
        }
    },

    /**
     * Update the lightbox image and counter
     */
    _updateLightbox() {
        const img = document.getElementById('gdmLightboxImage');
        const counter = document.getElementById('gdmLightboxCounter');
        if (img) img.src = this._screenshots[this._screenshotIndex] || '';
        if (counter) counter.textContent = `${this._screenshotIndex + 1} / ${this._screenshots.length}`;

        const prev = document.querySelector('.gdm-lightbox-nav.prev');
        const next = document.querySelector('.gdm-lightbox-nav.next');
        if (prev) prev.style.opacity = this._screenshotIndex === 0 ? '0.3' : '1';
        if (next) next.style.opacity = this._screenshotIndex === this._screenshots.length - 1 ? '0.3' : '1';
    },

    /**
     * Close the detail modal
     */
    close() {
        const modal = document.getElementById('gameDetailModal');
        modal.classList.remove('active');
        document.body.style.overflow = '';
        this.currentId = null;

        const videoPlayer = document.getElementById('gdmVideoPlayer');
        if (videoPlayer) {
            videoPlayer.pause();
            videoPlayer.removeAttribute('src');
            videoPlayer.innerHTML = '';
            videoPlayer.load();  // Abort pending network request & release buffers
        }

        this.closeLightbox();
    },

    /**
     * Clear the cache (e.g., on bfcache restore)
     */
    clearCache() {
        this.cache.clear();
    }
};

const HLTBManager = {
    pendingData: {},  // Keyed by context name

    /**
     * Lookup HLTB data for a given context
     * @param {Object} ctx - Context configuration object
     */
    lookup(ctx) {
        const query = document.getElementById(ctx.searchInputId)?.value?.trim();
        if (!query) {
            showNotification('Please enter a game title', 'warning');
            return;
        }

        const btn = document.getElementById(ctx.lookupBtnId);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '⏳ Searching...';
        }

        const pendingDiv = document.getElementById(ctx.pendingDivId);
        const savedDiv = document.getElementById(ctx.savedDivId);
        const searchingDiv = document.getElementById(ctx.searchingDivId);
        const resultDiv = document.getElementById(ctx.resultDivId);
        const errorDiv = document.getElementById(ctx.errorDivId);

        if (pendingDiv) pendingDiv.style.display = 'block';
        if (savedDiv) savedDiv.style.display = 'none';
        if (searchingDiv) searchingDiv.style.display = 'flex';
        if (resultDiv) resultDiv.style.display = 'none';
        if (errorDiv) errorDiv.style.display = 'none';

        fetch('/api/hltb/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                system_folder: ctx.systemFolder || '',
                year: ctx.year || '',
                game_id: ctx.gameId || null
            })
        })
        .then(r => r.json())
        .then(data => {
            if (searchingDiv) searchingDiv.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🔍 Lookup HLTB';
            }

            if (data.success && data.result) {
                HLTBManager.pendingData[ctx.name] = {
                    hltb_id: data.result.hltb_id || null,
                    match_name: data.result.match_name || query,
                    match_platform: data.result.match_platform || '',
                    confidence: data.result.confidence || 0,
                    platform_mismatch: data.result.platform_mismatch || false,
                    main_story: data.result.main_story || '--',
                    main_extra: data.result.main_extra || '--',
                    completionist: data.result.completionist || '--',
                    release_year: data.result.release_year || null,
                    developer: data.result.developer || null,
                    search_term_used: data.result.search_term_used || null,
                    matched_via_alternate: !!data.result.matched_via_alternate
                };

                const pending = HLTBManager.pendingData[ctx.name];
                const confidence = Math.round(pending.confidence);

                const matchTitle = document.getElementById(ctx.matchTitleId);
                const matchPlatform = document.getElementById(ctx.matchPlatformId);
                const matchConfidence = document.getElementById(ctx.matchConfidenceId);
                const matchHeader = document.getElementById(ctx.matchHeaderId);

                if (matchTitle) matchTitle.textContent = pending.match_name;
                if (matchPlatform) matchPlatform.textContent = pending.match_platform;
                if (matchConfidence) matchConfidence.textContent = confidence > 0 ? `${confidence}% match` : '';

                if (matchHeader) {
                    let headerHtml = `<span class="hltb-match-title">${escapeHtml(pending.match_name)}</span>`;
                    if (pending.match_platform) {
                        headerHtml += `<span class="hltb-match-platform">${escapeHtml(pending.match_platform)}</span>`;
                    }
                    if (pending.platform_mismatch) {
                        headerHtml += `<span class="hltb-match-warning">Platform not found</span>`;
                    }
                    if (pending.release_year) {
                        headerHtml += `<span class="hltb-match-year">${escapeHtml(String(pending.release_year))}</span>`;
                    }
                    if (pending.developer) {
                        headerHtml += `<span class="hltb-match-developer">${escapeHtml(pending.developer)}</span>`;
                    }
                    if (confidence > 0) {
                        headerHtml += `<span class="hltb-match-confidence">${confidence}% match</span>`;
                    }
                    if (pending.matched_via_alternate && pending.search_term_used) {
                        headerHtml += `<span class="hltb-match-alt-notice" title="Matched using this alternate/regional title — confirm it refers to the same game before saving.">⚡ via &ldquo;${escapeHtml(pending.search_term_used)}&rdquo;</span>`;
                    }
                    matchHeader.innerHTML = headerHtml;
                }

                const mainEl = document.getElementById(ctx.mainTimeId);
                const extrasEl = document.getElementById(ctx.extrasTimeId);
                const completeEl = document.getElementById(ctx.completeTimeId);

                if (mainEl) mainEl.textContent = pending.main_story;
                if (extrasEl) extrasEl.textContent = pending.main_extra;
                if (completeEl) completeEl.textContent = pending.completionist;

                if (resultDiv) resultDiv.style.display = 'block';
                if (pending.matched_via_alternate && pending.search_term_used) {
                    showNotification(
                        `Matched via alternate title "${pending.search_term_used}" — HLTB shows it as "${pending.match_name}". Confirm before saving.`,
                        'warning',
                        9000
                    );
                } else {
                    showNotification('Match found - please confirm to save', 'info');
                }
            } else {
                if (pendingDiv && !resultDiv) pendingDiv.style.display = 'none';
                if (errorDiv) {
                    errorDiv.textContent = data.error || 'No results found on HowLongToBeat';
                    errorDiv.style.display = 'block';
                } else {
                    showNotification(data.error || 'No HLTB data found', 'warning');
                }
            }
        })
        .catch(err => {
            if (searchingDiv) searchingDiv.style.display = 'none';
            if (pendingDiv && !resultDiv) pendingDiv.style.display = 'none';
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🔍 Lookup HLTB';
            }
            if (errorDiv) {
                errorDiv.textContent = 'Error connecting to HowLongToBeat';
                errorDiv.style.display = 'block';
            } else {
                showNotification('Error looking up HLTB', 'error');
            }
        });
    },

    /**
     * Save pending HLTB data
     * @param {Object} ctx - Context configuration object
     */
    save(ctx) {
        const pending = HLTBManager.pendingData[ctx.name];
        if (!pending) return;

        const playtime = `Main: ${pending.main_story} | Main+Extras: ${pending.main_extra} | 100%: ${pending.completionist}`;

        const savePromise = ctx.customSave
            ? ctx.customSave(pending, playtime)
            : fetch(`/api/hltb-save/${ctx.gameId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    playtime: playtime,
                    match_name: pending.match_name,
                    match_platform: pending.match_platform,
                    confidence: pending.confidence
                })
            }).then(r => r.json());

        savePromise
        .then(data => {
            if (data.success) {
                HLTBManager.updateSavedDisplay(ctx, pending);

                const pendingDiv = document.getElementById(ctx.pendingDivId);
                const savedDiv = document.getElementById(ctx.savedDivId);
                if (pendingDiv) pendingDiv.style.display = 'none';
                if (savedDiv) savedDiv.style.display = 'block';

                if (ctx.onSave) ctx.onSave(pending, playtime);

                HLTBManager.pendingData[ctx.name] = null;
                showNotification('HLTB data saved', 'success');
            } else {
                showNotification('Failed to save HLTB: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(err => showNotification('Error saving HLTB data', 'error'));
    },

    /**
     * Update the saved display section
     * @param {Object} ctx - Context configuration object
     * @param {Object} data - HLTB data to display
     */
    updateSavedDisplay(ctx, data) {
        const savedDiv = document.getElementById(ctx.savedDivId);
        if (!savedDiv || !data) return;

        const confidence = Math.round(data.confidence || 0);
        let headerHtml = '';
        if (data.match_name) {
            headerHtml = `<div class="hltb-match-header">
                <span class="hltb-match-title">${escapeHtml(data.match_name)}</span>
                ${data.match_platform ? `<span class="hltb-match-platform">${escapeHtml(data.match_platform)}</span>` : ''}
                ${data.platform_mismatch ? `<span class="hltb-match-warning">Platform not found</span>` : ''}
                ${data.release_year ? `<span class="hltb-match-year">${escapeHtml(String(data.release_year))}</span>` : ''}
                ${data.developer ? `<span class="hltb-match-developer">${escapeHtml(data.developer)}</span>` : ''}
                ${confidence > 0 ? `<span class="hltb-match-confidence">${confidence}% match</span>` : ''}
            </div>`;
        }

        savedDiv.innerHTML = `
            ${headerHtml}
            <div class="hltb-results">
                <div class="hltb-time-row">
                    <span class="hltb-label">Main Story</span>
                    <span class="hltb-value">${data.main_story || '--'}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Main + Extras</span>
                    <span class="hltb-value">${data.main_extra || '--'}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Completionist</span>
                    <span class="hltb-value">${data.completionist || '--'}</span>
                </div>
            </div>
            <div class="hltb-actions" style="margin-top: var(--spacing-sm);">
                <button class="btn btn-sm btn-danger" onclick="${ctx.clearFnName}()">✕ Clear</button>
            </div>
        `;
    },

    /**
     * Cancel pending lookup
     * @param {Object} ctx - Context configuration object
     */
    cancel(ctx) {
        HLTBManager.pendingData[ctx.name] = null;
        const pendingDiv = document.getElementById(ctx.pendingDivId);
        const savedDiv = document.getElementById(ctx.savedDivId);
        if (pendingDiv) pendingDiv.style.display = 'none';
        if (ctx.hasSavedData && savedDiv) savedDiv.style.display = 'block';
        showNotification('HLTB lookup cancelled', 'info');
    },

    /**
     * Clear saved HLTB data
     * @param {Object} ctx - Context configuration object
     */
    clear(ctx) {
        showConfirm('🗑️ Clear HLTB Data', 'Clear HLTB data for this game?', () => {
            const clearPromise = ctx.customClear
                ? ctx.customClear()
                : fetch(`/api/hltb-clear/${ctx.gameId}`, { method: 'POST' }).then(r => r.json());

            clearPromise
            .then(data => {
                if (data.success) {
                    const savedDiv = document.getElementById(ctx.savedDivId);
                    if (savedDiv) savedDiv.style.display = 'none';
                    if (ctx.onClear) ctx.onClear();
                    showNotification('HLTB data cleared', 'success');
                } else {
                    showNotification('Failed to clear HLTB: ' + (data.error || 'Unknown error'), 'error');
                }
            })
            .catch(err => showNotification('Error clearing HLTB data', 'error'));
        });
    }
};

const GameEditModal = {
    currentData: null,
    pendingHltbData: null,
    _dropdownAbortController: null,

    genreOptions: [],
    modesOptions: [],
    saveTypeOptions: [],
    gameStructureOptions: [],
    perspectiveOptions: [],
    dimensionOptions: [],
    controllerOptions: { defaults: [], others: [] },

    hltbContext: {
        name: 'gem',
        searchInputId: 'gemHltbSearchQuery',
        lookupBtnId: 'gemHltbLookupBtn',
        pendingDivId: 'gemHltbPending',
        savedDivId: 'gemHltbSaved',
        searchingDivId: 'gemHltbSearching',
        resultDivId: 'gemHltbResult',
        errorDivId: 'gemHltbError',
        matchTitleId: 'gemHltbMatchTitle',
        matchPlatformId: 'gemHltbMatchPlatform',
        matchConfidenceId: 'gemHltbMatchConfidence',
        mainTimeId: 'gemHltbMain',
        extrasTimeId: 'gemHltbExtras',
        completeTimeId: 'gemHltbComplete',
        clearFnName: 'clearHltbFromModal',
        get gameId() { return GameEditModal.currentData?.id; },
        get systemFolder() { return GameEditModal.currentData?.system_folder || ''; },
        get year() { const rd = GameEditModal.currentData?.release_date; return rd ? rd.substring(0, 4) : ''; },
        get hasSavedData() { return !!GameEditModal.currentData?.playtime_estimate; },
        onSave: function(pending, playtime) {
            if (GameEditModal.currentData) {
                GameEditModal.currentData.playtime_estimate = playtime;
                GameEditModal.currentData.hltb_match_name = pending.match_name;
                GameEditModal.currentData.hltb_match_platform = pending.match_platform;
                GameEditModal.currentData.hltb_match_confidence = pending.confidence;
                GameDetailModal.cache.set(GameEditModal.currentData.id, GameEditModal.currentData);
            }
        },
        onClear: function() {
            if (GameEditModal.currentData) {
                GameEditModal.currentData.playtime_estimate = null;
                GameEditModal.currentData.hltb_match_name = null;
                GameEditModal.currentData.hltb_match_platform = null;
                GameEditModal.currentData.hltb_match_confidence = null;
                GameDetailModal.cache.set(GameEditModal.currentData.id, GameEditModal.currentData);
            }
        }
    },

    /**
     * Open the game edit modal
     */
    open() {
        if (!GameDetailModal.currentId) return;

        const editModal = document.getElementById('gameEditModal');
        const game = GameDetailModal.cache.get(GameDetailModal.currentId);

        if (!game) {
            console.error('Game data not in cache');
            return;
        }

        if (this._dropdownAbortController) this._dropdownAbortController.abort();
        this._dropdownAbortController = new AbortController();

        this.currentData = game;

        document.getElementById('gemTitle').textContent = `Edit: ${game.title}`;

        this.switchTab('quick');

        const completionSelect = document.getElementById('gemCompletionStatus');
        completionSelect.value = game.completion_status || 'not_started';

        this.updateHltbDisplay(game);

        document.getElementById('gemTitle_field').value = game.title || '';
        document.getElementById('gemSortTitle').value = game.sort_title || '';
        document.getElementById('gemFranchise').value = game.franchise || '';
        this.initFranchiseToggle(game.franchise || '');
        document.getElementById('gemSimilarGames').value = game.similar_games || '';
        document.getElementById('gemEdition').value = game.edition || '';

        document.getElementById('gemReleaseDate').value = game.release_date || '';
        document.getElementById('gemRegion').value = game.region || '';
        document.getElementById('gemPublisher').value = game.publisher || '';
        document.getElementById('gemDeveloper').value = game.developer || '';

        this.initGenreTags(game.genre || '');
        this.loadGenreDropdown();
        this.initModesTags(game.modes || '');
        this.loadModesDropdown();
        document.getElementById('gemPlayers').value = game.players || 1;
        this.initGameStructureTags(game.game_structure || '');
        this.loadGameStructureDropdown();
        this.initPerspectiveTags(game.perspective || '');
        this.loadPerspectiveDropdown();
        this.initDimensionTags(game.dimension || '');
        this.loadDimensionDropdown();
        this.initCampaignToggle(game.campaign);

        this.initControllerTags(game.controller_support || '');
        this.loadControllerDropdown(game.system_id);
        this.initSaveTypeTags(game.save_type || '');
        this.loadSaveTypeDropdown();
        this.initExclusiveToggle(game.other_platforms || '');
        document.getElementById('gemEsrbRating').value = game.esrb_rating || '';
        document.getElementById('gemPegiRating').value = game.pegi_rating || '';
        document.getElementById('gemCeroRating').value = game.cero_rating || '';
        document.getElementById('gemUskRating').value = game.usk_rating || '';
        document.getElementById('gemAcbRating').value = game.acb_rating || '';
        document.getElementById('gemFpbRating').value = game.fpb_rating || '';
        document.getElementById('gemGracRating').value = game.grac_rating || '';
        document.getElementById('gemClassindRating').value = game.classind_rating || '';

        document.getElementById('gemDescription').value = game.description || '';

        document.getElementById('gemFullEdit').href = gameDetailUrl(game.id);

        document.getElementById('gemHltbSearchQuery').value = game.title || '';
        document.getElementById('gemHltbPending').style.display = 'none';
        document.getElementById('gemHltbLookupBtn').disabled = false;
        document.getElementById('gemHltbLookupBtn').innerHTML = '🔍 Lookup HLTB';
        this.pendingHltbData = null;

        editModal.classList.add('active');
    },

    /**
     * Switch to a specific tab
     * @param {string} tabId - The tab ID to switch to
     */
    switchTab(tabId) {
        document.querySelectorAll('.gem-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabId);
        });

        document.querySelectorAll('.gem-tab-content').forEach(content => {
            content.classList.toggle('active', content.id === 'gemTab' + tabId.charAt(0).toUpperCase() + tabId.slice(1));
        });
    },

    /**
     * Generate sort title from title
     */
    generateSortTitle() {
        const titleField = document.getElementById('gemTitle_field');
        const sortTitleField = document.getElementById('gemSortTitle');

        if (!titleField.value) return;

        let sortTitle = titleField.value.trim();

        const articles = ['the ', 'a ', 'an '];
        const lowerTitle = sortTitle.toLowerCase();
        for (const article of articles) {
            if (lowerTitle.startsWith(article)) {
                sortTitle = sortTitle.substring(article.length);
                break;
            }
        }

        const romanMap = [
            ['XVIII', '18'],
            ['XVII', '17'], ['XIII', '13'], ['VIII', '8'],
            ['XVI', '16'], ['XIV', '14'], ['XII', '12'], ['XIX', '19'], ['VII', '7'], ['III', '3'],
            ['XV', '15'], ['XI', '11'], ['XX', '20'], ['VI', '6'], ['IV', '4'], ['IX', '9'], ['II', '2'],
            ['X', '10'], ['V', '5'], ['I', '1']
        ];

        const singleLetterRomans = new Set(['I', 'V', 'X']);

        for (const [roman, arabic] of romanMap) {
            const padded = arabic.padStart(2, '0');
            if (singleLetterRomans.has(roman)) {
                sortTitle = sortTitle.replace(new RegExp('(?<![-\\w])' + roman + '(?![-\\w])', 'g'), padded);
            } else {
                sortTitle = sortTitle.replace(new RegExp('\\b' + roman + '\\b', 'g'), padded);
            }
        }

        sortTitle = sortTitle.replace(/\b(\d+)\b/g, (match) => {
            return match.length === 1 ? match.padStart(2, '0') : match;
        });

        sortTitleField.value = sortTitle;
    },

    /**
     * Save game edits
     */
    save() {
        if (!this.currentData) return;

        const formData = {
            title: document.getElementById('gemTitle_field').value.trim(),
            sort_title: document.getElementById('gemSortTitle').value.trim(),
            franchise: document.getElementById('gemFranchise').value.trim(),
            similar_games: document.getElementById('gemSimilarGames').value.trim(),
            edition: document.getElementById('gemEdition').value.trim(),
            release_date: document.getElementById('gemReleaseDate').value.trim(),
            region: document.getElementById('gemRegion').value.trim(),
            publisher: document.getElementById('gemPublisher').value.trim(),
            developer: document.getElementById('gemDeveloper').value.trim(),
            genre: document.getElementById('gemGenreHidden').value.trim(),
            modes: document.getElementById('gemModesHidden').value.trim(),
            players: parseInt(document.getElementById('gemPlayers').value) || 1,
            game_structure: document.getElementById('gemGameStructureHidden').value.trim(),
            perspective: document.getElementById('gemPerspectiveHidden').value.trim(),
            dimension: document.getElementById('gemDimensionHidden').value.trim(),
            campaign: document.getElementById('gemCampaign').value,
            controller_support: document.getElementById('gemControllerHidden').value.trim(),
            save_type: document.getElementById('gemSaveTypeHidden').value.trim(),
            other_platforms: this.getOtherPlatformsValue(),
            esrb_rating: document.getElementById('gemEsrbRating').value,
            pegi_rating: document.getElementById('gemPegiRating').value,
            cero_rating: document.getElementById('gemCeroRating').value,
            usk_rating: document.getElementById('gemUskRating').value,
            acb_rating: document.getElementById('gemAcbRating').value,
            fpb_rating: document.getElementById('gemFpbRating').value,
            grac_rating: document.getElementById('gemGracRating').value,
            classind_rating: document.getElementById('gemClassindRating').value,
            description: document.getElementById('gemDescription').value.trim()
        };

        const saveBtn = document.querySelector('.gem-footer-right .btn-primary');
        const originalText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<span class="btn-icon">⏳</span> Saving...';
        saveBtn.disabled = true;

        fetch(`/api/game/${this.currentData.id}/edit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        })
        .then(r => r.json())
        .then(data => {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;

            if (data.success) {
                GameDetailModal.cache.delete(this.currentData.id);

                document.getElementById('gdmTitle').textContent = formData.title;
                document.getElementById('gdmDeveloper').textContent = formData.developer || '-';
                document.getElementById('gdmPublisher').textContent = formData.publisher || '-';
                document.getElementById('gdmGenre').textContent = formData.genre || '-';
                document.getElementById('gdmFranchise').textContent = formData.franchise || '-';

                if (formData.description) {
                    const desc = formData.description;
                    document.getElementById('gdmDescription').textContent =
                        desc.length > 300 ? desc.substring(0, 300) + '...' : desc;
                }

                const ratingsEl = document.getElementById('gdmRatings');
                let ratingsHtml = _buildAgeRatingBadgesHtml(formData);
                if (this.currentData.critic_score) {
                    const scoreClass = this.currentData.critic_score >= 75 ? 'score-good' : (this.currentData.critic_score >= 50 ? 'score-mixed' : 'score-bad');
                    ratingsHtml += `<span class="game-badge score-badge ${scoreClass}">⭐ ${Math.round(this.currentData.critic_score)}</span>`;
                }
                ratingsEl.innerHTML = ratingsHtml;

                if (typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
                    AllGamesController.refreshCards(this.currentData.id);
                }

                this.close();

                const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ save: '✅', error: '❌' }[k] || k);
                if (typeof showModal === 'function') {
                    showModal(`${_ti('save')} Saved`, 'Game details updated successfully.');
                }
            } else {
                const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ error: '❌' }[k] || k);
                showModal(`${_ti('error')} Save Failed`, 'Failed to save: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            saveBtn.innerHTML = originalText;
            saveBtn.disabled = false;
            const _ti = typeof getThemedIcon === 'function' ? getThemedIcon : (k) => ({ error: '❌' }[k] || k);
            showModal(`${_ti('error')} Error`, 'Error saving game: ' + err.message);
        });
    },

    /**
     * Close the edit modal
     */
    close() {
        const editModal = document.getElementById('gameEditModal');
        editModal.classList.remove('active');
        this.currentData = null;
        this.pendingHltbData = null;
        if (this._dropdownAbortController) {
            this._dropdownAbortController.abort();
            this._dropdownAbortController = null;
        }
    },

    /**
     * Update the game card in the page after saving
     * @param {number} gameId - The game ID
     * @param {Object} formData - The updated form data
     */
    updateGameCardInPage(gameId, formData) {
        const card = document.querySelector(`.game-card-new[data-game-id="${gameId}"]`);
        if (!card) return;

        const titleEl = card.querySelector('.game-card-title');
        if (titleEl && formData.title) {
            titleEl.textContent = formData.title;
        }

        card.querySelectorAll('.meta-item').forEach(item => {
            const label = item.querySelector('.meta-label');
            const value = item.querySelector('.meta-value');
            if (!label || !value) return;

            const labelText = label.textContent;
            if (labelText === 'Genre' && formData.genre !== undefined) {
                if (formData.genre) {
                    value.textContent = formData.genre.split(',')[0].trim();
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Series' && formData.franchise !== undefined) {
                if (formData.franchise) {
                    value.textContent = formData.franchise.substring(0, 20) + (formData.franchise.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Developer' && formData.developer !== undefined) {
                if (formData.developer) {
                    const dev = formData.developer.split(',')[0].trim();
                    value.textContent = dev.substring(0, 20) + (dev.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            } else if (labelText === 'Publisher' && formData.publisher !== undefined) {
                if (formData.publisher) {
                    const pub = formData.publisher.split(',')[0].trim();
                    value.textContent = pub.substring(0, 20) + (pub.length > 20 ? '...' : '');
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            }
        });

        const existingAgeBadge = card.querySelector('.game-badge.age-rating-badge');
        const updatedRating = _getPreferredRatingFromGame(formData);
        if (updatedRating) {
            const tooltip = updatedRating.crossmapped ? `${updatedRating.label}: ${updatedRating.value} (cross-mapped)` : `${updatedRating.label}: ${updatedRating.value}`;
            let badgeHtml;
            if (updatedRating.image) {
                badgeHtml = `<img src="/static/images/ratings/${updatedRating.image}" alt="${escapeHtml(updatedRating.value)}" class="age-rating-img">`;
            } else {
                badgeHtml = `${escapeHtml(updatedRating.label.split(' (')[0])} ${escapeHtml(updatedRating.value)}`;
            }
            if (existingAgeBadge) {
                existingAgeBadge.className = `game-badge age-rating-badge${updatedRating.crossmapped ? ' crossmapped' : ''}`;
                existingAgeBadge.title = tooltip;
                existingAgeBadge.innerHTML = badgeHtml;
            } else {
                const badgeContainer = card.querySelector('.rating-badges');
                if (badgeContainer) {
                    const completionBadge = badgeContainer.querySelector('.game-badge.completion');
                    const newBadge = document.createElement('span');
                    newBadge.className = `game-badge age-rating-badge${updatedRating.crossmapped ? ' crossmapped' : ''}`;
                    newBadge.title = tooltip;
                    newBadge.innerHTML = badgeHtml;
                    if (completionBadge) {
                        completionBadge.after(newBadge);
                    } else {
                        badgeContainer.insertBefore(newBadge, badgeContainer.firstChild);
                    }
                }
            }
        } else if (existingAgeBadge) {
            existingAgeBadge.remove();
        }

        if (typeof window.relayoutMasonry === 'function') {
            requestAnimationFrame(() => window.relayoutMasonry());
        }
    },

    /**
     * Update HLTB display in the edit modal
     * @param {Object} game - The game data
     */
    updateHltbDisplay(game) {
        const savedDiv = document.getElementById('gemHltbSaved');
        let display = document.getElementById('gemHltbDisplay');

        if (!display && savedDiv) {
            savedDiv.innerHTML = `
                <div id="gemHltbDisplay" class="hltb-compact"></div>
                <div class="hltb-actions" style="margin-top: var(--spacing-sm);">
                    <button class="btn btn-danger btn-sm" onclick="clearHltbFromModal()">✕ Clear</button>
                </div>`;
            display = document.getElementById('gemHltbDisplay');
        }

        if (!display || !savedDiv) return;

        if (game.playtime_estimate) {
            const parts = game.playtime_estimate.split(' | ');
            const times = { main: '--', extras: '--', complete: '--' };

            parts.forEach(part => {
                const [key, val] = part.split(': ');
                if (key === 'Main') times.main = val;
                else if (key === 'Main+Extras') times.extras = val;
                else if (key === '100%') times.complete = val;
            });

            let matchHeader = '';
            if (game.hltb_match_name) {
                const confidence = game.hltb_match_confidence ? Math.min(Math.round(game.hltb_match_confidence * 100), 100) : null;
                matchHeader = `
                    <div class="hltb-match-header">
                        <span class="hltb-match-title">${escapeHtml(game.hltb_match_name)}</span>
                        ${game.hltb_match_platform ? `<span class="hltb-match-platform">${escapeHtml(game.hltb_match_platform)}</span>` : ''}
                        ${confidence ? `<span class="hltb-match-confidence">${confidence}% match</span>` : ''}
                    </div>`;
            }

            display.innerHTML = `
                ${matchHeader}
                <div class="hltb-time-row">
                    <span class="hltb-label">Main Story</span>
                    <span class="hltb-value">${escapeHtml(times.main)}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Main + Extras</span>
                    <span class="hltb-value">${escapeHtml(times.extras)}</span>
                </div>
                <div class="hltb-time-row">
                    <span class="hltb-label">Completionist</span>
                    <span class="hltb-value">${escapeHtml(times.complete)}</span>
                </div>`;
            savedDiv.style.display = 'block';
        } else {
            display.innerHTML = '<div class="hltb-empty">No playtime data</div>';
            savedDiv.style.display = 'none';
        }
    },

    /**
     * Update game completion status
     */
    updateCompletion() {
        if (!this.currentData) return;

        const status = document.getElementById('gemCompletionStatus').value;

        fetch(`/api/game/${this.currentData.id}/completion`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                this.currentData.completion_status = status;
                GameDetailModal.cache.set(this.currentData.id, this.currentData);

                const completionEl = document.getElementById('gdmCompletion');
                const labels = {
                    'in_progress': 'In Progress',
                    'played': 'Played',
                    'completed': 'Completed',
                    '100_percent': '100%'
                };
                const emojis = {
                    'in_progress': '🎮',
                    'played': '🕹️',
                    'completed': '✅',
                    '100_percent': '🏆'
                };
                if (status && status !== 'not_started') {
                    completionEl.innerHTML = `<span class="completion-badge status-${status}">${labels[status] || status}</span>`;
                    completionEl.style.display = 'block';
                } else {
                    completionEl.style.display = 'none';
                }

                const card = document.querySelector(`.game-card-new[data-game-id="${this.currentData.id}"]`);
                if (card) {
                    const badgeContainer = card.querySelector('.rating-badges');
                    let completionBadge = card.querySelector('.game-badge.completion');

                    if (status && status !== 'not_started') {
                        const statusClass = status === '100_percent' ? 'hundred-percent' : status.replace('_', '-');
                        const badgeContent = `${emojis[status]} ${labels[status]}`;

                        if (completionBadge) {
                            completionBadge.className = `game-badge completion ${statusClass}`;
                            completionBadge.textContent = badgeContent;
                        } else if (badgeContainer) {
                            completionBadge = document.createElement('span');
                            completionBadge.className = `game-badge completion ${statusClass}`;
                            completionBadge.title = 'Completion Status';
                            completionBadge.textContent = badgeContent;
                            badgeContainer.insertBefore(completionBadge, badgeContainer.firstChild);
                        }
                    } else if (completionBadge) {
                        completionBadge.remove();
                    }
                }
            } else {
                const _ei = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
                showModal(`${_ei} Update Failed`, 'Failed to update completion status: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(err => {
            const _ei = typeof getThemedIcon === 'function' ? getThemedIcon('error') : '❌';
            showModal(`${_ei} Error`, 'Error updating completion status');
        });
    },

    _createTag(container, className, value, onRemove) {
        const tag = document.createElement('span');
        tag.className = className;
        tag.textContent = value + ' ';
        const btn = document.createElement('span');
        btn.className = className === 'controller-tag' ? 'remove-controller' : 'remove-genre';
        btn.textContent = '×';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            onRemove();
        });
        tag.appendChild(btn);
        container.appendChild(tag);
    },

    loadGenreDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/genre', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.genreOptions = data.options;
                    this.updateGenreDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load genres:', err); });
    },

    updateGenreDropdown() {
        const dropdown = document.getElementById('gemGenreDropdown');
        const currentGenres = document.getElementById('gemGenreHidden').value.split(',').map(g => g.trim().toLowerCase()).filter(g => g);

        dropdown.innerHTML = '<option value="">+ Add genre...</option>';
        this.genreOptions.forEach(opt => {
            const genreValue = opt.value || opt;
            if (!currentGenres.includes(genreValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = genreValue;
                option.textContent = genreValue;
                dropdown.appendChild(option);
            }
        });
    },

    initGenreTags(genreString) {
        const container = document.getElementById('gemGenreContainer');
        const hidden = document.getElementById('gemGenreHidden');
        container.innerHTML = '';
        hidden.value = genreString;

        if (!genreString) return;

        genreString.split(',').forEach(genre => {
            genre = genre.trim();
            if (genre) {
                this._createTag(container, 'genre-tag', genre, () => this.removeGenre(genre));
            }
        });
    },

    addGenre(genre) {
        if (!genre) return;

        const hidden = document.getElementById('gemGenreHidden');
        const container = document.getElementById('gemGenreContainer');
        const currentGenres = hidden.value ? hidden.value.split(',').map(g => g.trim()) : [];

        if (currentGenres.some(g => g.toLowerCase() === genre.toLowerCase())) return;

        currentGenres.push(genre);
        hidden.value = currentGenres.join(', ');

        this._createTag(container, 'genre-tag', genre, () => this.removeGenre(genre));

        this.updateGenreDropdown();
    },

    removeGenre(genre) {
        const hidden = document.getElementById('gemGenreHidden');
        const container = document.getElementById('gemGenreContainer');

        const currentGenres = hidden.value.split(',').map(g => g.trim()).filter(g => g.toLowerCase() !== genre.toLowerCase());
        hidden.value = currentGenres.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === genre.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateGenreDropdown();
    },

    loadModesDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/game_modes', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.modesOptions = data.options;
                    this.updateModesDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load game modes:', err); });
    },

    updateModesDropdown() {
        const dropdown = document.getElementById('gemModesDropdown');
        const currentModes = document.getElementById('gemModesHidden').value.split(',').map(m => m.trim().toLowerCase()).filter(m => m);

        dropdown.innerHTML = '<option value="">+ Add mode...</option>';
        this.modesOptions.forEach(opt => {
            const modeValue = opt.value || opt;
            if (!currentModes.includes(modeValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = modeValue;
                option.textContent = modeValue;
                dropdown.appendChild(option);
            }
        });
    },

    initModesTags(modesString) {
        const container = document.getElementById('gemModesContainer');
        const hidden = document.getElementById('gemModesHidden');
        container.innerHTML = '';
        hidden.value = modesString;

        if (!modesString) return;

        modesString.split(',').forEach(mode => {
            mode = mode.trim();
            if (mode) {
                this._createTag(container, 'genre-tag', mode, () => this.removeMode(mode));
            }
        });
    },

    addMode(mode) {
        if (!mode) return;

        const hidden = document.getElementById('gemModesHidden');
        const container = document.getElementById('gemModesContainer');
        const currentModes = hidden.value ? hidden.value.split(',').map(m => m.trim()) : [];

        if (currentModes.some(m => m.toLowerCase() === mode.toLowerCase())) return;

        currentModes.push(mode);
        hidden.value = currentModes.join(', ');

        this._createTag(container, 'genre-tag', mode, () => this.removeMode(mode));

        this.updateModesDropdown();
    },

    removeMode(mode) {
        const hidden = document.getElementById('gemModesHidden');
        const container = document.getElementById('gemModesContainer');

        const currentModes = hidden.value.split(',').map(m => m.trim()).filter(m => m.toLowerCase() !== mode.toLowerCase());
        hidden.value = currentModes.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === mode.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateModesDropdown();
    },

    loadSaveTypeDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/save_type', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.saveTypeOptions = data.options;
                    this.updateSaveTypeDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load save types:', err); });
    },

    updateSaveTypeDropdown() {
        const dropdown = document.getElementById('gemSaveTypeDropdown');
        const currentSaveTypes = document.getElementById('gemSaveTypeHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add save type...</option>';
        this.saveTypeOptions.forEach(opt => {
            const saveTypeValue = opt.value || opt;
            if (!currentSaveTypes.includes(saveTypeValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = saveTypeValue;
                option.textContent = saveTypeValue;
                dropdown.appendChild(option);
            }
        });
    },

    initSaveTypeTags(saveTypeString) {
        const container = document.getElementById('gemSaveTypeContainer');
        const hidden = document.getElementById('gemSaveTypeHidden');
        container.innerHTML = '';
        hidden.value = saveTypeString;

        if (!saveTypeString) return;

        saveTypeString.split(',').forEach(saveType => {
            saveType = saveType.trim();
            if (saveType) {
                this._createTag(container, 'genre-tag', saveType, () => this.removeSaveType(saveType));
            }
        });
    },

    addSaveType(saveType) {
        if (!saveType) return;

        const hidden = document.getElementById('gemSaveTypeHidden');
        const container = document.getElementById('gemSaveTypeContainer');
        const currentSaveTypes = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentSaveTypes.some(s => s.toLowerCase() === saveType.toLowerCase())) return;

        currentSaveTypes.push(saveType);
        hidden.value = currentSaveTypes.join(', ');

        this._createTag(container, 'genre-tag', saveType, () => this.removeSaveType(saveType));

        this.updateSaveTypeDropdown();
    },

    removeSaveType(saveType) {
        const hidden = document.getElementById('gemSaveTypeHidden');
        const container = document.getElementById('gemSaveTypeContainer');

        const currentSaveTypes = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== saveType.toLowerCase());
        hidden.value = currentSaveTypes.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === saveType.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateSaveTypeDropdown();
    },

    loadControllerDropdown(systemId) {
        if (!systemId) return;

        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch(`/api/systems/${systemId}/controllers`, { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    this.controllerOptions.defaults = data.default_controllers || [];
                    this.controllerOptions.others = data.controllers || [];
                    this.updateControllerDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load controllers:', err); });
    },

    updateControllerDropdown() {
        const dropdown = document.getElementById('gemControllerDropdown');
        const currentControllers = document.getElementById('gemControllerHidden').value.split(',').map(c => c.trim().toLowerCase()).filter(c => c);

        dropdown.innerHTML = '<option value="">+ Add controller...</option>';

        const getCtrlName = (ctrl) => {
            if (typeof ctrl === 'string') return ctrl;
            return ctrl.name || '';
        };

        const defaultNames = this.controllerOptions.defaults.map(d => getCtrlName(d).toLowerCase());

        if (this.controllerOptions.defaults.length > 0) {
            const defGroup = document.createElement('optgroup');
            defGroup.label = '★ System Defaults';
            this.controllerOptions.defaults.forEach(ctrl => {
                const ctrlName = getCtrlName(ctrl);
                if (ctrlName && !currentControllers.includes(ctrlName.toLowerCase())) {
                    const opt = document.createElement('option');
                    opt.value = ctrlName;
                    opt.textContent = ctrlName;
                    defGroup.appendChild(opt);
                }
            });
            if (defGroup.children.length > 0) dropdown.appendChild(defGroup);
        }

        if (this.controllerOptions.others.length > 0) {
            const otherGroup = document.createElement('optgroup');
            otherGroup.label = 'Other Controllers';
            this.controllerOptions.others.forEach(ctrl => {
                const ctrlName = getCtrlName(ctrl);
                if (ctrlName && !currentControllers.includes(ctrlName.toLowerCase()) &&
                    !defaultNames.includes(ctrlName.toLowerCase())) {
                    const opt = document.createElement('option');
                    opt.value = ctrlName;
                    opt.textContent = ctrlName;
                    otherGroup.appendChild(opt);
                }
            });
            if (otherGroup.children.length > 0) dropdown.appendChild(otherGroup);
        }
    },

    initControllerTags(controllerString) {
        const container = document.getElementById('gemControllerContainer');
        const hidden = document.getElementById('gemControllerHidden');
        container.innerHTML = '';
        hidden.value = controllerString;

        if (!controllerString) return;

        controllerString.split(',').forEach(ctrl => {
            ctrl = ctrl.trim();
            if (ctrl) {
                this._createTag(container, 'controller-tag', ctrl, () => this.removeController(ctrl));
            }
        });
    },

    addController(controller) {
        if (!controller) return;
        controller = controller.trim();
        if (!controller) return;

        const hidden = document.getElementById('gemControllerHidden');
        const container = document.getElementById('gemControllerContainer');
        const currentControllers = hidden.value ? hidden.value.split(',').map(c => c.trim()) : [];

        if (currentControllers.some(c => c.toLowerCase() === controller.toLowerCase())) return;

        currentControllers.push(controller);
        hidden.value = currentControllers.join(', ');

        this._createTag(container, 'controller-tag', controller, () => this.removeController(controller));

        this.updateControllerDropdown();
    },

    removeController(controller) {
        const hidden = document.getElementById('gemControllerHidden');
        const container = document.getElementById('gemControllerContainer');

        const currentControllers = hidden.value.split(',').map(c => c.trim()).filter(c => c.toLowerCase() !== controller.toLowerCase());
        hidden.value = currentControllers.join(', ');

        container.querySelectorAll('.controller-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === controller.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateControllerDropdown();
    },

    initCampaignToggle(value) {
        const toggle = document.getElementById('gemCampaignToggle');
        const hidden = document.getElementById('gemCampaign');
        const label = document.getElementById('gemCampaignLabel');

        hidden.value = value || '';

        if (value === 'Yes' || value === '1' || value === 1) {
            toggle.checked = true;
            toggle.indeterminate = false;
            label.textContent = 'Yes';
        } else if (value === 'No' || value === '0' || value === 0) {
            toggle.checked = false;
            toggle.indeterminate = false;
            label.textContent = 'No';
        } else {
            toggle.checked = false;
            toggle.indeterminate = false;
            label.textContent = 'No';
        }
    },

    updateCampaignLabel() {
        const toggle = document.getElementById('gemCampaignToggle');
        const hidden = document.getElementById('gemCampaign');
        const label = document.getElementById('gemCampaignLabel');

        if (toggle.indeterminate) {
            toggle.indeterminate = false;
            toggle.checked = true;
        }

        if (toggle.checked) {
            hidden.value = 'Yes';
            label.textContent = 'Yes';
        } else {
            hidden.value = 'No';
            label.textContent = 'No';
        }
    },

    initExclusiveToggle(otherPlatforms) {
        const toggle = document.getElementById('gemExclusiveToggle');
        const label = document.getElementById('gemExclusiveLabel');
        const input = document.getElementById('gemOtherPlatforms');
        const hidden = document.getElementById('gemOtherPlatformsHidden');

        const isExclusive = !otherPlatforms || otherPlatforms.toLowerCase() === 'exclusive';

        toggle.checked = isExclusive;
        label.textContent = isExclusive ? 'Exclusive' : 'Multi-platform';
        input.style.display = isExclusive ? 'none' : 'block';
        input.value = isExclusive ? '' : otherPlatforms;
        hidden.value = otherPlatforms || '';
    },

    updateExclusiveToggle() {
        const toggle = document.getElementById('gemExclusiveToggle');
        const label = document.getElementById('gemExclusiveLabel');
        const input = document.getElementById('gemOtherPlatforms');
        const hidden = document.getElementById('gemOtherPlatformsHidden');

        if (toggle.checked) {
            label.textContent = 'Exclusive';
            input.style.display = 'none';
            hidden.value = 'Exclusive';
        } else {
            label.textContent = 'Multi-platform';
            input.style.display = 'block';
            hidden.value = input.value;
        }
    },

    getOtherPlatformsValue() {
        const toggle = document.getElementById('gemExclusiveToggle');
        if (toggle.checked) {
            return 'Exclusive';
        }
        return document.getElementById('gemOtherPlatforms').value.trim();
    },

    initFranchiseToggle(franchise) {
        const toggle = document.getElementById('gemFranchiseToggle');
        const label = document.getElementById('gemFranchiseLabel');
        const input = document.getElementById('gemFranchise');

        if (!toggle || !input) return;

        const isStandalone = !franchise || franchise.toLowerCase() === 'standalone';

        toggle.checked = isStandalone;
        label.textContent = isStandalone ? 'Standalone' : 'Part of a Series';
        input.style.display = isStandalone ? 'none' : 'block';
        if (isStandalone) input.value = '';
    },

    updateFranchiseToggle() {
        const toggle = document.getElementById('gemFranchiseToggle');
        const label = document.getElementById('gemFranchiseLabel');
        const input = document.getElementById('gemFranchise');

        if (toggle.checked) {
            label.textContent = 'Standalone';
            input.style.display = 'none';
            input.value = '';
        } else {
            label.textContent = 'Part of a Series';
            input.style.display = 'block';
        }
    },

    loadGameStructureDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/game_structure', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.gameStructureOptions = data.options;
                    this.updateGameStructureDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load game structures:', err); });
    },

    updateGameStructureDropdown() {
        const dropdown = document.getElementById('gemGameStructureDropdown');
        const currentStructures = document.getElementById('gemGameStructureHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add structure...</option>';
        this.gameStructureOptions.forEach(opt => {
            const structValue = opt.value || opt;
            if (!currentStructures.includes(structValue.toLowerCase())) {
                const option = document.createElement('option');
                option.value = structValue;
                option.textContent = structValue;
                dropdown.appendChild(option);
            }
        });
    },

    initGameStructureTags(structureString) {
        const container = document.getElementById('gemGameStructureContainer');
        const hidden = document.getElementById('gemGameStructureHidden');
        container.innerHTML = '';
        hidden.value = structureString;

        if (!structureString) return;

        structureString.split(',').forEach(structure => {
            structure = structure.trim();
            if (structure) {
                this._createTag(container, 'genre-tag', structure, () => this.removeGameStructure(structure));
            }
        });
    },

    addGameStructure(structure) {
        if (!structure) return;

        const hidden = document.getElementById('gemGameStructureHidden');
        const container = document.getElementById('gemGameStructureContainer');
        const currentStructures = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentStructures.some(s => s.toLowerCase() === structure.toLowerCase())) return;

        currentStructures.push(structure);
        hidden.value = currentStructures.join(', ');

        this._createTag(container, 'genre-tag', structure, () => this.removeGameStructure(structure));

        this.updateGameStructureDropdown();
    },

    removeGameStructure(structure) {
        const hidden = document.getElementById('gemGameStructureHidden');
        const container = document.getElementById('gemGameStructureContainer');

        const currentStructures = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== structure.toLowerCase());
        hidden.value = currentStructures.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('×', '').trim().toLowerCase() === structure.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateGameStructureDropdown();
    },

    loadPerspectiveDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/perspective', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.perspectiveOptions = data.options;
                    this.updatePerspectiveDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load perspectives:', err); });
    },

    updatePerspectiveDropdown() {
        const dropdown = document.getElementById('gemPerspectiveDropdown');
        if (!dropdown) return;
        const currentPerspectives = document.getElementById('gemPerspectiveHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add perspective...</option>';
        this.perspectiveOptions.forEach(opt => {
            const val = opt.value || opt;
            if (!currentPerspectives.includes(val.toLowerCase())) {
                const option = document.createElement('option');
                option.value = val;
                option.textContent = val;
                dropdown.appendChild(option);
            }
        });
    },

    initPerspectiveTags(perspectiveString) {
        const container = document.getElementById('gemPerspectiveContainer');
        const hidden = document.getElementById('gemPerspectiveHidden');
        container.innerHTML = '';
        hidden.value = perspectiveString;

        if (!perspectiveString) return;

        perspectiveString.split(',').forEach(perspective => {
            perspective = perspective.trim();
            if (perspective) {
                this._createTag(container, 'genre-tag', perspective, () => this.removePerspective(perspective));
            }
        });
    },

    addPerspective(perspective) {
        if (!perspective) return;

        const hidden = document.getElementById('gemPerspectiveHidden');
        const container = document.getElementById('gemPerspectiveContainer');
        const currentPerspectives = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentPerspectives.some(s => s.toLowerCase() === perspective.toLowerCase())) return;

        currentPerspectives.push(perspective);
        hidden.value = currentPerspectives.join(', ');

        this._createTag(container, 'genre-tag', perspective, () => this.removePerspective(perspective));

        this.updatePerspectiveDropdown();
    },

    removePerspective(perspective) {
        const hidden = document.getElementById('gemPerspectiveHidden');
        const container = document.getElementById('gemPerspectiveContainer');

        const currentPerspectives = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== perspective.toLowerCase());
        hidden.value = currentPerspectives.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('\u00d7', '').trim().toLowerCase() === perspective.toLowerCase()) {
                tag.remove();
            }
        });

        this.updatePerspectiveDropdown();
    },

    loadDimensionDropdown() {
        const signal = this._dropdownAbortController ? this._dropdownAbortController.signal : undefined;
        fetch('/api/dropdown-options/dimension', { signal })
            .then(r => r.json())
            .then(data => {
                if (data.success && data.options) {
                    this.dimensionOptions = data.options;
                    this.updateDimensionDropdown();
                }
            })
            .catch(err => { if (err.name !== 'AbortError') console.error('Failed to load dimensions:', err); });
    },

    updateDimensionDropdown() {
        const dropdown = document.getElementById('gemDimensionDropdown');
        if (!dropdown) return;
        const currentDimensions = document.getElementById('gemDimensionHidden').value.split(',').map(s => s.trim().toLowerCase()).filter(s => s);

        dropdown.innerHTML = '<option value="">+ Add dimension...</option>';
        this.dimensionOptions.forEach(opt => {
            const val = opt.value || opt;
            if (!currentDimensions.includes(val.toLowerCase())) {
                const option = document.createElement('option');
                option.value = val;
                option.textContent = val;
                dropdown.appendChild(option);
            }
        });
    },

    initDimensionTags(dimensionString) {
        const container = document.getElementById('gemDimensionContainer');
        const hidden = document.getElementById('gemDimensionHidden');
        container.innerHTML = '';
        hidden.value = dimensionString;

        if (!dimensionString) return;

        dimensionString.split(',').forEach(dimension => {
            dimension = dimension.trim();
            if (dimension) {
                this._createTag(container, 'genre-tag', dimension, () => this.removeDimension(dimension));
            }
        });
    },

    addDimension(dimension) {
        if (!dimension) return;

        const hidden = document.getElementById('gemDimensionHidden');
        const container = document.getElementById('gemDimensionContainer');
        const currentDimensions = hidden.value ? hidden.value.split(',').map(s => s.trim()) : [];

        if (currentDimensions.some(s => s.toLowerCase() === dimension.toLowerCase())) return;

        currentDimensions.push(dimension);
        hidden.value = currentDimensions.join(', ');

        this._createTag(container, 'genre-tag', dimension, () => this.removeDimension(dimension));

        this.updateDimensionDropdown();
    },

    removeDimension(dimension) {
        const hidden = document.getElementById('gemDimensionHidden');
        const container = document.getElementById('gemDimensionContainer');

        const currentDimensions = hidden.value.split(',').map(s => s.trim()).filter(s => s.toLowerCase() !== dimension.toLowerCase());
        hidden.value = currentDimensions.join(', ');

        container.querySelectorAll('.genre-tag').forEach(tag => {
            if (tag.textContent.trim().replace('\u00d7', '').trim().toLowerCase() === dimension.toLowerCase()) {
                tag.remove();
            }
        });

        this.updateDimensionDropdown();
    }
};

document.addEventListener('keydown', function(e) {
    const lightbox = document.getElementById('gdmScreenshotLightbox');
    if (lightbox && lightbox.classList.contains('active')) {
        if (e.key === 'Escape') {
            GameDetailModal.closeLightbox();
            return;
        }
        if (e.key === 'ArrowLeft') {
            GameDetailModal.navigateScreenshot(-1);
            return;
        }
        if (e.key === 'ArrowRight') {
            GameDetailModal.navigateScreenshot(1);
            return;
        }
    }

    if (e.key === 'Escape') {
        const customModal = document.getElementById('customModal');
        if (customModal && customModal.classList.contains('active')) return;

        const editModal = document.getElementById('gameEditModal');
        if (editModal && editModal.classList.contains('active')) {
            GameEditModal.close();
            return;
        }
        const detailModal = document.getElementById('gameDetailModal');
        if (detailModal && detailModal.classList.contains('active')) {
            GameDetailModal.close();
        }
    }
});

window.addEventListener('pageshow', function(event) {
    if (event.persisted) {
        GameDetailModal.clearCache();
    }
});

RetroDB.GameDetailModal = GameDetailModal;
RetroDB.GameEditModal = GameEditModal;
RetroDB.HLTBManager = HLTBManager;
RetroDB.gameDetailUrl = gameDetailUrl;

window.gameDetailCache = GameDetailModal.cache;
window.currentGameDetailId = null;
Object.defineProperty(window, 'currentGameDetailId', {
    get: () => GameDetailModal.currentId,
    set: (v) => { GameDetailModal.currentId = v; }
});

window.openGameDetailModal = (gameId) => GameDetailModal.open(gameId);
window.populateGameDetailModal = (game) => GameDetailModal.populate(game);
window.showGameDetailError = (message) => GameDetailModal.showError(message);
window.closeGameDetailModal = () => GameDetailModal.close();

window.HLTBManager = HLTBManager;

window.currentEditGameData = null;
Object.defineProperty(window, 'currentEditGameData', {
    get: () => GameEditModal.currentData,
    set: (v) => { GameEditModal.currentData = v; }
});

window.openGameEditModal = () => GameEditModal.open();
window.switchEditTab = (tabId) => GameEditModal.switchTab(tabId);
window.generateModalSortTitle = () => GameEditModal.generateSortTitle();
window.saveGameEdits = () => GameEditModal.save();
window.closeGameEditModal = () => GameEditModal.close();
window.updateGameCardInPage = (gameId, formData) => GameEditModal.updateGameCardInPage(gameId, formData);
window.updateHltbDisplay = (game) => GameEditModal.updateHltbDisplay(game);
window.updateGameCompletion = () => GameEditModal.updateCompletion();

window.gemHltbCtx = GameEditModal.hltbContext;
window.lookupHltbFromModal = () => HLTBManager.lookup(GameEditModal.hltbContext);
window.saveHltbFromModal = () => HLTBManager.save(GameEditModal.hltbContext);
window.cancelHltbFromModal = () => HLTBManager.cancel(GameEditModal.hltbContext);
window.clearHltbFromModal = () => HLTBManager.clear(GameEditModal.hltbContext);

window.loadModalGenreDropdown = () => GameEditModal.loadGenreDropdown();
window.updateModalGenreDropdown = () => GameEditModal.updateGenreDropdown();
window.initModalGenreTags = (s) => GameEditModal.initGenreTags(s);
window.addModalGenre = (g) => GameEditModal.addGenre(g);
window.removeModalGenre = (g) => GameEditModal.removeGenre(g);

window.loadModalModesDropdown = () => GameEditModal.loadModesDropdown();
window.updateModalModesDropdown = () => GameEditModal.updateModesDropdown();
window.initModalModesTags = (s) => GameEditModal.initModesTags(s);
window.addModalMode = (m) => GameEditModal.addMode(m);
window.removeModalMode = (m) => GameEditModal.removeMode(m);

window.loadModalSaveTypeDropdown = () => GameEditModal.loadSaveTypeDropdown();
window.updateModalSaveTypeDropdown = () => GameEditModal.updateSaveTypeDropdown();
window.initModalSaveTypeTags = (s) => GameEditModal.initSaveTypeTags(s);
window.addModalSaveType = (t) => GameEditModal.addSaveType(t);
window.removeModalSaveType = (t) => GameEditModal.removeSaveType(t);

window.loadModalControllerDropdown = (id) => GameEditModal.loadControllerDropdown(id);
window.updateModalControllerDropdown = () => GameEditModal.updateControllerDropdown();
window.initModalControllerTags = (s) => GameEditModal.initControllerTags(s);
window.addModalController = (c) => GameEditModal.addController(c);
window.removeModalController = (c) => GameEditModal.removeController(c);

window.initModalCampaignToggle = (v) => GameEditModal.initCampaignToggle(v);
window.updateModalCampaignLabel = () => GameEditModal.updateCampaignLabel();

window.initModalExclusiveToggle = (p) => GameEditModal.initExclusiveToggle(p);
window.updateModalExclusiveToggle = () => GameEditModal.updateExclusiveToggle();
window.getOtherPlatformsValue = () => GameEditModal.getOtherPlatformsValue();
window.updateGemFranchiseToggle = () => GameEditModal.updateFranchiseToggle();

window.loadModalGameStructureDropdown = () => GameEditModal.loadGameStructureDropdown();
window.addModalGameStructure = (v) => GameEditModal.addGameStructure(v);
window.removeModalGameStructure = (v) => GameEditModal.removeGameStructure(v);

window.loadModalPerspectiveDropdown = () => GameEditModal.loadPerspectiveDropdown();
window.addModalPerspective = (v) => GameEditModal.addPerspective(v);
window.removeModalPerspective = (v) => GameEditModal.removePerspective(v);

window.loadModalDimensionDropdown = () => GameEditModal.loadDimensionDropdown();
window.addModalDimension = (v) => GameEditModal.addDimension(v);
window.removeModalDimension = (v) => GameEditModal.removeDimension(v);

window.formatHltbTime = (hours) => {
    if (!hours || hours === 0) return '-';
    if (hours < 1) return Math.round(hours * 60) + ' mins';
    return hours.toFixed(1).replace('.0', '') + ' hrs';
};

window.addEventListener('beforeunload', () => {
    GameDetailModal.cache.clear();
});

window.GameDetailModal = GameDetailModal;
window.GameEditModal = GameEditModal;

/**
 * Initialize a date text input with auto-formatting and validation.
 * - Only allows digits, auto-inserts / after YYYY and MM
 * - On blur, validates the date is real (rejects 2024/02/30 etc.)
 * - Syncs with a companion hidden date picker if present
 * @param {string} textId - ID of the text input
 * @param {string} [pickerId] - ID of the hidden date picker input
 */
window.initDateMask = function(textId, pickerId) {
    const input = document.getElementById(textId);
    if (!input) return;

    input.addEventListener('input', function() {
        let v = this.value.replace(/[^\d]/g, '');
        if (v.length > 8) v = v.slice(0, 8);
        if (v.length > 4) v = v.slice(0, 4) + '-' + v.slice(4);
        if (v.length > 7) v = v.slice(0, 7) + '-' + v.slice(7);
        this.value = v;
    });

    input.addEventListener('blur', function() {
        const v = this.value;
        if (!v) return;
        const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!m) { this.value = ''; return; }
        const d = new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
        if (d.getFullYear() !== parseInt(m[1]) || d.getMonth() + 1 !== parseInt(m[2]) || d.getDate() !== parseInt(m[3])) {
            this.value = '';
        }
    });

    if (pickerId) {
        const picker = document.getElementById(pickerId);
        if (picker) {
            picker.addEventListener('change', function() {
                input.value = this.value;
            });
        }
    }
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        initDateMask('gemReleaseDate', 'gemReleaseDatePicker');
    });
} else {
    initDateMask('gemReleaseDate', 'gemReleaseDatePicker');
}

/**
 * Trigger AI metadata fill for the currently open game detail modal.
 * POSTs to /api/game/{id}/ai-fill, refreshes modal on success.
 */
window.triggerAiFill = function() {
    const gameId = GameDetailModal.currentId;
    if (!gameId) return;

    const btn = document.getElementById('gdmAiFill');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Filling...';

    fetch(`/api/game/${gameId}/ai-fill`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const count = data.filled_count || 0;
                if (count > 0) {
                    showNotification(`AI filled ${count} field${count !== 1 ? 's' : ''}: ${data.filled_fields.join(', ')}`, 'success');
                    GameDetailModal.cache.delete(gameId);
                    GameDetailModal.open(gameId);
                    if (typeof AllGamesController !== 'undefined' && AllGamesController.refreshCards) {
                        AllGamesController.refreshCards(gameId);
                    }
                } else {
                    showNotification('AI found no missing fields to fill', 'info');
                }
            } else {
                showNotification(data.error || 'AI fill failed', 'error');
            }
        })
        .catch(err => {
            showNotification('AI fill request failed: ' + err.message, 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        });
};

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

function performGlobalSearch(query) {
    if (query.length < 2) {
        hideSearchResults();
        return;
    }

    showSearchLoading();

    fetch(`/api/search?q=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            displaySearchResults(data);
        })
        .catch(error => {
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

    document.addEventListener('keydown', function(e) {
        if (RetroDBState.currentModal?.id === 'screenshotModal') {
            if (e.key === 'ArrowLeft') {
                navigateScreenshots(-1);
            } else if (e.key === 'ArrowRight') {
                navigateScreenshots(1);
            }
        }
    });
}

function openScreenshotModal(index) {
    RetroDBState.screenshotIndex = index;
    updateScreenshotDisplay();
    openModal('screenshotModal');
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
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

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
                await fetch('/api/restart', { method: 'POST' });

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
            const response = await fetch('/api/status');
            if (response.ok) {
                showNotification('Server restarted successfully!', 'success');
                setTimeout(() => location.reload(), 1000);
                return true;
            }
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
                const response = await fetch('/api/clean-missing-roms', {
                    method: 'POST'
                });

                const data = await response.json();

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
                const response = await fetch('/api/clear-clz-imports', {
                    method: 'POST'
                });

                const data = await response.json();

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
                const response = await fetch('/api/refresh-retroachievements', {
                    method: 'POST'
                });

                const data = await response.json();

                if (data.success) {
                    if (data.queued) {
                        const queue = JSON.parse(localStorage.getItem('raOperationsQueue') || '[]');

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

                const response = await fetch(endpoint, {
                    method: 'POST'
                });

                const data = await response.json();

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
        const response = await fetch('/api/games/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ game_id: gameId, title: title })
        });

        const data = await response.json();

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
        'g d': { action: () => window.location.href = '/dashboard', description: 'Go to Dashboard' },
        'g s': { action: () => window.location.href = '/systems', description: 'Go to Systems' },
        'g l': { action: () => window.location.href = '/games', description: 'Go to Library' },
        'g a': { action: () => window.location.href = '/analytics', description: 'Go to Analytics' },
        'g t': { action: () => window.location.href = '/settings', description: 'Go to Settings' },
        'g h': { action: () => window.location.href = '/help', description: 'Go to Help' },
        'g c': { action: () => window.location.href = '/changelog', description: 'Go to Changelog' },

        '/': { action: () => focusSearch(), description: 'Focus search box' },
        '?': { action: () => showShortcutsModal(), description: 'Show keyboard shortcuts' },
        'Escape': { action: () => closeAnyModal(), description: 'Close modal / cancel' },
    },

    gameShortcuts: {
        'e': { action: () => { if (typeof openEditModal === 'function') openEditModal(); }, description: 'Edit game' },
        's': { action: () => { if (typeof openScrapeModal === 'function') openScrapeModal(); }, description: 'Scrape game' },
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

function showShortcutsModal() {
    let modal = document.getElementById('shortcuts-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'shortcuts-modal';
        modal.className = 'custom-modal';
        modal.innerHTML = `
            <div class="custom-modal-content" style="max-width: 600px;">
                <div class="custom-modal-header">
                    <h3>⌨️ Keyboard Shortcuts</h3>
                    <button class="custom-modal-close" onclick="closeShortcutsModal()">×</button>
                </div>
                <div class="custom-modal-body">
                    <div style="margin-bottom: 1.5rem;">
                        <h4 style="color: var(--primary-cyan); margin-bottom: 0.75rem; font-size: 0.9rem;">NAVIGATION</h4>
                        <div class="shortcut-list">
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>d</kbd> <span>Dashboard</span></div>
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>s</kbd> <span>Systems</span></div>
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>l</kbd> <span>Library</span></div>
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>a</kbd> <span>Analytics</span></div>
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>t</kbd> <span>Settings</span></div>
                            <div class="shortcut-row"><kbd>g</kbd> <kbd>h</kbd> <span>Help</span></div>
                        </div>
                    </div>
                    <div style="margin-bottom: 1.5rem;">
                        <h4 style="color: var(--primary-cyan); margin-bottom: 0.75rem; font-size: 0.9rem;">ACTIONS</h4>
                        <div class="shortcut-list">
                            <div class="shortcut-row"><kbd>/</kbd> <span>Focus search</span></div>
                            <div class="shortcut-row"><kbd>Esc</kbd> <span>Close modal</span></div>
                            <div class="shortcut-row"><kbd>?</kbd> <span>Show shortcuts</span></div>
                        </div>
                    </div>
                    <div>
                        <h4 style="color: var(--primary-cyan); margin-bottom: 0.75rem; font-size: 0.9rem;">GAME PAGE</h4>
                        <div class="shortcut-list">
                            <div class="shortcut-row"><kbd>e</kbd> <span>Edit game</span></div>
                            <div class="shortcut-row"><kbd>s</kbd> <span>Scrape game</span></div>
                            <div class="shortcut-row"><kbd>←</kbd> <kbd>→</kbd> <span>Navigate screenshots</span></div>
                        </div>
                    </div>
                </div>
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
    }
    modal.classList.add('active');
}

function closeShortcutsModal() {
    const modal = document.getElementById('shortcuts-modal');
    if (modal) modal.classList.remove('active');
}

document.addEventListener('DOMContentLoaded', () => KeyboardShortcuts.init());

function trackGameView(gameId) {
    if (!gameId) return;
    fetch(`/api/game/${gameId}/track-view`, { method: 'POST' })
        .catch(e => console.warn('View tracking failed:', e));
}

document.addEventListener('DOMContentLoaded', () => {
    const match = window.location.pathname.match(/\/game\/(\d+)/);
    if (match) {
        trackGameView(match[1]);
    }
});

function updateCompletionStatus(gameId, status) {
    fetch(`/api/game/${gameId}/completion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: status })
    })
    .then(r => r.json())
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

})();
