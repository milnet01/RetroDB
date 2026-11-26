---
paths:
  - "services/**"
  - "scraper/**"
  - "routes/**"
---

# Data, media and scraper contracts

### Schema / data shapes
- `perspective`, `dimension`, `genre`, `modes`, `game_structure` are comma-separated multi-value TEXT fields.
- A scraped word in those five fields ends as a `FIELD_SCHEMAS` or dropdown value, or is dropped: `services/normalization.py` owns the names, `metadata_merger.fill_labels` applies them per source, and `canonicalize_metadata` runs once more before the save (PASS-59-206).
- `region` is single-value, dropdown-driven (`region_options` setting; default `default_region`).
- Genre canonical forms are hyphenated and must match `FIELD_SCHEMAS` in `scraper/scrape_ai.py` (e.g. `First-Person-Shooter`, `Shoot-em-up`, `Beat-em-up`, `Hack-n-Slash`, `Board-Card`).
- `players` is INTEGER. Scraper/AI ranges like `"1-4"` are normalized to the max (4) before saving.
- Sort title is auto-generated during scraping and AI Fill via `generate_sort_title()` in `services/game_utils.py`.
- When a system has curated default controllers in the DB, they always override scraped/AI controller values, never a typed one (credited `manual`).
- `units_sold` (INTEGER, migration 023) is filled only by the AI — scrape gap-fill and AI Fill; `scrape_ai.parse_units_sold()` turns "2.4 million" etc. into an int. The AI is asked for it in a call of its own; a total published only across several consoles goes to `sales_all_platforms` (TEXT JSON, migration 049), shown on the analytics page only (PASS-59-343).
- `release_dates` (TEXT, migration 024) is a JSON object of region code → date (`{"JP": "2002-11-17", "NA": "2002-11"}`), filled by IGDB and ScreenScraper, then the AI. `services/release_dates.py` parses, stores and displays it; `release_date` stays the row's own release, and holds only as much of a date as its source knows (`docs/specs/scrapers.md` "How exact a date is", PASS-59-207).
- Arcade sets (PASS-59-227): a file in `ARCADE_SET_FOLDERS` keeps its name, because MAME finds a game by it. `games.arcade_category` holds the catver.ini top level; `BIOS` hides a row from game lists until asked for.
- RPCS3 compatibility (PS3) is never stored: `services/rpcs3_compat.py` reads the local RPCS3's `GuiConfigs/compat_database.dat` (re-read when it changes) and looks games up by `games.disc_serial`. Local ROMs only, never imported games.
- Completion status is each person's own (PASS-59-332): `services/game_status.py` owns `user_game_status` (no row = Not Started) and `play_sessions`; `games.completion_status` is written by nothing. A games query reads it through `game_status.STATUS_JOIN` / `STATUS_COLUMN`. The launcher's stderr thread records each Play session when the emulator exits. Spec: `docs/specs/PASS-59-332-play-sessions.md`.
- Regional versions (PASS-59-106): only `services/version_groups.py` links rows through `games.version_group_id`. `_build_games_query` shows one row per group unless `group_versions=False`. Contract: `docs/specs/PASS-59-106-regional-versions.md`.

