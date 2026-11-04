# Scrapers

> **TL;DR** — Ten sources fan into one orchestrator (`hybrid_scraper`), one per-source merger (`metadata_merger`), one scorer (`match_scorer`) and one HTTP base layer (`base_scraper`). Every write is fill-only via `COALESCE(?, column)` so an empty upstream response can never wipe a curated value (Pass 30.4 / 40.6 / 45.3 are all instances of this rule being broken; the contract pins them shut). Image fetches MUST go through `base_scraper.download_image` or `metadata_merger._download_and_finalize` — both gate on SSRF, pin the resolved IP across the redirect chain, stream with a size cap, and write atomically.

---

## 1. Purpose

RetroDB ingests game metadata from a mix of remote APIs (IGDB, TGDB, RAWG, ScreenScraper, RetroAchievements, HLTB), a local file source (ES-DE `gamelist.xml` + `downloaded_media/`), and a generative AI fallback. Steam and Xbox modules supply per-user library imports and achievement data, not metadata. The scraper subsystem unifies these into a single `games` row: it walks one user-selected primary source, falls back to user-prioritised secondaries to fill any remaining gaps, and writes the result without ever overwriting a non-empty field unless the user has opted into Full Re-scrape mode.

Three contracts pin the subsystem and exist solely because they were broken in the past:

1. **Fill-only writes** — every `?` in a scraper UPDATE is wrapped in `COALESCE(?, column)` (Pass 30.4, Pass 40.6, Pass 45.3).
2. **Hardened image downloads** — SSRF gate + DNS pin + atomic write + size cap on every download path (Pass 40.7, Pass 45.2).
3. **Best-match selection** — title scoring + platform-match boost + region heuristics decide which candidate to apply when multiple results come back, with a minimum-score threshold that rejects wrong-game matches (e.g. "Alan Wake II" when searching "Alan Wake Remastered").

This document codifies all three plus the wiring that holds them together.

See also: CLAUDE.md "Scraper fill-only invariant" and "Schema / data shapes"; [`image-pipeline.md`](image-pipeline.md); `roadmap.md` Pass 30.4 / 40.6 / 40.7 / 41.4 / 41.5 / 45.2 / 45.3 / 45.6; `tests/test_scrape_fill_only.py`.

---

## 2. Source inventory

| Source            | File                              | Kind            | Requires key                                                              | Used for                                                                                          |
|-------------------|-----------------------------------|-----------------|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| ES-DE             | `scraper/scrape_esde.py`          | local-gamelist  | No (reads ES-DE folders on disk)                                          | Primary metadata + media when user has scraped via ES-DE; canonical `apply_*` pattern (see §5)    |
| TheGamesDB        | `scraper/scrape_thegamesdb.py`    | remote          | `tgdb_apikey`                                                             | Metadata + boxart + screenshots + fanart; platform-specific covers                                |
| IGDB              | `scraper/scrape_igdb.py`          | remote          | `igdb_client_id` + `igdb_client_secret`                                   | Richest metadata (genres, modes, perspectives, age ratings × 7 systems, franchise, similar games) |
| RAWG.io           | `scraper/scrape_rawg.py`          | remote          | `rawg` (settings key; falls back to `RAWG_API_KEY` in `config.py`)        | Metacritic critic score, user score; background picture as fanart, no boxart. Credits, ESRB and multiplayer modes only from a record on one platform (PASS-59-208); never a player count |
| ScreenScraper     | `scraper/scrape_screenscraper.py` | remote          | `screenscraper_username` + `_password` + `_devid` + `_devpassword`        | Retro-specific metadata, regional alt titles, system-specific media (boxart 3D, video, manual)    |
| Steam             | `scraper/scrape_steam.py`         | remote          | `steam_api_key` + `steam_id` (store app details need no key)              | Per-user owned-games import and achievement sync. Not a source in the hybrid walk: `SteamSyncJob` fills an imported game once from its store page, as primary source `steam` with `mark_scraped=False`. It leaves the date and genre to a scrape, because the date is the Steam release and the genre is nearly always Action.                |
| Xbox              | `scraper/scrape_xbox.py`          | remote          | `xbox_client_id` + `xbox_client_secret`, then a per-user Microsoft OAuth2 sign-in (XBL + XSTS tokens) | Per-user title import and achievement sync. Not a source in the hybrid walk. |
| RetroAchievements | `scraper/retroachievements.py`    | remote          | `ra_apikey`                                                               | `has_retroachievements`, `ra_game_id`, `ra_achievement_count`, `ra_points` (tail of hybrid apply) |
| AI Fill           | `scraper/scrape_ai.py`            | AI              | One of: `ai_gemini_api_key`, `ai_openai_api_key`, `ai_anthropic_api_key` (+ optional `ai_gemini_project_id`) | Final gap-fill for text-only fields; never media (see §12)                                        |
| HLTB              | `scraper/hltb_lookup.py`          | remote          | No (public site scrape)                                                   | Playtime estimates (main / extra / completionist) for HowLongToBeat                               |

**Platform coverage** (user, 2026-10-27). A source is searched only when it maps the game's system to one of its platforms, and every query it sends keeps that platform filter: `scrape_rawg.PLATFORM_MAP` (only platforms RAWG lists; no Intellivision, ColecoVision, PC Engine, arcade, Virtual Boy), `scrape_igdb.get_platform_id`, `scrape_thegamesdb.get_system_id`, `scrape_screenscraper.get_system_id`. An unmapped system gets `[]` without a request: searching without the filter matched games from other platforms. A system's name or folder must match an entry exactly; part of a name is no match. TheGamesDB files Mega Drive and Genesis as two platforms, so a game's own list is searched first and the other only if that finds nothing. Its documented comma-separated platform filter is ignored by the live service, which then returns every platform (tried 2026-10-31). The maps live in the scraper modules, not `config.py`, because an update never rewrites an installed `config.py`. Pinned by `tests/test_scraper_platform_coverage.py` and `tests/test_scraper_platform_maps.py`.

Per-source disable + priority: `data/scraper_settings.json` → `enabled` + `priority`. The first enabled source in priority order whose API key is configured wins as primary when the user picks one; the rest fall back in priority order (see §3).

---

## 3. Hybrid orchestration

Entry point: `scraper.hybrid_scraper.apply_hybrid_metadata(db_game_id, primary_source, primary_id, system_folder, secondary_sources=None, fill_gaps=True, force_overwrite=False, primary_data=None, restrict_to_selected=False, keep_media=False)`.

Two modes:

