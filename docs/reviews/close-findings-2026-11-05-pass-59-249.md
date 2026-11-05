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

| Finding | Verified | Disposition |
|---|---|---|
| Analytics manufacturer map misses ES-DE folders; use `SYSTEM_SPECS` (`services/formatters.py`) | yes | |
| "Recently scraped" misses re-scrapes (`app.py` `dashboard`) | yes | |
| Changelog/JSON reads in `app.py` lack `encoding=`; changelog YAML parsed per request | yes | |
| gzip check is a substring match (`gzip;q=0`) | not yet read | |
| `available_locales()` globs the disk on every call | not yet read | |
| Setup wizard: timezone not checked; raw sqlite connections lack try/finally | not yet read | |
| `stop_sentences([])` returns every service; server clock, not the user's | not yet read | |
| `(UK)` and comma-joined regions not in `_KNOWN_NON_PUBLISHER_TAGS` | not yet read | |

## C. Logging

| Finding | Verified | Disposition |
|---|---|---|
| `rom_tools` and `image_resize` lines also written to the scraping log | yes | |
| `CategoryFileHandler.emit` loads settings per record | not yet read | |

## D. Museum and GPU

| Finding | Verified | Disposition |
|---|---|---|
| Controller images saved under `STATIC_PATH`, not `IMAGE_PATH` (`routes/museum.py`) | yes | |
| `HSA_OVERRIDE_GFX_VERSION=10.3.0` forced; also set at `app.py` import, overwriting a user value | yes | |

## E. Imports (CLZ, platforms)

| Finding | Verified | Disposition |
|---|---|---|
| CLZ: non-Latin titles all match; preview creates systems | yes | |
| Steam `store_filled` check depends on JSON spacing | not yet read | |
| Import routes accept empty/None ids | not yet read | |
| Non-string Steam ID gives a 500 | not yet read | |
| Viewers can create system rows through fetch routes | not yet read | |
| Blank titles may match in platform imports | not yet read | |
| Xbox platform map lacks PC; 360 contract v2 may count 0/0 | not yet read | |
| Xbox history cap and partial lists are silent; delisted Steam apps re-asked | not yet read | |
| `main_story_hours` raises on "Main: ." | not yet read | |

## F. Bonus discs

| Finding | Verified | Disposition |
|---|---|---|
| Self-links and loops allowed; auto-link re-marks a disc the user unmarked | yes | |

## G. Image pipeline

| Finding | Verified | Disposition |
|---|---|---|
| GIFs upscaled then discarded | yes | |
| Upscale model download has no hash check | yes | |
| `upscale_queue.py` has no path containment check | not yet read | |
| `media_dir_is_healthy` counts any entry | not yet read | |
| GPU circuit-breaker race; swallowed error | not yet read | |
| Transparency kept only for RGBA on upscale | not yet read | |
| Two box faces naming one upload: second read empty | not yet read | |
| `webp_migrate._SOURCES` misses `boxart_back`, `game_logo` | not yet read | |
| WebP migrate disk guard asks twice the library size | not yet read | |
| `remove_box_faces` with unreadable record leaves files | not yet read | |

## H. Database, settings, restore

| Finding | Verified | Disposition |
|---|---|---|
| Restore removes `-wal`/`-shm` with connections open (`routes/settings.py` `api_restore`) | yes | |
| Migration 030 imports live code | not yet read | |
| `set_setting` read-modify-write unlocked | not yet read | |
| Lenient column helpers in migrations 001/012 swallow every error | not yet read | |
| `get_effective_path` crashes on a non-string | not yet read | |
| Orphan `pending_upscales` / game-scope `emulator_setting_choices` rows | not yet read | |
| `api_delete_game` leaves per-game rows behind | not yet read | |

## I. Maintenance and ROM scanning

| Finding | Verified | Disposition |
|---|---|---|
| Failed extraction leaves its folder; retries refused | not yet read | |
| Raw exception text in HTML (`settings.py`, `systems.py`) | yes | fixed in group A |
| `delete_images` "false" string is truthy | not yet read | |
| Two scans at once can add the same ROM twice | not yet read | |
| `rom_scanner.py` lacks `scan_roms.py`'s hidden/PS3/special-folder handling | not yet read | |
| Calculate Storage wrong for folder games | not yet read | |

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
