# PASS-59-66 — Trophies and achievements: per-user progress across five sources

**Status:** accepted (2026-10-17).
**Kind:** docs.
**Source:** ROADMAP PASS-59-66 (review-code sweep 2026-09-01: the trophies
findings had no statement of intent to judge against).
**Pairs with:** [`rom-tools.md`](rom-tools.md), the other spec filed under the
same item. **Related:** PASS-59-58 (empty PSN reply), PASS-59-110 (RA sequel
matching), PASS-59-63 (RPCS3 parser guards).

Layman: this is the rulebook for the achievements and trophies pages — where
each platform's progress comes from, how a game in your library is matched to
it, and how one person's progress and logins are kept apart from another's.

This spec was written after the code. It records the behaviour the code has
today, so a reviewer can tell a defect from a design choice. Each invariant
names the test that pins it, or says none does.

Cross-references:

- [`auth.md`](auth.md) § 5 owns the per-user data rule. This spec lists the
  trophy tables it covers and where they depart from it.
- [`jobs.md`](jobs.md) owns the job lifecycle: singleton lock, persistence,
  cancel, resume. This spec covers only what each trophy job reads and writes.
- [`settings.md`](settings.md) owns `user_settings` and
  `data/scraper_settings.json`, where the platform keys live.

## 1. Goal

One statement of where each platform's progress comes from, which data is
per user and which is shared, how games are linked, and what a sync keeps
when the platform sends nothing. A reviewer can then judge a finding against
intent.

## 2. Problem

1. Five sources write progress through different code paths: RetroAchievements
   (RA), PSN, Steam, Xbox, and RPCS3 trophy files on disk.
2. A cross-user leak was fixed once (Pass 27.2 tokens, Pass 31.x `user_id`),
   but nothing stated which data must stay per user.
3. An empty upstream reply wiped stored PSN counts (PASS-59-58). Other paths
   have the same shape and nothing said what should survive.

## 3. Scope decisions (agreed with the user)

- **Document, don't redesign.** Behaviour that looks wrong is recorded under
  §13 Open, not changed here. Decided in PASS-59-66's Plan.
- **Collector trophies** (`routes/collector_trophies.py`) are RetroDB's own
  badges, not a platform. They appear only where they read platform data.
- **Filename without the id**, as the dispatching session asked; see
  [`rom-tools.md`](rom-tools.md) §3.

## 4. Design

### 4.1 Sources

| Source | Pages and API | Upstream | Progress stored in |
|---|---|---|---|
| RA | `routes/achievements.py`, `routes/ra_sync.py` | RA Web API (`scraper/retroachievements.py`) | `game_achievement_progress` |
| PSN | `routes/trophies.py` (`/psn-trophies`, `/api/psn/*`) | `psnawp_api` | `psn_games`, `psn_trophies`, `psn_sync_status` |
| Steam | `routes/steam_achievements.py` | Steam Web API (`scraper/scrape_steam.py`) | `game_achievement_progress`, `steam_achievements` |
| Xbox | `routes/xbox_achievements.py` | Xbox Live (`scraper/scrape_xbox.py`) | `game_achievement_progress`, `xbox_achievements` |
| RPCS3 | `routes/trophies.py` (`/trophies`) | `TROPCONF.SFM` and `TROPUSR.DAT` files | nothing; the in-process `_trophy_cache` |

`routes/platform_import.py` also carries the Xbox sign-in, PSN library import,
and a second set of Steam and Xbox sync routes.

### 4.2 Per-user and shared data

**Per user** (each table has a `user_id`, and its unique key includes it):

- `user_platform_tokens` — key `(user_id, platform)` (migration 006, Pass 27.2).
- `psn_games` — `UNIQUE(npwr_id, user_id)`; `psn_trophies` hangs off the
  per-user `psn_games.id` (migration 007, Pass 31.1).