### Media handling
- Media fields (boxart, boxart_3d, boxart_back, screenshots, fanart, game_logo, video, manual) are never replaced during normal scraping — only filled when empty. Screenshots are always appended, never replaced. To get new media: clear it from the edit modal first, then re-scrape. Full Re-scrape mode overrides this and overwrites any field a source actually provides, media included, unless its "Keep existing media" option is ticked (then media whose file is on disk is kept); fields no source fills keep their existing value — hand-curated data is not blanked.
- Slipcase box faces (PASS-59-142) are not a media field: `games.box_faces` holds a JSON record and `<IMAGE_PATH>/box_faces/` the WebP faces. Only `services/box_faces.py` writes them: an editor's import (fill-only unless replaced), or a box `services/box3d/build.py` builds from the scans, matched to `boxart_3d` (PASS-59-331), at each scrape and in ROM Tools' Build 3D Boxes (PASS-59-326), marked `source: auto`. A build never writes over an import; an import replaces a built box, and Clear removes only a built one. The image jobs never touch them, and `boxart_3d` and a scraped `boxart_back` (PASS-59-225) are separate. `services/box3d/` is ported from Slipcase: keep its names, so a Slipcase fix copies across. Specs: `docs/specs/PASS-59-142-box-file-import.md`, `docs/specs/PASS-59-326-auto-3d-box.md`.
- MobyGames box scans (PASS-59-183): `games.box_scans` holds every scan of one real release, one key per source, and `<IMAGE_PATH>/box_scans/` the files. A scrape fills it from one cover group, fill-only per source except Full Re-scrape; ScreenScraper or ES-DE add the disc or cartridge where no source has one (PASS-59-328); Clear empties it and deletes its files. `services/box_scans.py` chooses the group and deletes, never outside the folder. A game passed over because MobyGames' hour was spent waits in `mobygames_pending` for `MobyGamesCatchUpJob`. Spec: `docs/specs/PASS-59-183-mobygames-source.md`.
- Screenshot truth (PASS-59-161): exact palettes cannot judge a shot, because emulators differ and stored shots are lossy and upscaled. `services/screenshot_fit.py` refuses at download only on an original's exact colour count, and for Game Boy alone, because real ZX Spectrum and C64 originals hold up to thousands of colours; stored shots are only ranked, for a person to judge in Screenshot Review.
- A screenshot the user deletes stays deleted (PASS-59-222): `api_delete_screenshot` keeps its dHash in `removed_screenshots`, and a merge that passes `game_id` to `get_existing_screenshot_hashes` drops a look-alike. A new screenshot source must pass it too. Spec: `docs/specs/scrapers.md`.
- During pre-population, media files are validated on disk — stale DB references (file deleted, filename still in DB) are auto-cleared so scrapers can re-download.

### Scraper fill-only invariant
- Every scraper UPDATE (`hybrid_scraper._save_game_row`, the one that writes a scrape) MUST wrap every `?` in `COALESCE(?, column_name)` so an empty response from a source preserves the existing scraped or curated value. Bare `publisher = ?, developer = ?` is a bug (Pass 30.4 fix). `_save_game_row` is the canonical pattern. `tests/test_scrape_fill_only.py` pins the contract.
- Five exceptions. AI Fill replaces a scraped value it disagrees with in the fields of `VALIDATE_FIELDS`, never a hand-edited one or one from MobyGames (its terms forbid feeding its content to an AI), keeping the old value under `replaced` in that scrape's history entry (PASS-59-211). A date for the game's own region from IGDB or ScreenScraper fills out a stored year or month it agrees with (PASS-59-207). Full Re-scrape mode in `hybrid_scraper` overwrites any field a source provides (fields no source fills are preserved, not blanked). AI Fill renames a game to the official title the AI gives (`docs/specs/scrapers.md` §12), keeping the old name as an alternate title. And the title runs the other way: with `games.title_locked = 1` no scrape writes `title` or `sort_title`, Full Re-scrape included — the title writes are `CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END` (PASS-59-159 §4.3).

### Service limits (PASS-59-215)
- A sender to an online service calls `service_limits.wait_for_turn` before each request and returns its usual nothing when that says no. "Not found" and "stopped" look alike by design; a caller that must tell them apart asks `service_limits.stopped`. Table: `docs/specs/scrapers.md` §10.

### AI answers (PASS-59-211)
- `services/field_sources.py` reads `games.scrape_history` to mark what the AI wrote. The game page marks AI ratings as a guess and says when each board started (user, 2026-11-02: label, do not remove). A hand edit is credited `(manual)`, which clears the mark; any new edit path must call `_note_hand_edits` in `routes/games.py`.

### Steam imports (PASS-59-218)
- `SteamSyncJob` also fills empty fields once per game from the store page, and keeps play time in `platform_play_time`, per user. `games.scraped` stays as it was. The mark that a game was filled is a `scrape_history` entry with `primary_source` `steam`. Steam's date and genre are left out on purpose. Spec: `docs/specs/scrapers.md`.
