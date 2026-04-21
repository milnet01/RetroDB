# RetroDB - Claude Code Project Guide

> Flask-based retro gaming ROM library manager with cyberpunk UI theme.

**Screenshots:** User screenshots are always at `/home/ants/Pictures/`

---

## Mandatory Workflow

### After Every Code Change
1. **Bump version** in `config.py` AND `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`)
2. **Add changelog entry** at top of `data/changelog.yaml`
3. **Rebuild CSS** if any `.css` file under `static/css/` was modified: `python3 build_css.py`
3b. **Rebuild JS** if any bundled `.js` file under `static/js/` was modified: `python3 build_js.py`
4. **Run tests** if any `services/*.py` or `scraper/*.py` was modified: `python3 -m pytest`
5. **Regenerate lockfile** if `requirements.txt` was edited: `pip-compile requirements.txt -o requirements.lock --strip-extras`
6. **Update this file** (`CLAUDE.md`) if any change adds, removes, or renames routes, templates, CSS files, JS files, or alters how pages/CSS/JS are created or used

### Version Bumping Rules
- **Patch** (x.x.N+1): Bug fixes, cleanup, refactoring, accessibility
- **Minor** (x.N+1.0): New features, enhancements, new options
- **Major** (N+1.0.0): Major releases, breaking changes

### CSS Modification Rules
- Never add inline `<style>` blocks that duplicate external CSS classes
- Check `static/css/components/` and `static/css/pages/` before writing inline styles
- Use CSS variables from `core/variables.css` — never hardcode colors
- If a style is used on 2+ pages, it belongs in external CSS
- After editing any external CSS file, run `python3 build_css.py` to regenerate `main.min.css`

### Code Standards
- Always follow existing patterns in the codebase for consistency
- Reference `docs/RETRODB_DESIGN_STANDARDS.md` for UI, CSS, JS, and API standards
- Reference `docs/STANDARDS_ADDENDUM.md` for version checklist and logging patterns
- Reference `docs/ROM_NAMING_STANDARD.md` for ROM file naming conventions
- Reference `docs/RETRODB_DESIGN_STANDARDS.md` §23 for controller naming conventions
- Both `/games` (Library) and `/system/<id>` pages use `AllGamesController` — keep them in sync
- `perspective` and `dimension` are comma-separated multi-value TEXT fields (like genre, modes, game_structure)
- `region` is a single-value field selected from a configurable dropdown (`region_options` in settings); default is set via `default_region` setting
- Genre canonical forms use hyphenated names matching `FIELD_SCHEMAS` in `scraper/scrape_ai.py` (e.g., `First-Person-Shooter`, `Shoot-em-up`, `Beat-em-up`, `Hack-n-Slash`, `Board-Card`)
- Sort title is auto-generated during scraping and AI Fill via `generate_sort_title()` from `services/game_utils.py`
- When a system has curated default controllers in the DB, they always override scraped/AI controller values
- Media fields (boxart, boxart_3d, screenshots, fanart, video, manual) are never replaced during normal scraping — only filled when empty. Screenshots are always appended, never replaced. To get new media, clear it from the edit modal first, then re-scrape. Full Re-scrape mode overrides this and replaces everything.
- During pre-population, media files are validated on disk — stale DB references (file deleted but filename still in DB) are automatically cleared so scrapers can re-download fresh media
- `players` is an INTEGER column; scrapers/AI may return ranges like "1-4" which are normalized to the max number (4) before saving
- **Multi-rating system**: 8 age rating systems supported (ESRB, PEGI, CERO, USK, ACB, FPB, GRAC, ClassInd) with DB columns `esrb_rating`, `pegi_rating`, `cero_rating`, `usk_rating`, `acb_rating`, `fpb_rating`, `grac_rating`, `classind_rating`. Cross-mapping via maturity tiers in `services/game_utils.py` (`map_rating()`, `get_preferred_rating()`). Empty ratings are auto-filled from any available rating during scraping, AI Fill, and manual editing. User's preferred system is set via `preferred_rating_system` in settings.
- **Rating images**: Official rating images in `static/images/ratings/{SYSTEM}/` for all 8 systems. `RATING_IMAGE_MAP` in `game_utils.py` maps `(system, value)` tuples to image paths. JS helpers (`get_rating_image_map_js()`, `get_rating_crossmap_js()`) produce JSON-serializable versions exposed as `window.RATING_IMAGE_MAP`, `window.RATING_TO_TIER`, `window.TIER_TO_RATING` via `base.html`. Game cards, detail modal, and game detail page all show the preferred system's rating image with cross-mapping fallback.