- `psn_sync_status` — one row per user.
- `game_achievement_progress` — `UNIQUE(game_id, user_id)`;
  `steam_achievements` and `xbox_achievements` include `user_id` in their
  unique keys (migration 009, Pass 31.2).
- `collector_trophies` — key `(id, user_id)` (migration 008, Pass 31.3).

Reads filter on the caller: `gap.user_id = ?` in the RA, Steam and Xbox
routes, `user_id = ?` in the PSN routes. Deleting a user removes these rows
(`routes/auth.py::_delete_user_and_owned_rows`).

**Shared by every user:**

- The link columns on `games`: `ra_game_id`, `ra_achievement_count`,
  `ra_points`, `has_retroachievements`, `steam_app_id`, `xbox_title_id`.
- PSN trophy images under `static/images/trophies/<npwr_id>/`, which the
  RPCS3 pages also use.
- `_trophy_cache` for RPCS3, keyed by trophy folder path.
- The RA account the background RA jobs use (§4.4).

`game_achievement_progress` holds one row per game and user, whatever the
source. Its `source` column is whichever sync wrote last.

### 4.3 Linking games to platform titles

- **RA.** By title, never by hash. `services/achievement_linking.py::match_ra_game`
  (refresh job) and `scraper/retroachievements.py::search_game_by_name`
  (scraper and the single-game refresh route) normalise titles and compare
  word sets. A sequel number must agree: `canonical_ra_word` folds `II` and
  `02` to `2`, and `ra_sequel_numbers` must match on both sides
  (PASS-59-110). RA has no manual link endpoint.
- **PSN.** The full sync matches the title with
  `clean_title_for_matching` — exact on the platform's folder, then exact
  across PlayStation folders, then substring. An existing link is never
  cleared by a sync (`COALESCE(excluded.linked_game_id, ...)`). Editors can
  set or clear a link with `POST /api/psn/link-game`, scoped to their own row.
- **Steam and Xbox.** Through `games.steam_app_id` and `games.xbox_title_id`,
  set at import (`routes/platform_import.py::_check_duplicate` matches on the
  platform id, then on `normalize_title_for_dedup` within the system).
- **RPCS3.** `routes/trophies.py::find_matching_game` matches at page render
  through an alias table and the same three passes as PSN. Nothing is stored.

### 4.4 Sync and refresh

All job classes follow [`jobs.md`](jobs.md): an in-process guard, a
cross-process `flock` named after the job, persisted progress and resume.

| Job | Started by (role) | Credentials | Writes |
|---|---|---|---|
| `RARefreshJob` (`ra_refresh`) | `/api/refresh-retroachievements[/<system_id>]` (admin) | global RA account (`_get_ra_credentials`) | `games` RA columns; commits per game |
| `RASyncJob` (`ra_sync`) | `/api/achievements/sync-system/<id>` (editor) | global RA account | `games.ra_achievement_count`; the caller's `game_achievement_progress` |
| `PSNRefreshJob` (`psn_refresh`) | `/api/psn/bulk-refresh/start` (login) | the caller's NPSSO | the caller's `psn_games`, `psn_trophies` |
| `SteamSyncJob` (`steam_sync`) | `/api/steam-achievements/sync-all`, `/api/steam/sync-achievements` (editor) | caller's `user_settings`, else `scraper_settings.json` | the caller's Steam rows |
| `XboxSyncJob` (`xbox_sync`) | `/api/xbox-achievements/sync-all`, `/api/xbox/sync-achievements` (editor) | global client id; the caller's tokens | the caller's Xbox rows |

Also:

- **PSN full sync** (`/api/psn/sync`, login) is a daemon thread, not a job
  class. One may run per user (`_psn_sync_states`, `_psn_sync_lock`). It is
  not persisted and has no cancel route.
