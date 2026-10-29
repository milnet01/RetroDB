<!-- ants-spec-format: 1 -->
# PASS-59-169 — RetroDB updates itself

**Status:** accepted (2026-10-27).
**Kind:** implement.
**Source:** ROADMAP PASS-59-169 (user request and decisions 2026-10-27:
check + one-click install, GitHub Releases, source and standalone installs;
no spec review, the implementation is the review).

Layman: RetroDB notices when a new version is out, shows an admin what is
new, and installs it with one click. It downloads the release, checks the
download is exactly the published file, backs up your database, swaps the
program files, restarts, and goes back to the old version by itself if the
new one does not start. Your games, settings, images and logs are never
touched.

## 1. Goal

An admin sees "RetroDB X.Y.Z is available" on the dashboard and in
Settings > System > Updates, with the release notes. **Download** fetches and
verifies the release in the background; **Install and restart** applies it.
After the restart the page reloads on the new version, or, if the new
version did not come up, on the old one with the reason shown. Source
installs (unzipped `RetroDB-vX.Y.Z-<Platform>.zip`) and standalone installs
(PyInstaller `RetroDB-vX.Y.Z-<Platform>[-CPU]-Standalone.zip`) are both
covered, on Linux, Windows and macOS.

## 2. Non-goals

- No unattended install. Checking can be automatic; installing always takes
  an admin's click (user, 2026-10-27).
- No downgrade and no pre-release channel: only GitHub's "latest" published,
  non-draft, non-pre-release release is considered, and only when it is
  newer than the running version.
