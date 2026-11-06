# close-findings ledger: PASS-59-249 (audit 2026-11-04 lows)

Source: `docs/reviews/2026-11-04-independent-audit.md` and the PASS-59-249 roadmap
body. Kept in the repository because the run spans sessions. One group per subject;
each group gets its own sweep and commit.

Disposition is one of: fixed, queued (with the item id), dismissed (with a reason).
An empty disposition means not yet closed. "yes" under Verified means the defect was
read in the tree on 2026-11-05; "not yet read" means it still needs that check.

## Dismissed before any group

| Finding | Verified | Disposition |
|---|---|---|
| `services/formatters.py` imported only by its test | No: `services/analytics.py`, `services/template_filters.py` and `routes/collector_trophies.py` import it | dismissed: the claim is false |

## A. Library lists and bulk edit

Tests: `tests/test_pass59_249_library_lists.py`, `tests/test_pass59_249_hltb_confidence.py`,
and additions to `tests/test_ai_fill_bulk.py` and `tests/test_ai_official_title.py`.
Each was run red against the unfixed code first.

| Finding | Verified | Disposition |
|---|---|---|
| Card ETag ignores achievement/PSN progress and launch changes | yes | fixed: the ETag is a hash of the built reply. Red: a 304 after progress was added |
| BIOS rows in header counts, letter bar and `api_filter_games` | partly: `/api/games` already hid them | fixed: shared `listed_sql` and `_LIST_COUNTS_SQL`, on the Library and console pages |
| `api_filter_games` includes bonus discs and does not group versions | yes | fixed: same `listed_sql`, plus `one_row_per_group` taken out of `_build_games_query` |
| Similar games lists own regional versions; drops NULL `is_bonus_disc` rows | yes | fixed: own group skipped, one row per group, `listed_sql` |
| Letter bar and accented first letters disagree | no: the bar's buttons are A to Z and "#", and `all-games-controller.js` files every other first letter under "#", as the `#` filter does | dismissed: no button sends an accented letter |
| Select all stops at its row cap silently | yes | fixed: reply carries `total` and `truncated`; the toast says the list was cut |
| Select all picks only the preferred version of each group | yes | dismissed: by design, `docs/specs/PASS-59-106-regional-versions.md` §4.3 ("a bulk action acts on what the user sees") |
| Bulk edit splits a string id; append mode crashes on a non-string | yes | fixed: 400 for a non-list or non-integer id, and for a non-text append value |
| Bulk edit runs `_note_hand_edits` outside the transaction | yes | fixed: runs on the bulk edit's own connection. Red: a failed save still credited a person |
| `_build_games_query` without `user_id` joins every user's progress | yes: latent, the one card caller passes it | fixed: the card query raises without `user_id` |
| Bulk AI fill count ignores a bad system id | yes | fixed: 400, as the run already did |
| AI Fill reply leaves out fields it fills | yes | fixed: reply carries a fixed field list plus every field filled |
| HLTB confidence of exactly 1 read as 100% | yes: every source sends a percent | fixed: always divided by 100 |
| Raw exception text returned as HTML | yes, five routes in `games.py`, `systems.py`, `settings.py` | fixed: logged and `abort(500)`, so the error page shows. Closes group I's `settings.py`/`systems.py` row too |

Run-level, group A:

- cited_by: `docs/specs/api-contracts.md` §5 (ETag) and §10 (bulk-id caps); `CLAUDE.md` regional versions line; `docs/specs/PASS-59-106-regional-versions.md` §4.3.
- swept: api-contracts §5.1 and §5.3 fixed (key recipe); §10 fixed (`truncated`); §5.2 agrees; `CLAUDE.md` agrees; PASS-59-106 §4.3 agrees; `templates/help.html` Select All and Alphabet Navigation lines agree.
- collateral: `tests/test_game_query.py` called the card query without a user; given `user_id=1`, or the count query where it pins bound values.
- surfaced: none.
- out_of_scope: `tests/test_etag_and_gzip.py` card-data test always skips on a 503, at HEAD too. Similar games' `reason` strings and the AI Fill button's "Filling..." are English-only. `test_the_shared_steam_key_is_for_admins_only[2]` fails in a full run and passes alone.
- falsified: none.

## B. Dashboard, changelog, app core

Tests: `tests/test_pass59_249_app_core.py`, plus additions to `tests/test_formatters.py`,
`tests/test_pass59_215_service_limits.py`, `tests/test_etag_and_gzip.py` and
`tests/test_pass59_248_hardening.py`. Each was run red against the unfixed code first.