- **Single-game syncs** run in the request: RA (`/api/achievements/sync/<id>`,
  editor, with the caller's own RA credentials), PSN
  (`/api/psn/sync/<npwr_id>`, login), Steam and Xbox (editor).
- **Ownership of the PSN bulk refresh.** Pause, resume and cancel refuse a
  caller who did not start it (`PSNRefreshJob._owns`). Its status blanks the
  current game for other users.
- **PSN keep-alive** (`services/jobs/psn_keepalive.py`) refreshes a user's
  PSN session once a day when it expires within 14 days. It never falls back
  to the NPSSO and skips sessions already expired.
- **Rate limits.** The PSN, Steam and Xbox bulk starts are limited to two an
  hour (`app.py`). The RA job starts are not rate-limited.
- **Upstream pacing.** PSN bulk refresh waits 2.5 s per game, Steam 1 s,
  Xbox 0.5 s, RA sync 0.5 s, RA refresh 1 s per console list.

### 4.5 Token storage

- `services/platform_tokens.py` is the one accessor for `user_platform_tokens`
  (platforms `psn`, `xbox`). Tokens are JSON text, not encrypted; the module
  header records the reason (the database file is mode 0600).
- Every accessor does nothing without a `user_id`.
- PSN: `routes/trophies.py::create_psn_client` uses cached tokens while the
  refresh token is unexpired, re-saves them, and otherwise falls back to the
  NPSSO. `/api/psn/token-info` reports expiry, never the tokens.
- Xbox: `scrape_xbox.get_authenticated_session` refreshes a stale token and
  clears the stored tokens when the refresh fails. The OAuth `state` is bound
  to the user who started sign-in.
- The NPSSO and the RA and Steam keys live in `user_settings` as plain text.
- `services/log_redactor.py::SecretRedactor` masks tokens, NPSSO and API keys
  in logs.

### 4.6 What survives an empty reply

- **PSN single-game sync and full sync** (PASS-59-58).
  `_psn_trophy_counts` maps a missing earned or defined block to `None`. The
  single-game UPDATE wraps each count, and `icon_url`, in `COALESCE(?, col)`.
  The full sync's `_upsert_psn_title` inserts `0` for a new title and keeps
  the stored value on conflict.
- **RA sync.** When the reply lists no achievements but says the game has
  some, the points columns keep their stored values (`skip_points`). The
  achievement counts are still written.
- **Steam and Xbox.** A failed call (`None`) writes nothing. An empty list
  writes zero earned and zero total.
- **Paths not covered** are listed in §13.

### 4.7 RPCS3 trophy files

`scraper/trophy_parser.py::TrophyManager` reads `NPWR*` folders directly under
the user's `rpcs3_trophy_path` (from `user_settings`, else the global
setting), skipping `_BU_` backups. `TROPCONF.SFM` is parsed with `defusedxml`.
`TROPUSR.DAT` is read big-endian with bounds checks: the table count is
capped to the file, an entry size below 48 bytes stops the read, and one
unreadable set is skipped without dropping the others. Rescanning is
admin-only (`/api/scan-trophies`).

## 5. Invariants

- **INV-1** — A PSN reply missing its earned or defined block leaves the
  stored counts unchanged on the single-game sync, the full sync and the
  bulk refresh; a new title stores zeros. The bulk refresh is tested in
  `tests/test_pass59_trophy_dataloss.py`. *Test:* `python3 -m pytest -q tests/test_pass59_psn_counts.py`
  → `4 passed`. *Breaks when:* `_psn_trophy_counts` maps a missing block to
  `0`, or a count column loses its `COALESCE`.
- **INV-2** — An RA title match never pairs games whose sequel numbers differ
  ("Donkey Kong Country 2" with "Donkey Kong Country"), in both matchers.
  *Test:* `python3 -m pytest -q tests/test_pass59_ra_sequels.py` →
  `29 passed`. *Breaks when:* number words are dropped as one-character
  words again, or `ra_sequel_numbers` is not compared.