- Git checkouts are never updated (`git pull` is the developer's tool), and
  neither is an install run under LocalWebServerManager (`LWSM_MANAGED=1`),
  whose manager restarts the process itself and would race the swap. Both
  still see the notice and a download link.
- Signature verification of the cosign bundles `release.yml` attaches is
  not in this pass (§7).

## 3. Where updates come from

`GET https://api.github.com/repos/milnet01/RetroDB/releases/latest`
(`services/updater.py::RELEASES_REPO`). Draft releases are invisible to this
endpoint, so the maintainer's existing "review the draft, then publish" step
is also the switch that offers an update to users. The tag is `vX.Y.Z`;
versions compare as integer tuples.

The asset for this install:

| Install | Asset | Checksum |
|---|---|---|
| source | `RetroDB-v{V}-{Platform}.zip` | its line in `SHA256SUMS.txt` |
| standalone | `RetroDB-v{V}-{Platform}-Standalone.zip`, else `RetroDB-v{V}-{Platform}-CPU-Standalone.zip` | `<asset>.sha256` |

`{Platform}` is `Linux`, `macOS` or `Windows`. A download URL must start
with `https://github.com/milnet01/RetroDB/releases/download/`; GitHub then
redirects to its file host, which `requests` follows. A release without a
matching asset or checksum is shown as available but not installable.

**Checking.** On demand (Check now) and, unless `update_check_auto` is off,
at most once every 24 hours, started in the background by an admin's
dashboard or Settings visit. The result is kept in memory and in
`data/update_check.json`, so a restart does not re-query. Unauthenticated
GitHub API use allows 60 requests an hour per address; one a day is far
below it.

## 4. Download and verify (old version, background job)

`services/updater.py::UpdateJob`, one at a time, admin only.

1. Clear `<BASE_DIR>/.update/download` and `.update/staging` from any
   earlier attempt.
2. Stream the asset to `.update/download/`, refusing more than 3 GiB, and
   hash it as it arrives. Fetch the checksum file (at most 64 KiB) and take
   the line naming the asset. A mismatch deletes the file and stops.
3. Extract into `.update/staging/`. Every member name must stay inside the
   staging folder (no absolute paths, no `..`), symlink members are refused,
   and Unix permission bits from the zip are restored (`& 0o755`) so the
   standalone binary, its libraries and `start.sh` stay executable. Total
   unpacked size is capped at 8 GiB.
4. The zip holds one top folder (`RetroDB-v{V}` or
   `RetroDB-v{V}[-CPU]-Standalone`); that folder is the new tree. It must
   hold `app.py` and a `config.example.py` whose `APP_VERSION` is `{V}`
   (source), or the `retrodb` / `retrodb.exe` program and `_internal/`
   (standalone).
5. State becomes `ready`. Nothing in the install has changed yet.

## 5. Install (old version hands over to the new version's helper)

`POST /api/updates/install`, admin only, state `ready`:

1. Back up the database with `services.database.backup_database` to
   `database/backups/pre_update_<from>_to_<to>_<stamp>.db`. Backups named
   `pre_*` are never pruned.
2. Write `.update/plan.json` (§5.1).
3. Start the **new** version's helper, detached from this process:
   source `python <staging>/updater_apply.py <plan>`, standalone
   `<staging>/retrodb[.exe] --apply-update <plan>`. Running the new
   version's helper means the update protocol is always the newest one, and
   on Windows nothing needs to replace a running program.
4. Answer the request, then shut down exactly as `/api/shutdown` does
   (drain jobs, SIGTERM).

The browser shows "Restarting…" and polls `/health` until it reports a
version, then reloads.

### 5.1 Plan file

```json
{"plan_version": 1, "kind": "source|standalone",
 "from_version": "3.33.0", "to_version": "3.34.0",
 "install_dir": "...", "rollback_dir": "...",
 "staging_root": "<BASE_DIR>/.update/staging",
 "staging_dir": "<staging_root>/<the zip's top folder>",
 "download_dir": "<BASE_DIR>/.update/download",
 "pid": 1234, "port": 5000,
 "restart_argv": ["..."], "restart_cwd": "...",
 "db_path": "...", "db_backup": "...",
 "status_path": "<BASE_DIR>/data/update_status.json",
 "log_path": "<BASE_DIR>/logs/update.log"}
```

### 5.2 The helper (`updater_apply.py`, standard library only)

`app.py` hands `--apply-update` to it before importing anything else, so
the standalone binary can run it without starting a server or touching the
database.

1. Wait up to 120 s for `pid` to exit.
2. Swap, recording every step in `rollback_dir`:
   - **standalone:** move the old `_internal/` and every top-level file the
     new tree also has (program, start script, `install-launcher.sh`,
     `packaging/`) into `rollback_dir`, then copy the new ones in. Copied,
     not moved: the helper is itself running from the staging tree.
   - **source:** for every file in the new tree, move the existing file (if
     any) into `rollback_dir`, then copy the new one in; remember files that
     are new. Files the previous update installed (`.update/manifest.json`)
     that the new version no longer has are moved to `rollback_dir` too.
     Afterwards write the new manifest.
   - **Never written, whatever the archive holds:** `config.py`,
     `database/`, `logs/`, `.update/`, `data/settings.json`,
     `data/scraper_settings.json`, `data/rom_tools_config.json`,
     `data/psn_tokens.json`, `data/xbox_tokens.json`, `data/.secret_key`,
     and every file under `static/images/` and `static/videos/` that the
     new tree does not itself ship.
3. **source only:** when `requirements.lock` changed, run the new tree's
   `installer_core.pip_install(select_pip_args(...))` with the install's own
   Python. A failure rolls back.
4. Start `restart_argv` in `restart_cwd`, detached, with
   `RETRODB_OPEN_BROWSER=0` (the open tab reloads itself), output appended
   to `log_path`.
5. Poll `http://127.0.0.1:<port>/health` for up to 180 s (the standalone
   warms its upscaler first). Success is a 200 whose `version` is
   `to_version`.
6. **Success:** write `status_path` `{"result": "updated", ...}`, delete the
   download, and on Linux/macOS the staging tree. `rollback_dir` stays until
   the next update, for a manual revert.
7. **Failure** (swap error, dependency install error, no healthy start):
   stop the new process, put every recorded file back, remove files the
   update added, restore the database from `db_backup` (removing `-wal` /
   `-shm`), start the old version the same way, and write
   `{"result": "rolled_back", "reason": ...}`.

On the next status request the old/new app reads `status_path` once,
shows the outcome to the admin, and removes leftovers the helper could not
(the Windows staging tree) once the helper's process is gone.

## 6. API (admin only)

| Route | Does |
|---|---|
| `GET /api/updates/status` | current version, latest release (version, notes, page URL, published date), `available`, `can_install` + `reason`, job state and progress, last result. Starts a background check when the cached one is over 24 h old and `update_check_auto` is on. |
| `POST /api/updates/check` | check now |
| `POST /api/updates/download` | start §4 |
| `POST /api/updates/install` | §5 |

Errors are the usual `error(...)` envelope (`docs/specs/api-contracts.md`).
Release notes are GitHub's release body, shown as plain text.

## 7. Threat model

What makes a download trustworthy here is HTTPS to GitHub plus the checksum
published with the release: a truncated, corrupted or CDN-substituted file
installs nothing. Someone who can publish a release on the repository can
also change its checksums, and could equally push code, so this adds no new
trust in anyone. Verifying the cosign keyless signatures `release.yml`
already attaches would also bind the file to the release workflow; it needs
the `sigstore` package and is a follow-up (roadmap).

Only admins can check, download or install. The URL prefix check keeps the
updater on the RetroDB release host. Archive extraction refuses path escape
and symlinks.

## 8. Settings

`update_check_auto` (bool, default on): the daily background check.
Settings > System > Updates has the toggle.

## 9. Verification

- Unit: version comparison, asset choice per install kind and platform,
  checksum parsing, URL prefix check, extraction refusing `..`, absolute
  paths and symlinks and keeping executable bits, the protected-path list.
- Helper end to end with a fake install: a tiny server script stands in for
  the app and answers `/health` with its version. Covers success, a new
  version that never becomes healthy (rollback restores files, removes added
  files, restores the database and restarts the old one), and the manifest
  removing files a later version dropped.
- Routes: admin-only, state machine refusals.