- **Normal (default; `force_overwrite=False`)** — pre-populate `metadata` from the existing `games` row so every per-source merger sees the current state and only writes into still-empty fields. Stale media references (file deleted but DB still names it) are detected via `os.path.exists` and conditionally NULLed under a `WHERE id = ? AND <field> = ?` guard so a concurrent upload between stat and clear isn't wiped (Pass 40.15).
- **Full Re-scrape (`force_overwrite=True`)** — `metadata` starts empty; every source applies as if the row were new. ES-DE deletes the row's old box art and 3D box only when it copied a replacement itself; a field another source already filled in this run is left alone. This is the only documented exception to fill-only.
  - **Keep existing media (`keep_media=True`, bulk mode `full_rescrape_keep_media`)** — seeds each media field whose file is on disk (`_seed_kept_media`), so it is not downloaded again and ES-DE leaves it alone; new screenshots still append (PASS-59-133).

Walk order:

Before step 1, a region tag in the ROM's file name (`extract_region_from_filename`) fills an empty `region`, so no source and no AI answers for it; a stored region stays, Full Re-scrape included (PASS-59-204). AI Fill also leaves `region` alone on a tagged file.

1. **Primary fetch** — `_pick_best_secondary` if the user picked from search results, else freshly fetched via the source-specific `fetch_*_extended` / `fetch_*_game_details`. Each primary dispatch is wrapped in `try / except` (Pass 41.4.B) so a malformed response from one provider falls through to gap-fill rather than aborting the whole hybrid apply.
2. **Apply primary** — call the matching `apply_<src>_to_metadata(metadata, data, db_game_id, result, fill_only=False)` from `metadata_merger.py`. `fill_only=False` lets the primary overwrite `title` only (other fields stay fill-only across both modes), unless the title is locked (§ Title lock below).
3. **Gap fill** — compute `missing = [k for k, v in metadata.items() if not v]`. Walk user priority (skipping primary, disabled sources, and sources already applied). When `restrict_to_selected=True`, fallback is further restricted to `secondary_sources` (plus AI); an empty list leaves AI alone. The game page's Apply sets it, passing only the results the user ticked (PASS-59-134). Each fallback for **TGDB, IGDB, RAWG, ScreenScraper, and AI** runs under the per-source circuit breaker (`_<src>_breaker` in `scraper_manager`) — five consecutive failures opens the breaker for 120 s. ES-DE has no breaker (see §11). ES-DE merges through `_merge_esde` in both roles, so its values reach `metadata` like any source's. As a fallback it finds the gamelist row for the game's own ROM file first and searches by title only if there is none (PASS-59-205). Steam, Xbox and HLTB are not part of the fallback walk; RetroAchievements runs only as the tail step (6).
4. **Post-merge passes** — region single-value reduction (`_normalize_region`), save-type detection (`detect_save_type`), controller support detection (`detect_controller_support`), curated DB-default controller override (`get_system_default_controller_name`), rating normalize + cross-map + content-inference (`_normalize_ratings`), `players` integer-coercion via `re.findall(r'\d+', ...)` + `max(...)`, sort-title regeneration.
5. **Single fill-only UPDATE** — one statement with `COALESCE(?, col)` on every column (see §5 for the exact SQL).
6. **RA tail** — `_apply_retroachievements_check` opens its own connection, looks up the game by ROM name, title and alternate titles, and stores the answer with `save_ra_link`: a hit links, a real miss clears, no answer changes nothing (`docs/specs/trophies.md` §4.3). Exceptions are swallowed so a down RA service can't poison the rest of the scrape.

The single UPDATE is **not** wrapped in a try/except fallback: a failure means `metadata` and the binding tuple have diverged (someone added a field but not the column), and the scraper must fail loudly. Per-source primary fetches and the RA check have their own narrow try/except blocks; the UPDATE itself does not.

---

## 4. Merge priority

Priority is the user's configured scraper order (Settings -> Scrapers, `fallback_settings['priority']`, default `scraper_manager.DEFAULT_SCRAPER_PRIORITY`: `screenscraper -> esde -> tgdb -> igdb -> rawg`). There is no per-field allow-list. Within a hybrid run:

1. The **primary** source applies first, wherever it sits in that list.
2. The remaining enabled scrapers then run in the user's order, minus the primary and any disabled one (`_run_fallbacks`).
   Every one but AI is searched and fetched at the same time, one thread per source; the records are then applied one by one in that order (PASS-59-132). AI runs at its turn, after the earlier records are applied, because its prompt names the fields still empty.
3. Each per-source merger in `metadata_merger.py` writes a field only while it is still empty (`if not metadata['field']`), so the first source to supply a value keeps it.

Which fields a source can fill is therefore decided by what that source's merger implements.

Fields no scraper supplies:

- `save_type` - the `detect_save_type` post-merge pass, AI fill, or manual entry.
- `china_rating` - inference, AI fill or manual; no Western scraper supplies a CADPA rating.
- `dimension`, `perspective`, `game_structure`, `edition`, `campaign`, `other_platforms`, `alternate_titles`, `sort_title` - written directly by the per-source mergers.

Tie-breakers:

- **ScreenScraper regions**: `scraper/ss_regions.by_region` is the one order for its names, dates, boxes and manuals (PASS-59-202): this copy's region, then `version_groups.preferred_regions()`, then the generic `ss` entry, then the rest as listed. `ss_regions.own_region` takes this copy's region from its file name's tag, else the stored value. Descriptions stay English. The smaller `video-normalized` is tried first and `video` only if that fails. A search result is scored against all its regional names. Games scraped earlier are put right by the job `ss_region_repair` (`jobs.md`).
- **Boxart**: ScreenScraper ships system-specific covers (Saturn JP boxart for a Saturn ROM) where IGDB ships the generic global cover, so order IGDB last if regional covers matter. RAWG has no covers: its `background_image` is wide art or a screenshot, so it fills fanart only, and ROM Tools > Clear RAWG Pictures from Box Art empties covers older scrapes took from it (PASS-59-203). RetroDB's sidebar links to RAWG on every page, as its terms ask. ES-DE ahead of a source means its local cover wins over that source's, as primary or as a fallback (PASS-59-205).
- **Screenshots**: never replaced, always *appended*, then deduped via `image_dedup.compute_dhash` with Hamming-distance threshold 10. Each per-source merger reads existing filenames + their hashes once, then calls `keep_screenshot_if_unique` on each new download. Visual dupes (re-encodes / resizes) are dropped before they reach the UPDATE. A screenshot the user deletes from a game keeps its dHash in `removed_screenshots`; passing `game_id` to `get_existing_screenshot_hashes` adds those, so every merger and the ES-DE copy drop a picture that looks like one removed (PASS-59-222). The Duplicate Screenshots tool records nothing: its user keeps one copy of that picture. IGDB and RAWG attach screenshots to the game, not to one platform's version, so on an 8-bit or 16-bit system theirs are taken only when the game lists exactly one platform (`base_scraper.per_game_screenshots_fit`, `screenshot_fit.EIGHT_AND_SIXTEEN_BIT`, PASS-59-161). Newer systems take them regardless, and may show another version's pictures.
- **Empty values never win**: the fill-only invariant (§5) means a later high-priority source filling an empty field always wins, but an empty response from a high-priority source never wipes what came from a lower-priority source.
- **Curated DB defaults always win for controllers**: `get_system_default_controller_name` runs after gap-fill and overrides whatever was scraped/inferred.

