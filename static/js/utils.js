/**
 * RetroDB Shared Utilities Module
 * Common functions used across all pages
 * Version: 1.16.0
 */

// Initialize the RetroDB namespace
window.RetroDB = window.RetroDB || {};

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

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
        // Fallback for older browsers
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

// =============================================================================
// LOCAL STORAGE HELPERS
// =============================================================================

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

// =============================================================================
// API HELPER
// =============================================================================

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

// =============================================================================
// NOTIFICATION SYSTEM
// =============================================================================

const Notifications = {
    container: null,

    // Configurable timeouts in seconds (can be set from settings)
    // These are defaults that can be overridden by window.NOTIFICATION_TIMEOUTS
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
        // Load timeouts from global settings if available
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
        // If custom duration was explicitly provided, use it
        if (customDuration !== undefined) {
            return customDuration;
        }
        // Use configured timeout for this type (in seconds, convert to ms)
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

        // Cap max visible notifications to prevent DOM bloat
        const MAX_NOTIFICATIONS = 8;
        const existing = this.container.querySelectorAll('.notification');
        if (existing.length >= MAX_NOTIFICATIONS) {
            // Remove oldest (first) notifications beyond limit
            for (let i = 0; i <= existing.length - MAX_NOTIFICATIONS; i++) {
                existing[i].remove();
            }
        }

        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;

        // Use themed icons if available, fallback to emoji
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

        // Animate in
        requestAnimationFrame(() => {
            notification.classList.add('show');
        });

        // Auto remove (0 = never auto-remove)
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

// Global shorthand - duration is optional, uses configured timeouts if not provided
function showNotification(message, type = 'info', duration) {
    return Notifications.show(message, type, duration);
}

// =============================================================================
// LOADING STATES
// =============================================================================

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

// =============================================================================
// DOM HELPERS
// =============================================================================

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

// =============================================================================
// DATE/TIME HELPERS
// =============================================================================

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

// =============================================================================
// STICKY SCROLL UTILITIES
// =============================================================================
// Universal scroll offset calculation for pages with sticky nav/tab bars.
// Mark any sticky navigation element with the `data-sticky-nav` attribute.
// StickyScroll automatically sums the heights of all stacked sticky headers
// that precede the target in document order, so anchor targets are never
// hidden behind navigation bars.

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
            // Skip hidden elements (e.g. inside inactive tab panels)
            if (!nav.offsetHeight) return;

            // Only count sticky navs that precede the target in document order
            if (targetEl) {
                const pos = nav.compareDocumentPosition(targetEl);
                if (!(pos & Node.DOCUMENT_POSITION_FOLLOWING)) return;

                // Scoped sticky nav: only applies to targets within its scope
                const scopeId = nav.dataset.stickyScope;
                if (scopeId) {
                    const scope = document.getElementById(scopeId);
                    if (scope && !scope.contains(targetEl)) return;
                }
            }

            // Calculate where this element's bottom edge sits when stuck
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
            // Skip hidden elements (e.g. inside inactive tab panels)
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

// =============================================================================
// REGISTER WITH RETRODB NAMESPACE
// =============================================================================

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

// =============================================================================
// EXPORT GLOBALS (backward compatibility)
// =============================================================================

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
