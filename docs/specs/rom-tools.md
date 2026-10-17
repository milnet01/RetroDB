# PASS-59-66 — ROM Tools: what each tool may change and how it guards the library

**Status:** accepted (2026-10-17).
**Kind:** docs.
**Source:** ROADMAP PASS-59-66 (review-code sweep 2026-09-01: the ROM Tools
findings had no statement of intent to judge against).
**Pairs with:** [`trophies.md`](trophies.md), the other spec filed under the
same item. **Related:** PASS-59-63 (fixes in this subsystem, landed 2026-10-17).

Layman: this is the rulebook for the ROM Tools pages — which tools can delete
or move your game files, who is allowed to run them, and what stops them
reaching files outside your ROM folder.

This spec was written after the code. It records the behaviour the code has
today, so a reviewer can tell a defect from a design choice. Each invariant
names the test that pins it, or says none does.

Cross-references:

- [`image-pipeline.md`](image-pipeline.md) §11 owns the ROM-root symlink guard
  (`_safe_under_root`, `_glob_under_rom_root`). This spec says where it is
  applied, not how it works.
- [`settings.md`](settings.md) owns the general settings file. ROM Tools keep
  their own file, `data/rom_tools_config.json` (§4.5 here).
- [`jobs.md`](jobs.md) owns the persisted background jobs. ROM Tools tasks are
  not jobs in that sense: they live only in process memory (§4.3).

## 1. Goal

One statement of what the ROM Tools subsystem may do to files under the ROM
root, and what protects them. A reviewer can then judge a finding against
intent instead of against the code's own docstrings.

## 2. Problem

The 2026-09-01 review found defects in ROM Tools that could only be phrased as
"the code contradicts itself". Nothing said which behaviour was intended.

1. Several tools delete or rewrite files with no undo. Their protections are
   spread over `routes/tools.py`, `scraper/rom_tools.py`,
   `services/rom_tools_validators.py` and `services/security.py::safe_path`.
2. Two task registries exist side by side (§4.3), with different id lengths,
   lifetimes and failure handling.
3. Role checks differ per endpoint, and only some are pinned by tests.

## 3. Scope decisions (agreed with the user)

- **Document, don't redesign.** The roadmap item asks for a statement of
  intent for existing code (PASS-59-66 Plan). Behaviour that looks wrong is
  recorded under §13 Open, not changed here. Decided by the orchestrator in
  the item's Plan.
- **Two documents, not seven.** ROM Tools and trophies get specs; the other
  uncovered subsystems get a recorded skip in
  [`../design.md`](../design.md) § 4.
  Decided in the item's Plan.
- **Filename without the id.** This file follows the project's subsystem-spec
  naming (`jobs.md`, `image-pipeline.md`), as the dispatching session asked,
  not `spec-format.md` §2's `<ID>-<topic>.md`.

## 4. Design

### 4.1 The tools

| Tool | Page | What it changes |
|---|---|---|
| Archive scanner | `/tools/archive-scanner` | Lists archives that are corrupt, hold several ROM files, or hold unwanted files. The scan itself changes nothing. |
| Remove files from archive | (archive scanner) | Deletes named members from a `.zip` (`zip -d`) or `.7z` (`7z d`). `.rar` is refused. |
| Clean archive | (archive scanner) | Deletes every member whose basename matches the saved unwanted patterns. |
| Create M3U / batch | (archive scanner) | Extracts a multi-file archive into a sibling folder, writes `noload.txt` and a sibling `.m3u`, and optionally moves the archive to the staging folder. The page calls `create-m3u` once per archive; nothing in the UI calls `batch-create-m3u`. |
| CHD converter | `/tools/chd-converter` | Runs `chdman createcd` on `.iso`, `.cue`, `.gdi` and `.mds` files; optionally deletes the source. |
| CHD verify | `/tools/chd-verify` | Runs `chdman verify`. Changes nothing. |
| Duplicate finder | `/tools/duplicate-finder` | Groups ROM files by hash, name or both; the delete call removes the files the user picked. |
| Screenshot dedup | `/tools/screenshot-dedup` | Groups a game's screenshots by MD5 or perceptual hash; the delete call removes files and rewrites `games.screenshots`. |

The Multi-Disc Organizer page is served from `routes/tools.py`, but its API is
`routes/reports.py` (`/api/reports/multidisc-scan`,
`/api/reports/organize-multidisc`). It is out of scope (§9).