- **INV-3** — Two users can hold rows for the same PSN title, Steam
  achievement or collector trophy, and legacy progress rows go to the first
  admin. *Test:* `python3 -m pytest -q
  tests/test_pass31_migrations.py::TestPSNUserIdMigration
  tests/test_pass31_migrations.py::TestCollectorTrophiesUserIdMigration
  tests/test_pass31_migrations.py::TestAchievementUserIdMigration` →
  `7 passed`. *Breaks when:* a unique key on these tables drops `user_id`.
- **INV-4** — Platform tokens are stored and read per `(user_id, platform)`,
  and a call without a `user_id` reads and writes nothing. *Test:* `python3 -m
  pytest -q tests/test_auth_hardening.py -k "psn_save_and_load_round_trip or
  tokens_isolated_between_users or tokens_isolated_between_platforms or
  clear_tokens_removes_row or save_with_no_user_id_is_noop"` → `5 passed`.
  *Breaks when:* `load_tokens` drops its `user_id` filter.
- **INV-5** — Deleting a user removes their tokens, PSN games and PSN
  trophies. *Test:* `python3 -m pytest -q
  tests/test_pass59_auth_api.py::test_deleting_a_user_removes_every_row_they_own`
  → `1 passed`. *Breaks when:* a new per-user trophy table is left out of
  `_delete_user_and_owned_rows`.
- **INV-6** — The Steam pages read only the caller's rows. *Test:* `python3 -m
  pytest -q tests/test_pass40_1_8_security.py::TestPass40_4SteamAchievementsUserScoping`
  → `2 passed`. These read source text. The PSN, RA and Xbox routes have no
  scoping test. *Breaks when:* a `user_id = ?` filter is removed from
  `routes/steam_achievements.py`.
- **INV-7** — A background job resumed from a snapshot with no `user_id`
  refuses to run, and a resumed job reprocesses the item in flight. *Test:*
  `python3 -m pytest -q
  tests/test_pass59_jobs_resume.py::TestResumeRefusesSnapshotWithoutUserId
  tests/test_pass59_jobs_resume.py::TestResumeDoesNotSkipTheInFlightItem
  tests/test_pass59_jobs_resume.py::TestRARefreshCommitsPerGame` →
  `10 passed`. The refusal is tested for RA sync and Steam sync only.
  *Breaks when:* `resume_from_params` falls back to a default user.
- **INV-8** — Each trophy job takes its own cross-process lock. *Test:*
  `python3 -m pytest -q
  tests/test_pass41_security.py::TestPass41_6AExtendSingletonLockOtherJobs`
  → `4 passed`. *Breaks when:* a job's `start()` stops calling
  `acquire_job_singleton_lock` with its own name.
- **INV-9** — The PSN keep-alive refreshes only sessions that expire within
  its window, and skips a user with no NPSSO. *Test:* `python3 -m pytest -q
  tests/test_psn_keepalive.py` → `2 passed`. *Breaks when:* an expired
  session is pinged, or the NPSSO fallback is allowed.
- **INV-10** — The scraper's RA check writes the `games` RA columns only on a
  match and swallows network errors. *Test:* `python3 -m pytest -q
  tests/test_pass38_ra_check_helper.py::TestApplyRetroachievementsCheck` →
  `6 passed`. *Breaks when:* a `None` result writes zeros.
- **INV-11** — A truncated or corrupt `TROPUSR.DAT` neither crashes the
  parser nor hides other games' trophies. *Test:* `python3 -m pytest -q
  tests/test_pass41_security.py::TestPass41_7ATropusrBounds
  tests/test_pass59_63_services.py::TestTrophyParserTruncated` → `3 passed`.
  *Breaks when:* the `entry_size < 48` guard or the per-set `try` in
  `load_all_trophy_sets` is removed.
- **INV-12** — Xbox tokens refresh only when stale, are cleared when a refresh
  fails, and sign-in checks the OAuth `state`. *Test:* `python3 -m pytest -q
  tests/test_pass45_security.py -k "fresh_token_skips_refresh or
  stale_token_triggers_refresh or failed_refresh_clears_tokens"` →
  `3 passed`, and `python3 -m pytest -q tests/test_auth_hardening.py -k
  "test_get_auth_url_accepts_state or test_callback_verifies_state"` →
  `2 passed`. *Breaks when:* a failed refresh leaves the old tokens stored.