---

## Project File Index

### Setup & Installation
| File | Purpose |
|------|---------|
| `setup.sh` | Entry point for new users — installs Python/pip/tkinter if missing, then launches GUI installer |
| `install_gui.py` | Tkinter graphical installer wizard (dark cyberpunk theme, step progress, log, launch button) |
| `install.py` | CLI installer fallback (auto-detects distro, colored output, all setup steps) |
| `start.sh` | Server launcher for Linux (checks deps, builds CSS, starts app) |
| `pyproject.toml` | Ruff + pytest config (no packaging — project is a Flask app, not a library) |
| `requirements.txt` | Runtime dependencies with semver ranges (user-facing `pip install -r`) |
| `requirements.lock` | Fully pinned transitive dependency list — regenerate with `pip-compile` |
| `tests/` | pytest suite — `python3 -m pytest` |
| `.github/workflows/ci.yml` | Lint + semgrep + smoke import + pytest on push/PR |
| `.github/workflows/release.yml` | On `v*.*.*` tag: build 3-platform ZIPs, draft GitHub Release |

### Configuration & Data
| File | Purpose |
|------|---------|
| `config.py` | App version, paths, API keys, system mappings (277 systems) |
| `data/settings.json` | User-editable settings (modified via web UI) — includes `region_options`, `default_region` |
| `data/scraper_settings.json` | Scraper priority & per-scraper toggles |
| `data/rom_tools_config.json` | ROM tools preferences |
| `data/changelog.yaml` | Version changelog (YAML with HTML body) |
| `data/psn_tokens.json` | PSN OAuth tokens — access + refresh (auto-generated, cached ~2 months) |
| `data/xbox_tokens.json` | Xbox OAuth tokens (auto-generated, not user-edited) |