### 4.2 Destructive operations and their protections

| Operation | Undo? | Protection |
|---|---|---|
| Remove files / clean archive | No. Members are gone. | Admin only. `safe_path` on the archive path. Clean refuses when the patterns match every member, and a pattern made only of `*`, `?` and `.` is refused at save. Success is reported only when a re-listing shows members actually left (`ArchiveScanner.remove_files_from_archive`). Member names follow `--` (zip) or `-i!` (7z), so a name starting with `-` is not read as a switch. |
| Create M3U | Partly. The archive is moved, not deleted. | Admin only. `move_to_staging` defaults to true and the page does not send it, so every M3U built from the page moves its archive. `safe_path` on every path. Refuses when the `.m3u` or the game folder already exists (PASS-59-63, see §13). The archive moves only when the caller asks (`move_to_staging`, or `delete_archives` on the batch call). The staging folder is server-side: `ArchiveScanner._staging_folder()`, which is `<temp_path>/m3u_staging`, else `data/m3u_staging` under RetroDB's own folder. The old default `temp_path`, `<system temp>/retrodb_romtools`, counts as empty. A name clash in staging gets a `_N` suffix. |
| CHD convert | Source deletion has no undo. | Admin only. `safe_path` per file, inside the worker. `convert_one_to_chd` writes `<name>.chd.part`, verifies it when verify is on, and only then renames it to `.chd`. The source is deleted only after the `.chd` is in place, and only when `chd_delete_originals` (or the request's `delete_originals`) is true. A failed run removes the `.part` file. With verify off, the source is kept, and the result says so. For a `.cue`, only the `.cue` is deleted; its `.bin` tracks stay. An existing `.chd` is replaced only when Skip existing is off (the request's `skip_existing`, else `chd_skip_existing`). |
| Duplicate delete | No. `os.remove`. | Admin only. `safe_path` per file. Nothing is staged. The request names its scan (`task_id`); the server refuses the whole request when it would delete every file of a group, refuses it when the scan is gone, and skips any file that scan did not group. |
| Screenshot delete | No. `os.remove`. | Admin only. A filename containing a path separator or `..` is refused. Files live under `static/images/screenshots/`, not the ROM root. |
| Save settings | Yes, by saving again. | Admin only (checked inside the handler). Every key goes through `validate_rom_tools_value`; an unknown key is refused. |

The scan endpoints write nothing. They are editor-only and rate-limited to five
a minute (`app.py`, the `_rate_limit('tools.api_*_scan', ...)` lines).

### 4.3 Task registries

Long work runs on a daemon thread and reports through a task the page polls at
`GET /api/rom-tools/task/<task_id>`. The poll endpoint checks the routes
registry first, then the scanner registry.

| | Routes registry | Scanner registry |
|---|---|---|
| Where | `routes/tools.py::_rom_tool_tasks` (plain dicts) | `scraper/rom_tools.py::_tasks` (`TaskStatus` objects, under `_task_lock`) |
| Used by | CHD convert, CHD verify, duplicate scan, screenshot dedup scan | Archive scan |
| Task id | `str(uuid.uuid4())` | `str(uuid.uuid4())` (`create_task`) |
| Failure | Every worker runs inside `_guarded_worker`: an uncaught exception sets `status='failed'`, stamps `end_time` and logs. | `scan_for_issues` catches its own exceptions and sets `status='error'`. |
| Pause | Each worker waits in `_wait_if_paused` before its next item. | Each worker sleeps while `paused`, and stops if it was cancelled meanwhile. |
| Cleanup | `_cleanup_completed_tasks` runs when a new task is created. It removes tasks in `completed`, `failed` or `cancelled` whose `end_time` is older than `_TASK_RETENTION_SECONDS`, and stamps `end_time` on a finished task that lacks one. A `running` task is never removed. | `create_task` removes `completed`, `error` or `cancelled` tasks whose `end_time` is older than `_TASK_RETENTION_SECONDS`. |

Neither registry is persisted. A restart loses every task and its log.
Cancel, pause and resume are admin-only. Cancel acts on a `running` or `paused` task.

### 4.4 Roles per endpoint

Decorators are from `services/auth.py`.

