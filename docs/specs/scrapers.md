# Scrapers

> **TL;DR** — Ten sources fan into one orchestrator (`hybrid_scraper`), one per-source merger (`metadata_merger`), one scorer (`match_scorer`) and one HTTP base layer (`base_scraper`). Every write is fill-only via `COALESCE(?, column)` so an empty upstream response can never wipe a curated value (Pass 30.4 / 40.6 / 45.3 are all instances of this rule being broken; the contract pins them shut). Image fetches MUST go through `base_scraper.download_image` or `metadata_merger._download_and_finalize` — both gate on SSRF, pin the resolved IP across the redirect chain, stream with a size cap, and write atomically.

---

## 1. Purpose

RetroDB ingests game metadata from a mix of remote APIs (IGDB, TGDB, RAWG, ScreenScraper, Steam, Xbox, RetroAchievements, HLTB), a local file source (ES-DE `gamelist.xml` + `downloaded_media/`), and a generative AI fallback. The scraper subsystem unifies these into a single `games` row: it walks one user-selected primary source, falls back to user-prioritised secondaries to fill any remaining gaps, and writes the result without ever overwriting a non-empty field unless the user has opted into Full Re-scrape mode.

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
| RAWG.io           | `scraper/scrape_rawg.py`          | remote          | `rawg` (settings key; falls back to `RAWG_API_KEY` in `config.py`)        | Metacritic critic score, user score, ESRB; platform-specific boxart                               |
| ScreenScraper     | `scraper/scrape_screenscraper.py` | remote          | `screenscraper_username` + `_password` + `_devid` + `_devpassword`        | Retro-specific metadata, regional alt titles, system-specific media (boxart 3D, video, manual)    |
| Steam             | `scraper/scrape_steam.py`         | remote          | No (public store API)                                                     | PC port metadata; HLTB-adjacent enrichment                                                        |
| Xbox              | `scraper/scrape_xbox.py`          | remote          | No (public store API)                                                     | Xbox port metadata; achievement-adjacent enrichment                                               |
| RetroAchievements | `scraper/retroachievements.py`    | remote          | `ra_apikey`                                                               | `has_retroachievements`, `ra_game_id`, `ra_achievement_count`, `ra_points` (tail of hybrid apply) |
| AI Fill           | `scraper/scrape_ai.py`            | AI              | One of: `ai_gemini_api_key`, `ai_openai_api_key`, `ai_anthropic_api_key` (+ optional `ai_gemini_project_id`) | Final gap-fill for text-only fields; never media (see §12)                                        |
| HLTB              | `scraper/hltb_lookup.py`          | remote          | No (public site scrape)                                                   | Playtime estimates (main / extra / completionist) for HowLongToBeat                               |

Per-source disable + priority: `data/scraper_settings.json` → `enabled` + `priority`. The first enabled source in priority order whose API key is configured wins as primary when the user picks one; the rest fall back in priority order (see §3).

---

## 3. Hybrid orchestration

Entry point: `scraper.hybrid_scraper.apply_hybrid_metadata(db_game_id, primary_source, primary_id, system_folder, secondary_sources=None, fill_gaps=True, force_overwrite=False, primary_data=None, restrict_to_selected=False)`.

Two modes:

- **Normal (default; `force_overwrite=False`)** — pre-populate `metadata` from the existing `games` row so every per-source merger sees the current state and only writes into still-empty fields. Stale media references (file deleted but DB still names it) are detected via `os.path.exists` and conditionally NULLed under a `WHERE id = ? AND <field> = ?` guard so a concurrent upload between stat and clear isn't wiped (Pass 40.15).
- **Full Re-scrape (`force_overwrite=True`)** — `metadata` starts empty; ES-DE captures old media filenames for *deferred* cleanup (only delete if a replacement was actually found); every source applies as if the row were new. This is the only documented exception to fill-only.

Walk order:

1. **Primary fetch** — `_pick_best_secondary` if the user picked from search results, else freshly fetched via the source-specific `fetch_*_extended` / `fetch_*_game_details`. Each primary dispatch is wrapped in `try / except` (Pass 41.4.B) so a malformed response from one provider falls through to gap-fill rather than aborting the whole hybrid apply.
2. **Apply primary** — call the matching `apply_<src>_to_metadata(metadata, data, db_game_id, result, fill_only=False)` from `metadata_merger.py`. `fill_only=False` lets the primary overwrite `title` only (other fields stay fill-only across both modes).
3. **Gap fill** — compute `missing = [k for k, v in metadata.items() if not v]`. Walk user priority (skipping primary, disabled sources, and sources already applied). When `restrict_to_selected=True` and the caller passed `secondary_sources`, fallback is further restricted to that allowlist (plus AI). Each fallback for **TGDB, IGDB, RAWG, ScreenScraper, and AI** runs under the per-source circuit breaker (`_<src>_breaker` in `scraper_manager`) — five consecutive failures opens the breaker for 120 s. ES-DE, Steam, Xbox, RetroAchievements, and HLTB do not have breakers (see §11).
4. **Post-merge passes** — region inference from filename (`extract_region_from_filename`), region single-value reduction (`_normalize_region`), save-type detection (`detect_save_type`), controller support detection (`detect_controller_support`), curated DB-default controller override (`get_system_default_controller_name`), rating normalize + cross-map + content-inference (`_normalize_ratings`), `players` integer-coercion via `re.findall(r'\d+', ...)` + `max(...)`, sort-title regeneration.
5. **Single fill-only UPDATE** — one statement with `COALESCE(?, col)` on every column (see §5 for the exact SQL).
6. **RA tail** — `_apply_retroachievements_check` opens its own connection, looks up the game by title + system folder, and updates `has_retroachievements` / `ra_*` columns on hit. Exceptions are swallowed so a down RA service can't poison the rest of the scrape.

The single UPDATE is **not** wrapped in a try/except fallback: a failure means `metadata` and the binding tuple have diverged (someone added a field but not the column), and the scraper must fail loudly. Per-source primary fetches and the RA check have their own narrow try/except blocks; the UPDATE itself does not.

---

## 4. Merge priority

Defined in `hybrid_scraper.FIELD_SOURCES`. Reading order = preference order. Within a single hybrid run the *primary* source applies first (regardless of where it sits in FIELD_SOURCES); secondaries then walk in user-priority order, filling only what the primary left empty. The table below shows the most relevant fields; the canonical mapping is the `FIELD_SOURCES` dict in `scraper/hybrid_scraper.py` (grep for the name). A few metadata-dict keys (`dimension`, `perspective`, `game_structure`, `edition`, `campaign`, `other_platforms`, `alternate_titles`, `sort_title`) are filled by per-source mergers in `metadata_merger.py` directly and don't carry their own FIELD_SOURCES row. `save_type` is a special case — it has a sentinel `FIELD_SOURCES['save_type'] = ['manual']` entry that prevents normal-source filling and defers to the `detect_save_type` post-merge pass instead.

| Field                                                                                          | Preference order                                |
|------------------------------------------------------------------------------------------------|--------------------------------------------------|
| title / publisher / developer / release_date / genre / description / players / modes           | esde → tgdb → igdb                              |
| esrb_rating                                                                                    | igdb → tgdb → rawg → screenscraper              |
| pegi_rating                                                                                    | igdb → tgdb → screenscraper                     |
| cero_rating / usk_rating / acb_rating                                                          | igdb → screenscraper                            |
| fpb_rating                                                                                     | screenscraper                                   |
| grac_rating / classind_rating                                                                  | igdb                                            |
| boxart                                                                                         | esde → screenscraper → rawg → tgdb → igdb       |
| boxart_3d                                                                                      | esde → screenscraper                            |
| screenshots / fanart                                                                           | esde → screenscraper → tgdb → igdb              |
| video / manual                                                                                 | esde → screenscraper                            |
| region                                                                                         | esde → screenscraper → filename                 |
| franchise                                                                                      | igdb → tgdb                                     |
| similar_games / playtime_estimate / controller_support                                         | igdb                                            |
| critic_score / critic_score_count                                                              | rawg → igdb → ai                                |
| user_score / user_score_count                                                                  | rawg → igdb → screenscraper → ai                |