### Routes (Flask Blueprints)
| File | URL Prefix | Purpose |
|------|-----------|---------|
| `app.py` | `/`, `/dashboard`, `/analytics`, `/changelog`, `/help`, `/setup`, `/api/setup`, `/api/timezones`, `/api/jobs/resume/<id>`, `/api/jobs/dismiss/<id>` | Main pages, setup wizard, timezone API, job recovery |
| `routes/auth.py` | `/login`, `/logout`, `/api/users/avatar`, `/api/users/avatar/remove` | Authentication, sessions, roles, avatars |
| `routes/games.py` | `/games`, `/game/<id>`, `/api/games`, `/api/games/ids`, `/api/games/card-data`, `/api/games/bulk-edit`, `/api/game/<id>/completion`, `/api/game/<id>/track-view`, `/api/recently-viewed`, `/api/filter-games`, `/api/game/<id>/edit`, `/api/game/<id>/detail` | Game list, detail, edit, bulk edit, tracking, filter options |
| `routes/games_hltb.py` | `/api/hltb-lookup/<id>`, `/api/hltb-save/<id>`, `/api/hltb-clear/<id>`, `/api/hltb/search` | HowLongToBeat playtime lookup, save, clear, generic search. Split from `routes/games.py`. |
| `routes/games_ai.py` | `/api/game/<id>/ai-fill` | AI-powered metadata fill via Gemini/OpenAI/Claude with smart overwrite + rating cross-map + scrape-history. Split from `routes/games.py`. |
| `routes/games_search.py` | `/api/games/search`, `/api/games/find`, `/api/games/<id>/similar`, `/compare`, `/api/games/compare` | External scraper search, local-library search, similar-games suggestions, side-by-side comparison. Split from `routes/games.py`. |
| `routes/games_media.py` | `/api/delete-game/<id>`, `/api/rename-rom/<id>`, `/api/delete-screenshot/<id>` | Destructive game actions: DB delete, ROM file rename, screenshot removal. Split from `routes/games.py`. |
| `routes/systems.py` | `/systems`, `/systems/<id>` | System browser & per-system game lists |
| `routes/achievements.py` | `/achievements`, `/api/achievements/*` | RetroAchievements integration |
| `routes/trophies.py` | `/trophies`, `/api/psn/games`, `/api/psn/games/ids`, PSN routes | RPCS3 local + PSN trophies (API-driven) |
| `routes/scraper.py` | `/api/scraper-settings` | Scraper config, API keys, rate limits |
| `routes/settings.py` | `/settings`, `/api/settings/*` | App settings, logging, backups |
| `routes/controllers.py` | `/api/controllers/*` | Controller CRUD & system defaults |
| `routes/reports.py` | `/reports`, `/api/reports/*` | ROM naming validation, stats |
| `routes/tools.py` | `/tools/`, `/archive-scanner`, `/chd-*`, `/duplicate-finder`, `/multi-disc-organizer`, `/screenshot-dedup` | ROM tools hub & suite |
| `routes/maintenance.py` | `/api/maintenance/*`, `/api/clear-clz-imports`, `/api/maintenance/image-resize/*` | ROM scanning, orphan cleanup, bulk updates, CLZ import cleanup, image standardization |
| `routes/bulk_scrape.py` | `/api/bulk-scrape*` | Bulk metadata scraping queue |
| `routes/scrape_logs.py` | `/logs`, `/api/logs/*` | Universal log viewer, log file management (all categories) |
| `routes/clz_import.py` | `/clz-import` (redirects to `/game-imports`), `/api/clz-import/*` | CLZ Games PDF import API |
| `routes/ra_sync.py` | `/api/ra-sync/*` | RetroAchievements background sync |
| `routes/bonus_discs.py` | `/api/bonus-discs/*` | Bonus disc detection & linking |
| `routes/collections.py` | `/tags`, `/lists`, `/list/<id>`, `/wishlist`, `/api/tags/*`, `/api/lists/*`, `/api/wishlist/*` (incl. `/<id>/scrape`, `/scrape-all`), `/api/games/<id>/tags/*` | Tags, named lists, wishlist management + metadata scraping |
| `routes/collector_trophies.py` | `/collector-trophies`, `/api/collector-trophies`, `/api/collector-trophies/refresh` | Collector trophy gamification system |
| `routes/museum.py` | `/museum`, `/museum/<id>`, `/api/museum/generate/*`, `/api/museum/controller-image/*`, `/api/museum/controller-image-upload/*` | Gaming system encyclopedia, AI content generation, controller image search/upload |
| `routes/platform_import.py` | `/platform-import` (redirects to `/game-imports`), `/api/steam/*`, `/api/xbox/*`, `/api/psn/import/*`, `/api/psn/fetch-library` | Steam, Xbox & PSN game library import, achievement sync, Xbox OAuth |
| `routes/steam_achievements.py` | `/steam-achievements`, `/steam-achievements/game/<id>`, `/api/steam-achievements/*` | Steam achievements landing + per-game detail with individual achievements |
| `routes/xbox_achievements.py` | `/xbox-achievements`, `/xbox-achievements/game/<id>`, `/api/xbox-achievements/*` | Xbox achievements landing + per-game detail with gamerscore |
| `routes/game_imports.py` | `/game-imports` | Consolidated game imports (CLZ, Steam, Xbox, PSN tabs) |