| Role | Endpoints |
|---|---|
| `login_required` | Every `/tools/*` page; `GET /api/rom-tools/settings`; `/api/rom-tools/status`; `/api/rom-tools/browse-folders`; `GET /api/rom-tools/task/<id>`; `/api/rom-tools/archive-scanner/contents` |
| `editor_required` | The five scan endpoints: archive scanner, CHD converter, CHD verify, duplicate finder, screenshot dedup |
| `admin_required` | Task cancel, pause and resume; archive `remove-files`, `clean`, `create-m3u`, `batch-create-m3u`; `chd-converter/convert`; `chd-verify/verify`; `duplicate-finder/delete`; `screenshot-dedup/delete` |
| admin, checked in the handler | `POST /api/rom-tools/settings` |

CHD verify writes nothing, yet is admin-only (Pass 41.10.B).

### 4.5 Settings

`data/rom_tools_config.json`, read by `load_rom_tools_config` over a fixed
defaults dict and written with `atomic_write_json`. The validator table in
`services/rom_tools_validators.py::_VALIDATORS` lists every key that may be
saved. Two keys carry security weight:

- `chdman_path` becomes `argv[0]` of `subprocess.run`. It may be the bare name
  `chdman` or `chdman.exe`, or an absolute path made of one entry in
  `_SAFE_BIN_PREFIXES` followed directly by `chdman` or `chdman.exe`.
- `duplicate_method` must be `hash`, `name` or `both`. The duplicate scan
  checks the request's own `method` against the same list and refuses others.

A tool run takes each on/off option from the request when it is a real
boolean, else from the saved setting (`_run_option`, Pass 59.49). Scanners are
built from saved settings (`_rom_tools_config`).

### 4.6 Path containment

Two separate guards apply.

1. **Request paths.** Every path a request names is passed to
   `services/security.py::safe_path(path, rom_root)`, which compares
   `realpath`s. Scan roots and single-path calls return 400 when it fails.
   Per-file lists (convert, verify, duplicate delete) count the file as failed
   and carry on. `browse-folders` falls back to the ROM root instead of
   refusing.
2. **Walk results.** Recursive walks drop any match that resolves outside the
   root. [`image-pipeline.md`](image-pipeline.md) §11 owns the guard. It is
   applied in `ArchiveScanner._find_archives_filtered`, `_find_archives`, the
   extracted-folder walk in `create_m3u_playlist`,
   `CHDConverter.find_convertible_files`, `CHDVerifier.find_chd_files`,
   `DuplicateFinder._find_rom_files` (recursive or not), and the CHD scan
   routes through `_glob_under_rom_root`. The duplicate-scan route's
   `os.walk` and `os.listdir` branches drop a symlinked file that resolves
   outside the root. `browse-folders` offers a parent link only inside the
   root.
   `CHDConverter`, `CHDVerifier` and `DuplicateFinder` are not called by any
   route; the routes carry their own loops.

### 4.7 External programs

`unzip`, `zip`, `7z`, `unrar` and `chdman`, each run through `subprocess.run`
with an argument list and a timeout. `check_rom_tools_availability` reports
which are on `PATH`. CHD convert and verify refuse to start when
`shutil.which(chdman_path)` finds nothing.

## 5. Invariants

- **INV-1** — Every endpoint that deletes, moves, rewrites or runs `chdman` on
  library files requires an admin. *Test:* `python3 -m pytest -q
  tests/test_pass41_security.py::TestPass41_10ATaskAuthz
  tests/test_pass41_security.py::TestPass41_10BConvertVerifyAuthz
  "tests/test_pass40_1_8_security.py::TestPass40_3ArchiveScannerM3u::test_create_m3u_requires_admin"
  "tests/test_pass40_1_8_security.py::TestPass40_3ArchiveScannerM3u::test_batch_create_m3u_requires_admin"`
  → `7 passed`. These cover task control, CHD convert and verify, and M3U;
  `remove-files`, `clean`, `duplicate-finder/delete` and
  `screenshot-dedup/delete` have no test. *Breaks when:* one of those routes
  is decorated `@login_required` or `@editor_required`.
- **INV-2** — A request-supplied path that resolves outside the ROM root is
  never passed to `chdman` or `os.remove`, and never extracted. *Test:*
  `python3 -m pytest -q
  tests/test_pass40_1_8_security.py::TestPass40_2ChdConvertVerifyPathValidation
  "tests/test_pass40_1_8_security.py::TestPass40_3ArchiveScannerM3u::test_batch_validates_each_path"
  "tests/test_pass40_1_8_security.py::TestPass40_3ArchiveScannerM3u::test_create_m3u_e2e_rejects_outside_rom_path"`
  → `7 passed`. No test covers the duplicate delete's per-file check.
  *Breaks when:* a worker uses a path from the request body without
  `safe_path(path, rom_root)`.