Tie-breakers:

- **Boxart**: ScreenScraper + RAWG ship system-specific covers (Saturn JP boxart for a Saturn ROM), IGDB ships the generic / global cover — that's why IGDB is last. ES-DE wins outright because the user already curated it.
- **Screenshots**: never replaced, always *appended*, then deduped via `image_dedup.compute_dhash` with Hamming-distance threshold 10. Each per-source merger reads existing filenames + their hashes once, then calls `keep_screenshot_if_unique` on each new download. Visual dupes (re-encodes / resizes) are dropped before they reach the UPDATE.
- **Empty values never win**: the fill-only invariant (§5) means a later high-priority source filling an empty field always wins, but an empty response from a high-priority source never wipes what came from a lower-priority source.
- **Curated DB defaults always win for controllers**: `get_system_default_controller_name` runs after gap-fill and overrides whatever was scraped/inferred.

---

## 5. Fill-only invariant

**The rule (scraper UPDATEs):** every `?` bound to a metadata-source value
in a scraper `UPDATE games` statement MUST be wrapped in
`COALESCE(?, column_name)` so an empty value from the upstream preserves
whatever's already in the column. Sources that own a direct `UPDATE games`:
`scrape_esde`, `scrape_igdb`, `scrape_thegamesdb`, and the hybrid
orchestrator's composite UPDATE in `hybrid_scraper`. `scrape_rawg` and
`scrape_screenscraper` do **not** own a direct `UPDATE games` — they write
through `scraper/metadata_merger.py::apply_*_to_metadata`, which feeds
into the hybrid UPDATE; the COALESCE protection therefore happens once,
in `hybrid_scraper`.

**Audit-column exception.** A handful of columns are bare by design,
because they're status / audit data — overwriting them is the point. As
of the current code base that means `scrape_history = ?` and
`scraped = 1` in the hybrid UPDATE, and `scraped = 1` in
`scrape_igdb.apply_metadata_to_game`. Leave those bare.

**AI Fill is a separate path.** `routes/games_ai.py` does **not** use the
COALESCE wrapper. It builds the `UPDATE games` with bare `field = ?`
clauses and protects the fill-only contract one layer up via a
`should_apply` pre-filter plus the Pass 45.3 "skip int=0" guard
(`int(float("0"))` and similar empty-int sentinels are filtered before
the clause is appended). Don't wrap the AI Fill UPDATEs in COALESCE —
that would block the cross-map / rating-inference paths that intentionally
overwrite (because the user opted into AI fill).

**The bug class scraper-COALESCE prevents:** bare `publisher = ?, developer = ?` in `apply_metadata_to_game` means that a TGDB or IGDB response that didn't return publisher/developer (very common — partial records) will silently NULL the column on every re-scrape. Pass 30.4 fixed the original instance for `publisher`/`developer`. Pass 40.6 closed the variant on `players` where the dict was initialised to `1` (so `COALESCE(1, players)` always returned 1 — the `COALESCE` was correct, the initialiser was wrong; fixed via `normalize_players_value` returning `int|None`). Pass 45.3 closed the same shape in AI Fill where bare `field = ?` writes after `int(float("0"))` were clobbering curated `players=4` with `0` — fixed by the `should_apply` skip-empty-int guard, not by adding COALESCE.

**Canonical site:** `scraper/scrape_esde.py::apply_esde_metadata`:

```sql
UPDATE games SET
    title       = COALESCE(?, title),
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
    video       = COALESCE(?, video),
    manual      = COALESCE(?, manual),
    region      = COALESCE(?, region),
    ...
WHERE id = ?
```

The hybrid orchestrator's UPDATE in `apply_hybrid_metadata` is the same pattern across ~40 columns (lines 1432-1520 in `hybrid_scraper.py`). The same pattern repeats in `scrape_igdb.apply_metadata_to_game` and `scrape_thegamesdb.apply_metadata_to_game`.

**Exception:** Full Re-scrape mode in `hybrid_scraper` (`force_overwrite=True`) intentionally bypasses fill-only — the user opted in. ES-DE in this mode still defers media deletion until a replacement is confirmed found.

**Test pin:** `tests/test_scrape_fill_only.py` exercises both IGDB and TGDB with an existing populated row + an empty API response and asserts every column survives. Re-asserts the failure-side contract too (DB error → `apply_metadata_to_game` returns `False`, not `True`, not a re-raise). ES-DE, the hybrid orchestrator UPDATE, and AI Fill are **not** currently covered by this test — extending coverage is a known roadmap item.

**When adding a new field** to the metadata dict in `hybrid_scraper.apply_hybrid_metadata`, add the corresponding column to the UPDATE binding tuple AND wrap the `?` in COALESCE in the same commit, and add a regression case to `tests/test_scrape_fill_only.py`. Drift between the metadata dict and the UPDATE tuple is precisely why the UPDATE has no try/except fallback — silent drift is the bug; loud failure is the contract.

---

## 6. Match scoring

`scraper/match_scorer.py::calculate_title_match_score(result_title, search_title) -> int` is the shared title scorer for every source. It runs both titles through `title_normalizer.strip_title_noise` (drops region tags, disc markers, edition tags, version tags) and `normalize_for_matching` (lowercases, strips possessive `'s`, drops apostrophe variants, replaces colons/dashes/slashes with spaces, normalises Roman numerals II/VII → 2/7) before comparing.

Score ladder (pure title similarity, 0-340 typical range):

1. Raw exact match before noise strip → **350**
2. Exact normalised match → **300** (+50 if raw exact)
3. Search words ⊆ result words → **150-280** (depends on extras; "Rogue" finds "Assassin's Creed Rogue")
4. Result words ⊆ search words → **30-100** (penalised — missing terms; "Assassin's Creed" should NOT beat "Assassin's Creed Rogue" when searching the latter)
5. Partial overlap → **20-120** (Jaccard-weighted by search coverage)
6. + word-order LCS bonus → **0-40**

Per-source extras layer on top via `calculate_<src>_score`:

- **+150 if `platform_match=True`** — the result's platform matched the system we searched on. This is the dominant signal; without it, even a perfect title from the wrong platform sits below a fuzzy match on the right platform.
- **+10-20 if `release_date` present** — recency / completeness signal.
- **+10-20 for region** — US/WORLD preferred (TGDB: `USA`/`WORLD` +20, `EUROPE`/`UK` +10; SS: `US`/`WOR` +20, `EU`/`UK` +10; IGDB has no region signal in search).
- **RAWG only**: +15 if Metacritic present, +10 if image present.

After per-source scoring, `ScraperManager.search_games` adds a **priority boost** based on the user's `priority` list: `boost = (len(priority) - idx) * 10` — first source +50, second +40, third +30, etc. for a five-source priority list. Meaningful enough to break ties, not large enough to override a clear title/platform mismatch.

Selection thresholds:

- `_pick_best_fallback(results, game_title, min_title_score=80)` — used for fresh fallback searches; rejects matches below 80 (avoids wrong-game pollution).
- `_pick_best_secondary(candidates, target_title, min_title_score=100)` — used when the user pre-selected secondaries in the search modal; threshold 100 because the user already endorsed *some* result from this source, so we expect a closer match.
- `scraper_manager.MIN_MATCH_SCORE = 200` — the bulk-scrape auto-selection floor (the "score" mode in match settings). Below this, the bulk scraper does not auto-accept the top match.