### Services
| File | Purpose |
|------|---------|
| `services/database.py` | SQLite connection, query helpers, WAL mode, `safe_column()` allowlist validator for SQL f-string interpolation |
| `services/database_init.py` | Schema bootstrap: `init_database()`, `ensure_user_tables()`, and data migrations (`_migrate_genre_canonical`, `_migrate_pegi_format`). Runs on every import (idempotent). |
| `services/analytics.py` | Pure data helpers (20 `_get_*` functions) feeding the `/analytics` page charts. No Flask/session coupling. |
| `services/formatters.py` | `format_size()`, `get_manufacturer()`, `MANUFACTURER_MAP` — shared by analytics, template filters, stats endpoints. |
| `services/template_filters.py` | Jinja filters (`timestamp_to_date`, `trophy_type_name`, `format_number`, `format_size`, `format_ratio`, `tz`). Entry point: `register_filters(app)`. |
| `services/game_query.py` | Shared game-list query helpers: `escape_like`, `_get_filter_options` (with 60 s TTL cache), `_build_games_query`, `get_retroachievements_info`, `get_trophy_info_for_game`, `get_bonus_discs_for_game`. Extracted from `routes/games.py`. |
| `services/log_redactor.py` | `SecretRedactor` logging filter — masks JWTs, OAuth tokens, API keys before they hit `logs/*.log` |
| `services/auth.py` | Password hashing, role decorators (`@login_required`, `@admin_required`) |
| `services/security.py` | Path validation (`safe_path`, `safe_filename`), login rate limiting |
| `services/game_utils.py` | Title parsing, sort titles, rating mappings, system constants (`COMPUTER_SYSTEMS`, `HANDHELD_SYSTEMS`, `ENGINE_SYSTEMS`, `get_system_type()`, `build_filename()`) |
| `services/jobs/` | Background job package (split from monolithic `jobs.py`) |
| `services/jobs/__init__.py` | Re-exports all classes and singleton instances for backward compatibility |
| `services/jobs/base.py` | Shared helpers: `_get_conn()`, `_get_ra_credentials()`, job persistence functions |
| `services/jobs/bulk_scrape.py` | `BulkScrapeJob` class — queue management, pause/resume, background scraping |
| `services/jobs/ra_sync.py` | `RASyncJob` class — RetroAchievements user progress sync |
| `services/jobs/ra_refresh.py` | `RARefreshJob` class — scan games for RA support |
| `services/jobs/psn_refresh.py` | `PSNRefreshJob` class — bulk PSN trophy syncing |
| `services/jobs/museum.py` | `MuseumGenerateJob` class — bulk AI museum content generation |
| `services/jobs/image_resize.py` | `ImageResizeJob` class — bulk image standardization (upscale/downscale) |
| `services/jobs/platform_sync.py` | `SteamSyncJob`, `XboxSyncJob` — background achievement sync for imported Steam/Xbox games |
| `services/image_utils.py` | Image standardization: Real-ESRGAN upscaling, Lanczos downscaling, per-type targets |
| `services/normalization.py` | Genre/modes normalization dicts, DB custom rules, preview/apply logic |
| `services/wishlist_scraper.py` | Wishlist metadata scraper — orchestrates `scraper_manager.search_games` + the per-source `apply_*_to_metadata` mergers to fill boxart/description/release/ratings/critic score on wishlist rows. Background-thread dispatch (`scrape_wishlist_item_async`, `scrape_unscraped_items_async`). Image files namespaced `w{id}_*` so they don't collide with owned-game boxart. |

### Scrapers (`scraper/`)
| File | Purpose |
|------|---------|
| `scraper/base_scraper.py` | Shared helpers: `http_get`, `http_post`, `download_image`, `rate_limit`, `safe_json` with retry/backoff |
| `scraper/hybrid_scraper.py` | Orchestration: `apply_hybrid_metadata()`, extended fetch, detection helpers |
| `scraper/metadata_merger.py` | Per-source apply functions: `apply_tgdb_to_metadata()`, `apply_igdb_to_metadata()`, `apply_ai_to_metadata()`, etc. |
| `scraper/scrape_metadata_igdb.py` | IGDB API scraper |
| `scraper/scrape_metadata_thegamesdb.py` | TheGamesDB API scraper |
| `scraper/scrape_rawg.py` | RAWG.io API scraper |
| `scraper/scrape_screenscraper.py` | ScreenScraper API scraper |
| `scraper/scrape_esde.py` | ES-DE local gamelist.xml parser |
| `scraper/scrape_ai.py` | AI metadata scraper (Gemini, OpenAI, Claude) — text fields only, gap-filling |
| `scraper/retroachievements.py` | RetroAchievements API integration |
| `scraper/scraper_manager.py` | Scraper orchestration and priority logic |
| `scraper/scrape_steam.py` | Steam Web API — owned games, achievements, player profiles |
| `scraper/scrape_xbox.py` | Xbox Live API — OAuth2 auth, title history, achievements |