---

### Identifying the file (PASS-59-217)

ScreenScraper is asked about the user's own file before a title search, unless a person ticked a result. `scrape_screenscraper.identify_by_file` accepts a reply only when it returns the CRC sent, or when a serial sent with a made-up file name finds a record, and it refuses records marked as no game. A miss falls through to the title search. Contract: [`PASS-59-217-identify-by-file.md`](PASS-59-217-identify-by-file.md).

### Extra data each source gives (PASS-59-216)

- **Title screens.** ScreenScraper's `sstitle` and TheGamesDB's `titlescreen` join `screenshots`. Each merge takes up to five shots and keeps one place for the title screen. TheGamesDB's has only its documentation behind it: no real reply has been seen.
- **Other titles.** IGDB's `game_localizations` and TheGamesDB's `alternates` join `alternate_titles`. TheGamesDB does not say where a title was used.
- **Other consoles.** IGDB's `platforms`, less this console, fill an empty `other_platforms`, spelled by `scrape_ai.known_platforms`. A name the schema lacks is left out. One platform writes nothing: IGDB can miss a version, so it does not prove `Exclusive`.
- **ES-DE's `rating`.** It fills `user_score` only when no online source gave one, and before the AI is asked. ES-DE does not record who set it; it may be the owner's own.
- **Logos (PASS-59-224).** `game_logo` is filled from ES-DE's `marquee` tag or `marquees/` folder, ScreenScraper's `wheel-hd` then `wheel`, TheGamesDB's `clearlogo` (same Images request), IGDB artwork type 7 then 5 (never 6, black), and Steam's `logo.png`. IGDB fanart skips logo, infographic and icon artworks. A record with no `game_logo` key, such as the wishlist's, gets no logo downloaded. Spec: `PASS-59-224-game-logos.md`.
- **Box backs (PASS-59-225).** `boxart_back` is filled from ES-DE's `backcovers/` folder, ScreenScraper's `box-2D-back` nearest the game's region, and TheGamesDB's boxart `side: back` (same request as the front). A back never stands in for a missing front. It is not a Fill Missing gap, so a game without one is not scraped again for it. It is separate from Slipcase's `box_faces`. The wishlist's record has no `boxart_back` key and downloads none.

## 5. Fill-only invariant

**The rule (scraper UPDATEs):** every `?` bound to a metadata-source value
in a scraper `UPDATE games` statement MUST be wrapped in
`COALESCE(?, column_name)` so an empty value from the upstream preserves
whatever's already in the column. Two places own a direct `UPDATE games`:
the hybrid orchestrator's composite UPDATE in `hybrid_scraper`, and
`scrape_esde.apply_esde_metadata`, which the ES-DE bulk import calls. Every
other source writes through `scraper/metadata_merger.py::apply_*_to_metadata`,
which feeds into the hybrid UPDATE.

**Audit-column exception.** A handful of columns are bare by design,
because they're status / audit data — overwriting them is the point. As
of the current code base that means `scrape_history = ?` and
`scraped = 1` in the hybrid UPDATE. Leave those bare.

**AI Fill is a separate path.** `services/ai_fill.py` does **not** use the
COALESCE wrapper. It builds the `UPDATE games` with bare `field = ?`
clauses and protects the fill-only contract one layer up via a
`should_apply` pre-filter plus the Pass 45.3 "skip int=0" guard
(`int(float("0"))` and similar empty-int sentinels are filtered before
the clause is appended). Don't wrap the AI Fill UPDATEs in COALESCE —
that would block the cross-map / rating-inference paths that intentionally
overwrite (because the user opted into AI fill).

**The bug class scraper-COALESCE prevents:** bare `publisher = ?, developer = ?` in a scraper UPDATE means that a source's response that didn't return publisher/developer (very common — partial records) will silently NULL the column on every re-scrape. Pass 30.4 fixed the original instance for `publisher`/`developer`. Pass 40.6 closed the variant on `players` where the dict was initialised to `1` (so `COALESCE(1, players)` always returned 1 — the `COALESCE` was correct, the initialiser was wrong; fixed via `normalize_players_value` returning `int|None`). Pass 45.3 closed the same shape in AI Fill where bare `field = ?` writes after `int(float("0"))` were clobbering curated `players=4` with `0` — fixed by the `should_apply` skip-empty-int guard, not by adding COALESCE.

**Canonical site:** `scraper/scrape_esde.py::apply_esde_metadata`, the ES-DE bulk import. A hybrid scrape merges ES-DE through `hybrid_scraper._merge_esde` instead. This SQL keeps an old value only when the new one is empty:

```sql
UPDATE games SET
    title       = CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END,
    publisher   = COALESCE(?, publisher),
    developer   = COALESCE(?, developer),
    release_date= COALESCE(?, release_date),
    genre       = COALESCE(?, genre),
    players     = COALESCE(?, players),
    modes       = COALESCE(?, modes),
    description = COALESCE(?, description),
    boxart      = COALESCE(?, boxart),
    boxart_3d   = COALESCE(?, boxart_3d),
    screenshots = COALESCE(?, screenshots),
    fanart      = COALESCE(?, fanart),
    game_logo   = COALESCE(?, game_logo),
    boxart_back = COALESCE(?, boxart_back),
    video       = COALESCE(?, video),
    manual      = COALESCE(?, manual),
    region      = COALESCE(?, region),
    ...
WHERE id = ?
```

The hybrid orchestrator's UPDATE (`hybrid_scraper.py::_save_game_row`) is the same pattern across its columns.

**Arcade sets** (PASS-59-227). In `services.game_utils.ARCADE_SET_FOLDERS` a file name is MAME's identity for a game. ROM Tools > MAME Names (`services/mame_names.py`) sets the title from MAME's list and locks it. A bulk scrape then searches by that title without its brackets, not by the file name. ScreenScraper's `identify_by_file` sends the zip's name as `romnom` and accepts a reply only if `romfilename` matches. ROM Reports will not rename these files.

**Title lock** (PASS-59-159 §4.3). `games.title_locked = 1` means no scraper writes `title` or `sort_title`, in normal or Full Re-scrape mode. Both sites above write `title` as `CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END`; `_save_game_row` writes `sort_title` the same way. Scrapers still search with a locked title. The edit windows set the lock when a title is changed, and their "Keep this title when scraping" tick box sets or clears it; the per-game Reset clears it. `tests/test_official_names.py` pins it.

