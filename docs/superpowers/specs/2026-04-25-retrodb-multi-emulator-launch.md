# RetroDB — Multi-Emulator Launch (Design)

> **Historical record.** This shipped as Pass 44 in v3.6.2 (commit `1a70052`). Copied from the retired `retroarch-frontend-design` workspace on 2026-10-13. The launcher is now governed by `docs/specs/PASS-59-64-launcher.md`; paths below still name the retired `/mnt/Storage` drive.

**Date:** 2026-04-25
**Target repo:** `/mnt/Storage/Scripts/Linux/RetroDB/`
**Author:** drafted via brainstorm session in `/mnt/Storage/Scripts/Linux/RetroArch/`
**Status:** awaiting user review
**Implementation handoff:** the active Claude Code session working in RetroDB

---

## Summary

Add a "Play" button to RetroDB game pages that launches each game in the right emulator — RetroArch for some platforms, DuckStation for PS1, PCSX2 for PS2, RPCS3 for PS3, Dolphin for GameCube/Wii, and so on. Per-platform default with per-game override. Standalone emulators are invoked directly; RetroArch is invoked with a per-platform core. The launcher backend is abstracted behind a `Launcher` interface so a future remote-launch agent (running on a separate TV-connected box) drops in without changing routes or UI.

## Goals (v1)

1. Click ▶ Play on a game → the right emulator opens with that ROM, no manual config per game.
2. RetroDB-native administration: registry editable in the web UI under Settings → Emulators, persisted in the SQLite DB, backed up with the rest of the data.
3. Multiple emulators per platform, with one marked default. Per-game override and per-game custom args.
4. RetroArch supported as a special case with explicit binary + cores-dir settings, since on Linux those usually live in different prefixes.
5. RBAC: a new `Player` role between Viewer and Editor — can launch and track play progress but cannot edit metadata or delete. Existing roles (Admin, Editor, Viewer) are extended, not changed.
6. Abstraction in place for a future remote-launch backend (split-box deployment) without rewriting the launch path.

## Non-goals (v1)

- Standalone RetroArch-only desktop frontend (Solution B in the brainstorm) — separate spec, after this lands.
- Playtime auto-tracking in a `launch_sessions` table — follow-on (the in-memory token registry can grow into a DB-backed one).
- Pre-launch / post-launch hook scripts (CPU governor, mute Discord, etc.).
- Kiosk / desktop-takeover mode.
- Controller-driven launch UX.
- ES-DE config import (would land as a v1.1 polish; design leaves room for it).
- Remote-launcher implementation (the `Launcher` interface is shipped, but only `LocalLauncher` exists).
- Parental controls: age-rating gating, hidden adult titles, time limits, per-game allowlists, "kid mode." The Player role is a coarse permission split, not a content filter. Those concerns are a separate future spec.

## Architecture

```
 Browser                  Flask routes              Services                 OS
 -------                  ------------              --------                 --
   │
   │ POST /api/game/42/launch
   ├────────────────────────►  routes/launch.py
   │                              │
   │                              │ resolve_launch_context(game_id=42)
   │                              ├──────────────────►  services/launch_resolver.py
   │                              │                       │
   │                              │                       │ SELECT game JOIN system_emulators ...
   │                              │                       │ → emulator + binary + args_template
   │                              │                       │ → substitute {rom}, {retroarch_core}, ...
   │                              │ ◄─────────────────────┤
   │                              │   LaunchContext(binary, argv, cwd, env)
   │                              │
   │                              │ get_launcher().launch(ctx)
   │                              ├──────────────────►  services/launcher/local.py
   │                              │                       │
   │                              │                       │ subprocess.Popen([...])
   │                              │                       ├──────────────────────────►  duckstation-qt
   │                              │ ◄─────────────────────┤   (or retroarch -L core, pcsx2-qt, ...)
   │                              │   LaunchHandle(token, pid)
   │ ◄────────────────────────────┤
   │   202 Accepted { token }
```

All services live in-process (same Flask worker as the rest of RetroDB). `LocalLauncher`'s in-memory token registry is process-scoped — acceptable for v1 single-worker dev; if/when RetroDB switches to a multi-worker WSGI server, see "Future work" §F1.

## Roles & permissions

The launch feature introduces a coarse split between "edits the catalog" and "plays games" that the existing three-role structure doesn't cleanly express. Adding one new role (`Player`) and two new permissions (`launch`, `track_progress`) covers the household / multi-user case without RBAC sprawl.