### Templates (45 files in `templates/`)
| Template | Page/Feature |
|----------|-------------|
| `base.html` | Master layout: sidebar, nav, scripts, CSS loading |
| `dashboard.html` | Home page with stats, recent games |
| `login.html` | User login |
| `setup.html` | First-run wizard |
| `force_change_password.html` | Initial password change |
| `systems.html` | System grid browser |
| `system_games.html` | Per-system game list (API-driven via AllGamesController) |
| `all_games.html` | Full library with infinite scroll |
| `game_detail.html` | Game detail + edit modal |
| `analytics.html` | Collection statistics with Chart.js (12 tabs: Summary, Charts, Developers, Gameplay, Playtime, Review Scores, Age Ratings, Achievements, Data Quality, Growth, Storage, Leaderboards) + Export (PNG/Clipboard/CSV) |
| `achievements.html` | RA achievements overview |
| `achievements_system.html` | Per-system achievements |
| `achievement_game.html` | Per-game achievements |
| `psn_trophies.html` | PSN trophy library |
| `psn_trophy_detail.html` | PSN trophy details |
| `local_trophies.html` | RPCS3 local trophies |
| `local_trophy_detail.html` | Local trophy details |
| `reports.html` | ROM naming validation & reports |
| `settings.html` | App settings (large: scrapers, logging, paths, API keys) |
| `rom_tools_settings.html` | ROM tools config |
| `archive_scanner.html` | Archive scanning tool |
| `chd_converter.html` | CHD conversion tool |
| `chd_verify.html` | CHD verification tool |
| `duplicate_finder.html` | Duplicate ROM finder |
| `multi_disc_organizer.html` | Multi-disc game organizer |
| `clz_import.html` | CLZ Games import (legacy, redirects to game_imports) |
| `platform_import.html` | Steam & Xbox import (legacy, redirects to game_imports) |
| `game_imports.html` | Unified tabbed import page (CLZ, Steam, Xbox, PSN) |
| `steam_achievements.html` | Steam achievements landing (all Steam games with progress) |
| `steam_achievement_game.html` | Steam per-game achievements (unlocked/locked with icons) |
| `xbox_achievements.html` | Xbox achievements landing (with gamerscore) |
| `xbox_achievement_game.html` | Xbox per-game achievements (with gamerscore badges) |
| `logs.html` | Universal log viewer (all categories) |
| `tags.html` | Tags management page |
| `lists.html` | Named lists overview |
| `list_detail.html` | Single list game view |
| `wishlist.html` | Wishlist page |
| `collector_trophies.html` | Collector trophy showcase with progress |
| `museum.html` | Museum landing page — timeline of systems by generation |
| `museum_system.html` | Per-system museum page with history, specs, top games, controllers |
| `compare_games.html` | Side-by-side game metadata comparison |
| `rom_tools_hub.html` | ROM tools hub landing page |
| `screenshot_dedup.html` | Screenshot deduplication tool (exact hash / visual similarity) |
| `help.html` | Full documentation (38 sections: install, getting started, platform notes, navigation, shortcuts, themes, dashboard, systems, API keys, settings, scraping, bulk scrape, AI fill, filtering, game details, bulk edit, compare, collections, imports, achievements, steam, xbox, HLTB, trophies, collector trophies, museum, analytics, reports, ROM tools, normalization, image resize, logs, maintenance, multi-user, backup, updating, troubleshooting, security) |
| `changelog.html` | Version history (reads `changelog.yaml`) |
| `_bulk_scrape_modal.html` | Bulk scrape modal (included partial) |
| `_bulk_edit_modal.html` | Bulk edit modal (included partial) |

### CSS Architecture (`static/css/`)
**Build:** `python3 build_css.py` concatenates all modules into `main.min.css`
**Load order:** Core → Layout → Components → Features → Pages → Effects → Utilities → Responsive

