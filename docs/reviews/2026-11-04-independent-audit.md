# Independent audit, 2026-11-04 (raw reports)

The multi-agent sweep before v4.0.0 (`roadmap.md` § Periodic Independent Review; PASS-59-113 step 9).

Each reviewer saw only its own files and the project documents. The reports below are copied word for word, in lane order. Nothing has been checked, sorted or dropped yet. Every finding is a reviewer's claim until it is checked against the code.

The partition in `roadmap.md` was out of date. It named four files that no longer exist and left launching, emulators, cheats and the updater uncovered. This sweep therefore used 15 lanes: the 14 originals, widened to cover newer files, plus lane 15.

Coverage was partial in some lanes. Lanes 12 (JavaScript), 13 (templates and CSS) and 14 (tests and tooling) mostly searched for patterns rather than reading whole files. Lane 15 did not open `services/emulator_seeder.py`. Each report states what it did not read.

---

## Lane 1 — Auth & security

## Subsystem: Auth & security

**Line counts as read (native Read, full):** services/auth.py 371, services/security.py 217, services/log_redactor.py 157, services/ssrf.py 217, services/path_browser.py 87, services/platform_tokens.py 70, services/ra_sign_in.py 109, services/ra_standalone.py 194, routes/auth.py 612.

**What I already had on arrival:** global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (including the LAN-only threat-model note), and a git snapshot (clean `main`, recent commits on PASS-59-113/155/236).

**What else I read:** `docs/specs/auth.md` §§6–13 and `services/database.py::query`, which returns dicts, so `g.user.get` works. I also searched for `SESSION_TYPE`, `session_interface` and `0o600`. No server-side session exists, and the database is chmod 0o600 in `database_init.py`. I did not read the other reference docs or `docs/decisions/`, and I read no tests.

### 1. Spec alignment

- **MEDIUM, routes/auth.py:476 and 513, against auth.md §7.** The spec says changing the password "invalidates hijacked cookies and concurrent sessions". The app uses Flask's signed-cookie session, and there is no server-side session or session-version field. So `session.clear()` only re-signs the cookie of the person making the request. Any other cookie carrying the same `user_id` stays valid for the full 7 days. An admin password reset (routes/auth.py:256-271) does not end any session either. Deactivating the account is the only real way to revoke access (services/auth.py:173). Fix: store a `session_epoch` on `users`, check it in `get_current_user`, and bump it whenever the password changes.
- **LOW, routes/auth.py:101, against auth.md §9 ("bucket clears on the next successful login").** Failures are recorded on the bare-IP bucket (routes/auth.py:67, 76, 84). A successful login clears `f"{ip}:login:{user_id}"`, a bucket that nothing ever fills, so the call does nothing. Not resetting on success is the safer behaviour. The spec text and the comment "Clear only THIS user's bucket" are wrong. Fix: delete the call and correct the spec.
- **LOW, routes/auth.py:484-507, against auth.md §9.** The spec says the force-change endpoint "re-verifies the user's current password". It does not; it only needs `force_password_change`.
- **LOW, routes/auth.py:349, 428, 484, against auth.md §13.1 ("No bare `@bp.route` on POST").** These three POST routes check `g.user` inline with no decorator. Users are still gated, but the invariant as written is broken.
- **LOW, services/platform_tokens.py:30 and auth.md §6.** Both describe the store as PSN and Xbox only. It now also holds `retroachievements` (services/ra_sign_in.py:21).
- **LOW, services/security.py:59 versus 82.** The docstring promises the path is "its own realpath (no symlink escape)". The code only rejects a link in the last part of the path. A symlinked parent folder passes. The damage is limited because the resolved path is what gets returned.

### 2. Weaknesses

- **MEDIUM, services/ssrf.py:211-214.** A relative `Location` header (for example `/img.png`) is fed straight into `validate_outbound_url`. That fails with "disallowed scheme: ''", so any download that redirects with a relative URL fails. Fix: `urljoin(current, next_url)`.
- **MEDIUM, routes/auth.py:560 versus 583-591.** The old avatar file is deleted before the new upload is checked. An invalid image therefore leaves the database pointing at a file that no longer exists. Fix: delete only after `img.save` succeeds.
- **LOW, services/ssrf.py:31-39.** `_ip_is_public` lets through ranges that are not public, such as 100.64.0.0/10 (carrier-grade NAT). Fix: `not ip.is_global`. The HEAD probes at ssrf.py:207 are not pinned, so a host that switches its DNS answer to a local address can still receive a blind HEAD request.
- **LOW, services/path_browser.py:72.** `_counts` scans every subfolder once per listing. On a ROM tree or network mount with many folders, the Browse dialog will be slow.
- **LOW, routes/auth.py:199-207.** A new account gets the known password `changeme` and accepts it until its first login. Anyone on the LAN can claim it first. This is by design under the household threat model.
- **LOW, routes/auth.py:115-118 and 260-261.** A non-string `next` or `new_password` raises a TypeError, and these routes have no `@handle_api_errors`. The result is an unformatted 500 instead of the JSON envelope.
- **LOW, services/security.py:36.** User-supplied filenames are logged raw, so newlines can forge log lines.

### 3. Gaps