- **INV-3** — A recursive scan never lists a file reached through a symlink
  that leaves the ROM root. *Test:* `python3 -m pytest -q
  tests/test_pass59_rom_tools.py::test_scan_skips_files_reached_through_an_escaping_symlink
  tests/test_pass59_rom_tools.py::test_extracted_folder_walk_is_guarded
  tests/test_pass41_security.py::TestPass41_14CRglobSymlinkGuard` →
  `6 passed`. The non-recursive finders and the duplicate-scan route are
  tested in `tests/test_pass59_119_rom_tools.py`. *Breaks when:* a `rglob` or `glob(..., recursive=True)` result is used
  without `_safe_under_root`.
- **INV-4** — A `chdman_path` outside the allowed shapes is never saved, and an
  unknown settings key is refused. *Test:* `python3 -m pytest -q
  tests/test_pass40_1_8_security.py::TestPass40_1ChdmanPathValidator
  "tests/test_pass40_1_8_security.py::TestPass40_1RouteIntegration::test_post_rejects_attacker_chdman_path"`
  → `14 passed`. *Breaks when:* `/usr/bin/python3` or `/tmp/chdman` is accepted.
- **INV-5** — A `.chd` appears at its final name only after `chdman createcd`
  succeeded and, when verify is on, `chdman verify` passed on the `.part`
  file. The source is deleted only after that. *Test:* `python3 -m pytest -q
  tests/test_pass40_9_16_security.py::TestPass40_11ChdAtomicConversion` →
  `4 passed`. These read the source text; no test runs a failing conversion.
  *Breaks when:* `chdman` writes straight to the `.chd` path, or the source
  is unlinked before `os.replace`.
- **INV-6** — Create M3U leaves an existing `.m3u` file or game folder
  untouched and reports failure. *Test:* `python3 -m pytest -q
  tests/test_pass59_63_services.py::TestCreateM3uRefusesExisting` →
  `3 passed`. *Breaks when:* the existence check before extraction is
  removed; `unzip -o` then overwrites the folder's files. Added by
  PASS-59-63 (§13).
- **INV-7** — Create M3U moves the source archive only when asked, and only
  into the server-side staging folder under the saved `temp_path`. *Test:*
  `python3 -m pytest -q tests/test_pass59_rom_tools.py::test_m3u_staging_follows_temp_path
  tests/test_pass59_destructive_ops.py::TestBatchM3uHonoursDeleteArchives` →
  `3 passed`. *Breaks when:* the batch call moves archives with
  `delete_archives` false, or a request field chooses the staging folder.
- **INV-8** — An empty unwanted-pattern list matches nothing, and the default
  patterns do not match a ROM whose name starts with "Readme" or "Release".
  *Test:* `python3 -m pytest -q
  tests/test_pass59_63_services.py::TestUnwantedPatterns` → `4 passed`.
  *Breaks when:* an empty list falls back to the defaults, or `readme*`
  returns. Added by PASS-59-63 (§13).
- **INV-9** — The saved `duplicate_method` is one of `hash`, `name`, `both`.
  *Test:* `python3 -m pytest -q
  tests/test_pass59_63_services.py::TestDuplicateMethodAllowlist` →
  `2 passed`. *Breaks when:* `size` is accepted. The request's `method` is
  tested in `tests/test_pass59_119_rom_tools.py::test_duplicate_scan_refuses_an_unknown_method`.
- **INV-10** — A routes-registry worker that raises ends its task `failed`
  with an `end_time`, and a file deleted before its turn counts as invalid
  without stopping the run. *Test:* `python3 -m pytest -q
  tests/test_pass59_rom_tools.py::test_worker_crash_marks_the_task_failed
  tests/test_pass59_rom_tools.py::test_verify_survives_a_file_deleted_before_its_turn`
  → `2 passed`. The screenshot scan's guard is tested in `tests/test_pass59_119_rom_tools.py`.
  *Breaks when:* a worker thread is started without
  `_guarded_worker`, or `os.path.getsize` moves back outside the `try`.
- **INV-11** — Routes-registry task ids are full UUIDs. *Test:* `python3 -m
  pytest -q tests/test_pass41_security.py::TestPass41_10CTaskIdFullUuid` →
  `2 passed`. *Breaks when:* `uuid.uuid4())[:8]` reappears in
  `routes/tools.py`. The scanner registry's ids and reaping are tested in
  `tests/test_pass59_119_rom_tools.py`.
