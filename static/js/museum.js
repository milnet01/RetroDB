/* =============================================================================
   RETRODB - Museum Page JavaScript
   Page-specific (NOT bundled) — handles AI generation, controller images,
   timeline filtering, and tab navigation.
   ============================================================================= */

// =============================================================================
// BULK GENERATION
// =============================================================================

let _pollTimer = null;

function startBulkGenerate() {
    showConfirm(
        'Generate All Museum Content',
        'This will use your configured AI provider to generate history and top games for all systems. This may take several minutes and use API credits. Continue?',
        function () {
            _doBulkGenerate(false);
        }
    );
}

function _doBulkGenerate(overwrite) {
    const btn = document.getElementById('generateAllBtn');
    if (btn) btn.disabled = true;

    API.post('/api/museum/generate-all', { overwrite: overwrite })
        .then(function (data) {
            if (data.success) {
                showNotification('Museum generation started', 'info');
                _showProgress();
                _startPolling();
            } else {
                showNotification(data.error || 'Failed to start generation', 'error');
                if (btn) btn.disabled = false;
            }
        })
        .catch(function () {
            showNotification('Failed to start generation', 'error');
            if (btn) btn.disabled = false;
        });
}

function cancelBulkGenerate() {
    API.post('/api/museum/cancel-generate')
        .then(function (data) {
            if (data.success) {
                showNotification('Cancellation requested', 'warning');
            }
        });
}

function _showProgress() {
    var el = document.getElementById('generateProgress');
    if (el) el.style.display = '';
}

function _hideProgress() {
    var el = document.getElementById('generateProgress');
    if (el) el.style.display = 'none';
}

function _startPolling() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(_pollStatus, 2000);
}

function _stopPolling() {
    if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
    }
}

function _pollStatus() {
    API.get('/api/museum/generate-status')
        .then(function (s) {
            // Update UI
            var pct = s.total_systems > 0
                ? Math.round((s.current_index / s.total_systems) * 100)
                : 0;

            var bar = document.getElementById('progressBar');
            if (bar) bar.style.width = pct + '%';

            var cur = document.getElementById('progressCurrent');
            if (cur) cur.textContent = formatNumber(s.current_index);

            var tot = document.getElementById('progressTotal');
            if (tot) tot.textContent = formatNumber(s.total_systems);

            var suc = document.getElementById('progressSuccess');
            if (suc) suc.textContent = formatNumber(s.success_count);

            var skip = document.getElementById('progressSkipped');
            if (skip) skip.textContent = formatNumber(s.skipped_count);

            var fail = document.getElementById('progressFailed');
            if (fail) fail.textContent = formatNumber(s.failed_count);

            var sys = document.getElementById('progressSystem');
            if (sys) sys.textContent = s.current_system_name || '...';

            var title = document.getElementById('progressTitle');
            if (title) {
                if (s.cancelled) {
                    title.textContent = 'Cancelled';
                } else if (s.completed) {
                    title.textContent = 'Complete!';
                } else {
                    title.textContent = 'Generating content...';
                }
            }

            // Stop polling when done
            if (!s.running) {
                _stopPolling();
                var btn = document.getElementById('generateAllBtn');
                if (btn) btn.disabled = false;

                var cancelBtn = document.getElementById('cancelGenBtn');
                if (cancelBtn) cancelBtn.disabled = true;

                if (s.error_message) {
                    showNotification(s.error_message, 'error');
                } else if (s.cancelled) {
                    showNotification('Generation cancelled', 'warning');
                } else {
                    showNotification(
                        'Generation complete: ' + formatNumber(s.success_count) + ' generated, ' +
                        formatNumber(s.skipped_count) + ' skipped, ' + formatNumber(s.failed_count) + ' failed',
                        'success'
                    );
                    // Reload to show updated content indicators
                    setTimeout(function () { location.reload(); }, 2000);
                }
            }
        })
        .catch(function () {
            // Silently ignore poll errors
        });
}


// =============================================================================
// SINGLE SYSTEM GENERATION
// =============================================================================