- **INV-13** — The bulk sync starts are rate-limited to two an hour. *Test:*
  `python3 -m pytest -q tests/test_pass45_security.py::TestPass45_8RateLimits`
  → `3 passed`. *Breaks when:* a bulk start's `_rate_limit` line is removed.
- **INV-14** — Legacy token files are imported once and never overwrite a
  token saved since. *Test:* `python3 -m pytest -q
  tests/test_migration_015.py` → `4 passed`. *Breaks when:* migration 015
  uses `INSERT OR REPLACE`.
- **INV-15** — NPSSO values and API keys are masked in logs. *Test:*
  `python3 -m pytest -q tests/test_auth_hardening.py -k
  "npsso_field_redacted or api_key_field_redacted"` → `2 passed`. *Breaks
  when:* `SecretRedactor` drops the `npsso` key.
- **INV-16** — PSN bulk-refresh pause, resume and cancel refuse a user who
  did not start the job. *Test:* none. *Breaks when:* `_owns` is bypassed.
- **INV-17** — A sync never clears an existing PSN game link. *Test:* none.
  *Breaks when:* `linked_game_id` loses its `COALESCE` in `_upsert_psn_title`.
- **INV-18** — When RA Refresh cannot fetch a console's game list, it
  counts that console's games failed and leaves their RA links as they
  were. *Test:* `tests/test_pass59_trophy_dataloss.py::test_failed_ra_list_fetch_keeps_links`.
  *Breaks when:* a failed fetch is cached as an empty list.
- **INV-19** — Clear RA data deletes only RA progress rows; Steam and Xbox
  rows stay. *Test:* `tests/test_pass59_trophy_dataloss.py::test_clear_ra_data_keeps_steam_and_xbox_rows`.
  *Breaks when:* either `/api/clear-ra-data` delete loses its source filter.

## 6. Failure modes

- **Platform unreachable.** Steam and Xbox count the game skipped; RA sync
  counts it failed; RA Refresh counts every game on a console failed when
  that console's game list will not load; PSN bulk refresh fails the whole run when the title list
  is empty or the fetch passes 300 s.
- **Expired PSN session.** `create_psn_client` clears the cache and signs in
  with the NPSSO; an expired NPSSO surfaces as a sign-in error.
- **Failed Xbox refresh.** Stored tokens are cleared; the user signs in again.
- **Restart mid-sync.** Job classes can be resumed ([`jobs.md`](jobs.md)). The
  PSN full sync cannot; it restarts from the beginning.
- **Corrupt RPCS3 file.** That set is skipped and logged.

## 7. Tests

| Invariant | Test |
|---|---|
| INV-1 | `tests/test_pass59_psn_counts.py`; `tests/test_pass59_trophy_dataloss.py` (bulk refresh) |
| INV-2 | `tests/test_pass59_ra_sequels.py` |
| INV-3 | `tests/test_pass31_migrations.py` (PSN, collector, achievement classes) |
| INV-4 | `tests/test_auth_hardening.py` (token store cases) |
| INV-5 | `tests/test_pass59_auth_api.py::test_deleting_a_user_removes_every_row_they_own` |
| INV-6 | `tests/test_pass40_1_8_security.py::TestPass40_4SteamAchievementsUserScoping` |
| INV-7 | `tests/test_pass59_jobs_resume.py` |
| INV-8 | `tests/test_pass41_security.py::TestPass41_6AExtendSingletonLockOtherJobs` |
| INV-9 | `tests/test_psn_keepalive.py` |
| INV-10 | `tests/test_pass38_ra_check_helper.py::TestApplyRetroachievementsCheck` |
| INV-11 | `tests/test_pass41_security.py::TestPass41_7ATropusrBounds`; `tests/test_pass59_63_services.py::TestTrophyParserTruncated` |
| INV-12 | `tests/test_pass45_security.py` (Xbox token cases); `tests/test_auth_hardening.py` (state cases) |
| INV-13 | `tests/test_pass45_security.py::TestPass45_8RateLimits` |
| INV-14 | `tests/test_migration_015.py` |
| INV-15 | `tests/test_auth_hardening.py` (redactor cases) |
| INV-16 | none |
| INV-17 | none |
| INV-18 | `tests/test_pass59_trophy_dataloss.py` |
| INV-19 | `tests/test_pass59_trophy_dataloss.py` |