### `services/auth.py::ROLE_PERMISSIONS` — final shape after edit

```python
ROLE_PERMISSIONS = {
    'admin':  {'view', 'edit', 'delete_metadata', 'delete_rom', 'scrape',
               'manage_users', 'manage_settings', 'system_functions',
               'launch', 'track_progress'},                    # 2 added to existing
    'editor': {'view', 'edit', 'delete_metadata', 'scrape',
               'launch', 'track_progress'},                    # 2 added to existing
    'player': {'view', 'launch', 'track_progress'},            # NEW ROLE
    'viewer': {'view'},                                         # unchanged
}
```

Permission semantics:

| permission | gates |
|---|---|
| `launch` | `POST /api/game/<id>/launch`, `POST /api/launch/<token>/kill`. (`GET .../status` and `GET /api/launches/active` are `view`-only — same as a Viewer being able to see what someone else is doing.) |
| `track_progress` | `POST /api/game/<id>/completion` (`routes/games.py:1101`), `POST /api/game/<id>/track-view` (`routes/games.py:1119`), and any future write-on-play endpoints (e.g. last-played timestamp, future `launch_sessions` playtime updater). |

These are the **only** routes whose decorators change as part of this pass. Everything else keeps its current `@admin_required` / `@editor_required` decorator. In particular: Player **cannot** edit game metadata, manage scrape, manage users, or change settings. The two existing `track-view` / `completion` endpoints are upgraded from "any logged-in user" (current state) to "users with `track_progress` permission" — Editor and Admin retain access; Viewer loses it; Player gains it. Viewers losing this is intentional: you couldn't realistically track progress as a Viewer because you couldn't launch the game in the first place.

### Decorator — already exists

`services/auth.py:237` already provides `@permission_required(permission)` — a decorator factory that gates a route on a permission string from `ROLE_PERMISSIONS`. The launch routes use this verbatim; **no new decorator code is required**. The existing `@admin_required` / `@editor_required` decorators stay as-is for backward-compat (other routes continue to use them).

For dynamic permission-from-settings (the launch endpoint, which reads `launch_required_permission` at request time so admins can change it without a restart), the route uses `has_permission(get_setting(...))` inline rather than the decorator factory:

```python
@bp.route('/api/game/<int:game_id>/launch', methods=['POST'])
@login_required
@handle_api_errors
def api_launch_game(game_id):
    required = get_setting('launch_required_permission', 'launch')
    if not has_permission(required):
        return error(f'This action requires the "{required}" permission', 403)
    # ... resolve + launch ...
```

The other launch endpoints take their permission as a fixed string and use `@permission_required('launch')` / `@permission_required('view')` directly.

### User management UI and validation

RetroDB has admin-only user creation (no self-registration — `routes/auth.py:166 api_create_user`); newly-created users default to `viewer` and that stays unchanged. Two existing role-allowlists in `routes/auth.py` must be widened to include `'player'`:

- `routes/auth.py:176` — `api_create_user` allowlist `['admin', 'editor', 'viewer']` → add `'player'`.
- `routes/auth.py:227` — `api_update_user` allowlist (same list) → add `'player'`.

The shared list should be hoisted to a module constant (`VALID_ROLES = tuple(ROLE_PERMISSIONS.keys())` in `services/auth.py`) so future role additions only touch one place. The user-create / user-edit templates get `Player` added to the role `<select>`.

No data migration: `users.role` is `TEXT NOT NULL DEFAULT 'viewer'` with no CHECK constraint (`services/database_init.py:90`), so no schema change is required for the new value. Existing users keep their current role.

### Setting change

`launch_required_role` becomes `launch_required_permission`, defaulting to `"launch"`. Reasoning: more flexible (admins can later define new roles by editing `ROLE_PERMISSIONS` without changing the setting), and the launch routes are already built around the permission check rather than a role check. The setting is only consulted by the route to allow tightening (e.g. set to `"edit"` to require Editor or higher even though the default permission is broader). Default is the matching permission name, so out-of-the-box behavior is "anyone with the `launch` permission can launch."

This replaces the `launch_required_role` key in the §Settings section.

## Data model — migration `010_emulators.py`

Mirrors the existing `controllers` / `system_controllers` / `is_default` shape established by the controllers feature (`routes/controllers.py`).