- **INV-12** — A run option sent as a real boolean wins; anything else falls
  back to the saved setting. *Test:* `python3 -m pytest -q
  tests/test_pass59_rom_tools.py::test_run_option_prefers_the_request_then_the_setting`
  → `1 passed`. *Breaks when:* a string `"false"` from the request is read as
  a choice.
- **INV-13** — The cleanup removes finished routes-registry tasks older than
  `_TASK_RETENTION_SECONDS` and never a `running` one. *Test:* none.
  *Breaks when:* `running` joins the status tuple in
  `_cleanup_completed_tasks`.
- **INV-15** — The five scan endpoints are editor-only and rate-limited.
  *Test:* `python3 -m pytest -q
  tests/test_pass41_security.py::TestPass41_10DScanAuthzAndRateLimit` →
  `10 passed`. *Breaks when:* a scan route drops `@editor_required` or its
  `_rate_limit` line in `app.py`.
- **INV-14** — Removing archive members reports success only when a
  re-listing shows at least one member gone. *Test:* none. *Breaks when:*
  the result is taken from `zip`'s return code alone.
- **INV-16** — Clean never removes every member of an archive, and a pattern
  made only of `*`, `?` and `.` is never saved. *Test:* `tests/test_pass59_119_rom_tools.py` (Clean cases).
  *Breaks when:* `clean_archive` loses its every-member check, or
  `unwanted_patterns` goes back to the plain string-list validator.
- **INV-17** — With verify off, CHD convert keeps the source; with Skip
  existing on, it leaves an existing `.chd` alone. *Test:* `tests/test_pass59_119_rom_tools.py` (CHD cases).
  *Breaks when:* `convert_one_to_chd` deletes without `do_verify`, or the
  route passes a fixed `skip_existing`.
- **INV-18** — Duplicate delete removes only files its scan grouped, and
  never every file of a group. *Test:* `tests/test_pass59_119_rom_tools.py` (duplicate delete cases).
  *Breaks when:* the route stops reading `task_id` or drops the group check.
- **INV-19** — A paused task starts no new item until resumed, and can be
  cancelled, in both registries. *Test:* `tests/test_pass59_119_rom_tools.py` (pause cases). *Breaks when:*
  a worker loop loses `_wait_if_paused`, or cancel needs `running`.
- **INV-20** — With no Temporary Path set, Create M3U never stages archives in
  the system temp dir. *Test:* `tests/test_pass59_119_rom_tools.py` (staging cases). *Breaks when:*
  `_staging_folder` falls back to `tempfile.gettempdir()`.

## 6. Failure modes

- **Staging on a cleared disk.** A Temporary Path the user sets inside a
  folder cleared at boot loses any archive staged there. The default is
  `data/m3u_staging`, which is not cleared.
- **Restart mid-task.** Both registries are in memory. The task and its log
  are lost; a CHD conversion leaves at most a `.chd.part` file, which the next
  run of the same file removes.
- **`chdman` missing.** Convert and verify return 400 before creating a task.
- **Archive tool missing.** The `subprocess.run` call raises; the scanner
  logs a warning and reports no issues for that archive
  (`_check_archive_issues` catches the exception).
- **Timeouts.** Each external call has one (`convert_one_to_chd`: one hour
  for convert, ten minutes for verify; extraction five minutes; member
  removal two minutes). A timeout marks that file failed and the run goes on.
- **File gone between scan and action.** Verify counts it invalid; duplicate
  delete counts it failed; screenshot delete counts it deleted.
- **Scan results gone before a duplicate delete.** The routes registry drops
  a finished scan after `_TASK_RETENTION_SECONDS`; a delete naming it is
  refused and the page says to scan again.

## 7. Tests