**Exception:** Full Re-scrape mode in `hybrid_scraper` (`force_overwrite=True`) intentionally bypasses fill-only — the user opted in. ES-DE in this mode deletes old box art only once it has copied a replacement.

**Source ids are stricter.** `hybrid_scraper._save_source_ids` stores the IGDB and ScreenScraper game ids a scrape used, as regional-version signals (PASS-59-106 §4.5). It writes `COALESCE(igdb_id, ?)`: a stored id is kept, because a later wrong match would otherwise relink a game. Full Re-scrape writes `COALESCE(?, igdb_id)`. A ScreenScraper record for this exact file replaces the stored `screenscraper_id` (PASS-59-217). Pinned by `tests/test_scrape_fill_only.py::test_source_ids_fill_only`.

**Test pin:** `tests/test_scrape_fill_only.py` runs a real hybrid scrape over a populated row with a source that has nothing, and asserts the values survive. It also asserts that the IGDB and TheGamesDB merges keep stored media and add screenshots. AI Fill is not covered by it.

**When adding a new field** to the metadata dict in `hybrid_scraper.apply_hybrid_metadata`, add the corresponding column to the UPDATE binding tuple AND wrap the `?` in COALESCE in the same commit, and add a regression case to `tests/test_scrape_fill_only.py`. Drift between the metadata dict and the UPDATE tuple is precisely why the UPDATE has no try/except fallback — silent drift is the bug; loud failure is the contract.

---

## 6. Match scoring

`scraper/match_scorer.py::calculate_title_match_score(result_title, search_title) -> int` is the shared title scorer for every source. It runs both titles through `title_normalizer.strip_title_noise` (drops region tags, disc markers, edition tags, version tags), `services/game_utils.py::normalize_article_for_comparison` (moves a trailing article to the front: `Legend of Zelda, The` and `Legend of Zelda, The: Ocarina of Time` compare as `The Legend of Zelda…`; English `The`/`A`/`An` only) drops accents, apostrophes and the marks `.`, `!` and `?` (`Pokémon` is `Pokemon`, `Conker's` is `Conkers`, `R.B.I.` is `RBI`), then `normalize_for_matching` (lowercases, replaces colons/dashes/slashes with spaces, normalises Roman numerals II/VII → 2/7) before comparing. A title left empty by that (it was only tags, such as `(USA)`) scores 0.

Score ladder (pure title similarity, 0-350; the bands below are maxima, not floors):

1. Raw exact match before noise strip → **350**
2. Exact normalised match → **300** (+50 if raw exact)
3. Search words ⊆ result words → up to **280** (fewer extras score higher; "Rogue" finds "Assassin's Creed Rogue")
4. Result words ⊆ search words → up to **100** (penalised — missing terms; "Assassin's Creed" should NOT beat "Assassin's Creed Rogue" when searching the latter)
5. Partial overlap → up to **120** (Jaccard-weighted by search coverage)
6. + word-order LCS bonus → **0-40**

A different sequel number caps a non-exact match at **40** (PASS-59-208): `Doom` and `Doom II`, `FIFA 98` and `FIFA 99`. A `1` does not count. A number only one title has is forgiven when the words after it are all in the other title, because sources drop it from a subtitle (`Golden Sun 2 - The Lost Age`, `Golden Sun: The Lost Age`). ES-DE's search has its own scoring and leaves such a game out with `sequel_numbers_agree`.

Per-source extras layer on top via `calculate_<src>_score`:

- **+150 if `platform_match=True`** — the result's platform matched the system we searched on. This is the dominant signal; without it, even a perfect title from the wrong platform sits below a fuzzy match on the right platform.
- **+10 if `release_date` present** — completeness signal, the same for every source.
- **+10-20 for region** — `match_scorer.region_bonus`: +20 for the user's `default_region` or World, +10 for the next region in `version_groups.preferred_regions()` (by default Europe for a USA user). TGDB names and ScreenScraper codes (`us`, `eu`, `uk`, `jp`, `wor`) map to the setting names first. IGDB has no region signal in search.

No source earns more for being richer (PASS-59-208), so equal titles on one platform are decided by the user's order.

After per-source scoring, `ScraperManager.search_games` adds a **priority boost** based on the user's `priority` list: `boost = (len(priority) - idx) * 10` — first source +50, second +40, third +30, etc. for a five-source priority list. Meaningful enough to break ties, not large enough to override a clear title/platform mismatch.

Selection thresholds:

- `match_scorer.MIN_TITLE_SCORE` (80) — the title score a match must reach on its own. `_pick_best_fallback` uses it for fresh fallback searches, and never picks a result whose `platform_match` is false.
- `_pick_best_secondary(candidates, target_title, min_title_score=100)` — used when the user pre-selected secondaries in the search modal; threshold 100 because the user already endorsed *some* result from this source, so we expect a closer match.
- `scraper_manager.MIN_MATCH_SCORE = 200` — the bulk-scrape auto-selection floor (the "score" mode in match settings). Below this, the bulk scraper does not auto-accept the top match. The result must also reach `MIN_TITLE_SCORE`, because platform and bonus points alone can reach 200.
- IGDB's search leaves out DLC, expansions, bundles, mods, episodes, seasons, forks, packs and updates (`game_type`) unless the title is exact, so a ROM that is itself a hack still finds its record.

---

### HowLongToBeat

`scraper/hltb_lookup.py` scores on its own 0-to-1 scale (`title_score`): characters compared on the scorer's cleaned title, with a different sequel number capped below every bar. Titles differing only in spacing never count as different numbers. Equal scores go to the result nearest the game's year.

The bulk job applies a match only at or above its threshold, on the game's own platform (`on_platform`: whole names from the site's list), and no more than a year later than the game. A port comes after its original, so an earlier release passes. Everything else waits on `/hltb/review`, with the time unsaved.

The site sends no developer in a search reply. Requests are at least a second apart.

Saved matches are checked only when a person presses Check Saved Play Times in ROM Tools (`stored_match_problem`). No game changes until a person decides: Approve keeps the time and sets `games.hltb_match_reviewed`, so the check does not ask again; Reject clears it.

`games.playtime_estimate` is text. Anything adding it up uses `services/playtime.py`.

A saved match keeps HowLongToBeat's game ID (`games.hltb_id`), which links to its page, and `comp_all_count` (`games.hltb_players`), shown as how many players timed it. A match saved before PASS-59-216 has neither until it is looked up again.

## 7. Title normalization

Two distinct passes, both lossless and idempotent:

- **`scraper/title_normalizer.py`** — the *match-time* normalizer. Strips noise (`strip_title_noise`) and produces a word-set comparison string (`normalize_for_matching`). Never touches the title we save to the DB; lives in the scoring path only.
- **`scraper/metadata_normalizer.py::normalize_title(title)`** — the *save-time* normalizer. Converts "Call of Duty - World at War" → "Call of Duty: World at War" when the dash looks like a subtitle separator, collapses ` : ` / ` ,` spacing, applies the user's article-placement setting (`The Witcher` ↔ `Witcher, The`). Runs once per source merger before the value lands in `metadata['title']`.

**Search-time spelling is per source** (probed live, PASS-59-147). TGDB, RAWG and ES-DE get the title as written; IGDB strips quotes and query-syntax characters itself (`scrape_igdb.search_games`). ScreenScraper finds nothing for a subtitle unless its colon has a space before it, so `scrape_screenscraper.search_queries` sends `A : B` (a spaced dash counts as a colon), then `A` alone if that finds nothing. Every other character is left as written: dropping an apostrophe, hyphen, `&`, `*` or accent made ScreenScraper find nothing. `tests/test_pass59_147_ss_title_spelling.py` pins these.

Integration with scoring: `calculate_title_match_score` always runs `strip_title_noise`, then `normalize_article_for_comparison`, then `normalize_for_matching` on both inputs before comparing — callers never need to pre-normalise. Roman-numeral normalisation in `normalize_for_matching` uses `base_scraper.normalize_roman_numerals` (II-XX → 2-20; deliberately excludes solo "I" and "X" because they're common as a pronoun and as a brand suffix respectively).

---

## 8. Per-field normalization

Multi-value text columns are comma-separated; the canonical forms are pinned by `scraper/scrape_ai.py::FIELD_SCHEMAS` and `services/game_utils.py` (CLAUDE.md "Schema / data shapes"):

A word in these columns ends as a `FIELD_SCHEMAS` value or one added to the field's dropdown; any other word is dropped (PASS-59-206). `metadata_merger.fill_labels` converts each source's text, so a source whose words are all dropped leaves the field open for the next. Words belonging in another field (`FPV`, `3D`, `Sandbox`) fill it only when empty. `canonicalize_metadata` runs once more after the merge, for values already stored and to make `players` and `modes` agree. A `normalization_rules` row whose target is not such a value is ignored. The Tidy Genres, Perspectives and Modes card applies the same conversion to stored rows.

- **`genre`** — hyphenated, mapped to a fixed allowlist (`First-Person-Shooter`, `Shoot-em-up`, `Beat-em-up`, `Hack-n-Slash`, `Board-Card`, etc.). `services/normalization.py::normalize_genre` runs at every entry point that writes genre.
- **`dimension`** — `2D`, `2.5D`, `3D`, `AR (Augmented Reality)`, `FMV (Full Motion Video)`, `Pseudo-3D`, `VR`.
- **`perspective`** — `First-Person`, `Isometric`, `Side-Scroller`, `Third-Person`, `Top-Down`, `Vertical-Scroller`.
- **`modes`** — `Single-Player`, `Local Co-op`, `Online Multiplayer`, `Split-Screen`, `Versus`, etc. `services/normalization.py::normalize_modes` collapses scraper variants to this set.
- **`game_structure`** — `Open-World`, `Linear`, `Metroidvania`, `Roguelike`, `Sandbox`, etc.
- **`save_type`** — `Battery-Backed RAM`, `Memory Card`, `Cloud Save`, `Password`, `None`, etc. `hybrid_scraper.detect_save_type` provides a system-folder-based fallback when no source supplied a value.

Single-value:

- **`region`** — single-value dropdown driven by `region_options` in settings (default `['USA', 'Europe', 'Japan', 'World']`). `_normalize_region` reduces multi-value scraped values to one (pick the first that matches a configured option, else the user's `default_region`).
- **`players`** — INTEGER. Scraper ranges like `"1-4"` are normalised to the max via `re.findall(r'\d+', ...)` + `max(int(n) for n in nums)` immediately before save. The `services/game_utils.py::normalize_players_value` helper does the same coercion in the route layer so JSON-edit and form-POST paths can't smuggle a string into an INTEGER column (Pass 40.6).

Ratings: see §4 for the 8-system precedence; `services/game_metadata_service.cross_map_ratings` fills empty ratings by mapping from any present rating via the maturity-tier table in `services/game_utils.py`. `normalize_esrb_rating` collapses legacy values (`KA` → `E`, `E10` → `E10+`) before cross-mapping fires.

Sort title: `services/game_utils.py::generate_sort_title` runs in the post-merge pass — strips leading articles, lowercases, collapses whitespace.

---

## 9. Image pipeline integration

The scraper subsystem ends at the file on disk and the filename written to the DB column. Everything downstream — responsive variants (`-sm`, `-md`, `-lg`), WebP re-encoding, dHash-based dedup recompute, ESRGAN upscale — is owned by `services/image_utils.py`. See [`image-pipeline.md`](image-pipeline.md) for the full chain.

Hand-off points:

- **Download** — `base_scraper.download_image` and `metadata_merger._download_and_finalize` both call `services.image_utils.finalize_downloaded_image(dest_path, parent_dir)` immediately after `os.replace`. This re-encodes to match the destination extension (so `dest_path=*.webp` becomes actual WebP bytes), standardises size, and generates responsive variants. If `finalize_downloaded_image` raises, the downloader deletes the on-disk file and returns `False` so the caller does NOT set `metadata[field]` to a broken filename.
- **Screenshot dedup** — `scraper/image_dedup.py::compute_dhash` returns a 64-bit difference hash; `get_existing_screenshot_hashes` reads existing files; `keep_screenshot_if_unique(new_path, filename, existing_hashes, source)` gates whether the new screenshot is appended (threshold = Hamming distance 10). `Image.DecompressionBombError` is caught alongside `OSError`/`ValueError` (Pass 41.14.A / 45.6) so one bomb image doesn't abort the dedup loop for the whole game.
- **Bomb protection** — `services/image_utils` sets `Image.MAX_IMAGE_PIXELS` globally (Pass 45.6); PIL raises `DecompressionBombError` rather than allocating a gigabyte of RAM for a maliciously-crafted dimensions header.

---

## 10. HTTP base contract

`scraper/base_scraper.py` is the only sanctioned HTTP layer for the `scraper/` package. Every adapter (TGDB, IGDB, RAWG, ScreenScraper, AI, RA, Steam, Xbox) goes through it (Pass 41.5 / 41.5.B closed most carry-overs; Xbox followed in Pass 59.26). The key and status probes in `routes/scraper.py` (`api_check_scraper`, `api_scraper_allowance`) call `requests` directly and are outside this contract: a probe must not wait out a 429 backoff.

`scraper/service_limits.py` (PASS-59-215) sets the gap between calls to each service and holds each service's stop. A stopped service's sender returns its usual nothing without calling, and a caller that must tell "no answer" from "no such game" asks `stopped()`. A stop lives in memory: a restart forgets it, and saving API keys clears it.

| Service | Gap between calls | Stops when | For |
|---|---|---|---|
| ScreenScraper | The reply's `maxrequestspermin`; doubled on a 429. One call at a time, for `maxthreads` | A 430 or 431, a reply in words naming a quota, or a reply at its daily limit | One hour: the service does not say when its day ends |
| TheGamesDB | None; the limit is monthly | A reply shows a key spent, or a 403 or 429: that key is passed over. All keys passed over stops the service | The reply's refresh timer, or one day |
| RAWG | 0.3 s | A 401, 403 or 429 naming a limit, or `X-RateLimit-Remaining` at zero | One day |
| IGDB | 0.26 s: its limit is 4 a second | Never; a 429 raises, as other errors do | - |
| HowLongToBeat | 1 s, token requests included | A 429 after `http_post`'s retries | 15 minutes |
| Steam store | 1.5 s: its limit is undocumented, about 200 calls in five minutes as usually reported | A 403 or 429 | Five minutes; the sync carries on, and the next one asks about games it missed |

A bulk scrape carries on with its other sources and leaves a game found nowhere unstamped, so a later run asks again. HowLongToBeat's and Fix Box and Manual Regions' jobs end. Each status reply has `service_stops`, sentences from `services/service_stop_text.py`. Media downloads are not paced or stopped.

The Settings allowance check calls TheGamesDB's `/v1/API/Limit`, which its documentation says does not count. The key test still calls `/v1/Platforms`: how `/v1/API/Limit` answers a bad key has not been seen.

`http_get(url, params=None, headers=None, timeout=30, retries=2, max_bytes=None)` and `http_post(url, data=None, json_data=None, headers=None, timeout=30, retries=2, max_bytes=None)`:

- Shared `requests.Session` for connection pooling.
- Exponential backoff with jitter on transient failures: `(2 ** attempt) + random.random()` seconds, max 2 retries (Pass 26.4). 429 respects `Retry-After` header (capped at 60 s). 500/502/503/504 retried; other 4xx returned to caller.
- `max_bytes` cap on response body (Pass 32.14) — checks `Content-Length` first, then `len(response.content)`. Applied on AI + RA paths where the body is otherwise unbounded.

`download_image(url, dest_path, timeout=15)` is the only sanctioned image downloader (with `metadata_merger._download_and_finalize` as its functional twin used inside per-source mergers — same hardening, same contract):

- **SSRF gate** (Pass 32.6) — `services.ssrf.validate_outbound_url` rejects non-http(s) schemes and any host that resolves to private/loopback/link-local/metadata IPs (`169.254.169.254`, `127.0.0.1`, `10/8`, …). An attacker-controlled upstream metadata record (TGDB, RAWG, etc.) cannot otherwise steer the scraper into the cloud-metadata endpoint.
- **Redirect-chain validation + DNS pin** (Pass 32.7, Pass 45.2) — `validate_and_pin_url` walks every redirect hop manually through the SSRF gate AND captures the resolved IP. The subsequent `requests.get(safe_url, ...)` runs inside `pin_host_ip(host, ip)`, which forces every `getaddrinfo` for that hostname in the calling thread to return the captured IP for the duration of the GET — defeating DNS rebinding between validate and fetch.
- **Streaming with size cap** (Pass 25.7) — `MAX_MEDIA_DOWNLOAD_BYTES` (default 50 MB). `Content-Length` rejected pre-stream; running total checked per 8 KB chunk and aborted on overflow.
- **Atomic write** (Pass 40.15) — `tempfile.mkstemp` in the same directory, `f.flush() + os.fsync()`, then `os.replace(tmp, dest)`. The previous version streamed directly to `dest_path`; any mid-stream exception (connection reset, OOM, SIGKILL) left a partial file at `dest_path`, and the `if os.path.exists(dest_path)` short-circuit then treated the corrupt bytes as "already downloaded" forever. Tempfile is cleaned up in `finally:` on every exit path.
- **No SSRF bypass survived Pass 40.7** — `_download_tgdb_image` used to call `http_get` + raw `open(local).write(r.content)` with no SSRF / no streaming / no cap. It now delegates to `base_scraper.download_image`; the wrapper only contains TGDB-specific URL absolutisation and filename construction.

---

## 11. Caching

Two layers, both bounded:

- **`scraper/scraper_cache.py`** — ScreenScraper search-result cache. Keyed `f"{game_id}:{system_id}"`, TTL 10 minutes, hard cap 500 entries (evicts expired entries first, then oldest by timestamp). Thread-safe (`_cache_lock`). Saves a request between the user picking a result and `apply_screenscraper_to_metadata` running. On a miss, `hybrid_scraper._ss_record_by_id` asks for that game with `scrape_screenscraper.get_game_by_id` (`jeuInfos` with `gameid`), so a pick is never swapped for another game.
- **`scraper_manager._settings_cache`** — 30 s cache on `data/scraper_settings.json`. `load_scraper_settings` returns the cached dict if `(now - cache_time) < 30`. Avoids re-parsing settings JSON on every per-game scrape inside a bulk run.

Circuit breakers (`circuitbreaker` package, see `scraper_manager`): 5 consecutive failures opens the breaker for 120 s. Active on TGDB, IGDB, RAWG, ScreenScraper, AI. When `circuitbreaker` is not installed, `_<src>_breaker` is a no-op decorator (`_noop_breaker`).

---

## 12. AI Fill specifics

`scraper/scrape_ai.py` is a multi-provider AI scraper (Google Gemini, OpenAI, Anthropic Claude). Public surface:

```python
get_game_details(game_id, title, system_name, system_folder, existing_metadata) -> dict | None
check_api_status() -> dict
```

Text-only. AI never returns images, screenshots, videos, or manuals — `AI_FILLABLE_FIELDS` is the explicit allowlist.

**`FIELD_SCHEMAS`** pins canonical values for every dropdown-style field (`genre`, `game_structure`, `perspective`, `dimension`, `modes`, `save_type`, `other_platforms`, the 8 rating systems). The AI prompt presents these allowlists to the model; the response validator enforces them post-call (drops or maps unknown values). The full schema and prompt construction live in `scraper/scrape_ai.py` — do not duplicate the strings here, they drift.

**`PLATFORM_ALIASES`** maps non-canonical platform names the AI may produce (`ps1` → `PlayStation`, `playstation portable` → `PSP`).

**Integer-column trap (Pass 45.3):** AI Fill writes through `services/ai_fill.py`. The integer columns (`players`, `critic_score`, `critic_score_count`, `user_score`, `user_score_count`, `units_sold`) coerce via `int(float(value))`. If the AI returns `"0"`, that becomes `0` — and a bare `field = ?` UPDATE then clobbers a curated `players=4` with `0`. Fix: any integer coerce to `0` is **skipped** entirely from the UPDATE clause (chosen over `COALESCE(NULLIF(?, 0), col)` because the existing `should_apply` filter already guarantees we only reach the int-coerce on values worth writing). Regression tests in `tests/test_pass45_security.py::TestPass45_3*`.

**Sales (`units_sold`):** only the AI fills it, in the scrape's AI gap-fill and in AI Fill; no API scraper publishes sales. The prompt asks for lifetime copies sold on the row's platform from free published sources and for null when only a multi-platform total exists. `parse_units_sold()` turns what a model writes (`"2.4 million"`, `"~850k"`, `"2,400,000"`) into an integer and drops anything above 500 million.

**Release dates by region (`release_dates`):** IGDB and ScreenScraper fill it from their per-region dates, and the AI fills it when no source has, in the scrape's AI gap-fill and in AI Fill. A stored region keeps its date; a source only adds regions it lacks (`release_dates.merge_release_dates`). The prompt asks for an object keyed by region code (`NA`, `EU`, `JP`, `AU`, `KR`, `CN`, `TW`, `BR`, `AS`, `WW`) with `YYYY-MM-DD`, `YYYY-MM` or `YYYY` dates. `services/release_dates.parse_release_dates()` also takes region names (`"Japan"`, `"PAL"`) and a list of `{region, date}`, drops unknown regions and impossible dates, and the column stores compact JSON in region order. `release_date` stays the date of the row's own release.

**How exact a date is (PASS-59-207).** `release_date` holds `YYYY-MM-DD`, `YYYY-MM` or `YYYY`, as much as the source knows.

- **IGDB**: `release_dates` entries for this console, read with their `date_format`. `first_release_date` is never stored: it is the earliest for any console or region, and a year-only one reads as 31 December. A record with no entry for this console gives no date. The Famicom and Super Famicom count as the NES and SNES, because IGDB files Japanese releases under them.
- **Which region**: `release_dates.pick_release_date`: this copy's region, a worldwide release, the user's preferred regions, then the earliest.
- **Padded dates**: `release_dates.source_date` turns `YYYY-01-01` into `YYYY` for every source but IGDB, and for ES-DE the first of any month into `YYYY-MM`. 1 January 1970 is dropped.
- **RAWG**: this console's `released_at`, else the record's `released`.
- **Filling out**: a date for this copy's own region replaces a stored year or month it agrees with, such as `1987-06-14` over `1987`. This comes only from IGDB and ScreenScraper, and is the one way a scrape changes a filled date outside Full Re-scrape. RAWG, TheGamesDB and ES-DE never do it, as they cannot say the day belongs to this region.
- **Disagreements**: a date over a year from the regional date of the copy's region is logged and left, as neither is proof.
- **Older rows**: ROM Tools > Tidy Release Dates (`game_cleanup.fix_release_dates`) cuts stored dates back by the source `scrape_history` credits. A date no scrape credits stays, except 1 January 1970.

**Franchise (PASS-59-212).** Only a source that names a series fills it: IGDB (`franchise`, `franchises`, then `collections`), ScreenScraper (`familles`, a repeated name kept once) and the AI. TheGamesDB and RAWG name none, and nothing derives one from a title.

**Full Re-scrape keeps what no source gave (PASS-59-214).** Before the derived steps run, `region`, `save_type`, `controller_support` and every rating no source filled are seeded from the row, so cross-mapping, inference and the folder guess have nothing to write over. A curated system controller still wins. If the merged scrape fails unexpectedly, the scrape reports failure and writes nothing; no single-source route takes over.

**Clean text (PASS-59-213).** `canonicalize_metadata` cleans what is about to be saved, from any source.

- **Descriptions**: `normalization.clean_description` removes web codes, Windows line endings, heading and bullet marks, and footnote marks. ScreenScraper's is taken only in a wanted language, so a French-only one leaves the field for the next source. IGDB's `summary` comes before `storyline`.
- **Companies**: `normalization.COMPANY_ALIASES` holds plainly one company under several spellings. Separate companies stay separate.
- **Alternate titles**: IGDB's executable names are skipped; RAWG's are used only from a one-console record.
- **Region**: `_normalize_region` keeps one value from `USA/Europe` and turns `North America` into `USA`. A single value outside the options stays, as `France` is true and the default would not be.

**AI answers are checked and marked** (PASS-59-211).

- A score needs a stated scale or a value above 10: `8.5/10` becomes 85, a bare `7` is refused, and so is anything above 100. A sales range, a sum of money or a figure under 1,000 is refused. A list answer is joined, a placeholder such as `N/A` is dropped, and a game's own system is removed from `other_platforms`.
- A score count is written only with an AI score from the same answer. `services/field_sources.py::ai_marks` also hides a stored AI count beside another source's score.
- A scrape gap-fill asks only about empty fields. With no search tool, the prompt says so and asks for remembered published figures only.
- AI Fill keeps a value it replaces under `replaced` in its history entry.
- The per-system save type guess is gone for cartridge systems, and AI Fill no longer writes `Standard Edition` by default.

**AI age ratings** (user, 2026-11-02). They stay, new and stored. The game page marks each `AI guess`, and says it is based on the game's content and when each board started. A rating credited `AI` or `ratings (inferred from content)` is marked; a scraper's value, a person's edit or a cross-mapping is not. Only the game page carries marks; the library cards do not.

Start years in `RATING_SYSTEMS`, checked 2026-11-02:

| Board | Year | Source and strength |
|---|---|---|
| ESRB | 1994 | esrb.org |
| PEGI | 2003 | secondary sources agree |
| CERO | 2002 | secondary source |
| USK | 1994 | secondary sources agree |
| ACB | 1994 | when game classification began; secondary sources agree |
| FPB | 1998 | when the board began work, including games; one source |
| GRAC | 2006 | founded as the Game Rating Board; secondary sources agree |
| ClassInd | 2001 | when games began; one weak source |
| CADPA | 2020 | standard released December 2020, in force July 2021 |

**Official title** (user, 2026-10-27). For a game with a ROM and an unlocked title, `get_game_details` also asks for `official_title` (the title as released in the ROM's region) and `old_title_region`. Both are outside `AI_FILLABLE_FIELDS`; `_validate_all_fields` keeps them after `_clean_official_title`. `metadata_merger.apply_ai_to_metadata` (manual and bulk scrape) and `services/ai_fill.py` (the AI Fill button and Bulk AI Fill) rename the game to it, keeping the replaced name as an alternate title tagged with `old_title_region`. It is an exception to fill-only for `title`, as the user asked. A locked title is never asked about, and `_save_game_row` never writes one. Pinned by `tests/test_ai_official_title.py`.

**Circuit breaker:** `_ai_breaker` (5 failures / 120 s recovery) wraps `fetch_ai_metadata` calls from `hybrid_scraper` so a repeatedly-failing provider doesn't burn a quota on every gap-fill attempt.

---

## 13. Adding a new source

End-to-end checklist for a new remote source `foo`:

1. **Create `scraper/scrape_foo.py`** with:
   ```python
   def search_games(title, system_name=None, limit=10) -> list[dict]:
       # Returns list of {id, name, source: 'foo', scraper: 'foo',
       #                  release_date?, platform?, platform_match?, region?, ...}
       ...

   def fetch_game_details(game_id) -> dict | None:
       # Returns the canonical record fetched by ID.
       ...

   ```
   All HTTP calls go through `base_scraper.http_get` / `http_post`. All image downloads go through `base_scraper.download_image` or `metadata_merger._download_and_finalize`. No bare `requests.get` calls.

2. **Add an `apply_foo_to_metadata(metadata, foo_data, db_game_id, result, fill_only=False)`** in `scraper/metadata_merger.py`. Pattern: title is `if not metadata['title'] or not fill_only`; every other field is `if not metadata['field']`. Append `f'<field> (FOO)'` to `result['filled_fields']` on each fill. Use `normalize_title`, `normalize_genre`, `normalize_modes`, `normalize_esrb_rating` for canonical values. For images, call `_download_and_finalize` and only set `metadata[field] = filename` on `True`. For screenshots, use `keep_screenshot_if_unique` against `get_existing_screenshot_hashes`.

3. **Wire into `hybrid_scraper.apply_hybrid_metadata`**:
   - Add an `elif primary_source == 'foo':` branch wrapped in `try / except` (Pass 41.4.B pattern; log + fall through to gap-fill on exception).
   - Add an `elif fallback_source == 'foo':` branch in the gap-fill loop with `if secondary_sources` shortcut + fresh-search path (use `_pick_best_secondary` / `_pick_best_fallback`).

4. **Wire into `scraper_manager.ScraperManager.search_games`**:
   - Import `search_games` as `search_foo`.
   - Add a `FOO_AVAILABLE` try/except import flag.
   - Add a search block (mirror the TGDB block) that calls `_foo_breaker(search_foo)` and sets `result['source'] = 'foo'`, `result['score'] = calculate_foo_score(result, title)`.
   - Add `'foo'` to `source_map` for the priority boost.
   - Add a `calculate_foo_score` in `scraper/match_scorer.py` mirroring the existing per-source scorers (title score + platform-match +150 + region bonus).

5. **Settings**:
   - Add `'foo'` to the default `priority` list and `enabled` dict in `scraper_manager.load_scraper_settings`.
   - Add the API key under `api_keys` in `data/scraper_settings.json` and route it via `get_api_key('foo_apikey', 'FOO_API_KEY_CONFIG_NAME')`.
   - Add a `SCRAPER_FOO_ENABLED` default in `config.py` + `config.example.py`.

6. **Tests** (required for landing):
   - `tests/test_scrape_fill_only.py` — add `apply_foo_to_metadata` to the media tests, so stored media stays and empty media fills.
   - `tests/test_hybrid_scraper.py` — pin per-source scoring extras against `scraper/match_scorer.py`.
   - `tests/test_pass40_9_16_security.py` (the Pass 40 SSRF tests) — if `foo` downloads images, add SSRF + redirect-chain tests asserting it goes through `base_scraper.download_image`.

7. **Docs** — extend §2 source inventory; add `foo` to the §4 default priority order if it ships enabled; update CLAUDE.md "Scraper fill-only invariant" only if `foo` introduces a new exception (it shouldn't).

---

## 14. Known invariants

- Every `?` in a scraper UPDATE is wrapped in `COALESCE(?, column)` (Pass 30.4 / 40.6 / 45.3).
- Fill-only across every source; the only documented exception is `force_overwrite=True` in `hybrid_scraper` (Full Re-scrape).
- Screenshots are always *appended*, never replaced. Dedup via dHash with Hamming threshold 10.
- ScreenScraper, TheGamesDB, IGDB and RAWG downloads pass the game id as `screenshot_of`; `services/screenshot_fit.py` refuses a Game Boy original with too many colours (PASS-59-161). It decides by exact colour count, only on an unscaled lossless original, and before finalizing. ZX Spectrum and C64 are not refused: real originals overlap other systems' shots. ES-DE copies and manual uploads are not checked.
- Media fields (`boxart`, `boxart_3d`, `boxart_back`, `fanart`, `game_logo`, `video`, `manual`) are filled only when empty; clear them via the edit modal to force a re-fetch.
- Stale media references (file deleted, filename still in DB) are detected pre-merge and conditionally NULLed under `WHERE id = ? AND <field> = ?` (Pass 40.15).
- Every image download MUST go through `base_scraper.download_image` or `metadata_merger._download_and_finalize` — both gate on SSRF, walk the redirect chain, pin the resolved IP, stream with `MAX_MEDIA_DOWNLOAD_BYTES` cap (50 MB default), and write atomically (Pass 25.7, 32.6, 32.7, 40.7, 40.15, 45.2).
- Every API call from a `scraper/` module goes through `base_scraper.http_get` / `http_post` — backoff with jitter on 429/5xx, optional `max_bytes` cap (Pass 26.4, 32.14). Route-level key and status probes in `routes/scraper.py` are exempt (§10).
- `players` is INTEGER; ranges like `"1-4"` are normalised to the max (4) via `re.findall + max` before save. `normalize_players_value` is the canonical helper for route-layer writes (Pass 40.6).
- `genre` values are hyphenated and constrained to `FIELD_SCHEMAS` in `scrape_ai.py`. New genres added to either list must be added to both.
- Curated DB-default controllers always override scraped/AI controller values (`get_system_default_controller_name`).
- Per-source primary fetches are wrapped in `try / except`; on failure the orchestrator logs and falls through to gap-fill (Pass 41.4.B). The final UPDATE is **not** wrapped — drift between the metadata dict and the binding tuple must fail loudly.
- ScreenScraper search results are cached for 10 min. Settings JSON is cached for 30 s. Per-source circuit breakers open after 5 failures, recover after 120 s.
- AI Fill is text-only; never writes media. Integer-column writes skip the UPDATE clause when the coerced value is `0` (Pass 45.3).
- Sort title is auto-generated from title via `services/game_utils.py::generate_sort_title` during scrape and AI Fill.
- Rating cross-mapping fills empty rating systems from any present rating via the maturity-tier table in `services/game_utils.py`; content inference is the final fallback when no rating system is filled at all.