function generateContent(systemId) {
    var btn = document.getElementById('generateBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating...';
    }

    API.post('/api/museum/generate/' + systemId)
        .then(function (data) {
            if (data.success) {
                showNotification('Content generated successfully', 'success');
                // Reload to display new content
                setTimeout(function () { location.reload(); }, 1000);
            } else {
                showNotification(data.error || 'Generation failed', 'error');
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Generate Content';
                }
            }
        })
        .catch(function () {
            showNotification('Generation request failed', 'error');
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Generate Content';
            }
        });
}


// =============================================================================
// CONTROLLER IMAGES
// =============================================================================

function _updateControllerImage(controllerId, imageFilename) {
    var card = document.querySelector('[data-controller-id="' + controllerId + '"]');
    if (!card) return;
    var imgContainer = card.querySelector('.museum-controller-image');
    if (imgContainer) {
        // Preserve the hidden file input
        var fileInput = imgContainer.querySelector('input[type="file"]');
        imgContainer.innerHTML = '<img src="/static/images/controllers/' +
            imageFilename + '?t=' + Date.now() + '" alt="Controller" loading="lazy" onclick="openControllerLightbox(this)">' +
            '<div class="museum-controller-image-actions">' +
            '<button class="btn btn-xs btn-ghost" onclick="event.stopPropagation();uploadControllerImage(' + controllerId + ')" title="Upload replacement image">Replace</button>' +
            '</div>';
        if (fileInput) imgContainer.appendChild(fileInput);
    }
}

function _resetPlaceholder(controllerId) {
    var card = document.querySelector('[data-controller-id="' + controllerId + '"]');
    if (!card) return;
    var imgContainer = card.querySelector('.museum-controller-image');
    if (imgContainer) {
        var fileInput = imgContainer.querySelector('input[type="file"]');
        var placeholder = imgContainer.querySelector('.museum-controller-placeholder');
        if (!placeholder) {
            placeholder = document.createElement('div');
            placeholder.className = 'museum-controller-placeholder';
            imgContainer.insertBefore(placeholder, fileInput);
        }
        placeholder.innerHTML = '<span>&#128377;&#65039;</span>' +
            '<div class="museum-controller-image-actions">' +
            '<button class="btn btn-sm btn-ghost" onclick="fetchControllerImage(' + controllerId + ')">Search</button>' +
            '<button class="btn btn-sm btn-ghost" onclick="uploadControllerImage(' + controllerId + ')">Upload</button>' +
            '</div>';
    }
}