| Finding | Verified | Disposition |
|---|---|---|
| Analytics manufacturer map misses ES-DE folders; use `SYSTEM_SPECS` | yes, and wider: most ES-DE folders with a `SYSTEM_SPECS` maker fell to "Other" | fixed: `get_manufacturer` falls back to the first maker `SYSTEM_SPECS` names |
| "Recently scraped" misses re-scrapes | yes | fixed: ordered in SQL by each game's newest history entry. A `manual` entry (a hand edit, PASS-59-211) no longer counts as a scrape |
| Changelog/JSON reads in `app.py` lack `encoding=`; changelog YAML parsed per request | yes | fixed: `encoding='utf-8'` on every text read in `app.py`; `_changelog_file` parses once per file change |
| gzip check is a substring match | yes | fixed: `request.accept_encodings['gzip']` |
| `available_locales()` globs the disk on every call | yes | fixed: read again only when `translations/` changes |
| Setup wizard: timezone not checked; raw sqlite connections lack try/finally | yes | fixed: an unknown zone is refused before anything is saved; both connections use `closing()` |
| `stop_sentences([])` returns every service; server clock | yes | fixed: `[]` asks about none; the time goes through `tz_filter` |
| `(UK)` and comma-joined regions not in `_KNOWN_NON_PUBLISHER_TAGS` | yes: latent, no caller reads `publisher` | fixed: region words shared, alone or comma-joined, with UK and four more |

Run-level, group B:

- cited_by: `docs/specs/api-contracts.md` §6.1; `docs/specs/i18n.md` §3 (`available_locales`).
- swept: api-contracts §6.1 rule 6 fixed; i18n.md §3 fixed; `docs/specs/scrapers.md` §10 table names no stop-text time, agrees; i18n foundation design doc is a dated design record, frozen.
- collateral: none.
- surfaced: none.
- out_of_scope: none.
- falsified: none.

## C. Logging

Test: `tests/test_pass59_249_logging.py`, run red against the unfixed code first.

| Finding | Verified | Disposition |
|---|---|---|
| `rom_tools` and `image_resize` lines also written to the scraping log | yes | fixed: `CategoryFileHandler.emit` skips a line whose closest logger entry (`category_of`) is another category's. Propagation to the root log is kept |
| `CategoryFileHandler.emit` loads settings per record | yes, but `load_settings` is cached by file date: a line costs one stat and a dict copy, never a file read | dismissed: no read happens per line |

Run-level, group C:

- cited_by: none outside `log_manager.py`.
- swept: `CATEGORY_LOGGERS` comment on propagation agrees (it still sets `propagate=False` for same-category children).
- collateral: none. surfaced: none. out_of_scope: none. falsified: none.

## D. Museum and GPU

Tests: `tests/test_pass59_249_museum.py`, `tests/test_pass59_249_gpu_env.py`, each run red first.

| Finding | Verified | Disposition |
|---|---|---|
| Controller images saved under `STATIC_PATH`, not `IMAGE_PATH` | yes: in the standalone build `STATIC_PATH` is inside the bundle an update replaces | fixed: `_controller_dirs`/`_controller_image_file` save to `IMAGE_PATH/controllers` and read the user folder, then the bundle. URLs are unchanged: `/static/images/<path>` already serves both roots |
| `HSA_OVERRIDE_GFX_VERSION=10.3.0` forced; also at `app.py` import, overwriting a user value | yes, at both | fixed: `services/gpu_env.py` sets it only when every GPU reports gfx103x in the kernel topology, and never over a set value. `app.py` MIOpen variables use `setdefault` |

Run-level, group D:

- cited_by: `start.sh` (its own gfx1032 gate, Pass 59.17); `tests/test_pass59_packaging.py` pins that gate.
- swept: `start.sh` agrees (narrower: gfx1032 only; an explicit value wins in both); `app.py` image-route comment agrees; hardware images stay bundle-only shipped assets.
- collateral: none. surfaced: none.
- out_of_scope: a bare `import app` outside pytest during this run opened the live database (startup warning only).
- falsified: none.

## E. Imports (CLZ, platforms)

Test: `tests/test_pass59_249_imports.py`, all ten run red first.