| Directory | Files | Purpose |
|-----------|-------|---------|
| `core/` | `variables.css`, `reset.css`, `typography.css`, `themes.css` | Design tokens, normalize, fonts, theme overrides |
| `layout/` | `layout.css`, `sidebar.css`, `responsive.css` | Page structure, nav, breakpoints |
| `components/` | `buttons.css`, `forms.css`, `cards.css`, `badges.css`, `tables.css`, `tabs.css`, `modals.css`, `toasts.css`, `progress.css`, `tags.css`, `queue-manager.css` | Reusable UI components |
| `features/` | `game-cards.css`, `game-modals.css`, `trophies.css`, `achievements.css`, `stat-boxes.css`, `filters.css`, `hltb.css` | Feature-specific styles |
| `pages/` | `game-list.css`, `pages.css` | Page-specific styles, system badge colors |
| `effects/` | `animations.css`, `backgrounds.css` | Keyframes, body gradient/scanlines |
| (root) | `utilities.css` | Helper classes (margin, padding, text) |

### JavaScript (`static/js/`)
**Build:** `python3 build_js.py` concatenates bundled files into `app.bundle.js`
**Bundle order:** utils -> page-lifecycle -> filters -> bulk-scrape -> bulk-edit -> toast-controller -> game-list -> game-modals -> main

| File | Bundle | Purpose |
|------|--------|---------|
| `theme.js` | No (FOUC) | Theme switching, persistence, canvas effects (Matrix rain, Ocean reflection, Cyberpunk volumetric noise smoke with hardware detection) |
| `utils.js` | Yes (1) | Shared helpers (formatBytes, formatNumber, API calls) |
| `page-lifecycle.js` | Yes (2) | Page state persistence |
| `filters.js` | Yes (3) | AlphabetNav (used by achievements/trophies pages) |
| `bulk-scrape.js` | Yes (4) | Bulk scrape queue UI |
| `bulk-edit.js` | Yes (5) | Bulk edit controller for game list pages |
| `toast-controller.js` | Yes (6) | Notification system, job status polling |
| `game-list.js` | Yes (7) | FanartController, BackToTopController, RARefreshController |
| `game-modals.js` | Yes (8) | Game detail/edit modals, screenshot carousel |
| `main.js` | Yes (9) | Core init, sidebar, search, tooltips |
| `all-games-controller.js` | No (page) | API-driven game list for `/games` and `/system/<id>` (infinite scroll, filters) |
| `achievements.js` | No (page) | Achievement display interactions |
| `trophies.js` | No (page) | Trophy display interactions |
| `settings-page.js` | No (page) | Settings form handling |
| `log-viewer.js` | No (page) | Universal log viewer (all categories) |
| `rom-tools.js` | No (page) | ROM tool operations, TaskPoller, PauseButton |
| `museum.js` | No (page) | Museum bulk generation, controller images, tab navigation, filtering |
| `app.bundle.js` | Output | Generated bundle (do not edit directly) |

### Global JS Functions & Objects (available on every page)

These are defined in the bundle (`app.bundle.js`) and `base.html` inline scripts. **Always use these exact names in template `<script>` blocks — never invent aliases.**