```sql
CREATE TABLE IF NOT EXISTS emulators (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL UNIQUE,        -- "DuckStation", "PCSX2", "RetroArch"
    binary_name           TEXT NOT NULL,                -- "duckstation-qt", "pcsx2-qt", "retroarch"
    binary_path_override  TEXT,                         -- absolute path; NULL = settings/PATH lookup
    args_template         TEXT NOT NULL,                -- '-batch -fullscreen "{rom}"'
    is_retroarch          INTEGER NOT NULL DEFAULT 0,
    description           TEXT,
    enabled               INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT,
    updated_at            TEXT
);

CREATE TABLE IF NOT EXISTS system_emulators (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id       INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
    emulator_id     INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
    is_default      INTEGER NOT NULL DEFAULT 0,
    retroarch_core  TEXT,                               -- bare filename: "snes9x_libretro.so" — required iff emulator.is_retroarch=1
    extra_args      TEXT,                               -- per-system flags appended to args_template
    UNIQUE(system_id, emulator_id)
);

ALTER TABLE games ADD COLUMN emulator_override_id INTEGER REFERENCES emulators(id);
ALTER TABLE games ADD COLUMN launch_args_override TEXT;

CREATE INDEX IF NOT EXISTS idx_system_emulators_system  ON system_emulators(system_id);
CREATE INDEX IF NOT EXISTS idx_system_emulators_default ON system_emulators(system_id, is_default);
```

Migration file follows the project convention: `services/migrations/scripts/010_emulators.py` with an idempotent `apply(conn)` function. Use `_add_column_if_missing` for the two `games` columns so legacy DBs don't error on re-run.

### Seed data

`data/emulator_seeds.json` (new) — read on first run and merged with `INSERT OR IGNORE ... WHERE NOT EXISTS` semantics keyed by `emulators.name` and the `(system_id, emulator_id)` pair. Re-running the import never duplicates rows.

v1 seed list (12 emulators + per-system mapping for known systems):

| name | binary_name | args_template | is_retroarch |
|---|---|---|---|
| RetroArch | retroarch | `-L "{retroarch_core}" "{rom}"` | 1 |
| DuckStation | duckstation-qt | `-batch -fullscreen "{rom}"` | 0 |
| PCSX2 | pcsx2-qt | `-batch -fullscreen "{rom}"` | 0 |
| RPCS3 | rpcs3 | `--no-gui "{rom}"` | 0 |
| Dolphin | dolphin-emu | `-b -e "{rom}"` | 0 |
| Cemu | cemu | `-g "{rom}" -f` | 0 |
| ScummVM | scummvm | `--fullscreen --path="{rom_dir}"` | 0 |
| MAME | mame | `-rompath "{rom_dir}" "{rom_name}"` | 0 |
| mGBA | mgba-qt | `-f "{rom}"` | 0 |
| melonDS | melonDS | `"{rom}"` | 0 |
| Citra | citra-qt | `"{rom}"` | 0 |
| PPSSPP | PPSSPPSDL | `--fullscreen "{rom}"` | 0 |

Seed `system_emulators` entries map RetroDB's existing system names (Sony Playstation → DuckStation default + RetroArch (Beetle PSX HW) alternate; Nintendo SNES → RetroArch (snes9x) default; etc.). Full seed list lives in the JSON file — see `data/emulator_seeds.json` content scaffolded in §Implementation.

## Settings (RetroDB-wide)

New keys in `data/settings.json` (loaded via `settings_manager.py`):

```json
{
  "retroarch_binary":              "",
  "retroarch_cores_dir":           "",
  "launcher_backend":              "local",
  "launch_required_permission":    "launch",
  "launch_concurrent_same_game":   "reject"
}
```

| key | type | meaning |
|---|---|---|
| `retroarch_binary` | str | Absolute path to the `retroarch` executable. Empty = fall back chain in resolver. May literally be `flatpak run org.libretro.RetroArch` (split on whitespace, first token must be `flatpak` or absolute path). |
| `retroarch_cores_dir` | str | Directory containing `*_libretro.{so,dll,dylib}` cores. Empty = fall back chain. |
| `launcher_backend` | enum: `"local"` \| `"remote"` | Selects `Launcher` impl in the factory. v1 only `"local"` is implemented; setting to `"remote"` errors on launch. |
| `launch_required_permission` | str — any permission key in `ROLE_PERMISSIONS` | Permission required to call `POST /api/game/<id>/launch`. Defaults to `"launch"` (so Admin / Editor / Player can all launch). Set to `"edit"` to restrict to Editor/Admin only, etc. See §Roles & permissions. |
| `launch_concurrent_same_game` | enum: `"reject"` \| `"kill_and_relaunch"` | Behavior when `Play` is clicked on a game that's already running. |