| Finding | Verified | Disposition |
|---|---|---|
| CLZ: non-Latin titles all match; preview creates systems | yes | fixed: the shared title key keeps non-Latin letters (CLZ now uses `normalize_title_for_dedup` instead of its own copy); the preview names a new system and the import creates it, admin only |
| Steam `store_filled` check depends on JSON spacing | yes; today's writer uses `json.dumps` defaults, so it matched | fixed: read with `json_each` |
| Import routes accept empty/None ids | yes | fixed: `_sent_id`; a game with no id counts as failed, in all three routes |
| Non-string Steam ID gives a 500 | yes | fixed: the id is read as text |
| Viewers can create system rows through fetch routes | yes | fixed: `_ensure_system_exists` creates only with the `edit` permission |
| Blank titles may match in platform imports | yes, through non-Latin titles | fixed with the CLZ row's title key |
| Xbox platform map lacks PC; 360 contract v2 may count 0/0 | yes (code read; Microsoft's replies not checked) | queued on PASS-59-261, which replaces this code |
| Xbox history cap and partial lists are silent; delisted Steam apps re-asked | yes | Steam: fixed, a store "no such app" is recorded once. Xbox: queued on PASS-59-261 |
| `main_story_hours` raises on "Main: ." | yes | fixed: the number must hold a digit |

Run-level, group E:

- cited_by: `docs/specs/scrapers.md` Steam row (store fill); CLAUDE.md Steam imports line.
- swept: scrapers.md Steam row, fixed (delisted sentence added); CLAUDE.md Steam line, agrees; help.html CLZ section, agrees (names no system creation); `game_imports.html` CLZ table, fixed (a new-system row is selectable).
- collateral: the new tests pushed the Steam import route past its rate limit for later test files; fixed with a limiter reset, as other files do.
- surfaced: none. out_of_scope: none. falsified: none.

## F. Bonus discs

Test: `tests/test_pass59_249_bonus_discs.py`, all four run red first.

| Finding | Verified | Disposition |
|---|---|---|
| Self-links and loops allowed | yes, and auto-link could pick a parent it marked later in the same sweep | fixed: a link is one level only (no self-link, no bonus-disc parent, no game with discs of its own); auto-link marks every disc before linking |
| Auto-link re-marks a disc the user unmarked | yes: unlink sets `is_bonus_disc = 0`, which detection reads as never judged | queued as PASS-59-262: it needs a new column, because every list reads any other value of `is_bonus_disc` as hidden |

Run-level, group F:

- cited_by: none in docs.
- swept: the help manual's bonus disc section names no linking rule, agrees.
- collateral: none. surfaced: none. out_of_scope: none. falsified: none.

## G. Image pipeline

Test: `tests/test_pass59_249_images.py`, all thirteen run red first.

| Finding | Verified | Disposition |
|---|---|---|
| GIFs upscaled then discarded | yes | fixed: `standardize_image` and the resize job skip a GIF |
| Upscale model download has no hash check | yes | fixed: a default-address download must match Hugging Face's published SHA-256 (`_MODEL_DIGESTS`); a cached default model of the wrong size is fetched again |
| `upscale_queue.py` has no path containment check | yes | fixed: `_media_files` keeps only names inside their folder (`safe_path`) |
| `media_dir_is_healthy` counts any entry | yes | fixed: hidden/temp files and `-sm`/`-md` variants do not count |
| GPU circuit-breaker race; swallowed error | yes | fixed: `_gpu_run` reads the queue once and raises when it stops; a GPU upscaler never runs its session off the GPU thread; the after-switch case logs |
| Transparency kept only for RGBA on upscale | yes | fixed: LA, PA and palette-with-transparency upscale as RGBA |
| Two box faces naming one upload: second read empty | yes | fixed: each upload is read once |
| `webp_migrate._SOURCES` misses `boxart_back`, `game_logo` | yes | fixed: both added (`game_logos/` folder) |
| WebP migrate disk guard asks twice the library size | yes | fixed: twice the largest file |
| `remove_box_faces` with unreadable record leaves files | yes | fixed: deletes the faces carrying the game's id |

Run-level, group G:

- cited_by: `docs/specs/image-pipeline.md` (model download, §12.1, invariants 4 and 9); `docs/specs/PASS-59-142-box-file-import.md` removal rule.
- swept: image-pipeline model passage, fixed; §12.1 worklist and disk precheck, fixed (also dropped two stale line citations); invariant 4, fixed; invariant 9, fixed; GIF table rows, agree; box file spec removal rule, fixed; help.html, agrees (names no WebP columns).
- collateral: `tests/test_webp_migrate.py` fixture lacked the two new columns; added.
- surfaced: none. out_of_scope: none. falsified: none.

## H. Database, settings, restore

Test: `tests/test_pass59_249_database.py`, ten of eleven run red first (a `None` path already worked).

| Finding | Verified | Disposition |
|---|---|---|
| Restore removes `-wal`/`-shm` with connections open (`routes/settings.py` `api_restore`) | yes; an open connection kept reading the old file after a restore | fixed: the backup is copied in with SQLite's backup API; no side files deleted, no file swap; the jobs check closes its connection |
| Migration 030 imports live code | yes | fixed in part: a missing helper skips the tidy with a log instead of failing boot. The drift half is dismissed: 030 runs only on upgrades from below 30, where today's tidy is the wanted one, and freezing copies of the mapping tables costs more than it saves |
| `set_setting` read-modify-write unlocked | yes | fixed: a process-wide lock around read, change and save. Two processes can still race; this app runs one |
| Lenient column helpers in migrations 001/012 swallow every error | yes | fixed: only `duplicate column name` is hidden; 001's default uses single quotes. Edited under migrations.md §4's carve-out (nil effect on databases past 12) |
| `get_effective_path` crashes on a non-string | yes | fixed |
| Orphan `pending_upscales` / game-scope `emulator_setting_choices` rows | yes | fixed: migration 040 adds delete triggers and removes existing orphans |
| `api_delete_game` leaves per-game rows behind | yes, in part: progress, views, removed screenshots, HLTB pending and play time cascade (`get_db` turns foreign keys on); media was already deleted | fixed for what was left: box face files (`delete_unshared_media` calls `box_faces.delete_faces_of`) and the two tables above |

Run-level, group H:

- cited_by: `docs/specs/migrations.md` (helpers note, pre-restore backups, migration table).
- swept: migrations.md helpers note, fixed (it said 001 and 012 stay as they are); restore passage, fixed (how a restore writes); migration table, fixed (row 040); help.html restore text, agrees (names no mechanism).
- collateral: none. surfaced: none.
- out_of_scope: `game_cleanup.clean_missing_roms` deletes games without deleting their media or box faces; left to the orphan sweep, not changed here.
- falsified: none.

## I. Maintenance and ROM scanning

Test: `tests/test_pass59_249_maintenance.py`, seven of eight run red first (`True` already worked). Two tests passed before the fix on their first draft and were tightened until they failed.

| Finding | Verified | Disposition |
|---|---|---|
| Failed extraction leaves its folder; retries refused | yes | fixed: the folder this call made is removed on any failure before the playlist is written |
| Raw exception text in HTML (`settings.py`, `systems.py`) | yes | fixed in group A |
| `delete_images` "false" string is truthy | yes | fixed: only JSON `true` deletes |
| Two scans at once can add the same ROM twice | no as stated: `games.rom_path` is UNIQUE. What is real: the refused insert raised and ended that console's folder | fixed: `INSERT OR IGNORE`, counting only rows added |
| `rom_scanner.py` lacks `scan_roms.py`'s hidden/PS3/special-folder handling | yes | fixed by deletion: the fallback ran only if `scraper.scan_roms` failed to import, which ships with the app; `run_inline_scan` and its tests removed |
| Calculate Storage wrong for folder games | yes | fixed: a folder's size is its files', links not followed |

Run-level, group I:

- cited_by: `docs/plans/2026-04-25-retrodb-multi-emulator-launch.md` names `services/rom_scanner.py`.
- swept: that plan, frozen (a dated plan); help.html, agrees (no mechanism named); `tests/test_scan_library_rom_path.py` header and fake cursor, fixed.
- collateral: a function-local `import shutil` in `create_m3u_playlist` shadowed the module's and broke the new cleanup; removed.
- surfaced: none. out_of_scope: none. falsified: none.

## J. Collections, achievements, trophies, tools

| Finding | Verified | Disposition |
|---|---|---|
| Collector-trophies docstring says library-wide | not yet read | |
| `ra_sync` second writer of RA link columns | not yet read | |
| Tag/list names, colours, sort_order unvalidated | not yet read | |
| Wishlist rename skips duplicate check | not yet read | |
| `ra_rom_name` splits on `/` only | not yet read | |
| Editors cannot pause/cancel ROM-tool scans they start | not yet read | |
| Removed trophies still count toward rank | not yet read | |

## K. Records and catalogs

| Finding | Verified | Disposition |
|---|---|---|
| `apply_esde_metadata` has no production caller; docs name it canonical | yes | |
| Obsolete `#~` entries duplicate live msgids in every locale but `eo` | yes | |

## Open questions from the audit (not findings; to ask or file)

- `reset_to_defaults` resets `setup_completed`.
- Where Steam's date and genre are left out.
- Unreadable PS3 serial re-reads all PS3 discs on each Library load.
- `get_system_type` casing vs the naming validator.
- `queued=True` replies with no server-side queue (RA sync, achievements).
- Does the log viewer strip credentials?
- Collector trophies not filtered by source.
- DecompressionBomb not caught in code (PASS-59-250 fixes only the doc).

## Run-level fields, per group at its sweep

Filled when each group's sweep runs.