---

## 7. Title normalization

Two distinct passes, both lossless and idempotent:

- **`scraper/title_normalizer.py`** — the *match-time* normalizer. Strips noise (`strip_title_noise`) and produces a word-set comparison string (`normalize_for_matching`). Never touches the title we save to the DB; lives in the scoring path only.
- **`scraper/metadata_normalizer.py::normalize_title(title)`** — the *save-time* normalizer. Converts "Call of Duty - World at War" → "Call of Duty: World at War" when the dash looks like a subtitle separator, collapses ` : ` / ` ,` spacing, applies the user's article-placement setting (`The Witcher` ↔ `Witcher, The`). Runs once per source merger before the value lands in `metadata['title']`.

Integration with scoring: `calculate_title_match_score` always runs `strip_title_noise` then `normalize_for_matching` on both inputs before comparing — callers never need to pre-normalise. Roman-numeral normalisation in `normalize_for_matching` uses `base_scraper.normalize_roman_numerals` (II-XX → 2-20; deliberately excludes solo "I" and "X" because they're common as a pronoun and as a brand suffix respectively).

---

## 8. Per-field normalization

Multi-value text columns are comma-separated; the canonical forms are pinned by `scraper/scrape_ai.py::FIELD_SCHEMAS` and `services/game_utils.py` (CLAUDE.md "Schema / data shapes"):

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

`scraper/base_scraper.py` is the only sanctioned HTTP layer for the scraper subsystem. Every adapter (TGDB, IGDB, RAWG, ScreenScraper, AI, RA, Steam, Xbox) goes through it (Pass 41.5 / 41.5.B closed the carry-overs).

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

- **`scraper/scraper_cache.py`** — ScreenScraper search-result cache. Keyed `f"{game_id}:{system_id}"`, TTL 10 minutes, hard cap 500 entries (evicts expired entries first, then oldest by timestamp). Thread-safe (`_cache_lock`). Used because the ScreenScraper API does not support fetch-by-ID — the only way to get a full result is to keep the search-result payload around between the user picking a result and `apply_screenscraper_to_metadata` running.
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

**Integer-column trap (Pass 45.3):** AI Fill writes through `routes/games_ai.py`. The integer columns (`players`, `critic_score`, `critic_score_count`, `user_score`, `user_score_count`) coerce via `int(float(value))`. If the AI returns `"0"`, that becomes `0` — and a bare `field = ?` UPDATE then clobbers a curated `players=4` with `0`. Fix: any integer coerce to `0` is **skipped** entirely from the UPDATE clause (chosen over `COALESCE(NULLIF(?, 0), col)` because the existing `should_apply` filter already guarantees we only reach the int-coerce on values worth writing). Regression tests in `tests/test_pass45_security.py::TestPass45_3*`.

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

   def apply_foo_to_game(db_game_id, foo_data) -> bool:
       # Standalone single-source UPDATE. Mirrors the COALESCE pattern from
       # scrape_esde.apply_esde_metadata exactly.
       ...
   ```
   All HTTP calls go through `base_scraper.http_get` / `http_post`. All image downloads go through `base_scraper.download_image` or `metadata_merger._download_and_finalize`. No bare `requests.get` calls.

2. **Add an `apply_foo_to_metadata(metadata, foo_data, db_game_id, result, fill_only=False)`** in `scraper/metadata_merger.py`. Pattern: title is `if not metadata['title'] or not fill_only`; every other field is `if not metadata['field']`. Append `f'<field> (FOO)'` to `result['filled_fields']` on each fill. Use `normalize_title`, `normalize_genre`, `normalize_modes`, `normalize_esrb_rating` for canonical values. For images, call `_download_and_finalize` and only set `metadata[field] = filename` on `True`. For screenshots, use `keep_screenshot_if_unique` against `get_existing_screenshot_hashes`.

3. **Wire into `hybrid_scraper.apply_hybrid_metadata`**:
   - Add an `elif primary_source == 'foo':` branch wrapped in `try / except` (Pass 41.4.B pattern; log + fall through to gap-fill on exception).
   - Add an `elif fallback_source == 'foo':` branch in the gap-fill loop with `if secondary_sources` shortcut + fresh-search path (use `_pick_best_secondary` / `_pick_best_fallback`).
   - Add `'foo': ['foo']` (or insert into existing field lists) in `FIELD_SOURCES` for every field `foo` can supply.

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
   - `tests/test_scrape_fill_only.py` — add a test exercising `apply_foo_to_game` with an existing populated row + an empty API response; assert every column survives. Mirror the IGDB/TGDB tests.
   - `tests/test_match_scorer.py` — pin per-source scoring extras.
   - `tests/test_pass40_security.py` (or successor) — if `foo` downloads images, add SSRF + redirect-chain tests asserting it goes through `base_scraper.download_image`.

7. **Docs** — extend §2 source inventory; add a row to `FIELD_SOURCES` table in §4 if `foo` contributes any new field; update CLAUDE.md "Scraper fill-only invariant" only if `foo` introduces a new exception (it shouldn't).

---

## 14. Known invariants

- Every `?` in a scraper UPDATE is wrapped in `COALESCE(?, column)` (Pass 30.4 / 40.6 / 45.3).
- Fill-only across every source; the only documented exception is `force_overwrite=True` in `hybrid_scraper` (Full Re-scrape).
- Screenshots are always *appended*, never replaced. Dedup via dHash with Hamming threshold 10.
- Media fields (`boxart`, `boxart_3d`, `fanart`, `video`, `manual`) are filled only when empty; clear them via the edit modal to force a re-fetch.
- Stale media references (file deleted, filename still in DB) are detected pre-merge and conditionally NULLed under `WHERE id = ? AND <field> = ?` (Pass 40.15).
- Every image download MUST go through `base_scraper.download_image` or `metadata_merger._download_and_finalize` — both gate on SSRF, walk the redirect chain, pin the resolved IP, stream with `MAX_MEDIA_DOWNLOAD_BYTES` cap (50 MB default), and write atomically (Pass 25.7, 32.6, 32.7, 40.7, 40.15, 45.2).
- Every API call goes through `base_scraper.http_get` / `http_post` — backoff with jitter on 429/5xx, optional `max_bytes` cap (Pass 26.4, 32.14).
- `players` is INTEGER; ranges like `"1-4"` are normalised to the max (4) via `re.findall + max` before save. `normalize_players_value` is the canonical helper for route-layer writes (Pass 40.6).
- `genre` values are hyphenated and constrained to `FIELD_SCHEMAS` in `scrape_ai.py`. New genres added to either list must be added to both.
- Curated DB-default controllers always override scraped/AI controller values (`get_system_default_controller_name`).
- Per-source primary fetches are wrapped in `try / except`; on failure the orchestrator logs and falls through to gap-fill (Pass 41.4.B). The final UPDATE is **not** wrapped — drift between the metadata dict and the binding tuple must fail loudly.
- ScreenScraper search results are cached for 10 min (no fetch-by-ID API). Settings JSON is cached for 30 s. Per-source circuit breakers open after 5 failures, recover after 120 s.
- AI Fill is text-only; never writes media. Integer-column writes skip the UPDATE clause when the coerced value is `0` (Pass 45.3).
- Sort title is auto-generated from title via `services/game_utils.py::generate_sort_title` during scrape and AI Fill.
- Rating cross-mapping fills empty rating systems from any present rating via the maturity-tier table in `services/game_utils.py`; content inference is the final fallback when no rating system is filled at all.