| Name | Source | Usage |
|------|--------|-------|
| `showNotification(msg, type, duration?)` | `utils.js` | Toast notifications. Types: `'success'`, `'error'`, `'warning'`, `'info'` |
| `showConfirm(title, msg, onConfirm, opts?)` | `base.html` | Confirmation dialog with callback |
| `showModal(title, msg, onConfirm?, showCancel?, onCancel?)` | `base.html` | Generic modal dialog |
| `escapeHtml(text)` | `utils.js` | HTML entity escaping |
| `formatNumber(num)` | `utils.js` | Thin-space thousands separator |
| `formatBytes(bytes, decimals?)` | `utils.js` | Human-readable file sizes |
| `copyToClipboard(text)` | `utils.js` | Clipboard write with fallback |
| `debounce(fn, wait)` | `utils.js` | Debounce wrapper |
| `throttle(fn, limit)` | `utils.js` | Throttle wrapper |
| `API` | `utils.js` | `.get(url)`, `.post(url, data)`, `.postForm(url, formData)` |
| `Storage` | `utils.js` | `.get(key)`, `.set(key, val)`, `.remove(key)`, `.clearAll()` |
| `Notifications` | `utils.js` | `.show()`, `.success()`, `.error()`, `.warning()`, `.info()` |
| `LoadingState` | `utils.js` | `.show(msg)`, `.hide(el)`, `.update(el, msg)` |
| `DOM` | `utils.js` | `.$()`, `.$$()`, `.create()`, `.toggle()`, `.delegate()` |
| `DateUtils` | `utils.js` | `.formatDate()`, `.formatDateTime()`, `.relative()` |
| `PageLifecycle` | `page-lifecycle.js` | Timer/observer/event management with auto-cleanup |
| `DOMCache` | `page-lifecycle.js` | `.getById()`, `.query()`, `.queryAll()`, `.clear()` |
| `AlphabetNav` | `filters.js` | `.init(config)`, `.scrollToLetter(el)` |
| `BulkScrapeController` | `bulk-scrape.js` | Bulk scrape queue management |
| `BulkEditController` | `bulk-edit.js` | Bulk edit modal controller |
| `UnifiedToastController` | `toast-controller.js` | Job status polling & persistent toasts |
| `ThemeIcons` | `toast-controller.js` | Theme-specific icon maps for all 7 themes |
| `getThemedIcon(key, fallback?)` | `toast-controller.js` | Get themed icon by key (job type, state, notification type) |
| `GameDetailModal` | `game-modals.js` | `.open(id)`, `.close()`, `.clearCache()` |
| `GameEditModal` | `game-modals.js` | `.open(id)`, `.save()`, `.close()` |
| `HLTBManager` | `game-modals.js` | `.lookup(ctx)`, `.save(ctx)`, `.cancel(ctx)`, `.clear(ctx)` |
| `triggerAiFill` | `game-modals.js` | AI metadata fill for current game detail modal |
| `StickyScroll` | `utils.js` | `.stackPositions()`, `.to(target, padding?)`, `.getStickyOffset(el?)`, `.updateMargins(padding?)` — universal sticky header scroll offset & stacking |
| `KeyboardShortcuts` | `main.js` | Global keyboard shortcut handler |
| `NOTIFICATION_TIMEOUTS` | `base.html` | Timeout config `{success, info, warning, error}` |

---

## Key Design Tokens

```
Primary:   --primary-cyan: #4cc9f0    --neon-cyan: #4cc9f0
Secondary: --primary-magenta: #f72585
Accent:    --neon-green: #22c55e  --neon-red: #ef4444  --neon-orange: #f59e0b  --neon-purple: #a855f7
Backgrounds: --bg-darkest: #0a0e17  --bg-darker: #0d1117  --bg-medium: #151b24  --bg-light: #1a222d
Text:      --text-primary: #e8eaed  --text-secondary: #9aa0a6  --text-muted: #6e7378
Fonts:     --font-heading: 'Orbitron'  --font-primary: 'Rajdhani'  --font-mono: 'Share Tech Mono'
Themes:    cyberpunk (default), matrix, amber, ocean, christian (Cathedral), bladerunner (Blade Runner), elite (Elite 1984)
```

---

## Distribution (Patreon Releases)

### Build Command
```bash
python3 build_dist.py            # Build all 3 platforms
python3 build_dist.py linux      # Build Linux only
python3 build_dist.py macos      # Build macOS only
python3 build_dist.py windows    # Build Windows only
```

### Output
- **Staging area:** `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB/`
- **Filename format:** `RetroDB-v{VERSION}-{Platform}.zip` (e.g. `RetroDB-v2.4.2-Linux.zip`)
- **Platforms:** Linux, macOS, Windows (each gets its own platform-specific start script)