### RetroArch path auto-detect

Implemented as a one-shot probe invoked from a new endpoint `POST /api/settings/retroarch/detect` (called by an `Auto-detect` button in the Emulators settings page). Probe order:

| Field | Probe order (first match wins) |
|---|---|
| `retroarch_binary` | `/usr/bin/retroarch` → `/usr/local/bin/retroarch` → `~/.local/bin/retroarch` → `flatpak info org.libretro.RetroArch` returns 0 → store `flatpak run org.libretro.RetroArch` → `shutil.which("retroarch")` |
| `retroarch_cores_dir` | `~/.config/retroarch/cores/` → `/usr/lib64/libretro/` → `/usr/lib/libretro/` → `/var/lib/flatpak/exports/share/libretro/cores/` |

Validation runs whenever the value changes (or on the same endpoint with `validate=true`):

- Binary: must be executable; `--version` (5s timeout) must produce stdout containing `"RetroArch"`.
- Cores dir: must exist; must contain at least one `*_libretro.so` (or `.dll` / `.dylib` to keep the design portable).

Status returned: `{"binary": {"path": "...", "version": "1.22.2"}, "cores_dir": {"path": "...", "core_count": 47}}` or per-field `{"error": "..."}`.

## Args template language

A deliberately small substitution syntax — **not** general-purpose templating. Every variable is `shlex.quote`d at substitution time. The fully-substituted string is then `shlex.split`-ed into `argv`; `Popen` is invoked with `shell=False`.

| token | value |
|---|---|
| `{rom}` | absolute path to the primary ROM file |
| `{rom_dir}` | dirname of `{rom}` |
| `{rom_name}` | basename of `{rom}` without final extension |
| `{retroarch_core}` | absolute path to the resolved core file (only present when `emulators.is_retroarch=1`) |
| `{disc_paths}` | space-separated absolute paths from `bonus_discs` for this game (multi-disc) |
| `{system_extra_args}` | `system_emulators.extra_args` (auto-appended; explicit token form available when ordering matters) |
| `{game_extra_args}` | `games.launch_args_override` (auto-appended; explicit token available) |

Default expansion order if no explicit `{system_extra_args}` / `{game_extra_args}` tokens appear in `args_template`: `<args_template>` + ` ` + `<extra_args>` + ` ` + `<launch_args_override>`. If either token appears explicitly, it's substituted in place and not auto-appended.

Unknown `{tokens}` raise `LaunchResolutionError("Unknown template variable: {x}")` — fail loud, never silently empty-substitute.

## Resolution algorithm

`services/launch_resolver.py::resolve_launch_context(game_id) -> LaunchContext`:

1. `SELECT * FROM games WHERE id = ?`. 404 if missing.
2. Pick emulator:
   1. If `games.emulator_override_id` IS NOT NULL → that emulator.
   2. Else `SELECT FROM system_emulators WHERE system_id = ? AND is_default = 1`.
   3. Else `SELECT FROM system_emulators WHERE system_id = ? ORDER BY id LIMIT 1`.
   4. Else raise `LaunchResolutionError("No emulator configured for system <name>")` → 422 in route.
3. Verify `emulators.enabled = 1`. Else raise.
4. Resolve binary:
   - If `is_retroarch` → use `settings.retroarch_binary` else `binary_path_override` else `shutil.which(binary_name)`. If the result is a multi-token string (e.g. `flatpak run …`), split on whitespace; first token must be `flatpak` or an absolute path; bail otherwise.
   - Non-RA → `binary_path_override` else `shutil.which(binary_name)`. 422 if not found.