| Invariant | Test |
|---|---|
| INV-1 | `tests/test_pass41_security.py::TestPass41_10ATaskAuthz`, `::TestPass41_10BConvertVerifyAuthz`; `tests/test_pass40_1_8_security.py::TestPass40_3ArchiveScannerM3u` (admin cases) |
| INV-2 | `tests/test_pass40_1_8_security.py::TestPass40_2ChdConvertVerifyPathValidation`; `::TestPass40_3ArchiveScannerM3u` (path cases) |
| INV-3 | `tests/test_pass59_rom_tools.py` (symlink cases); `tests/test_pass41_security.py::TestPass41_14CRglobSymlinkGuard` |
| INV-4 | `tests/test_pass40_1_8_security.py::TestPass40_1ChdmanPathValidator`, `::TestPass40_1RouteIntegration`, `::TestPass40_1OtherSettingsValidators` |
| INV-5 | `tests/test_pass40_9_16_security.py::TestPass40_11ChdAtomicConversion` |
| INV-6 | `tests/test_pass59_63_services.py::TestCreateM3uRefusesExisting` |
| INV-7 | `tests/test_pass59_rom_tools.py::test_m3u_staging_follows_temp_path`; `tests/test_pass59_destructive_ops.py::TestBatchM3uHonoursDeleteArchives` |
| INV-8 | `tests/test_pass59_63_services.py::TestUnwantedPatterns` |
| INV-9 | `tests/test_pass59_63_services.py::TestDuplicateMethodAllowlist` |
| INV-10 | `tests/test_pass59_rom_tools.py` (worker cases) |
| INV-11 | `tests/test_pass41_security.py::TestPass41_10CTaskIdFullUuid` |
| INV-12 | `tests/test_pass59_rom_tools.py::test_run_option_prefers_the_request_then_the_setting` |
| INV-13 | none |
| INV-14 | none |
| INV-15 | `tests/test_pass41_security.py::TestPass41_10DScanAuthzAndRateLimit` |
| INV-16 | `tests/test_pass59_119_rom_tools.py` |
| INV-17 | `tests/test_pass59_119_rom_tools.py` |
| INV-18 | `tests/test_pass59_119_rom_tools.py` |
| INV-19 | `tests/test_pass59_119_rom_tools.py` |
| INV-20 | `tests/test_pass59_119_rom_tools.py`; `tests/test_pass59_rom_tools.py::test_m3u_staging_follows_temp_path` |

`tests/test_pass59_rom_tools_js.py` checks that `rom-tools.js` loads without
the i18n helpers; it pins no invariant here.

## 8. Alternatives considered (and rejected)

None. This spec records existing behaviour; it chose no design.

## 9. Out of scope

- The Multi-Disc Organizer's API in `routes/reports.py` — not part of this
  subsystem's code; not yet queued for a spec.
- Changing any behaviour listed in §13 — each needs its own roadmap item;
  none is queued by this document.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | Partial: the tests in §7 cover task control, CHD and M3U; nothing covers `remove-files`, `clean`, `duplicate-finder/delete` or `screenshot-dedup/delete` |
| INV-2 | Partial: §7's tests cover CHD and M3U; nothing covers duplicate delete's `safe_path` |
| INV-3 | Partial: §7's tests cover the CHD scan routes and the extracted-folder walk |
| INV-4 | §7's tests |
| INV-5 | Partial: source-text checks only |
| INV-6 | §7's test |
| INV-7 | §7's tests |
| INV-8 | §7's test |
| INV-9 | §7's test |
| INV-10 | §7's tests |
| INV-11 | §7's test |
| INV-12 | §7's test |
| INV-13 | **nothing** |
| INV-14 | **nothing** |
| INV-15 | §7's test |
| INV-16 | §7's tests |
| INV-17 | §7's tests |
| INV-18 | §7's tests |
| INV-19 | §7's tests |
| INV-20 | §7's tests |

## 11. Cross-doc impact

- [`../design.md`](../design.md) § 4 points here and records the skipped
  subsystems.
- [`image-pipeline.md`](image-pipeline.md) §11 stays the owner of the symlink
  guard; no change there.

## 12. Cold-eyes loop log

No review run. Rule 14's gate is cancelled by RetroDB's `CLAUDE.md`
(§ Contract Reviews), so: no gate, cancelled by RetroDB CLAUDE.md.

## 13. Open

Behaviour the code has now that a reviewer may judge a defect. None is
queued by this document.

- **PASS-59-63 landed during this write-up** (commit `21044fa`). INV-6,
  INV-8 and INV-9 describe it: the M3U overwrite refusal, `is not None` for
  the pattern list, the anchored `readme` / `release` globs, and the `hash` /
  `name` / `both` allowlist (formerly `size` in place of `both`).
- **Screenshot delete trusts the filename.** It removes any matching file in
  the screenshots folder, whether or not that game lists it.
- **Duplicate delete has no staging.** Unlike Create M3U, deleted duplicates
  cannot be recovered.