function _showControllerOverlay(controllerId, message) {
    var card = document.querySelector('[data-controller-id="' + controllerId + '"]');
    var imgContainer = card ? card.querySelector('.museum-controller-image') : null;
    if (!imgContainer) return;
    // Remove any existing overlay
    var existing = imgContainer.querySelector('.museum-controller-upload-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.className = 'museum-controller-upload-overlay';
    overlay.innerHTML = '<div class="loading-spinner-small"></div><span class="museum-controller-upload-text">' + escapeHtml(message) + '</span>';
    imgContainer.appendChild(overlay);
}

function _removeControllerOverlay(controllerId) {
    var card = document.querySelector('[data-controller-id="' + controllerId + '"]');
    if (!card) return;
    var overlay = card.querySelector('.museum-controller-upload-overlay');
    if (overlay) overlay.remove();
}

function removeControllerBg(controllerId) {
    _showControllerOverlay(controllerId, 'Removing background\u2026');

    API.post('/api/museum/controller-image-removebg/' + controllerId)
        .then(function (data) {
            _removeControllerOverlay(controllerId);
            if (data.success && data.image) {
                showNotification('Background removed', 'success');
                _updateControllerImage(controllerId, data.image);
            } else {
                showNotification(data.error || 'Background removal failed', 'error');
                location.reload();
            }
        })
        .catch(function () {
            _removeControllerOverlay(controllerId);
            showNotification('Background removal failed', 'error');
            location.reload();
        });
}

function fetchControllerImage(controllerId) {
    var card = document.querySelector('[data-controller-id="' + controllerId + '"]');
    var placeholder = card ? card.querySelector('.museum-controller-placeholder') : null;
    if (placeholder) {
        placeholder.innerHTML = '<span class="spinner"></span><span class="text-muted" style="font-size:0.75rem">Searching &amp; removing background...</span>';
    }

    API.post('/api/museum/controller-image/' + controllerId)
        .then(function (data) {
            if (data.success && data.image) {
                showNotification('Controller image saved', 'success');
                _updateControllerImage(controllerId, data.image);
            } else {
                showNotification(data.error || 'Failed to fetch image', 'error');
                _resetPlaceholder(controllerId);
            }
        })
        .catch(function () {
            showNotification('Failed to fetch controller image', 'error');
            _resetPlaceholder(controllerId);
        });
}

function uploadControllerImage(controllerId) {
    var fileInput = document.getElementById('ctrlUpload' + controllerId);
    if (fileInput) fileInput.click();
}

function handleControllerUpload(controllerId, input) {
    if (!input.files || !input.files[0]) return;

    var file = input.files[0];
    if (file.size > 10 * 1024 * 1024) {
        showNotification('Image must be under 10MB', 'error');
        input.value = '';
        return;
    }

    showConfirm(
        'Upload Controller Image',
        'Remove background from the uploaded image?',
        function () { _doUpload(controllerId, file, true); },
        function () { _doUpload(controllerId, file, false); }
    );
}

function _doUpload(controllerId, file, removeBg) {
    var msg = removeBg ? 'Uploading & removing background\u2026' : 'Uploading\u2026';
    _showControllerOverlay(controllerId, msg);

    var formData = new FormData();
    formData.append('image', file);
    formData.append('remove_bg', removeBg ? 'true' : 'false');

    API.postForm('/api/museum/controller-image-upload/' + controllerId, formData)
        .then(function (data) {
            _removeControllerOverlay(controllerId);
            if (data.success && data.image) {
                showNotification('Controller image uploaded', 'success');
                _updateControllerImage(controllerId, data.image);
            } else {
                showNotification(data.error || 'Upload failed', 'error');
                _resetPlaceholder(controllerId);
            }
        })
        .catch(function () {
            _removeControllerOverlay(controllerId);
            showNotification('Upload failed', 'error');
            _resetPlaceholder(controllerId);
        });

    // Clear the file input for potential re-use
    var fileInput = document.getElementById('ctrlUpload' + controllerId);
    if (fileInput) fileInput.value = '';
}

function fetchAllControllerImages(systemId) {
    showConfirm(
        'Fetch All Controller Images',
        'This will search for and download images for all controllers without images. Continue?',
        function () {
            showNotification('Fetching controller images...', 'info');
            API.post('/api/museum/controller-images-bulk/' + systemId)
                .then(function (data) {
                    if (data.success) {
                        var r = data.results;
                        showNotification(
                            r.success + ' fetched, ' + r.skipped + ' skipped, ' + r.failed + ' failed',
                            r.success > 0 ? 'success' : 'warning'
                        );
                        if (r.success > 0) {
                            setTimeout(function () { location.reload(); }, 1500);
                        }
                    } else {
                        showNotification(data.error || 'Bulk fetch failed', 'error');
                    }
                })
                .catch(function () {
                    showNotification('Bulk fetch request failed', 'error');
                });
        }
    );
}


// =============================================================================
// TIMELINE FILTERING (Landing Page)
// =============================================================================

function filterMuseumSystems() {
    var search = (document.getElementById('museumSearch') || {}).value || '';
    search = search.toLowerCase().trim();

    var typeFilter = (document.getElementById('museumTypeFilter') || {}).value || '';

    // Persist filter state
    Storage.set('museum_search', search);
    Storage.set('museum_type_filter', typeFilter);

    var eras = document.querySelectorAll('.museum-era');
    eras.forEach(function (era) {
        var cards = era.querySelectorAll('.museum-system-card');
        var visibleCount = 0;

        cards.forEach(function (card) {
            var name = card.getAttribute('data-name') || '';
            var type = card.getAttribute('data-type') || '';

            var matchSearch = !search || name.indexOf(search) !== -1;
            var matchType = !typeFilter || type === typeFilter;

            if (matchSearch && matchType) {
                card.style.display = '';
                visibleCount++;
            } else {
                card.style.display = 'none';
            }
        });

        // Hide entire era if no visible cards
        era.style.display = visibleCount > 0 ? '' : 'none';
    });
}

function _restoreMuseumFilters() {
    var savedSearch = Storage.get('museum_search', '');
    var savedType = Storage.get('museum_type_filter', '');

    var searchInput = document.getElementById('museumSearch');
    var typeSelect = document.getElementById('museumTypeFilter');

    if (searchInput && savedSearch) searchInput.value = savedSearch;
    if (typeSelect && savedType) typeSelect.value = savedType;

    // Apply filters if any were restored
    if (savedSearch || savedType) filterMuseumSystems();
}

function _saveScrollPosition() {
    if (document.getElementById('museumTimeline')) {
        Storage.set('museum_scroll_y', window.scrollY);
    }
}

function _restoreScrollPosition() {
    var savedY = Storage.get('museum_scroll_y', 0);
    if (savedY > 0) {
        // Use requestAnimationFrame to ensure layout is complete
        requestAnimationFrame(function () {
            window.scrollTo(0, savedY);
        });
    }
}


// =============================================================================
// CONTROLLER IMAGE LIGHTBOX
// =============================================================================

var _lightboxImages = [];
var _lightboxIndex = 0;

function _collectControllerImages() {
    _lightboxImages = [];
    var cards = document.querySelectorAll('.museum-controller-card');
    cards.forEach(function (card) {
        var img = card.querySelector('.museum-controller-image > img');
        if (img) {
            var name = card.querySelector('.museum-controller-name');
            _lightboxImages.push({
                src: img.src,
                title: name ? name.textContent : ''
            });
        }
    });
}

function openControllerLightbox(imgEl) {
    _collectControllerImages();
    var clickedSrc = imgEl.src;
    _lightboxIndex = 0;
    for (var i = 0; i < _lightboxImages.length; i++) {
        if (_lightboxImages[i].src === clickedSrc) {
            _lightboxIndex = i;
            break;
        }
    }
    _updateControllerLightbox();
    var lb = document.getElementById('museumControllerLightbox');
    if (lb) {
        lb.classList.add('active');
        if (window.ModalFocusTrap) {
            ModalFocusTrap.activate(lb, imgEl, { onEscape: closeControllerLightbox });
        }
    }
}

function closeControllerLightbox() {
    var lb = document.getElementById('museumControllerLightbox');
    if (lb) lb.classList.remove('active');
    if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
}

function navigateControllerLightbox(delta) {
    if (_lightboxImages.length === 0) return;
    _lightboxIndex += delta;
    if (_lightboxIndex < 0) _lightboxIndex = _lightboxImages.length - 1;
    if (_lightboxIndex >= _lightboxImages.length) _lightboxIndex = 0;
    _updateControllerLightbox();
}

function _updateControllerLightbox() {
    var img = document.getElementById('museumLightboxImage');
    var title = document.getElementById('museumLightboxTitle');
    var prevBtn = document.querySelector('.museum-lightbox-nav.prev');
    var nextBtn = document.querySelector('.museum-lightbox-nav.next');

    if (_lightboxImages.length === 0) return;

    var entry = _lightboxImages[_lightboxIndex];
    if (img) img.src = entry.src;
    if (title) title.textContent = entry.title;

    var showNav = _lightboxImages.length > 1;
    if (prevBtn) prevBtn.style.display = showNav ? '' : 'none';
    if (nextBtn) nextBtn.style.display = showNav ? '' : 'none';
}

// =============================================================================
// HARDWARE IMAGE LIGHTBOX
// =============================================================================

function openHardwareLightbox(imgEl) {
    var lb = document.getElementById('museumHardwareLightbox');
    var lbImg = document.getElementById('museumHwLightboxImage');
    var lbTitle = document.getElementById('museumHwLightboxTitle');
    if (!lb || !lbImg) return;

    lbImg.src = imgEl.src;
    if (lbTitle) lbTitle.textContent = imgEl.alt || '';
    lb.classList.add('active');
    if (window.ModalFocusTrap) {
        ModalFocusTrap.activate(lb, imgEl, { onEscape: closeHardwareLightbox });
    }
}

function closeHardwareLightbox() {
    var lb = document.getElementById('museumHardwareLightbox');
    if (lb) lb.classList.remove('active');
    if (window.ModalFocusTrap) ModalFocusTrap.deactivate();
}

// =============================================================================
// TAB NAVIGATION (System Page)
// =============================================================================

function switchMuseumTab(event, tabId) {
    if (event) event.preventDefault();

    // Update nav active state
    var navItems = document.querySelectorAll('.museum-nav-item');
    navItems.forEach(function (item) { item.classList.remove('active'); });

    if (event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }

    // Show/hide sections
    var sections = document.querySelectorAll('.museum-section');
    sections.forEach(function (section) {
        section.style.display = section.id === tabId ? '' : 'none';
    });

    // Update URL hash
    if (history.replaceState) {
        history.replaceState(null, null, '#' + tabId);
    }

    // Recalculate sticky positions
    if (typeof StickyScroll !== 'undefined') {
        StickyScroll.stackPositions();
        StickyScroll.updateMargins();
    }
}

// =============================================================================
// PAGE INIT
// =============================================================================

document.addEventListener('DOMContentLoaded', function () {
    // --- System page: handle hash-based tab navigation ---
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) {
        var navItems = document.querySelectorAll('.museum-nav-item');
        navItems.forEach(function (item) {
            if (item.getAttribute('href') === '#' + hash) {
                switchMuseumTab({ preventDefault: function () {}, currentTarget: item }, hash);
            }
        });
    }

    // --- Lightbox keyboard navigation ---
    document.addEventListener('keydown', function (e) {
        // Hardware lightbox (single image — ESC only)
        var hwLb = document.getElementById('museumHardwareLightbox');
        if (hwLb && hwLb.classList.contains('active')) {
            if (e.key === 'Escape') closeHardwareLightbox();
            return;
        }

        // Controller lightbox (multi-image — ESC + arrows)
        var lb = document.getElementById('museumControllerLightbox');
        if (!lb || !lb.classList.contains('active')) return;
        if (e.key === 'Escape') closeControllerLightbox();
        else if (e.key === 'ArrowLeft') navigateControllerLightbox(-1);
        else if (e.key === 'ArrowRight') navigateControllerLightbox(1);
    });

    // --- Landing page: restore filters, scroll, and check generation status ---
    if (document.getElementById('museumTimeline')) {
        _restoreMuseumFilters();
        _restoreScrollPosition();

        // Save scroll position and stop polling on navigate away
        window.addEventListener('beforeunload', function() {
            _saveScrollPosition();
            _stopPolling();
        });
        // Also save when clicking any link (beforeunload doesn't always fire on SPA-like navigations)
        document.addEventListener('click', function (e) {
            var link = e.target.closest('a[href]');
            if (link && !link.getAttribute('href').startsWith('#')) {
                _saveScrollPosition();
            }
        });

        // Check if bulk generation is already running (user navigated away and back)
        _checkRunningGeneration();
    }
});

function _checkRunningGeneration() {
    API.get('/api/museum/generate-status')
        .then(function (s) {
            if (s.running) {
                // Generation is still going — show progress and resume polling
                var btn = document.getElementById('generateAllBtn');
                if (btn) btn.disabled = true;
                _showProgress();
                _pollStatus();      // Immediately update UI with current state
                _startPolling();    // Then continue polling
            }
        })
        .catch(function () {
            // Ignore — no generation running
        });
}