## 8. Alternatives considered (and rejected)

None. This spec records existing behaviour; it chose no design.

## 9. Out of scope

- Collector trophy rules and scoring — not yet queued for a spec.
- The PSN, Steam and Xbox library import (adding games) — recorded as a skip
  in [`../design.md`](../design.md).
- Changing any behaviour listed in §13 — none is queued by this document.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | §7's test |
| INV-2 | §7's test |
| INV-3 | §7's tests |
| INV-4 | §7's tests |
| INV-5 | §7's test |
| INV-6 | Partial: source-text checks on the Steam routes; nothing on the PSN, RA or Xbox routes |
| INV-7 | Partial: the user-id refusal is tested for RA sync and Steam sync only |
| INV-8 | §7's test |
| INV-9 | §7's tests |
| INV-10 | §7's tests |
| INV-11 | §7's tests |
| INV-12 | §7's tests |
| INV-13 | §7's tests |
| INV-14 | §7's tests |
| INV-15 | §7's tests |
| INV-16 | **nothing** |
| INV-17 | **nothing** |
| INV-18 | §7's tests |
| INV-19 | §7's tests |

## 11. Cross-doc impact

- [`../design.md`](../design.md) § 4 points here and records the skipped
  subsystems.
- [`auth.md`](auth.md) § 5 stays the owner of the per-user rule; §13 lists
  where trophy code departs from it.

## 12. Cold-eyes loop log

No review run. Rule 14's gate is cancelled by RetroDB's `CLAUDE.md`
(§ Contract Reviews), so: no gate, cancelled by RetroDB CLAUDE.md.

## 13. Open

Behaviour the code has now that a reviewer may judge a defect. None is
queued by this document.

- **PASS-59-110 landed during this write-up** (commit `10b2f15`). INV-2
  describes the committed code. Links made before it stay wrong until an
  all-systems RA Refresh runs.
- **RA single-game sync stores zero totals.** `api_sync_game_achievements`
  reads `total_count`, but `get_user_game_progress_custom` returns
  `achievement_count`.
- **RA background jobs use the global RA account** while writing the caller's
  progress rows. The single-game route uses the caller's own account.
- **Steam and Xbox jobs walk every game** with a platform id, not only the
  caller's.
- **Not scoped to the caller:** dashboard achievement totals
  (`app.py::get_stats`); RA, Steam and Xbox job status and cancel;
  `/api/jobs/resume/<id>` resuming an admin-only job for any signed-in user.
- **PSN bulk refresh starts without the user's cached tokens.**
  `create_psn_client(self._npsso)` is called with no `user_id` on a thread
  with no request user, so it signs in with the NPSSO each time. Inferred
  from the code; not tested.
- **`user_settings.rpcs3_trophy_path` is not path-validated.** The global
  setting is. Only `NPWR*` folders and fixed filenames are read.
- **Collector stats may count Steam and Xbox earns twice.**
  `_gather_collection_stats` adds all-source `game_achievement_progress` sums
  to counts from `steam_achievements` and `xbox_achievements`. Inferred from
  the SQL; not tested.
- **`/api/psn/save-npsso` returns the raw exception text** to the client.