### What's Included
| Category | Included | Excluded |
|----------|----------|----------|
| Code | All `.py`, templates, CSS, JS | `config.py` (user API keys) |
| Images | `hardware/`, `systems/`, `ratings/`, `avatars/`, `placeholder.png` | All scraped media (`boxart/`, `screenshots/`, `fanart/`, `boxart_3d/`, `manuals/`, `trophies/`) |
| Videos | — | `static/videos/` (scraped game videos) |
| Data | `changelog.yaml` | `settings.json`, `scraper_settings.json`, `rom_tools_config.json`, `hltb_dataset.csv`, `.secret_key` |
| Database | `database/.gitkeep` (empty dir) | All `.db` files |
| Start scripts | Platform-specific only | Other platforms' scripts |

### Platform Differences
- **Linux:** includes `start.sh`, excludes `start.bat` and `start.command`
- **macOS:** includes `start.command`, excludes `start.bat` and `start.sh`
- **Windows:** includes `start.bat`, excludes `start.sh` and `start.command`

### Release Checklist
1. Bump version in `config.py` and add changelog entry
2. Ensure `config.example.py` is up to date with any new settings
3. Run `python3 build_dist.py` to generate all 3 ZIPs
4. Upload from `/mnt/Storage/Scripts/Linux/Staging_Area/RetroDB/` to Patreon

---

## Standards Documents
- `docs/RETRODB_DESIGN_STANDARDS.md` — Full UI/CSS/JS standards (22 sections)
- `docs/STANDARDS_ADDENDUM.md` — Version checklist, logging system
- `docs/ROM_NAMING_STANDARD.md` — ROM file naming conventions

---

## Common Patterns

### Adding a new page
1. Create route in `routes/` and register blueprint in `app.py`
2. Create template extending `base.html` with `{% block content %}`
3. Add page-specific CSS to `pages/pages.css` or inline `{% block styles %}`
4. Add sidebar link in `base.html` if needed

### Modifying CSS
1. Edit the source file in `static/css/<category>/<file>.css`
2. Run `python3 build_css.py` to rebuild `main.min.css`
3. Template inline `<style>` blocks are for truly page-unique styles only

### Modifying JS
1. Edit the source file in `static/js/<file>.js`
2. If the file is part of the bundle (see JS table above), run `python3 build_js.py` to rebuild `app.bundle.js`
3. Never edit `app.bundle.js` directly — it is generated output

### Database access
```python
from services.database import get_db
db = get_db()
games = db.execute("SELECT * FROM games WHERE system_id = ?", [system_id]).fetchall()
```

### Sticky navigation scroll offsets
- Add `data-sticky-nav` to any `position: sticky` element that contains anchor links (`<a href="#id">`)
- Add `data-sticky-scope="containerId"` to a sticky nav that only applies within a specific container (e.g. the letter nav is scoped to the system controllers wrapper — its height is excluded from offset calculations for targets outside that container)
- Use `StickyScroll.to(targetOrId)` for JS-driven smooth scroll (auto-calculates offset from all stacked sticky headers)
- `StickyScroll.stackPositions()` dynamically sets CSS `top` on each visible `[data-sticky-nav]` so stacked sticky elements don't overlap
- Both `stackPositions()` and `updateMargins()` are called on DOMContentLoaded in `main.js`
- If a page switches panels/tabs that show/hide sticky navs, call `stackPositions()` then `updateMargins()` after the switch

### Theme-aware icons
- Use `getThemedIcon(key)` in JS to get an icon matching the current theme (e.g. `getThemedIcon('error')` returns `❌` on cyberpunk, `✗` on matrix)
- Available keys: job types (`bulk-scrape`, `ra-sync`, `ra-refresh`, etc.), states (`paused`, `resume`, `complete`, `queued`, `cancelled`), notifications (`success`, `error`, `warning`, `info`), stats (`stat-success`, `stat-failed`, `stat-skipped`), actions (`starting`, `running`, `cancel`, `save`, `loading`, `background`)
- In HTML templates: use `data-themed-icon="key"` attribute — `main.js` auto-populates on DOMContentLoaded
- `ThemeIcons` object in `toast-controller.js` holds the complete icon map for all 7 themes

### Number formatting
- Jinja: `{{ value|format_number }}` (thin-space thousands separator)
- JS: `formatNumber(value)` from `utils.js`
