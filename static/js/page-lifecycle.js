/**
 * RetroDB Page Lifecycle & Cleanup Manager
 * Handles memory leak prevention, event listener cleanup, and page state management
 * Version: 1.19.0
 */

window.RetroDB = window.RetroDB || {};

// =============================================================================
// PAGE LIFECYCLE MANAGER
// =============================================================================

const PageLifecycle = (function() {
    'use strict';
    
    // Tracking arrays for cleanup
    const eventListeners = [];
    const intervals = [];
    const timeouts = [];
    const observers = [];
    const abortControllers = [];
    
    // Page state for scroll position and filter restoration
    let pageState = null;
    let pageKey = null;
    
    // =============================================================================
    // EVENT LISTENER TRACKING
    // =============================================================================
    
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
        
        // Return removal function
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
    
    // =============================================================================
    // INTERVAL/TIMEOUT TRACKING
    // =============================================================================
    
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
            // Remove from tracking after execution
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
    
    // =============================================================================
    // MUTATION OBSERVER TRACKING
    // =============================================================================
    
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
    
    // =============================================================================
    // ABORT CONTROLLER TRACKING
    // =============================================================================
    
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
    
    // =============================================================================
    // PAGE STATE MANAGEMENT
    // =============================================================================
    
    /**
     * Initialize page state tracking
     * @param {string} key - Unique key for this page's state
     */
    function initPageState(key) {
        pageKey = key;
        
        // Pass 36.5 — use safeParseJSON so a poison entry gets cleared
        // on first read instead of re-throwing every page load.
        const restored = safeParseJSON(pageKey, null, sessionStorage);
        if (restored) {
            pageState = restored;
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
    
    // =============================================================================
    // SCROLL POSITION MANAGEMENT
    // =============================================================================
    
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
    
    // =============================================================================
    // DEBOUNCE & THROTTLE (with cleanup)
    // =============================================================================
    
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
    
    // =============================================================================
    // CLEANUP
    // =============================================================================
    
    /**
     * Clean up all tracked resources
     */
    function cleanup() {
        // Remove all tracked event listeners
        eventListeners.forEach(entry => {
            try {
                entry.target.removeEventListener(entry.type, entry.handler, entry.options);
            } catch (e) { /* Ignore errors during cleanup */ }
        });
        eventListeners.length = 0;
        
        // Clear all intervals
        intervals.forEach(id => window.clearInterval(id));
        intervals.length = 0;
        
        // Clear all timeouts
        timeouts.forEach(id => window.clearTimeout(id));
        timeouts.length = 0;
        
        // Disconnect all observers
        observers.forEach(obs => {
            try { obs.disconnect(); } catch (e) { /* Ignore */ }
        });
        observers.length = 0;
        
        // Abort all pending requests
        abortControllers.forEach(ctrl => {
            try { ctrl.abort(); } catch (e) { /* Ignore */ }
        });
        abortControllers.length = 0;
        
        // Clear debounce timeouts
        debounceTimeouts.forEach(id => window.clearTimeout(id));
        debounceTimeouts.clear();

        // Clear DOMCache to release DOM element references
        if (typeof DOMCache !== 'undefined' && DOMCache.clear) {
            DOMCache.clear();
        }
    }
    
    /**
     * Register cleanup on page unload
     */
    function registerUnloadCleanup() {
        // Use beforeunload for cleanup
        window.addEventListener('beforeunload', cleanup);
        
        // Also use pagehide for bfcache support
        window.addEventListener('pagehide', (event) => {
            if (event.persisted) {
                // Page is being cached, save state
                saveScrollPosition();
            } else {
                // Page is being unloaded
                cleanup();
            }
        });
        
        // Handle pageshow for bfcache restoration
        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                // Page restored from bfcache
                restoreScrollPosition(0);
            }
        });
    }
    
    // =============================================================================
    // INITIALIZATION
    // =============================================================================
    
    // Auto-register cleanup on load
    if (typeof document !== 'undefined') {
        registerUnloadCleanup();
    }
    
    // =============================================================================
    // PUBLIC API
    // =============================================================================
    
    return {
        // Event listeners
        addEventListener,
        removeEventListener: (entry) => removeEventListener(entry),
        
        // Timers
        setInterval,
        clearInterval,
        setTimeout,
        clearTimeout,
        
        // Observers
        createObserver,
        disconnectObserver,
        
        // Abort controllers
        createAbortController,
        removeAbortController,
        
        // Page state
        initPageState,
        savePageState,
        getPageState,
        clearPageState,
        saveScrollPosition,
        restoreScrollPosition,
        
        // Utilities
        debounce,
        
        // Cleanup
        cleanup,
        registerUnloadCleanup
    };
})();

// Register with RetroDB namespace
RetroDB.PageLifecycle = PageLifecycle;
// Expose globally (backward compatibility)
window.PageLifecycle = PageLifecycle;

// =============================================================================
// DOM CACHE MANAGER
// Prevents repeated DOM queries
// =============================================================================

const DOMCache = (function() {
    'use strict';

    const cache = new Map();
    const MAX_CACHE_SIZE = 500;  // Prevent unbounded growth

    /** Evict oldest entries if cache exceeds max size */
    function _evictIfNeeded() {
        if (cache.size <= MAX_CACHE_SIZE) return;
        // Delete oldest entries (first inserted in Map iteration order)
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