5. Resolve core (RA only): join `settings.retroarch_cores_dir` with `system_emulators.retroarch_core`. The file must exist; 422 otherwise. The default cores dir falls back to `~/.config/retroarch/cores/` if the setting is empty.
6. Build template variables and substitute via `str.format_map(SafeDict(...))` where `SafeDict.__missing__` raises `LaunchResolutionError("Unknown template variable: {x}")` (no silent blanks). All seven tokens in the §Args template language table are always present in the map (empty string when there's no value, e.g. `{disc_paths}` for a single-disc game), so they never trigger the missing-key path.
7. Auto-append `extra_args` / `launch_args_override`: if the template did **not** contain the literal substring `{system_extra_args}`, append ` ` + `system_emulators.extra_args` (when non-empty) to the substituted string. Same for `{game_extra_args}` and `games.launch_args_override`. The check is on the **pre-substitution** template string.
8. `shlex.split` the final string → `argv`.
9. Validate `rom_path`: must exist, must be a regular file, must resolve under one of the configured ROM root directories (existing RetroDB scan paths; reject otherwise to defeat path traversal via DB tampering).
10. Return `LaunchContext(binary=Path, argv=List[str], cwd=Path|None, env=dict|None, game_id, emulator_id, token=secrets.token_urlsafe(12))`.

## Service layer

```
services/launcher/
  __init__.py           # get_launcher() factory; reads settings.launcher_backend
  base.py               # Launcher Protocol; LaunchContext, LaunchHandle, LaunchStatus dataclasses;
                        # LaunchResolutionError, LauncherError, BinaryNotFoundError
  local.py              # LocalLauncher: subprocess.Popen + in-process registry
  registry.py           # ProcessRegistry: thread-safe {token: (Popen, started_at, game_id, emulator_id)}
                        # GC pass on every status() call; entries linger 1h after exit so the UI can
                        # surface "exited 30s ago, exit code 1"
services/launch_resolver.py   # game_id -> LaunchContext (DB lookup + template render + validation)
```

### `Launcher` Protocol

```python
@dataclass(frozen=True)
class LaunchHandle:
    token: str
    pid: int
    game_id: int
    emulator_id: int
    started_at: float

@dataclass
class LaunchStatus:
    state: Literal["running", "exited"]
    exit_code: int | None
    runtime_s: float

class Launcher(Protocol):
    def launch(self, ctx: LaunchContext) -> LaunchHandle: ...
    def status(self, token: str) -> LaunchStatus: ...
    def kill(self, token: str, *, timeout_s: float = 5.0) -> LaunchStatus: ...
    def active(self) -> list[LaunchHandle]: ...
```

`LocalLauncher.kill` sends `SIGTERM`, polls every 100ms for `timeout_s`, then `SIGKILL`. Returns the final `LaunchStatus`.

## Routes — `routes/launch.py`

| Method | Path | Decorator | Behavior |
|---|---|---|---|
| POST | `/api/game/<int:game_id>/launch` | `@permission_required(settings["launch_required_permission"])` | Resolve + launch. **202** with `{token, pid, emulator: {id,name}, argv, started_at}`. **403** if user lacks the configured launch permission. **404** if game missing. **409** if same `game_id` already running and policy=`reject` (body includes `existing_token`). **422** on resolver failure (missing emulator, binary not found, rom missing, core missing). **500** on `OSError` from `Popen`. |
| GET | `/api/launch/<token>/status` | `@permission_required('view')` | **200** `{state, exit_code, runtime_s, game_id, emulator_id}`. **404** if token unknown. Any logged-in user can poll status. |
| POST | `/api/launch/<token>/kill` | `@permission_required('launch')` | **200** with the post-kill `LaunchStatus`. **404** if unknown. **403** RBAC. Admin can additionally kill any token via the future "kill any" admin endpoint; v1 only allows kill if the caller has `launch`. |
| GET | `/api/launches/active` | `@permission_required('view')` | **200** `{launches: [LaunchHandle...]}`. Used by the nav indicator. |
| POST | `/api/settings/retroarch/detect?validate=true\|false` | `@admin_required` | Runs the auto-detect probe (see §RetroArch path auto-detect). **200** with `{binary: {...}, cores_dir: {...}}`. Admin-only since it writes settings. |

The launch decorator reads the setting *at request time* (not at import time) so admins can change `launch_required_permission` without restarting Flask.

Emulator-registry CRUD lives in a separate blueprint `routes/emulators.py` — endpoints to be enumerated in the implementation plan. The shape mirrors `routes/controllers.py`.

Response helpers: use `success(...)` / `error(...)` per RetroDB Pass 2 convention. Body shapes documented above are the **payload inside `data:`** field.

## UI surface

Three additions to existing pages — no new top-level nav.

### Game detail page (`templates/game_detail.html`)

- New primary button next to "Edit": **▶ Play** (Bootstrap `btn-success`).
- Right of it: a small label `via <emulator_name>`. Hovering it shows a tooltip with the resolved argv. Clicking opens the existing edit modal scrolled to the new "Launch" section.

### Edit-game modal (`templates/_modals/...` — existing)

Two new fields under a "Launch" section:
- `Emulator override` — `<select>` populated from `GET /api/emulators/for-system/<system_id>` (returns the system's `system_emulators` rows + an `(auto)` first option meaning "use system default"). Persists to `games.emulator_override_id`.
- `Custom launch args` — free-text. Persists to `games.launch_args_override`. Inline help: "Appended to the emulator's args template after substitution. Use shell-quoted strings."

### New page — Settings → Emulators (`/settings/emulators`)

Two tabs:

**Tab 1: Emulators (registry CRUD)**
- Table: name, binary, version-detected (live-probed), default-for-N-systems, enabled toggle, edit, delete.
- Add / edit modal: name, binary_name, binary_path_override (with file picker), args_template (textarea with template-variable cheat-sheet), is_retroarch, description, enabled.

**Tab 2: Per-system mapping**
- For each system in `systems` table, a row with chips of currently-mapped emulators (one marked default with a star). Click a chip to edit its `extra_args` and (if RetroArch) `retroarch_core` filename. "Add emulator" button to map a new one.

**RetroArch panel (pinned at top of the page)**

```
┌─ RetroArch ──────────────────────────────────────────────┐
│ Binary       [/usr/bin/retroarch                ] [Pick] │
│ Cores dir    [/home/me/.config/retroarch/cores/ ] [Pick] │
│                                          [Auto-detect]   │
│  ✓ retroarch 1.22.2 found · 47 cores in cores dir         │
└──────────────────────────────────────────────────────────┘
```

The status line is populated by `POST /api/settings/retroarch/detect?validate=true` on page load and after any field change. `[Pick]` opens a server-side directory/file picker — reuse RetroDB's existing path picker if there is one (used elsewhere in Settings); otherwise this is a v1 polish item that can ship as a plain text input first.

### Top-nav indicator

A small ▶ badge appears in the existing top-nav (next to the user menu) when `GET /api/launches/active` returns non-empty. Polled every 5s when the page is foregrounded. Clicking opens a popover listing active launches with title, emulator, runtime, and a Kill button. Implemented as a small JS partial wired into `base.html`.

## Edge cases

| case | behavior |
|---|---|
| Binary not found | 422, message `"Emulator binary not found: <name>"`. UI shows toast + link to Settings → Emulators. |
| Cores dir not set + RA emulator selected | Resolver applies fallback `~/.config/retroarch/cores/`. If still missing the specific core, 422 with the core filename. |
| Multi-disc game | `bonus_discs` rows for the game contribute to `{disc_paths}`. RetroArch entries that need an `.m3u` are out of scope for v1 — users can produce one with the existing ROM tools and point `rom_path` at the `.m3u`. DuckStation et al. auto-detect siblings of disc 1. |
| Archive ROM (`.zip` / `.7z`) | Passed through verbatim. v1 does not auto-extract. RetroArch handles `.zip`; standalone emulators vary — that's the user's responsibility per their existing workflow. |
| Concurrent launch of same game | `launch_concurrent_same_game="reject"` (default) → 409 with `existing_token`. UI offers "Kill & relaunch" which issues `POST /api/launch/<existing_token>/kill` then re-issues the launch. `"kill_and_relaunch"` → the launch endpoint does both within a single request: it locates the existing handle, calls `LocalLauncher.kill(token)` (which blocks up to `timeout_s` for SIGTERM then SIGKILL), removes the entry from the registry, and only then proceeds with the new launch. The endpoint does not return until the new process is spawned. |
| Concurrent launch of different games | Allowed. The resolver makes no global lock. |
| Emulator exits immediately (bad path / missing BIOS) | Detected on the first `status` poll; UI surfaces `exit_code` and the `stderr` tail (LocalLauncher captures last 4KB of stderr). |
| Path traversal in `rom_path` | Resolver re-validates the path is under a configured ROM root (existing scan paths). Rows whose `rom_path` no longer resolves there are rejected at launch time. |
| Symlink in cores dir | Allowed (resolved). |
| Unicode in paths | Use `Path` and `subprocess.list2cmdline` won't be involved — `argv` is a list, paths are passed as `str`. |
| RetroArch flatpak | `retroarch_binary = "flatpak run org.libretro.RetroArch"`. Resolver splits on whitespace; `argv[0]` becomes `"flatpak"`, the rest are prepended. The cores dir setting must point at the flatpak's exposed cores dir (`~/.var/app/org.libretro.RetroArch/config/retroarch/cores/`). |
| `retroarch_cores_dir` outside `argv[0]`'s flatpak sandbox | Won't work; document in the field's help text. Out of scope to auto-bridge. |

## Security

- **Command injection.** Templates use `str.format_map` then `shlex.split`. No `shell=True`. Every variable is `shlex.quote`d before substitution. Test: feed `rom_path = "; rm -rf /"`; verify it's quoted into a single argv token.
- **Binary allowlist.** `binary_name` and `binary_path_override` are validated:
  - `binary_name`: matches `^[a-zA-Z0-9._-]+$`.
  - `binary_path_override`: must be absolute, must exist, must be executable (`os.access(p, os.X_OK)`).
  - Special-cased: `retroarch_binary = "flatpak run <app-id>"` where `<app-id>` matches `^[a-zA-Z0-9._-]+$`.
- **RBAC.** Launch endpoints check `has_permission(settings["launch_required_permission"])` (default `"launch"`). Viewer cannot launch; Player, Editor, Admin can. The `track_progress` endpoints (`completion`, `track-view`) tighten from "any logged-in user" to `track_progress`-permission only — Viewer loses access (intentional: they can't launch the game so progress tracking is meaningless), Player gains it.
- **CSRF.** Existing RetroDB CSRF middleware (if present) covers the new POST endpoints. If RetroDB doesn't currently have CSRF on `POST /api/...` endpoints, this spec doesn't add it — note as a roadmap item.
- **Rate-limit.** Out of scope for v1. A single-user instance with editor RBAC is sufficient. Note as a follow-on for multi-user public deployments.

## Testing

Following RetroDB's `tests/test_*.py` convention:

| file | covers |
|---|---|
| `tests/test_launch_resolver.py` | Template substitution, override precedence (game > system-default > system-fallback > error), missing-emulator error, RetroArch core path resolution, multi-disc `{disc_paths}`, unknown-token error, path-traversal rejection. |
| `tests/test_launcher_local.py` | Uses `/bin/sleep 60` as a fake emulator. Verifies launch / status / kill (TERM then KILL) / token registry / 409 on dup / GC of expired entries / stderr capture. |
| `tests/test_routes_launch.py` | Mocks `LocalLauncher`. Verifies RBAC (viewer→403, player→202, editor→202, admin→202), 422 / 409 / 404 / 500 wire shapes, response uses `success()`/`error()` helpers. |
| `tests/test_auth_player_role.py` | `has_permission('launch')` for each role; `permission_required('launch')` decorator integration with the new role; `ROLE_PERMISSIONS` shape; `track-view` and `completion` re-gating (viewer→403 after change). |
| `tests/test_emulator_registry_routes.py` | CRUD on `/settings/emulators` and `/settings/systems/<id>/emulators`. Idempotent re-seed. |
| `tests/test_retroarch_detect.py` | Auto-detect probe with mocked filesystem. Validation success/failure paths. |
| `tests/test_migration_010.py` | Idempotent re-apply, `_add_column_if_missing` semantics on the `games` columns. |

Coverage target: existing project floor (services/* and routes/*).

## Implementation plan (file-by-file)

A separate implementation plan will be produced via the `writing-plans` skill once this design is approved. The expected file changes are:

**New files:**
```
services/migrations/scripts/010_emulators.py
services/launch_resolver.py
services/launcher/__init__.py
services/launcher/base.py
services/launcher/local.py
services/launcher/registry.py
routes/launch.py
routes/emulators.py                            # registry CRUD + system mapping
data/emulator_seeds.json
templates/settings_emulators.html
templates/_modals/_emulator_edit_modal.html
templates/_partials/_retroarch_panel.html
static/js/emulators_settings.js
static/js/launch_indicator.js                  # nav-bar badge + popover
tests/test_launch_resolver.py
tests/test_launcher_local.py
tests/test_routes_launch.py
tests/test_emulator_registry_routes.py
tests/test_retroarch_detect.py
tests/test_migration_010.py
```

**Modified files:**
```
app.py                                         # register new blueprints
services/auth.py                               # ROLE_PERMISSIONS additions, VALID_ROLES constant (permission_required decorator already exists)
routes/auth.py                                 # widen create/update role allowlists to include 'player' (lines 176, 227); switch to VALID_ROLES
routes/games.py                                # re-gate completion + track-view to @permission_required('track_progress')
templates/game_detail.html                     # ▶ Play button + via-emulator label
templates/base.html                            # nav-bar launch indicator hook
templates/_modals/<existing-edit-modal>        # add Launch section
templates/<user-management-page>               # add "Player" to role dropdown (admin-only UI)
config.py / config.example.py                  # APP_VERSION + APP_LAST_UPDATE bump
data/changelog.yaml                            # changelog entry at top
data/settings.json                             # add the 5 new keys
services/settings_validators.py                # validators for the 5 new keys (incl. permission-string check)
roadmap.md                                     # mark this pass as done
docs/RETRODB_DESIGN_STANDARDS.md               # if a section on subprocess launching or new role helps; else skip
```

`services/database_init.py` is not modified: `users.role` has no CHECK constraint, so the new `'player'` value is accepted without a schema change.

Per RetroDB's CLAUDE.md mandatory workflow, the implementation must also: bump version (this is a minor — `x.N+1.0`), add changelog entry, rebuild CSS/JS if any bundled file changed, run pytest.

## Future work (out of scope, captured for context)

- **F1.** Multi-worker launcher backend. The in-memory `ProcessRegistry` is process-scoped. When/if RetroDB switches to gunicorn/uwsgi multi-worker, swap the registry for a SQLite-backed one (`launch_sessions` table) so any worker can answer status queries about any launch.
- **F2.** `launch_sessions` table + playtime auto-tracking (game total playtime, last-played).
- **F3.** Pre-launch / post-launch hook scripts (e.g. set CPU governor, mute Discord, switch audio output).
- **F4.** ES-DE config import (`es_systems.cfg` + `es_find_rules.cfg` → `emulators` + `system_emulators` rows).
- **F5.** Remote-launcher implementation: tiny Flask agent on a TV box, HTTPS + shared secret. The `Launcher` Protocol is already in place.
- **F6.** Solution B — standalone RetroArch-only desktop frontend. Separate spec; can reuse the `emulators`/`system_emulators` schema as a read source if it shares the SQLite DB, or define its own.
- **F7.** Per-emulator multi-piece path settings (PCSX2 BIOS dir, RPCS3 firmware dir, etc.) when a real need arises.
- **F8.** Controller-driven launch UX.
- **F9.** Parental controls / content filtering: rating-tier gating per user, hidden-from-Player flag per game, time-of-day windows, daily play-time caps. Builds on top of the Player role but is its own UX surface.
- **F10.** Per-user emulator preferences (e.g. one user prefers Beetle PSX HW, another prefers DuckStation for the same platform). Currently `emulator_override_id` is per-game; per-user overrides would need a (`user_id`, `game_id`) table.

## Open questions

None remaining at design time. Concrete tweaks captured during review will land as inline edits to this file before the implementation plan is written.

---

## Appendix A — `data/emulator_seeds.json` skeleton

The implementation will materialize this. Listed here so the shape is unambiguous.

```json
{
  "emulators": [
    {
      "name": "RetroArch",
      "binary_name": "retroarch",
      "args_template": "-L \"{retroarch_core}\" \"{rom}\"",
      "is_retroarch": 1,
      "description": "Reference libretro frontend; used per-platform via cores."
    },
    {
      "name": "DuckStation",
      "binary_name": "duckstation-qt",
      "args_template": "-batch -fullscreen \"{rom}\"",
      "is_retroarch": 0,
      "description": "Sony PlayStation (PS1)."
    }
    /* ... PCSX2, RPCS3, Dolphin, Cemu, ScummVM, MAME, mGBA, melonDS, Citra, PPSSPP ... */
  ],
  "system_emulators": [
    {
      "system_folder": "psx",
      "emulator_name": "DuckStation",
      "is_default": 1
    },
    {
      "system_folder": "psx",
      "emulator_name": "RetroArch",
      "retroarch_core": "mednafen_psx_hw_libretro.so",
      "is_default": 0
    }
    /* ... mappings keyed by `systems.folder` so the seed survives system_id renumbering ... */
  ]
}
```

System mappings reference systems by `systems.folder` (the existing UNIQUE column) rather than `id`, so the seed is portable across instances. The seeder resolves folder → id at apply time and skips entries whose folder isn't present.