- **MEDIUM, routes/auth.py:308.** Deleting a user removes their `user_platform_tokens` row. It does not call `ra_standalone.sign_out`, so their RetroAchievements token stays in DuckStation's or PCSX2's settings file. It is only removed when someone else next plays. Deactivating a user (routes/auth.py:252) has the same gap.
- **LOW, services/log_redactor.py:27, 64.** No pattern covers a JSON `"Token":` key (the shape of RetroAchievements' login reply) or `cheevos_token = ...`. In `cheevos_token`, the `_` before `token` stops `\btoken\b` from matching. Nothing in scope logs either today, so this is a latent gap.
- **LOW, routes/auth.py:379-409.** `items_per_page` and `timezone` are saved without any check on type or range.
- **LOW, services/ra_standalone.py:184-192.** Sign-out is keyed on the RetroAchievements username only. If two RetroDB users share one RA account, one signing out removes the sign-in for both.
- **Open question:** at ra_standalone.py:154-157, if PCSX2 has already moved the token to `secrets.ini`, I could not tell from code in scope which copy PCSX2 prefers when RetroDB later writes a new Token line to `PCSX2.ini`.

### Summary, top 3

1. A password change or reset does not revoke other sessions, which contradicts auth.md §7 (MEDIUM).
2. SSRF redirect handling breaks on a relative `Location` header (MEDIUM).
3. Deleting or deactivating a user leaves their RetroAchievements token in the emulator settings files (MEDIUM). The avatar is also deleted before the new upload is validated (MEDIUM).

No CRITICAL or HIGH findings under the LAN-only threat model. These checked clean: the password hashing and constant-time compare, the open-redirect check, the last-admin guards, and the "never raises" handling in `ra_standalone`.

---

## Lane 2 — Database & schema

**Subject line counts (read with `Read`):** services/database.py 450 · services/database_init.py 220 · services/atomic_io.py 130 · settings_manager.py 339 · services/migrations/__init__.py 129 · _helpers.py 54 · scripts 001 488, 002 52, 003 26, 004 80, 005 79, 006 122, 007 278, 008 125, 009 268, 010 54, 011 126, 012 63, 013 133, 014 31, 015 74, 016 91, 017 23, 018 65, 019 17, 020 28, 021 38, 022 27, 023 15, 024 15, 025 15, 026 25, 027 67, 028 16, 029 53, 030 68, 031 16, 032 14, 033 22, 034 14, 035 18, 036 15, 037 16.

**Already in my context when I started:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (MEMORY.md), and a git snapshot (branch main, clean, five recent commits). The only references I opened were migrations.md §§3–9, 11 and 14, and settings.md "Atomic-write contract" and "Known invariants". I did not read RETRODB_DESIGN_STANDARDS §25 or STANDARDS_ADDENDUM. This is a depth pass. Nothing below was executed.

## Subsystem: Database & schema

### 1. Spec alignment

- **MEDIUM: backups are not written the way the docs say.** settings.md (Atomic-write contract) says DB backups go through `atomic_write_bytes(mode=0o600)`. migrations.md §7 says a backup "never exists at the umask default". In the code, `backup_database` (database.py:356-361) writes straight into `dst_path` at the default permissions, and only applies `chmod` afterwards (line 373). So the full copy, password hashes included, sits briefly at 0644. A crash during the copy also leaves a partial file under the final `roms_backup_*` name.
- **LOW: migration 016's header is wrong about foreign keys.** 016_version_groups.py:13 says RetroDB "never turns on `PRAGMA foreign_keys`". But database.py:103 and database_init.py:53 both turn it on. So 016's `ON DELETE SET NULL` and `ON DELETE CASCADE` clauses are enforced, and they duplicate what its triggers do.
- **LOW: migration 012 commits inside the migration.** 012_emulators.py:62 calls `conn.commit()`, which breaks §6/§14.4 ("runner owns the transaction"). The spec admits this in §6. Its log line, 012:63, also says "migration 010".
- **LOW: migration 030 depends on live code.** 030_tidy_stored_text.py:39-40 imports live `scraper.scrape_ai` and `services.normalization`. 027:14 states the principle "a migration never changes meaning later". Because of these imports, 030's behaviour changes whenever those modules change. If either module is renamed, every upgrade from below version 30 fails at boot.

### 2. Weaknesses

- **MEDIUM (unverified, legacy upgrades only): migration 007 may fail to commit.** It rebuilds a *parent* table, `psn_games`, under `defer_foreign_keys` with FKs on (007:158, 207). Dropping the parent counts each `psn_trophies` row as a deferred violation. Renaming the new table in does not clear that count, and deleting the children later does not clear it either, because the parent is found again. If so, COMMIT would fail at `__init__.py:122`, and boot would abort on every start. This only happens if the legacy `psn_trophies` table carried an FK clause, which I could not check. The spec's §9 pattern has the same blind spot for any future rebuild of a parent table.
- **MEDIUM: two processes starting at once can rewind the version.** `apply_pending` reads `user_version` once, before taking the lock (`__init__.py:96`), and never reads it again inside `BEGIN IMMEDIATE` (line 119). A second process starting at the same time would re-run every migration from its stale number and set `user_version` back down. That re-runs the data migrations (028, 029, 030). This is conditional on more than one process booting at once.
- **MEDIUM: cached settings can be changed by accident.** `load_settings` returns a *shallow* copy of the cache (settings_manager.py:200). A caller that edits a nested dict (`logging`, `notification_timeouts`, `naming_convention`) without saving changes the cache itself.
- **LOW: unlocked read-modify-write.** `set_setting` (settings_manager.py:298-302) and `_guard_unreadable_file` (248-270) take no lock, so two concurrent saves can lose one update.
- **LOW: lenient column helpers hide errors.** The helpers in 001:19-24 and 012:19-24 swallow every `OperationalError`. On a SQLite build with DQS disabled, the double-quoted default at 001:103 would fail and `completion_status` would go missing without any message.
- **LOW: crash on non-text paths.** `get_effective_path` calls `.strip()` on any value (settings_manager.py:314), so a non-string value raises `AttributeError`.

### 3. Gaps

- **LOW: orphan rows after a game is deleted.** `pending_upscales` (019) and `emulator_setting_choices` rows with `scope='game'` (018:41-50) have no FK and no delete trigger, unlike 021's proposals table.
- **LOW: plaintext token files stay on disk.** 015:70 renames the legacy OAuth token files to `.migrated-015` and never deletes them, even when `INSERT OR IGNORE` stored nothing.
- **Open question:** `reset_to_defaults` (settings_manager.py:319-321) also resets `setup_completed` to False, which presumably sends the user back through the setup wizard. I could not settle whether that is intended.

**Top 3 priorities:**
1. Check the 007 parent-rebuild FK count on a legacy fixture.
2. Make backups atomic and 0600 from the start.
3. Re-read `user_version` after taking the lock in `apply_pending`.

---

## Lane 3 — Scraper orchestration & metadata

**Subject files read in full with `Read` (line counts):** scraper_manager.py 653 · hybrid_scraper.py 1813 · metadata_merger.py 1667 · metadata_normalizer.py 237 · match_scorer.py 293 · title_normalizer.py 100 · scraper_cache.py 48 · image_dedup.py 136 · service_limits.py 124 · game_metadata_service.py 380 · normalization.py: lines 280–694 of 694 (lines 1–279 are the mapping tables; I saw them only in outline) · field_sources.py 103 · release_dates.py 273 · version_groups.py 441.

**Already in my context when I started:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (`MEMORY.md`), a git snapshot (clean tree, last five commits) and `.claude/rules/ratings.md`. Outside my subject I read only `docs/specs/scrapers.md` §§3–6 and §§10–12, PASS-59-106 §4.5, and two short slices of `scraper/scrape_esde.py` to check a date path. I did not read any tests.

## Subsystem: Scraper orchestration & metadata

### 1. Spec alignment
- **MEDIUM — the circuit breakers cover only AI in gap-fill.** scrapers.md §3 says each fallback for TGDB, IGDB, RAWG, ScreenScraper and AI runs under its breaker. Only AI does (`hybrid_scraper.py:1280-1281`). `_fetch_tgdb`, `_fetch_igdb`, `_fetch_rawg` and `_fetch_screenscraper` (`hybrid_scraper.py:1038-1154`) call the scrapers directly. The breakers are applied only in `search_games` (`scraper_manager.py:381,399,417,456`).
- **MEDIUM — `_download_and_finalize` does not match the contract it claims.** It is described as `download_image`'s "functional twin … same contract", and scrapers.md §10 says the temp file is cleaned up in `finally:` on every exit path. Here, the early `return False` on a non-200 reply, an over-cap `Content-Length`, or a stream over the cap (`metadata_merger.py:151-170`) leaves the `.dl_*` temp file from `mkstemp` (`:142`) in the media folder. There is no `finally`, and no fsync.
- **MEDIUM — the cleanup step can erase stored values.** `canonicalize_metadata` (`normalization.py:547-553`) runs on values loaded from the database, not only on scraped words. A stored genre, mode or perspective that is not a canonical or dropdown value becomes `''`, and `COALESCE('', genre)` writes that over it (`hybrid_scraper.py:1769`). `_reconcile_players_and_modes` (`normalization.py:495-498`) also rewrites a stored `players` value. Neither is among CLAUDE.md's five exceptions.
- **LOW — the documents disagree with each other.** scrapers.md §3 calls Full Re-scrape "the only documented exception to fill-only". CLAUDE.md lists five exceptions, and neither list includes the primary source replacing an unlocked title (`metadata_merger.py:365,623,842,1193`; `hybrid_scraper.py:1202`).
- **LOW — the system-default controller replaces hand edits too.** In a normal scrape the stored `controller_support` is overwritten by the system default (`hybrid_scraper.py:1745-1747`), including one a person typed. CLAUDE.md claims this only for scraped and AI values.

### 2. Weaknesses
- **MEDIUM — ScreenScraper credentials can reach the logs.** Its media URLs carry account credentials in the query string, as `metadata_merger.py:202-205` itself says. Failure logs print the full URL (`metadata_merger.py:123,130,152,157,168,178,1087,1094`).
- **MEDIUM — a failed video or manual download can damage a file the game still uses.** `download_ss_media` writes these straight to `dest_path` with `'wb'` (`metadata_merger.py:1112`). The exception path leaves a partial file (`:1128`), and a stream over the cap deletes the file (`:1121`). In Full Re-scrape without keep-media, that path can be the existing `{id}_ss_video.mp4` the row still points to, and COALESCE keeps that reference.
- **MEDIUM — a scrape can overwrite edits made while it runs.** A normal scrape loads every field from the row at the start (`hybrid_scraper.py:1404-1416`). It then writes them all back at the end with `COALESCE(old_value, col)` (`:716-815`). Any hand edit or AI Fill in between, which can be several seconds with fallbacks and AI, is overwritten.
- **LOW — a log check can abort the save.** `year_gap_with_own_region` calls `int(str(release_date)[:4])` (`release_dates.py:197`). A stored `release_date` that does not start with a year would raise, and the outer except (`hybrid_scraper.py:1807`) would roll back the whole scrape. I have not checked whether such values exist in the database.
- **LOW — IGDB query built by string formatting.** `fetch_igdb_extended` puts the id into the IGDB query text with an f-string (`hybrid_scraper.py:284`). I did not check whether the id arriving from the request is validated first.
- **LOW — a real region can be replaced with the default.** A multi-value region where no part is in the options becomes `default_region` (`hybrid_scraper.py:551-552`), so "Brazil, Korea" becomes USA.
- **LOW — cache keys do not line up for ids without a system.** An id with no system part is looked up as `"123:None"` (`hybrid_scraper.py:1076-1077`), but stored under `"123:"` when `systeme` is missing (`scraper_manager.py:564,579`). The result is a needless fetch by id, not wrong data.

### 3. Gaps
- **LOW/MEDIUM — ratings derived from an AI guess are not marked as guesses.** A rating cross-mapped from an AI guess is credited `cross-map→X` (`hybrid_scraper.py:453`). `ai_marks` does not count that as a guess (`field_sources.py:21,69`), so a PEGI rating derived from an AI ESRB shows as official.
- **LOW — a rejection can be bypassed by grouping.** Union-find joins clusters through shared members (`version_groups.py:420-427`). A pair the user rejected, or two different discs, can land in one suggestion through a third game. `allowed()` checks pairs only. The Link button's tick boxes mitigate this.
- **LOW — re-listed screenshots are not de-duplicated.** Files already on disk and re-listed are kept without the dedup check (`metadata_merger.py:762-763,953-954,1058-1059,1458-1459`).

No problems found in `match_scorer.py`, `title_normalizer.py`, `metadata_normalizer.py`, `scraper_cache.py` (apart from the key mismatch above), `service_limits.py` or `image_dedup.py`.

**Top 3 priorities:**
1. Keep ScreenScraper credentials out of the download-failure logs.
2. Fix the downloads: clean up the temp file on every exit in `_download_and_finalize`, and write videos and manuals to a temp file and rename it, as images are.
3. Resolve the fill-only gaps: either stop `canonicalize_metadata` and players reconciliation rewriting stored curated values, or document them as exceptions; and close the lost-update window, for example by re-reading the row just before the save.

---

## Lane 4 — Per-source scrapers

## Subsystem: Per-source scrapers

**Line counts, as read with `Read`.** Not every file was read in full; the skipped ranges are listed after the counts.
- base_scraper.py 528
- scrape_igdb.py 656
- scrape_thegamesdb.py 1121
- scrape_rawg.py 400
- scrape_screenscraper.py 1098
- ss_regions.py 68
- scrape_esde.py 1303
- scrape_ai.py 1624
- retroachievements.py 571
- hltb_lookup.py 478
- services/ai_fill.py 335
- services/scraper_settings_validators.py 194

**Ranges I skipped, all static lookup tables, so nothing in them is reviewed:**
- igdb 146–372
- tgdb 303–519
- rawg 1–109
- ss 46–195
- esde 93–257
- ai 61–315
- ra 31–97
- hltb 1–87

**Already in my context on arrival:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB MEMORY.md index, and a git snapshot (clean main, five recent commits). `.claude/rules/ratings.md` and `rules/14-contract-gate.md` were loaded automatically during the run.

**Other files I opened to check claims:**
- `docs/specs/scrapers.md` §10, §12 and lines 120–139
- `services/log_redactor.py` patterns
- `services/release_dates.py` (`source_date`, `_clean_date`)
- caller searches with `Grep` after `workspace_search` hit its rate limit

### 1. Spec alignment

- **MEDIUM — `ai_fill.py:142-145` compares raw text before normalizing.** It tests `value != current` before turning the value into its stored form. The players case: a stored `4` against the AI's `"1-4"` counts as a disagreement. The code then writes the same 4 (`:153`), records `replaced['players']='4'`, and adds `players (AI)` to the history. The same happens when a multi-value genre comes back in a different order. `field_sources` would then mark an unchanged scraped value as the AI's. Fix: normalize first (`normalize_players_value`, sorted multi-value sets), then compare.
- **MEDIUM — `ai_fill.py:142`: AI Fill can replace a hand edit.** CLAUDE.md says AI Fill replaces a *scraped* value it disagrees with. The code replaces any current value in `VALIDATE_FIELDS`, including one credited `(manual)`. Nothing in `ai_fill.py` reads that credit. I cannot tell from the docs whether hand edits are meant to be exempt; this is open question 1.
- **MEDIUM — `scrape_screenscraper.py:541-565`: `get_game_info` skips two of the spec's stop rules.** Spec §10 says the service stops on a reply in words naming a quota, and on a reply at its daily limit. This path:
  - never calls `_note_account_limits`, so it learns neither the per-minute pace nor the daily stop;
  - turns a plain-text quota reply into `None` with no `service_limits.stop`.

  `_search_once` (`:380-383`) and `_jeu_from_reply` (`:951`) do both. Fix: apply the same two checks here.
- **LOW — `scrape_esde.py:969-1194`: the "canonical" COALESCE example is dead code.** CLAUDE.md and scrapers.md call `apply_esde_metadata` the canonical fill-only site. Its only non-test caller is `bulk_import_esde`, and `bulk_import_esde` has no caller outside tests (`Grep` over all `*.py`).
- **LOW — scrapers.md line 35 names `ai_anthropic_api_key`.** The code (`scrape_ai.py:388`) and the validator (`scraper_settings_validators.py:40`) use `ai_claude_api_key`. The doc should change, not the code.

### 2. Weaknesses

- **MEDIUM — `scrape_screenscraper.py:1015-1062`: streamed responses are never closed.** Replies are fetched with `stream=True`, and none of these exits closes them:
  - an oversized reply (`:1023`, `:1036`);
  - a 429 or 5xx before a retry (`:1049`, `:1057`);
  - a 430 or 431 (`:1043`).

  On a shared `Session`, each can hold a pooled connection until garbage collection runs. Fix: `response.close()` before each early return or `continue`.
- **LOW — `base_scraper.py:80-88`: `max_bytes` does not limit memory.** The check runs after `requests` has already read the whole body. It protects JSON parsing only, unlike the streamed cap in ScreenScraper.
- **LOW — `scrape_esde.py:892-912`: ES-DE media copies are looser than downloads.**
  - `shutil.copy2` has no size cap. The allowed roots include the whole ROM folder (`:59`), so a gamelist tag pointing at a ROM copies it into IMAGE_PATH.
  - The copy is not atomic.
  - fanart and game logos are never finalized; `download_image` does finalize them (`base_scraper.py:392-395`).
- **LOW — `scrape_igdb.py:641`:** `where id = {game_id};` is put into the query without an `int()` cast. Any risk stays inside IGDB queries.
- **LOW — `hltb_lookup.py:363`:** `abs(found_year - wanted_year)` assumes `release_world` is an int. A string raises, the catch-all at `:476` turns it into `None`, and the whole lookup is lost. The token globals (`:153`) are also unlocked; a race there only costs an extra request.
- **Checked, and it holds:** credentials sent as query parameters (RA `y`, TGDB `apikey`, RAWG `key`, ScreenScraper `sspassword`) could appear in `http_get`'s connection-error logs (`base_scraper.py:162`). The `log_redactor` patterns cover all four parameter names. That only works where the filter is attached, which I did not check.

### 3. Gaps

- **LOW, latent — `scrape_esde.py:1170-1183`: `bulk_import_esde` builds data `apply_esde_metadata` cannot read.**
  - It sends no `esde_data` and stores the raw `releasedate`. `source_date("19910101T000000")` then fails `_clean_date` (it reads `"19910101T0"`), so every date is lost.
  - The gamelist media tags (cover, 3dbox and the rest) are never passed, so only the folder lookup can find media.
  - It also crashes on a NULL `rom_path` (`:1165`), and misses folder ROMs because it never strips the trailing `/`.
- **LOW — `scrape_esde.py:872-873`:** a `~/` media path from a gamelist is never expanded with `expanduser`, so it never resolves.
- **LOW — `scrape_esde.py:1058`:** ES-DE can change `title` without regenerating `sort_title`. `ai_fill.py:195-198` does regenerate it.

### Open questions

1. Are hand-edited values in `VALIDATE_FIELDS` meant to be safe from AI Fill's validation overwrite?
2. `scrape_igdb.py:388` reads `release_dates.region`, while `:630` reads `release_region`. If IGDB has retired `region`, the region shown in search results is always empty. I have not checked IGDB's API.
3. `scrape_ai.py:1590`: the Claude key check sends `max_tokens: 20` with no `output_config`. The comment at `:937` says thinking counts toward `max_tokens`, so this check may report a working key as failed. Not verified.
4. `scraper_settings_validators.py:141-146` passes `api_keys` through without checking it. That is safe only if the route really discards it; the route is outside my scope.

### Top 3 priorities

1. AI Fill's raw-text comparison: it marks unchanged values as the AI's, and may overwrite hand edits.
2. ScreenScraper's `get_game_info` does not stop or slow down as the spec says.
3. ScreenScraper's streamed responses are never closed.

---

## Lane 5 — Platform imports

**Subject files, line counts as read** (whole files, read with `Read`): routes/platform_import.py 1092; routes/steam_achievements.py 158; routes/xbox_achievements.py 177; routes/game_imports.py 32; scraper/scrape_steam.py 229; scraper/scrape_xbox.py 516; scraper/trophy_parser.py 390; services/playtime.py 22; services/jobs/platform_sync.py 898; services/jobs/psn_keepalive.py 140; services/jobs/psn_refresh.py 745.

**Already in my context before I read anything:** the global ~/.claude/CLAUDE.md, /mnt/Games/CLAUDE.md, the RetroDB CLAUDE.md, the RetroDB memory index (MEMORY.md), a git status snapshot (clean, last 5 commits), and the rule files .claude/rules/ratings.md and ~/.claude/rules/14-contract-gate.md, which loaded during the run.

**Notes on how the run went:** `workspace_search` was rate-limited once, so I used `Grep` for the docs searches. Every check I planned was run. Outside the subject I read: the Steam/Xbox/PSN lines of docs/specs/scrapers.md and jobs.md, jobs.md lines 236–271, and the start of `get_saved_api_keys` in routes/scraper.py. The report runs a little over 600 words, to keep a file:line on every finding.

## Subsystem: Platform imports (Steam, Xbox, PSN)

### 1. Spec alignment
- **MEDIUM. Steam credentials still fall back to one shared file for every user.** In services/jobs/platform_sync.py:52-63, `_get_steam_credentials(user_id)` reads data/scraper_settings.json whenever that user's row lacks a key or an ID. The comment at routes/platform_import.py:161-169 says this call removed the cross-user read, and cites auth.md: "the RA fallback [is] the only install-wide read permitted". It did not remove it. A household member with no Steam settings gets another person's library, and the sync job (platform_sync.py:527, :539) writes that person's play time and achievements under their own user id. Fix: when `user_id` is given, skip the file fallback.
- **MEDIUM. Xbox gamertag is dropped on every token refresh.** In scrape_xbox.py:318-325 the refresh removes `xuid` and `gamertag`. The comment says "the XSTS / profile lookup below re-validates", but nothing after that calls `get_gamertag` or saves the values again. So once the token has refreshed, `api_xbox_status` (platform_import.py:509-510) shows "Unknown" and an empty xuid. Separately, `api_xbox_fetch_library` returns `session.get('gamertag')` (platform_import.py:617), but the session dict (scrape_xbox.py:349-354) never holds that key, against its docstring at :297. So the fetch always returns an empty gamertag.
- **LOW. User-facing text not wrapped for translation.** This breaks CLAUDE.md step 8: `message='Game has no achievements'` (steam_achievements.py:120, xbox_achievements.py:139), and the job error strings shown through `jsonify` (platform_sync.py:346, 463, 652, 755).
- **Open question (not verified).** CLAUDE.md and scrapers.md:32 say "Steam's date and genre are left out". The subject only passes the raw store details on (platform_sync.py:101-105). Any exclusion must live in `hybrid_scraper.apply_hybrid_metadata`, which is outside my scope.

### 2. Weaknesses
- **MEDIUM. Any failed Xbox refresh deletes the stored tokens.** `refresh_access_token` returns None on any exception, including a timeout or a server error (scrape_xbox.py:141-143). `get_authenticated_session` then calls `clear_tokens` (scrape_xbox.py:334). A passing network outage therefore forces the user to sign in again. The comment says "revoked / 401-loop", but the code cannot tell those apart.
- **MEDIUM. PSN keep-alive can renew the same session twice, and its window is always open.** `_started` is per process (psn_keepalive.py:34), and there is no singleton lock of the kind the jobs use. Each worker process would renew the same refresh token, and the file header says Sony replaces that token on each renewal. Separately, the 14-day threshold (:30) is longer than the 10-day lifetime the header states (:9-10), so every live session is renewed every day.
- **LOW. The "already filled from the store" check depends on JSON spacing.** `store_filled` is `LIKE '%"primary_source": "steam"%'` (platform_sync.py:86). A history writer using compact separators would never match, and every game would be re-asked on every sync. I did not open the writer.
- **LOW. After SIGTERM, the loops keep running with no delay.** The loops check only `cancelled` (platform_sync.py:502, 821; psn_refresh.py:434). Once shutdown is signalled, `shutdown_requested.wait()` returns at once (:568, :876, psn_refresh.py:530), so requests go out unthrottled until the process exits. A paused PSN job also leaves its pause loop on shutdown and goes on processing (psn_refresh.py:460-465).
- **LOW. No validation of IDs sent to the import routes.** IDs are used as sent (platform_import.py:278, 658, 1021). An empty or `None` id becomes `steam_app_id ''` or the text `'None'`, and a `rom_path` like `steam_import/windows/`.
- **LOW. A non-string Steam ID crashes the fetch.** `steam_id.isdigit()` (platform_import.py:187) raises an error, so a 500, if the JSON body sends a number.
- **LOW. A viewer can create system rows.** The fetch-library routes allow any signed-in user (@login_required) but call `_ensure_system_exists`, which writes (platform_import.py:202, 550, 897).
- **LOW. Unverified: blank titles may match each other on import.** The import routes key duplicates on `normalize_title(...)` without the empty-title guard that `_DuplicateIndex` has (platform_import.py:274, 654 vs :123). Titles that normalise to `''` would then match each other.

### 3. Gaps
- **MEDIUM. PSN import never links by title.** Steam and Xbox do (platform_import.py:290, 678). A PSN title match is only skipped (:1039-1041). The existing game never gets `psn_npwr_id`, and `psn_games.linked_game_id` is never set for it or for an npwr skip (:1036). That user's trophies stay unlinked.
- **LOW. Xbox platform mapping may misfile PC titles.** `XBOX_PLATFORM_MAP` has no `'PC'` key (scrape_xbox.py:34-45), and unknown devices default to `xboxone` (:483). If titlehub reports PC titles as "PC", which I have not verified, they would be filed as Xbox One. Xbox 360 titles fetched with contract v2 (:431) may come back with no achievements and be counted as a successful 0/0. That is also unverified.
- **LOW. Partial results look complete.** Xbox title history stops at 1000 entries and returns a partial list on errors with no warning (scrape_xbox.py:357, 387-409). Delisted Steam apps are asked about again on every sync (platform_sync.py:101-102).
- **LOW.** `main_story_hours` raises an error on the text "Main: ." (playtime.py:13, :21).

**Clean as far as I read:** trophy_parser.py's bounds checks, the Xbox OAuth state check (platform_import.py:446-455), and per-user scoping of the SQL in psn_refresh.py.

### Summary: top 3 priorities
1. Remove the shared-file Steam credential fallback when a user id is given (platform_sync.py:52).
2. Keep the Xbox tokens when a refresh fails for a passing reason, and fetch the gamertag again after a refresh (scrape_xbox.py:318-335).
3. Link PSN imports by title, as Steam and Xbox do, and set `linked_game_id` on skips (platform_import.py:1036-1041).

---

## Lane 6 — Image pipeline & media

**Line counts as read (native Read, in full):** image_utils.py 1056 · jobs/image_resize.py 427 · jobs/webp_migrate.py 494 · game_media_service.py 334 · media_cleanup.py 539 · screenshot_fit.py 93 · box_faces.py 361 · upscale_queue.py 198.

**Already in my context when I started:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB MEMORY.md index, and a git status snapshot (clean, last five commits).

**What I read outside the scope files, only to check claims:** `docs/specs/image-pipeline.md` §2–15, `PASS-59-142` §4.1–6, `routes/maintenance.py` lines 140–185, the header of `services/wishlist_scraper.py` and its `w{item_id}` line, `routes/games.py` lines 636–655, and the chmod lines in `services/atomic_io.py`. One `workspace_search` hit the rate limit, so I ran that search with Grep instead. I read no tests and no git log.

## Subsystem: Image pipeline & media

### 1. Spec alignment
- **LOW** — Spec §15 rule 3 says every `Image.open` catches `DecompressionBombError` with its own log line. These do not: `image_resize.py:374-379`, `webp_migrate.py:358,376,397`, `screenshot_fit.py:87`. `fit_error`'s docstring promises only `OSError`, and the bomb error is not an `OSError`, so a caller catching `OSError` would crash.
- **LOW** — Spec §12.1 says a failed disk-space check "transitions to `failed`". The code returns before `persist_job_start` (`webp_migrate.py:173-177`), and `finally` sets completed or cancelled (`:247`). The spec also names the method `_run()`; it is `_worker` (`:149`).
- **LOW** — `_atomic_save` (`image_utils.py:994-1010`) never chmods, so mkstemp's owner-only mode (0600) carries onto every resized, re-encoded, variant or migrated image. `atomic_write_bytes`, used for uploads, does chmod (`atomic_io.py:75`). I did not check what mode it sets by default.
- **LOW** — `_save_image` swallows save errors (`image_utils.py:1055`). So `image_resize.py:406-407` counts a failed save as "upscaled" or "downscaled", and `failed_count` reads too low.

### 2. Weaknesses
- **HIGH** — The orphan sweep deletes wishlist media. Both routes pass only `games` rows (`routes/maintenance.py:152,165`). Wishlist files are named `w<id>_…` (`wishlist_scraper.py:9-12,247`) and sit in the same folders; `clear_rawg_covers` resolves them under `IMAGE_PATH/boxart` (`media_cleanup.py:452-490`). Their prefix `w12` is not a number and no game row names them, so `media_cleanup.py:240-259` marks them orphaned and `clean_orphaned_files` deletes them. Fix: include wishlist rows, or the `w<id>` prefix, in the keep set.
- **MEDIUM** — `webp_migrate` has no path containment check. `webp_migrate.py:305` joins the stored database value with no `safe_path`, writes the new file at `:347`, and deletes the original at `:367`/`:419`. `media_cleanup.py:72` and `game_media_service.py:118` both guard this, and `game_media_service.py:86-89` treats `../` in scraper filenames as a real risk. A WebP copy is left behind. `upscale_queue.py:107` has the same gap, but it rewrites in place and never deletes (LOW).
- **MEDIUM** — `webp_migrate` breaks shared filenames. If two rows name the same file, the first conversion deletes the original. For the second row, `:341-342` finds the file missing and returns "skipped" before the adopt-existing-WebP check, so that row keeps pointing at a deleted `.jpg`. Fix: run the adopt check before the missing-file check.
- **MEDIUM** — The background upscaler can overwrite a newer download. `standardize_image` reads the pixels (`image_utils.py:812-814`), upscales, then asks `still_wanted` (`:860`). `still_wanted` checks only that the game still names the file and that it exists (`upscale_queue.py:111-113`). If a Full Re-scrape rewrites the same filename during the upscale, the upscaled old picture replaces it. The re-queued pass then finds that file already in the size band, so the new download is lost. Fix: also compare the file's modified time or inode.
- **LOW** — Real-ESRGAN time is wasted on GIFs. The resize job lists `.gif` (`image_resize.py:201`) and upscales it, then `_save_image` discards the result (`image_utils.py:1035-1036`). This repeats on every run, and the job counts it as "upscaled".
- **LOW** — The model download has no hash check. Once a bad file (for example an HTML error page) is saved at the model path, `image_utils.py:375` never downloads it again, and `:469` turns upscaling off on every start.
- **LOW** — `media_dir_is_healthy` (`media_cleanup.py:101-105`) counts any entry. A folder left holding only `-sm`/`-md` variants or `.save_*` temp files passes the mass-missing guard.
- **LOW** — Race when the GPU circuit breaker trips. Threads already inside `enhance` see `_gpu_queue` become None (`:284`) and call the GPU session from their own thread, or call `.put` on None (`:96`). The errors are swallowed without a log (`:944`), and Lanczos is used.
- **LOW** — Transparency is kept only for RGBA (`image_utils.py:893`). LA, or palette images with transparency, become RGB on the upscale path (`:917-918`).
- **LOW** — If two faces in a box file name the same upload, the second `_read` gets empty bytes and the import fails as `bad_image` (`box_faces.py:306`).

### 3. Gaps
- **LOW** — `_SOURCES` (`webp_migrate.py:34-39`) leaves out `boxart_back` and `game_logo`, so old JPG/PNG back covers never move to WebP. This matches the spec's list of four columns.
- **LOW** — The disk guard asks for twice the whole library's size (`webp_migrate.py:167`), though only about one file's worth is needed at a time. It refuses on large libraries.
- **LOW** — `remove_box_faces` with an unreadable record (`box_faces.py:356-360`) clears the column but leaves the files. They carry a live game's ID prefix, so the orphan sweep never removes them.

**Checked and nothing found:** `box_faces` runs every check before any write and deletes old faces only after the update (§4.2/4.3). The symlink check runs before `safe_path` (`:85-87`, INV-5). The orphan cleaner's time rule matches §10 item 3. `screenshot_fit` refuses on colour count for Game Boy only, as CLAUDE.md says.

**Open question:** I took the wishlist media folder from `clear_rawg_covers` and the `wishlist_scraper` header. I did not trace the download helper's destination path. Confirm that before acting on the HIGH finding.

**Top 3 priorities:** (1) the orphan sweep deleting wishlist media; (2) containment and the shared-file order in `webp_migrate`; (3) the background upscaler overwriting a re-scraped file.

---

## Lane 7 — Background jobs

**Subject files as read (line counts):** `services/jobs/__init__.py` 117, `base.py` 838, `ai_fill_bulk.py` 209, `alt_titles_backfill.py` 316, `bulk_scrape.py` 1097, `hltb_bulk.py` 378, `mame_names.py` 152, `museum.py` 526, `museum_images.py` 157, `player_cores.py` 164, `ra_refresh.py` 382, `ra_sync.py` 412, `ss_region_repair.py` 279, `services/apply_progress.py` 375. I read all of them in full with `Read`. I also read `docs/specs/jobs.md` in full. I did not open `RETRODB_DESIGN_STANDARDS.md` or `STANDARDS_ADDENDUM.md`, because no finding needed them.

**Already in my context on arrival:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (MEMORY.md), and a git snapshot (clean `main`, last commit `3a43bb1f`). Rule 14's `14-contract-gate.md` was injected while I worked.

**Outside the subject, to check two claims:** `find_definition` on `match_ra_game_for_file`, and a search for `DB_PATH` in `config*.py`.

**Brief vs. lane file:** they did not conflict. This was an unmarked packet, so I ran it as a depth pass.

## Subsystem: Background jobs

### 1. Spec alignment

- **MEDIUM**: `jobs.md` §5 says `request_shutdown` drains every singleton except webp. But `base.py:50-65` also leaves out `player_cores_job`, and the spec's lock table lists `player_cores.lock`. `PlayerCoresJob` has no `cancel()` either (`player_cores.py:27-164`). A shutdown mid-download is not drained.
- **LOW**: `__init__.py:69-117`: `__all__` leaves out the classes `MameNamesJob` and `SsRegionRepairJob`, though their singletons are listed.
- **LOW**: the lock directory is described in three ways. `base.py:294` says `data/job_locks/`, and `jobs.md` §5 says `data/` must be on a local disk. The real directory is `dirname(DB_PATH)/job_locks`, which is `database/job_locks` (`base.py:318`, `config.py:40`).
- **LOW**: `jobs.md` §4 says progress is saved every 10 items or 30 seconds. `ai_fill_bulk.py` and `mame_names.py` never call `persist_job_progress`, so the recovery banner always shows zero progress for them.
- **LOW**: §9 says all jobs return `current` and `total`. `museum.py:96-109` returns `current_index` and `total_systems` instead.

### 2. Weaknesses

- **HIGH**: `hltb_bulk.py:288-299`: the auto-apply `UPDATE` has 7 `?` placeholders (playtime, name, platform, confidence, `hltb_id`, `hltb_players`, id) but passes only 5 values. Every auto-apply raises "Incorrect number of bindings", which line 347 counts as `failed`. High-confidence matches are never applied. Remedy: pass `result.get('game_id')` and `result.get('players')` before `game['id']`.
- **HIGH**: `ra_refresh.py:330` passes `game.get('folder')`, but the rows only hold `system_folder` (lines 198, 226, 236). `match_ra_game_for_file` (`services/achievement_linking.py:410`) therefore always sees `system_folder=None`. The file-hash match never runs in RA Refresh, and `copy_fits` is always `None`. Remedy: pass `game.get('system_folder')`.
- **MEDIUM**: `bulk_scrape.py:454-460` and `537-543`: when the old worker has not exited 60 seconds after a swap or demote, the handler runs `reset()`. That clears `cancelled`, so the old thread's loop at line 812 carries on through its own `_game_ids` list alongside the new worker. Two scrapes then share one set of counters. Remedy: give each run a generation token and check it in the loop, instead of relying on the shared `cancelled` flag.
- **MEDIUM**: `bulk_scrape.py` does slow database writes while holding `self._lock`, which goes against invariant 2:
  - `persist_job_queued` (line 265) and `remove_queued_job` (lines 355, 365, 692), with retry backoff up to about 7 seconds.
  - Status polls block meanwhile.
- **MEDIUM**: `ss_region_repair.py:254`: `_repair_game` has no per-game `try`. One `search_game` network error ends the whole run as `failed`.
- **MEDIUM (uncertain)**: `ai_fill_bulk.py:181-182`: an exception from `load_game` or `fill_game` also ends the whole run. I did not open `fill_game` to see whether it catches its own errors.
- **MEDIUM**: `ra_sync.py:308-315` sends the RetroAchievements (RA) API key as a URL query parameter. Line 382 logs the exception text, and a `requests` connection error includes the URL with its query, so the key can end up in the log file.
- **LOW**: `bulk_scrape.py:290` / `_start_next_queued`: between a worker finishing (line 1049) and the lock release in `_start_next_queued`, `start()` tries to open the flock again in the same process. That fails, and the user is told the scrape is "running on another worker process".
- **LOW**: `base.py:499-505`: if the commit on a shared connection fails after all retries, the transaction stays open. The job's long-lived connection then keeps SQLite's write lock.
- **LOW**: `base.py:778-782` compares ISO `completed_at` values (`T…+00:00`) with `datetime('now', ...)` text (a space separator). Rows on the cutoff day sort wrongly, so retention is off by up to a day.
- **LOW**: `bulk_scrape.py:222-228` and `786-799`: the connection is not closed on an exception.
- **LOW**: `apply_progress.py:130`: `self.result.get` assumes the result is a dict.

### 3. Gaps

- **HIGH**: a demoted or swapped job is lost on restart. Its remainder is re-queued in memory only, with no `db_queue_id` (`bulk_scrape.py:415-435`, `502-522`). The old worker's row ends as `cancelled` (line 1051). The resume-while-running queue entry (`bulk_scrape.py:615-630`) is not saved either. After a restart, none of these reappear in the recovery banner.
- **LOW**: when a service's limit stops a run, it ends as `completed` with no error message: `hltb_bulk.py:266-267`, `ss_region_repair.py:255-256`. The user cannot tell a run that stopped early from one that finished.
- **LOW**: `bulk_scrape.py:588-597`: resuming an old multi-system job with no `game_ids` re-queries the whole library.
- **Open question**: `player_cores.py:58` returns `'success'` as a list, and `ai_fill_bulk.py:148` / `museum_images.py:64` return it as an int. The comment at `bulk_scrape.py:199-201` says a route that spreads `get_status()` into its reply lets this key overwrite the reply's own `success` flag. I did not check those routes; they are out of scope.

**Clean on reading (checked, nothing found):** `apply_progress` locking and context-variable handoff, `mame_names` and `museum_images` cleanup, and the `museum` paths that set `persist_id = None` after reporting a failure.

**Summary: top 3 priorities**
1. HLTB auto-apply binding count (`hltb_bulk.py:288-299`): the feature is silently dead.
2. RA Refresh folder key (`ra_refresh.py:330`): the hash match never runs.
3. Demoted or swapped scrapes are not saved (`bulk_scrape.py:415-435`, `502-522`), and the swap timeout leaves two workers running (`bulk_scrape.py:454-460`).

---

## Lane 8 — Game routes & detail/edit

**Subject files and their line counts as I read them:** routes/games.py 1510, routes/games_ai.py 80, routes/games_hltb.py 186, routes/games_media.py 234, routes/games_search.py 194, routes/versions.py 110, routes/ai_fill_bulk.py 139, services/game_query.py 381, services/hltb_service.py 467, services/rpcs3_compat.py 194. I read every file in full.

**Already in my context when I started:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (MEMORY.md), and a git snapshot (clean `main`, last commit 3a43bb1f).

**One disagreement, and how I settled it:** your brief sets the output to open with the `## Subsystem` header. My lane file says a return always opens with line counts and the context list. I followed the lane file, so those come first.

**What I checked against:** the CLAUDE.md claims, and the "Group rules" section of PASS-59-106 (§4.1). I did not read `.claude/rules/ratings.md`, `RETRODB_DESIGN_STANDARDS.md`, `STANDARDS_ADDENDUM.md` or `api-contracts.md`, so nothing below is checked against them.

## Subsystem: Game routes & detail/edit

### 1. Spec alignment

- **HIGH — opening a game page permanently deletes its screenshot list when the image drive is not there.** See `routes/games.py:736-746` and `:953-962`. CLAUDE.md says stale media is cleared "during pre-population". In the code it happens on every page view and every modal view, and any logged-in user triggers it, viewers included. If `IMAGE_PATH` is unmounted (this household has already moved drives), every game viewed loses its list for good. Fix: clear only during scans, or check that the folder exists first.
- **MEDIUM — a MAME arcade set can be renamed.** See `routes/games_media.py:66-130`. CLAUDE.md (PASS-59-227) says these files keep their name because MAME finds a game by it. The route never checks `ARCADE_SET_FOLDERS` or `is_arcade_set`, and `rom_type_problem` checks only the file extension.
- **LOW — BIOS sets and regional versions still show in some lists and counts.**
  - `api_filter_games` (`games.py:1456-1492`) includes BIOS sets and bonus discs, and does not group versions.
  - The Library header counts (`games.py:94-103`) and the letter bar (`:113-117`) include BIOS rows.
  - Similar games (`games_search.py:122-170`) can list the game's own regional versions. It also drops rows whose `is_bonus_disc` is NULL, while other queries treat NULL as "not a bonus disc".

### 2. Weaknesses

- **MEDIUM — the card-data cache can show stale progress.** The ETag (`games.py:296-313`) is built from `games.updated_at`. But the card also carries each user's achievement and PSN progress and `can_launch`, and changes to those tables do not bump `updated_at`. So the server answers 304 and the card keeps old progress.
- **MEDIUM — the form edit blanks any field the form did not send.** Every key defaults to `''` (`games.py:457-460`), and the UPDATE writes all of them (`:592-634`). Any field the template does not render is set to NULL. The JSON edit path updates only the fields it is sent. I did not check whether a template still posts to this route.
- **MEDIUM — bulk edit is slow and not atomic on large selections.** `_note_hand_edits` runs once per game, with its own SELECT and UPDATE, outside the transaction (`games.py:1257-1258`). That is up to 10,000 round trips. If the bulk UPDATE then fails, the history still credits a hand edit that never happened.
- **LOW — bulk edit does not check the type of `game_ids` (`games.py:1192, 1257-1268`).** A string `"123"` becomes the ids 1, 2 and 3, so the wrong games are edited. In append mode, a value that is not a string makes `.lower()` fail (`:1297`).
- **LOW — select-all can stop at 10,000 games without saying so.** `/api/games/ids` cuts the list at 10,000 and returns `total=len(ids)` (`games.py:233-238`), so the page cannot tell. Grouping also means "select all" picks only the preferred version of each group.
- **LOW — filters match parts of words.** Filtering on "Action" also matches "Action-Adventure", and excluding it hides those games too (`game_query.py:247-257`).
- **LOW — the "#" letter and accented first letters disagree.** SQLite's `UPPER` changes only A–Z, while Python's `.upper()` (`game_query.py:296`) changes all letters. A button for lowercase "é" finds nothing, and "É" titles appear under both "#" and "É".
- **LOW — HLTB confidence of exactly 1 is ambiguous.** A value of 1 is read as 100% (`hltb_service.py:111, 342`).
- **LOW — a calling trap in the query builder.** Without a `user_id`, `_build_games_query` joins progress rows for every user (`game_query.py:360`). On a multi-user install that repeats cards, rather than just showing "everyone's data" as its docstring says.
- **LOW — raw error text goes to the page.** `games.py:131` and `:904` return the exception message unescaped as HTML.

### 3. Gaps

- **MEDIUM — Reset does less than it says.** The message says "All metadata cleared" (`games.py:677-705`). But it leaves `sort_title`, `perspective`, `dimension`, `game_structure`, `campaign`, `edition`, `other_platforms` and `alternate_titles` in place. It removes no media files, and it refreshes neither the filter and analytics caches nor the upscale queue, though the edit path does (`:659-661`).
- **LOW — deleting a game leaves things behind.** `api_delete_game` (`games_media.py:34-63`) removes no media or box-face files. It also leaves rows in other per-game tables: progress, views, `removed_screenshots`, HLTB pending and play time. The spec says foreign keys are off. I did not check whether a trigger cleans those rows. If none does, a new game that reuses the id inherits them.
- **LOW — the AI Fill reply leaves out fields it fills.** The reply (`games_ai.py:43-76`) has no `units_sold`, `release_dates`, `critic_score`, `user_score`, `sort_title` or `title_locked`, although bulk fill lists those groups (`ai_fill_bulk.py:42-58`).
- **LOW — the bulk AI fill count ignores a bad system id.** A system id that is not a number counts all systems instead of being refused (`ai_fill_bulk.py:94`), unlike the run route.

**Open question:** if a PS3 disc's serial cannot be read and `disc_ids` stores nothing, every Library load starts a new background read of all PS3 discs (`games.py:206-207`, `rpcs3_compat.py:162-194`). So does every view of that game page (`games.py:724`). I did not read `disc_ids`.

**I found nothing wrong in:** `routes/versions.py` and the HLTB routes' permission checks. Every SQL string built in these files goes through an allowlist or a fixed map.

## Summary — top 3
1. Stop the game page and modal deleting screenshot lists on view (HIGH).
2. Block renaming MAME arcade sets (MEDIUM).
3. Make the card-data ETag change when progress or launch state changes (MEDIUM).

---

## Lane 9 — Maintenance, settings, systems, ROM scanning, reports

## Subsystem: Maintenance, settings, systems, ROM scanning, reports

**Line counts as read:** routes/systems.py 482 · maintenance.py 556 · settings.py 714 · scraper.py 926 · bulk_scrape.py 261 · controllers.py 601 (I read only lines 145–601; the `SYSTEM_DEFAULT_CONTROLLER` table at lines 1–144 is **unread**) · reports.py 962 · routes/mame_names.py 61 · rom_scanner.py 175 · game_cleanup.py 360 · rom_identity.py 80 · rom_tools_validators.py 192 · settings_validators.py 297 · services/mame_names.py 173 · disc_serial.py 275 · scan_roms.py 308 · rom_tools.py 1843.

**Already in my context when I started:** the global, `/mnt/Games` and RetroDB `CLAUDE.md` files, the MEMORY.md index (which mentions `.m3u` files and ScreenScraper credentials in logs), and a git snapshot listing recent commits. `.claude/rules/ratings.md` loaded partway through.

**How I checked:** I did not read the reference docs in full. I searched `ROM_NAMING_STANDARD.md` for "M3U" and `docs/specs/settings.md` for path, backup and validation terms. One search hit the rate limit, so I used `Grep` for it.

### 1. Spec alignment
- **HIGH — the Organize Multi-Disc action overwrites an existing `.m3u` playlist.** `reports.py:621` and `:658` open the playlist with `open(m3u_path,'w')` and never check whether it already exists. The only check is in the scan (`:470`, `:552`), and the action does not repeat it. `ROM_NAMING_STANDARD.md` (Creating M3U Games) says creating a playlist "refuses when the playlist or the game folder already exists". `rom_tools.py:832` does refuse, so the two paths behave differently. Fix: refuse when the `.m3u` already exists, and in the move case when the folder does too.
- **MEDIUM — the scraper check routes skip `service_limits.wait_for_turn`.** `CLAUDE.md` (Service limits) says every request to an online service waits for its turn first. `scraper.py:324`, `:396`, `:479`, `:567`, `:610`, `:667`, `:712` and `:787–811` call TGDB, RAWG, ScreenScraper and the AI providers directly. I could not tell whether checks are exempt on purpose (open question).
- **LOW — Clear Scraped Data does not clear all five scraped multi-value fields.** `CLAUDE.md` names five; `game_cleanup.py:29–38` leaves out `perspective`, `dimension` and `game_structure`.

### 2. Weaknesses
- **HIGH — the Duplicate Finder's name mode marks a disc set's own files as duplicates.** `rom_tools.py:1702` groups files by stem only, so `Game.cue` and `Game.bin` are "duplicates" and the newer one is "kept" (`:1722`). `delete_duplicates` (`:1793–1817`) then unlinks any path it is given: it does not check the path is under the ROM root, is in a group, or that one copy survives. Its caller is `routes/tools.py`, outside my scope (open question). Fix: group by stem plus extension, and check deletions server-side.
- **HIGH — ScreenScraper and TGDB credentials can reach the logs.** A `requests` connection error's message includes the full URL with its query. `scraper.py:504` and `:507` log it with `sspassword` and `devpassword` in the parameters. `:605` logs it with the TGDB private `apikey`, and `:918` with the Gemini `key=`. Fix: log only `type(e).__name__`.
- **MEDIUM — files are moved but the database is not told.** Organize (`reports.py:649`) and the Create M3U staging move (`rom_tools.py:922`) both leave `games.rom_path` pointing at the old location. The parent folder still exists, so the next "Clean missing ROMs" counts those games as missing and deletes their rows and all scraped data (`game_cleanup.py:70–77`).
- **MEDIUM — Organize can overwrite a ROM.** `os.makedirs(..., exist_ok=True)` (`reports.py:638`) accepts an existing folder, and `shutil.move` (`:649`) replaces any same-named file already in it.
- **MEDIUM — Organize writes broken playlists for cue/bin sets.** Every moved file goes into the `.m3u`, `.bin` tracks next to their `.cue` (`reports.py:659`, extension list at `:432`).
- **MEDIUM — removing files from a zip uses wildcard matching.** `zip -d` matches names as patterns (`rom_tools.py:684`), and ROM names often contain brackets like `[!]`. The success check (`:711–720`) never confirms that the removed files are a subset of those requested. Fix: pass `-nw` and compare against the request.
- **MEDIUM — CHD conversion with "delete originals" handles disc sets badly.** It lists both `.bin` and `.cue` (`:1250`), both convert to the same `.chd`, and deleting the original removes only the file chdman was given (`:110`). A playlist pointing at the `.cue` is not updated.
- **LOW — Restore removes the database's `-wal` and `-shm` files while other connections may still be open** (`settings.py:429–435`). The jobs check at `:366` also leaves a connection open.
- **LOW — a failed extraction leaves its folder behind** (`rom_tools.py:839`, `:857`), so every retry is refused as "already exists".
- **LOW — error pages put raw exception text in HTML** (`settings.py:195`, `systems.py:216`, `:270`).
- **LOW — a JSON `"false"` string turns on image deletion.** `delete_images` is used as plain truthy (`maintenance.py:140`).

### 3. Gaps
- **MEDIUM — renaming a `.bin` breaks the `.cue` that names it, and renaming a disc inside a playlist folder breaks the `.m3u`.** Neither rename route checks for this (`reports.py:679`, `:809`).
- **LOW — two scans at once can add the same ROM twice.** The scan checks for an existing row, then inserts (`scan_roms.py:262–273`), with no lock. I did not check whether `games.rom_path` has a UNIQUE constraint.
- **LOW — the two scanners differ.** The fallback scanner skips the hidden-file, PS3 and special-folder handling of the main one (`rom_scanner.py:121–170` against `scan_roms.py:144`, `:189`).
- **LOW — Calculate Storage gives wrong sizes for folder games.** `getsize` on a `.PS3` folder returns the folder entry's size (`systems.py:469`).

**Open questions:** whether `routes/tools.py` keeps `delete_duplicates` and `create_m3u_playlist` inside the ROM root; whether `wait_for_turn` is meant to cover check routes; whether `game_utils.get_system_type` returns the lowercase names the naming validator accepts (`settings_validators.py:36`), since `SYSTEM_TYPE_MAP` holds Title-case ones (`systems.py:27`). Not checked: what is in `controllers.py:1–144`.

**Top 3 priorities**
1. Duplicate Finder name mode plus the unchecked `delete_duplicates`: it can delete working disc files.
2. Organize Multi-Disc: overwrites `.m3u` playlists and ROMs, and leaves database paths stale, so the cleanup then deletes those games.
3. Credentials written to the logs from the scraper check routes.

---

## Lane 10 — Collections, achievements, trophies, museum, tools

## Subsystem: Collections, achievements, trophies, museum, tools

**Subject files, read in full with `Read`:** collections.py 787 lines · achievements.py 515 · trophies.py 1974 · collector_trophies.py 663 · museum.py 1100 · ra_sync.py 209 · bonus_discs.py 416 · clz_import.py 661 · scrape_logs.py 239 · tools.py 1568 · wishlist_scraper.py 404 · achievement_linking.py 474.

**Already in my context when I started:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, RetroDB `CLAUDE.md`, the project's MEMORY.md index, and a git snapshot (clean tree, last commit 3a43bb1f). I did not read any tests or the git log. I read only the log viewer's code, never a scrape log.

**Where your brief and my lane file disagreed:** your brief said to prefer Ants slices. My lane file says to read the subject with `Read`. I read the subject with `Read` and used Ants verbs for cross-checks. The cross-checks were `log_manager.get_full_log_content`, `security.safe_path`, `database.query`, the tags schema in the migrations, and `docs/specs/auth.md` (`track_progress`).

### 1. Spec alignment
- **HIGH: per-user tag names fail with a 500.** `collections.py:167-181` claims each user's tag names are separate. But `migrations/scripts/001_baseline.py:313` still has `name TEXT NOT NULL UNIQUE COLLATE NOCASE`, and migration 005 only adds `owner_id`. So when a second user creates a tag name another user already has, the insert fails and they get "internal error". The same applies to `collections.py:301` (tag auto-create) and `:217` (rename). Fix: a migration making the unique key `(owner_id, name)`.
- **MEDIUM: year-only CLZ dates get a made-up day.** `clz_import.py:619-621` stores "2018" as `2018-01-01`. CLAUDE.md (PASS-59-207) says `release_date` holds only as much of a date as the source knows.
- **MEDIUM: failures returned as HTTP 200.** api-contracts §3.2 says no route does this. These do: `museum.py:600, 656, 660, 685, 692, 703, 726, 730, 740, 744`; `achievements.py:410`; `trophies.py:1696, 1775, 1808, 1830`.
- **MEDIUM: exception text reaches the user.** This breaks §13 / invariant 4. `trophies.py:191` and `:221` put the exception text (`%(error)s`) in the message, and it is returned at `:1107, :1326, :1808, :1879`.
- **LOW: museum docstrings say admin-only, but the route allows editors.** `museum.py:339, 482` versus `@editor_required` at `:480`.
- **LOW: collector-trophies docstring is out of date.** `collector_trophies.py:267-269` says achievement stats are library-wide. The code at `:313-335` counts them per user.
- **LOW: a second writer of RA link columns.** `achievement_linking.py:446` says `save_ra_link` is the only writer. `ra_sync.py:170-174, 199-200` also writes them, and leaves `ra_copy_fits` unchanged.

### 2. Weaknesses
- **HIGH: a full PSN sync overwrites manual links.** `trophies.py:1089` uses `COALESCE(excluded.linked_game_id, psn_games.linked_game_id)`, so any automatic match replaces a link the user set at `:1642`. The matcher is a loose substring test (`:1259-1263`, also `:426-429`), so "Doom" can link to "Doom Eternal", across PlayStation systems. Fix: keep the existing link first, or store a "set by hand" flag.
- **MEDIUM: controller images are saved under `config.STATIC_PATH`.** See `museum.py:332, 489, 529, 728`. `tools.py:1265-1267` itself says runtime media belongs under `IMAGE_PATH`, because the two folders differ in a frozen build. I did not check whether an update replaces `static/`.
- **MEDIUM: one GPU setting is forced for every AMD card.** `museum.py:882-883` sets `HSA_OVERRIDE_GFX_VERSION=10.3.0` for the whole process. That is wrong for AMD cards that are not RDNA2, and RetroDB ships to other people.
- **MEDIUM: Sony sign-in runs while holding the sync lock.** `trophies.py:1100-1107` calls `get_psn_client()` (network auth) inside `_psn_sync_lock`. Every user's status poll and the running worker's progress updates wait behind it.
- **MEDIUM: the PSN process-wide patch is not backed in this file.** `trophies.py:62-65` patches `pyrate_limiter` for the whole process so it never limits. The comment says a 2.5s delay between games makes up for it, but no such delay exists in `_run_psn_full_sync` (`:1226-1283`).
- **MEDIUM: one game's PSN sync blocks the request.** `trophies.py:1344` pulls the whole trophy-title list to find one game, and `:1525` downloads every trophy icon one at a time.
- **MEDIUM: the duplicate finder can delete shared disc tracks.** In hash mode, identical bytes count as duplicates (`tools.py:976-978`). An identical audio-track `.bin` shared by two releases can be deleted, which breaks the other release's `.cue`. Deleting also leaves `games.rom_path` pointing at a missing file (`:1196-1198`).
- **MEDIUM: wishlist items can get stuck on "scraping".** In the bulk path, an exception after `_set_status('scraping')` is logged but the status is never reset (`wishlist_scraper.py:391-392`). Scrape-all never picks up "scraping" items again (`:374-385`), and a server restart leaves the same state. Nothing stops two scrape-all threads running at once.
- **LOW:**
  - The screenshot-dedup delete does not check that a filename belongs to that game, and does not require keeping one copy (`tools.py:1519-1557`).
  - Task logs include exception text and are readable by any signed-in user (`tools.py:96, 938, 1128`).
  - Tag and list names, colours and `sort_order` are not validated; a `null` name causes a 500 (`collections.py:204-205, 448-451`).
  - Renaming a wishlist item skips the duplicate check that adding does (`:689`).
  - Bonus-disc linking allows a disc to be its own parent, or a loop (`bonus_discs.py:179-204`).
  - `ra_rom_name` splits paths only on `/` (`achievement_linking.py:396`). I did not check whether Windows builds store backslashes.

### 3. Gaps
- **MEDIUM: non-admins can never refresh their RPCS3 trophies.** The cache at `trophies.py:353-355` is cleared only by `api_scan_trophies`, which is admin-only and uses the admin's own path (`:509-514`). Other users see stale data until the server restarts.
- **MEDIUM: titles with no Latin letters all look the same to the CLZ import.** `clz_import.py:30-46` turns a Japanese-only title into an empty string. All such titles then match each other, and every one after the first is skipped as already existing (`:536-537, :600`).
- **LOW:**
  - The CLZ "parse" (preview) step already creates system rows before the user confirms (`clz_import.py:473-486`).
  - Auto-link marks again a disc the user un-marked (`bonus_discs.py:136, :387`).
  - Wishlist images named `w{id}` are not removed when the item is deleted (`collections.py:734`).
  - Editors can start ROM-tool scans but cannot pause or cancel them (`tools.py:395, 418, 438`).
  - Trophies removed from the definitions still count toward rank (`collector_trophies.py:530-534`).

**Checked and found nothing:**
- Log-viewer path traversal: `log_manager` guards it.
- `safe_path` resolves symlinks before its check.
- Ownership scoping in collections.
- SSRF pinning in the museum image fetch.
- RA title-matching logic.

**Open questions:**
- `ra_sync.py:50-68` and `achievements.py:367-386` answer `queued=True`, but nothing server-side holds a queue. Does the client run it?
- Does the log viewer remove credentials before sending a log?
- `collector_trophies.py:341-345` does not filter by source, unlike the earned count at `:316-321`. Is that intended?

**Top 3 priorities:**
1. Fix the tags unique key.
2. Stop the PSN sync overwriting manual links.
3. Move controller images to `IMAGE_PATH`, and stop the wishlist "scraping" status getting stuck.

---

## Lane 11 — Core app, i18n & shared utilities

## Subsystem: Core app, i18n & shared utilities

**Subject line counts, from my own native `Read` of each file (the number is the last numbered line):** app.py 2094 (the harness reported 2095), config.example.py 2096 (the harness reported 2097), server_port.py 143, log_manager.py 385, platform_utils.py 68, routes/__init__.py 1, services/api_helpers.py 84, services/template_filters.py 125, services/formatters.py 45, services/game_utils.py 1653 (the harness reported 1654), services/analytics.py 792, services/assets.py 67, services/i18n.py 96, services/i18n_labels.py 97, services/service_stop_text.py 28. I read all of them in full.

**Already in my context when I arrived:** the global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index (MEMORY.md), and a git snapshot (clean `main`, with recent commits including "Translations: every screen message in all 20 languages (PASS-59-113 step 7)"). `.claude/rules/ratings.md` loaded automatically while I was reading.

**How I worked:** `workspace_search` hit its rate limit, so I used `Grep` instead. I did not open `config.py`. Outside the subject files I opened only `docs/specs/i18n.md` (searched, not read in full), `routes/scrape_logs.py` around its `get_log_content` call, and the `extract_filename_hints` call sites in `routes/games_search.py` and `services/jobs/bulk_scrape.py`.

### 1. Spec alignment
- **Confirmed sound:** the self-updater hand-off really is first (app.py:8-14). The asset cache-busting (per-file hash with an `APP_VERSION` fallback) matches CLAUDE.md (assets.py:53-67).
- **Not a finding:** a browser asking for `Accept-Language: eo` gets the pseudolocale even for a non-admin (app.py:222). The spec documents this on purpose (i18n.md line 199).
- **MEDIUM — on-screen text not marked for translation.** This contradicts CLAUDE.md step 8 and the "every screen message" commit. Examples:
  - the dashboard's recovery-banner descriptions and its Resume/Start labels (app.py:1368-1410);
  - the job-route errors (app.py:1475, 1489, 1492, 1496, 1519);
  - the setup-route errors and "Setup complete!" (app.py:1627, 1665, 1669, 1673, 1772, 1777);
  - the CSRF message (app.py:811, 814), the 404/500 envelopes (app.py:672, 682), and the dashboard and analytics 500 text (app.py:1425, 1545);
  - "Unknown" in formatters.py:40.
- **LOW — a comment contradicts the code.** app.py:748-751 says the CSP "ships in report-only mode", but it is enforcing (app.py:536-556).
- **LOW — docstrings that are wrong.** game_utils.py:1400 says "Mega Man X2" becomes "X02". The pattern at :1427 and the `\b` at :1438 leave it as "X2". game_utils.py:607 says "all 8 regional ratings"; there are 9.

### 2. Weaknesses
- **MEDIUM — any import of `app.py` marks running jobs as interrupted.** app.py:1858-1867 does this whenever `DEBUG_MODE` is off. If a second process imports `app` while the server is running, it flags the live server's jobs as interrupted. It also installs SIGTERM/SIGINT handlers in that process.
- **MEDIUM — possible changelog crash on Windows (not verified).** The changelog files are opened without `encoding=` (app.py:1557, 1567), and `changelog.yaml` contains 1128 non-ASCII characters. On Windows Python before UTF-8-by-default, `/changelog` would fail to decode. I did not check which Python the Windows build uses or whether it sets UTF-8 mode. The same pattern appears at app.py:958, 1187, 1719.
- **MEDIUM — category logs get duplicate lines.** `rom_tools` loggers (`scraper.rom_tools`, `scraper.scan_roms`) and `image_resize`'s `services.jobs.image_resize` keep propagating up to `scraper` / `services.jobs`. Those parents carry the `scraping` handler, so the records are also written to the scraping log. `propagate=False` is set only when the parent is in the same category (log_manager.py:255-258).
- **LOW — the setup wizard is open before setup finishes.** `setup_api` has no login and no CSRF check (app.py:800-804, 1653). Until setup completes, anyone on the network can rewrite the admin's username and password (app.py:1690-1694). `timezone` is not checked against the real zone list (app.py:1763). `.strip()` on a non-string value gives a 500 (app.py:1676, 1739). The raw sqlite connections have no try/finally (app.py:1684-1703, 1758-1766).
- **LOW — double-click resume.** `resume_job` has no guard, so two quick clicks can start the same job twice (app.py:1467-1498).
- **LOW — the gzip check is a substring match.** `gzip;q=0` still gets gzipped (app.py:590).
- **LOW — sessions can reset on every restart.** If the secret key cannot be written, a new one is made each start and everyone is signed out, with nothing logged (app.py:139-143).
- **LOW — heavy reads on every request or log line.** The full changelog YAML is parsed on every request, including each "Load More" (app.py:1557-1570). `available_locales()` globs the disk on every call (i18n.py:49-50). `CategoryFileHandler.emit` loads the settings for every log record (log_manager.py:193).

### 3. Gaps
- **MEDIUM — wrong manufacturer in Analytics.** The manufacturer map is missing ES-DE folder names that config uses. `atarilynx`, `atarijaguar`, `sg-1000`, `sfc` and `n64dd` all show as "Other" (formatters.py:8-27 against config.example.py:215-384). `SYSTEM_SPECS[...]['manufacturer']` already holds this data, so there are two sources that disagree.
- **LOW — "Recently scraped" misses re-scrapes.** It only looks at the 20 newest games by id. An older game scraped again today never appears (app.py:1318-1339).
- **LOW — `stop_sentences([])` returns every service, not none.** service_stop_text.py:13. Its times use the server's local clock, not the user's time zone (:19).
- **LOW — `(UK)` would be taken as a publisher.** `(UK)` and comma-joined regions are missing from `_KNOWN_NON_PUBLISHER_TAGS` (game_utils.py:95). This does no harm today: both callers read only `year`.
- **LOW — numbers and sizes ignore the user's language.** `format_number` always uses a space as the thousands separator, and `format_size` uses English units (template_filters.py:32-45).

**Summary — top 3 priorities**
1. Mark the remaining on-screen strings in app.py for translation, since v4 claims full coverage.
2. Stop a plain `import app` from marking jobs interrupted (app.py:1858).
3. Add `encoding='utf-8'` to the changelog and JSON reads in app.py (Windows risk, not verified), and fix the duplicate lines in the category logs.

---

## Lane 12 — Frontend JavaScript

## Subsystem: Frontend JavaScript (`static/js/*.js`, bundles and vendor excluded)

**What I read.** I read two files in full with `Read`: `game-launch.js` (198 lines) and `launch-indicator.js` (112 lines). I read only slices of four others: `toast-controller.js` lines 240–349 and 560–787, `game-modals.js` lines 340–358 and 1295–1316, `all-games-controller.js` lines 600–680, and `rom-tools.js` lines 395–440. I did not open the other 22 source files at all.

**One conflict I settled.** My lane file says to read the whole subject. The subject is over 16,500 lines across 28 files, and your brief asks for slices. I followed the brief and covered the rest with pattern searches across every source file (risky `innerHTML`, timers, `t()` usage, hard-coded strings, ARIA attributes). So for the unopened files, "nothing found" only means those searches found nothing. It is not a statement that the code is sound. `workspace_search` hit its rate limit partway through, and I used `Grep` for the remaining searches.

**Already in my context on arrival:** the global `CLAUDE.md`, `/mnt/Games/CLAUDE.md`, the RetroDB `CLAUDE.md`, the RetroDB memory index, and a git snapshot (branch main, clean, last commit 3a43bb1f). `.claude/rules/js-template-contracts.md` loaded while I worked.

### 1. Spec alignment
- **MEDIUM — the Library card text is not translated.** `all-games-controller.js:621-651`. The card labels Genre, Series, Developer, Publisher and Year are hard-coded English, as is the tooltip "Click to filter, Shift+click to exclude". So are these badge tooltips: "Bonus/Extra Disc", "Has N bonus disc(s)" (with English plural logic), "CLZ Import (No ROM file)", "Steam Import", "Xbox Import", "PSN Import", "Has RetroAchievements", and "(cross-mapped)" at :669. CLAUDE.md step 8 requires every user-facing string to go through `t()`. This card appears on both `/games` and `/system/<id>`. Fix: wrap each in `t('...')`.
- **Confirmed:** `t()` is only ever called with string literals. The only non-literal match is its own definition at `utils.js:103`.
- **LOW — stale comment.** `game-launch.js:196` says "Expose for the inline onclick attribute". The CSP contract forbids inline `onclick`. Fix: update the comment.
- **LOW — native dialog.** `game-launch.js:134` uses the browser's `confirm()` rather than the project's `showConfirm`. That breaks the theming and focus contract. Fix: use `showConfirm`.

### 2. Weaknesses
- **MEDIUM — job-end logic in the toast poller can never run.** `toast-controller.js:709-738`. `updateToasts` (called at :709) sets `activeOperations[type] = isActive` at :771. `pollStatus` then reads that same value back as `wasActive` at :714. So `wasActive` always equals `isActive`, and the branches at :721, :725 and :735 (which all need "now inactive, was active") never fire. Effects:
  - Other browser tabs never get the `job-completed` message.
  - The 5-second "server restarted, wait for auto-resume" poll is dead code.
  - A toast left showing after a server restart keeps polling at 2 s with no end.

  Fix: read `wasActive` before calling `updateToasts`.
- **LOW — open modals lose their faster refresh.** `toast-controller.js:645` sets a 1.5 s poll while a modal is open. The next poll that finds `!wasActive` calls `_startActivePolling` (:717), which replaces it with 2 s.
- **MEDIUM — card filter links cannot be used from the keyboard.** `all-games-controller.js:637-648`. The `meta-clickable` spans have click handlers but no `tabindex`, no `role="button"` and no key handler. Keyboard and screen-reader users cannot reach them. Fix: use `<button>`, or add `tabindex="0"`, a role and an Enter handler.
- **LOW — play screen does not hold focus.** `game-launch.js:64-97`. It is marked `role="dialog"` and `aria-modal`, but it does not use `ModalFocusTrap`, so Tab can move behind it.
- **LOW — launch list popover is mouse-only.** `launch-indicator.js:60-95`. Escape does not close it, focus is not moved into it, and a click outside does not close it.
- **LOW — untranslated fallback name.** `launch-indicator.js:78`: `game #… (pid …)`.
- **LOW — values inserted without escaping.** `game-modals.js:354` and `:1313` put `completion_status` into a class name and label without escaping. `all-games-controller.js:662,667` put `r.image` / `ageRating.image` into `src` without escaping. These rely on the server sending clean values, which is a small risk on a LAN-only, one-household app. Fix: `esc()`.

### 3. Gaps
- **LOW — core download wait has no time limit and can fake success.** `game-launch.js:32-41`. `waitForCore` loops with no timeout. If the status endpoint returns an error page, its body parses to `{}`, the core counts as finished, and the user sees the confusing "core installed but game still cannot start" message (:165).
- **LOW — a failed Kill says nothing.** `launch-indicator.js:49-57` swallows the error; the user only notices the game is still listed.

### Summary: top 3
1. Fix the `wasActive` ordering in `toast-controller.js:709-714`. It silences cross-tab completion messages and the server-restart handling.
2. Translate the Library card labels and tooltips in `all-games-controller.js:621-669`.
3. Make the card filter links keyboard-usable (`all-games-controller.js:637-648`), and trap focus on the play screen (`game-launch.js:64`).

**Open question:** in the 22 files I did not open, the rest of `toast-controller.js`, and the parts of `game-modals.js` and `all-games-controller.js` outside the slices above, I have checked only these patterns: risky `innerHTML`, timers, `t()` usage and hard-coded strings. A full pass would need those files assigned to more lanes.

---

## Lane 13 — Templates & CSS

## Subsystem: Templates & CSS

**Line counts:** I did not read any subject file in full. The scope is the whole `templates/` tree plus every `static/css/` source file, which is too large for one lane. I ran targeted searches, then read slices around each hit, so this was a search-led depth pass, not a full read. "Nothing found" below means my search found nothing. It does not mean the area is sound.

**Present on arrival:** global `~/.claude/CLAUDE.md`, `/mnt/Games/CLAUDE.md`, RetroDB `CLAUDE.md`, the RetroDB memory index, and a git snapshot (clean `main`, latest commit 3a43bb1f). I did not open `.claude/rules/js-template-contracts.md` or `RETRODB_DESIGN_STANDARDS.md` §7; I worked from the CLAUDE.md summaries of them.

**Precedence:** none of the brief's rules conflicted with the lane file.

### 1. Spec alignment

- **MEDIUM — the theme spec overclaims.** `docs/specs/themes.md:405-406` says every component already uses the colour variables, so a theme re-skins the whole UI. It does not:
  - 530 literal `rgba(` colours and 184 hex colours sit outside `variables.css` and `themes.css`.
  - The worst files are `pages/game-list.css` (for example lines 1086-1099) and `components/badges.css:118-290`.
  - Fixed dark backgrounds, e.g. `pages/pages.css:292,304`, do not change with the theme.
  - Many focus rings are hard-coded cyan `rgba(76,201,240,…)`, e.g. `forms.css:44`, `buttons.css:166`. Under the Matrix, Amber and Cathedral themes they stay cyan.
  - This also breaks CLAUDE.md's "no hardcoded colors" rule.
  - Fix: move these to tokens, or change the spec claim.
- **LOW — sticky bar with no `top`.** `pages/pages.css:2097` (`.museum-nav`) sets `position: sticky` with no `top`, so it never sticks. CLAUDE.md requires `top: var(--sticky-top)` on page-level sticky bars.
- **LOW — leftover old stylesheet.** `static/css/main.css:657,4029,4108` has page-level sticky bars at `top: 0`. `build_css.py` does not build this file. If nothing loads it, it is dead and misleading; I did not check whether anything does.
- **LOW — setup page skips the path-box macro.** `setup.html:146-147,185,192` uses its own Browse buttons, not `browse_button()`. It may be on purpose (the macro shows for admins only, and setup runs before any admin exists), but nothing documents it.
- **Nothing found** on these contract checks:
  - Placement of `needs_games_bundle` and `adaptive_layout`: all were before the first `{% block %}`, including `achievements_system.html:2,6`.
  - Every adaptive page has a `page-box`.
  - No bare `%` inside a `_()` msgid.
  - No `t('…')` inside a template `<script>`.
  - The help pages have the same number of `id=` and `href="#…"` anchors in all 21 copies. I compared counts, not the values.

### 2. Weaknesses

- **MEDIUM — untranslated text a user will see:**
  - `base.html:841-880`: the whole job-queue panel ("Running", "Demote", "Cancel this queued scrape", and so on).
  - `setup.html`: almost all placeholders and buttons, e.g. lines 114-275 (only 7 `_()` calls in the file).
  - `tags.html:43,49,54-63,417-418`.
  - `list_detail.html:65,93,98` and `compare_games.html:180,185`.
  - `rom_tools_settings.html:344,363-364`.
  - `game_detail.html:5369,5678`.
- **MEDIUM — unescaped HTML in the queue panel.** `base.html:842,868` puts `system_name` into an HTML template string without `escapeHtml`, while other templates do escape. The risk is low on a LAN, but the pattern is inconsistent.
- **MEDIUM — weak keyboard focus, a problem for a partially sighted user:**
  - `game-modals.css:487-490`, `tags.css:240-243,265-268`, `game-list.css:376/405`, `filters.css:80-83`, `forms.css:251-254`, `trophies.css:235-238`: focus only changes a 1px border colour. Several of these give hover the same style, so focus cannot be told apart from hover.
  - `launch-indicator.css:112-114` removes focus styling completely.
  - There is no global `:focus-visible` rule in `core/`.
- **LOW — screen readers:**
  - The tag colour swatches (`tags.html:54-63`) have a title only. They have no `aria-label`, and their selected state (the `.active` class) is never announced (`aria-pressed`).
  - The trophy images use `alt="P"`, `"G"`, `"S"`, `"B"` (`local_trophies.html:144-156` and the same pattern in `psn_trophy_detail.html` and `local_trophy_detail.html`).

### 3. Gaps

- **MEDIUM — no right-to-left support.** Hebrew is a shipped language (`i18n.md:438`), but `base.html:2` sets no `dir="rtl"`, and the CSS has no `[dir]` or `:dir()` rules. Fix: emit `dir` for right-to-left locales.
- **LOW — help section missing from the contents list.** `help.html:559` (`#emulators-play`) has no entry in the table of contents (`help.html:18-55`).

I did not check behaviour at 375px; that needs a browser, not a code read.

**Top 3 priorities:** the unthemed hard-coded colours and focus rings; weak or missing focus indication; the untranslated queue panel, setup page and tag pages.

---

## Lane 14 — Tests, tooling, CI/CD, installers

## Subsystem: Tests, tooling, CI/CD, installers

**Lines read in full:** `tests/conftest.py` 161, `.github/workflows/ci.yml` 291, `release.yml` 258, `dependabot-lockfile.yml` 89, `scripts/ci_local.sh` 295, `pyproject.toml` 97, `.pre-commit-config.yaml` 25, `requirements.txt` 51, `tests/test_ci_gate_parity.py` 81, `tests/test_media_path_isolation.py` 56.
**Read in part:** `test_pass46_frozen_paths.py` lines 25–134, `test_server_port.py` 180–239, `test_retroarch_detect.py` 85–139, `test_emulator_autodetect.py` 80–109, `build_dist.py` 45–59.
**Searched only (grep):** installer lockfile fallback, test writes to settings files, test network calls.
**Not opened:** `install*.py` bodies, `.semgrep.yml`, `.gitleaks.toml`, most of `tests/`. This is a partial depth pass, so I certify nothing about the files I did not open.

**Already in my context when I started:** the global and project `CLAUDE.md`, the RetroDB memory index (it includes "test-media-isolation" and "bare-import-app-touches-real-db"), a git snapshot (clean tree on main, five recent commit titles), and `.claude/rules/git-hooks.md` and `distribution.md`, which loaded during the run.

### 1. Spec alignment

- **MEDIUM. `dependabot-lockfile.yml:7-9`, `:47-50`, `:18-19`.** The header says the Dependabot PR "goes green on its own". But a push made with `GITHUB_TOKEN` starts no new workflow run. So the new head commit gets no CI run, and the PR does not turn green by itself. Lines 18–19 say `pull-requests: write` is for a `gh` re-run call, and no such call exists. Fix: push with a token that can start workflows, or drop the claim and the extra permission.
- **LOW. `pyproject.toml:3`.** It says the lock is "generated by `pip-compile`". It is now built with `uv pip compile` (`ci_local.sh:232`).
- **LOW. `release.yml:76-77`.** The comment names the retired `/mnt/Storage` as the default staging path. `build_dist.py:53` now uses `/mnt/Games/...`.
- **LOW. `ci_local.sh:290`.** The failure message tells the reader to override with `git push --no-verify`. The script's own header (`:30-31`) and `git-hooks.md` say skipping needs the user.

### 2. Weaknesses

- **HIGH (safety). `tests/conftest.py:31`, `:47`.** Outside pytest-xdist, conftest keeps any `RETRODB_DB_PATH` or `RETRODB_IMAGE_PATH` already set in the shell. `CLAUDE.md` step 5 runs plain `python3 -m pytest`, which does not use xdist. A shell that exports the live paths would therefore point tests at the real DB or media. `test_media_path_isolation.py:26-30` checks only that config matches the environment variable, not that it is a temporary directory, so it would still pass. Also, the `STATIC_PATH` override (`:54`) is guarded by the `IMAGE_PATH` variable alone. With only `RETRODB_IMAGE_PATH` set, `static/` and `static/videos` stay real. Fix: always mint the temporary directories under pytest, or refuse any path outside the temp root.
- **MEDIUM (live data). `conftest.py` as a whole.** `settings_manager.SETTINGS_FILE` and `SCRAPER_SETTINGS_FILE` have no environment override, and conftest does not redirect them. `test_server_port.py:187-201` admits that it reads the operator's real `data/settings.json`. `admin_test_client` (`conftest.py:151`) stubs `load_settings` but not `save_settings`. A route test that reaches `routes/settings.py:655` (or `:522`, `:600`) would write the stub `{'setup_completed': True}` over the real file. My search found no test doing this today, so the risk is latent. Fix: redirect both files to temp in conftest.
- **MEDIUM (supply chain).** These installs have no pinned version:
  - `release.yml:64` (`cyclonedx-bom`) and `release.yml:158` (`pyyaml`), in a job holding `contents: write` and `id-token: write`;
  - `dependabot-lockfile.yml:66` (`uv`), with a token left in `.git/config` that can write.

  `requirements-ci.txt` pins with `==` but has no hashes (`ci_local.sh:92`).
- **MEDIUM. `release.yml:3-5`.** A tag push builds and signs a release with no test or gate step, and nothing requires CI to have passed on that commit.
- **LOW. `release.yml:120-123`.** The verification comment advises `--certificate-identity-regexp '.*'`. That accepts a signature from any GitHub Actions workflow, which defeats the signature.
- **LOW. `ci_local.sh:205`.** Semgrep uses the live registry rule packs (`p/...`), so its verdict can change with no change in the code.
- **LOW. `ci_local.sh:168`.** The import smoke isolates only the DB path, not the media paths.

### 3. Gaps

- **MEDIUM.** The staged-tree rule in `CLAUDE.md` (`git stash --keep-index`) has no enforcement in the pre-commit stage (`.pre-commit-config.yaml` runs only ruff and gitleaks). It is partly covered by the pre-push fresh-checkout run, which `git-hooks.md` describes; I did not open that hook.
- **LOW.** `release.yml:145`: on `workflow_dispatch`, `GITHUB_REF_NAME` is the branch name, so the release notes say "No changelog entry found". `distribution.md` acknowledges this, and `release-standalone.sh` fixes it afterwards.

### Open questions

- I did not settle whether `GITHUB_TOKEN` on Dependabot-triggered `pull_request` runs honours the elevated `permissions:` block. If it does not, the push at `dependabot-lockfile.yml:88` fails outright.

### Summary: top 3

1. Make conftest always isolate the DB, images and static paths under pytest, ignoring inherited variables (HIGH).
2. Redirect `SETTINGS_FILE` and `SCRAPER_SETTINGS_FILE` in conftest (MEDIUM).
3. Pin the tool installs in `release.yml` and `dependabot-lockfile.yml`, and add a gate step to the release workflow (MEDIUM).

---

## Lane 15 — Game launching, emulators, player install, cheats, self-updater

## Subsystem: Game launching, emulators, player install, cheats, self-updater

**Line counts as read.** Read in full: `updater_apply.py` (455), `services/updater.py` (576), `services/cheats.py` (624), `services/launch_resolver.py` (655), `services/player.py` (349), `services/player_install.py` (242), `routes/launch.py` (332), `routes/cheats.py` (94), `routes/updates.py` (73), `services/retroarch_command.py` (46).

Read in part:
- `services/player_cores.py`, lines 128–207 and 340–539.
- `services/standalone_settings.py`, lines 120–449.
- `routes/launch_settings.py`, lines 55–134.

Searched only, not read: `routes/emulators.py` (decorators and inputs) and `services/emulator_adapters.py` (`_ini`, `_under`, `retroarch_cfg`, `retroarch_path`).

**Not opened at all: `services/emulator_seeder.py`.** I make no claim about it or about the unread parts of the other files.

**One conflict, and how I settled it.** The review-lane rules say to read every subject file in full; the brief says to save tokens. With 16 files I read the security-relevant ones in full and the rest in part, as listed above.

**Already in my context on arrival:** the global `CLAUDE.md`, `/mnt/Games/CLAUDE.md`, RetroDB's `CLAUDE.md`, the MEMORY.md index, and a git snapshot (clean `main`, recent commits on PASS-59-113 and PASS-59-155).

### 1. Spec alignment

- **MEDIUM — the protected-path list depends on the user's RetroArch, and nothing guards its main settings file.** CLAUDE.md says a sign-in token never reaches "the base cfg". `_PROTECTED_KEYS` (`services/player.py:58-66`) only filters what `after_session` copies into a game's record (`player.py:328`, `player.py:341`).
  - The token sits in the run layer, which is loaded on top of the main file (`player.py:277-285`, `player.py:293`).
  - RetroArch's menu "Save Current Configuration" writes the whole merged config into the `--config` file, `data/player/retroarch.cfg`. This is what RetroArch does in general; I did not test it here.
  - `_set_keys(base, keys)` (`player.py:268`) never removes `cheevos_*` lines. A saved token would stay in the base file for every later launch, including another user's or a signed-out one.
  - Fix: strip the `cheevos_*` keys from the base file in `_set_keys` before each launch.
- **LOW — the standalone build's version is never checked.** `validate_tree` checks it for source installs only (`services/updater.py:311-321`). Spec §4.4 asks for the same. The `/health` version check (`updater_apply.py:411`) catches it later, at the cost of a full swap and rollback.
- **LOW — `/api/updates/dismiss` is missing from spec §6.** The route exists at `routes/updates.py:68`.
- **Matches the spec, checked:**
  - the protected-path set (`updater_apply.py:34-41` against spec §5.2);
  - INV-4, an emulator's own cheat file is never overwritten (`cheats.py:566`);
  - INV-7, a zip entry cannot escape its folder (`cheats.py:187-189`);
  - INV-10, a client's `source` must be one of the game's lists (`cheats.py:458`).

### 2. Weaknesses

- **MEDIUM — a helper that fails early leaves RetroDB stopped.** The old app shuts itself down unconditionally (`updater.py:518`). The helper then returns without restarting anything, and without writing a status file, when:
  - the plan version is not the one it knows (`updater_apply.py:387-389`), which is the cross-version case CLAUDE.md warns about;
  - a plan key is missing, or the `rmtree`/`makedirs` at `updater_apply.py:397-398` raises, before the `try`.

  Fix: wrap the whole of `apply()` and restart `restart_argv` on any early exit.
- **MEDIUM — a sign-in token can be left on disk.** `run/<token>.cfg` holds the RetroAchievements token and is deleted only in `after_session` (`player.py:349`). A crash, a kill, or an update restart during a session leaves it there. Nothing sweeps `data/player/run/`. Fix: clear stale run files at startup.
- **LOW — two player launches at once can both get through.** The one-session check is check-then-act with no lock (`routes/launch.py:87-92`).
- **LOW — no scan-root check when `rom_path` is empty.** With the setting unset, the ROM check is skipped entirely (`launch_resolver.py:469-477`).
- **LOW — the command port is open to the network.** The run layer turns network commands on for `.m3u` games and on macOS/Windows (`player.py:278-279`). The comment at `player.py:47-48` says official RetroArch listens on every interface, so other machines on the LAN can send it commands during a session. This is acceptable under the LAN-only threat model, but it is not stated.
- **LOW — writing an emulator's settings file has rough edges.** `write_lines` (`standalone_settings.py:281-287`):
  - leaves its temp file behind if the write fails;
  - replaces a symlinked settings file with a plain one;
  - takes `mkstemp`'s 0600 permissions instead of keeping the file's own.

  Separately, `_read_lines` reads strict UTF-8 (`standalone_settings.py:391`), so a non-UTF-8 ini file makes the Cheats panel fail with a 500.
- **LOW — core downloads are checked by CRC32 only.** The check is `player_cores.py:419`, taken from the index on the same host. That protects against corruption but does not authenticate the file. RetroArch itself and 7-Zip are pinned by SHA-256 (`player_install.py:45-59`), which is good.
- **LOW — the pack index file is written in place.** `sources.json` is written non-atomically (`cheats.py:214`). Two downloads of the same pack would share the `.{pack}-old-{pid}` folder name (`cheats.py:204`).

### 3. Gaps

- **LOW — cheat changes can be taken back from the wrong game.** `take_back` picks up a `.cht` with the ROM's file name from any core's folder (`cheats.py:501-502`). A copy left behind by a failed earlier session of another game with the same file name could replace this game's list.
- **LOW — the cheat path does not catch every error.** `place_for_launch` and `take_back` catch `OSError` only (`cheats.py:491`, `cheats.py:508`). A `ValueError` or `KeyError` from `library_name` would break INV-11 ("a cheat problem never stops a launch"). I did not confirm that `library_name` can raise.

Nothing found, within what I read, on:
- shell injection in launch arguments: the template is split once and no value is split again (`launch_resolver.py:436-445`);
- zip-slip in updates, cheat packs or shader packs (`updater.py:272-295`, `player_cores.py:455-457`);
- updater URL restrictions (`updater.py:147`);
- updater checksum handling (`updater.py:368-374`).

### Top 3 priorities
1. Make the updater helper always restart something on an early exit (`updater_apply.py:385-398`).
2. Keep `cheevos_*` keys out of the player's base `retroarch.cfg` (`player.py:268`).
3. Clear stale run-layer token files at startup (`player.py:281-285`, `player.py:349`).
