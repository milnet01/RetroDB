# PASS-59-64 — Launch contract: resolving, spawning and the bundled player

**Status:** spec draft (2026-09-26).
**Kind:** implement.
**Source:** ROADMAP PASS-59-64 (review-code launch lane 2026-09-01; scope
widened by user decisions 2026-09-26, relayed with the RetroArch fork session).
**Pairs with:** PASS-59-81 (core ranking, per-game settings presets, core
download). **Blocker for:** PASS-59-53, PASS-59-54, PASS-59-55, which implement
clauses of this spec.

Layman: this is the rulebook for how RetroDB starts a game — which program it
runs, what it tells that program, how it stops it — including the bundled
player that sets up cores and settings for you.

## 1. Goal

One contract for the launcher subsystem, so that each module in it can be
reviewed against intent rather than against its own docstrings. After this
ships, three things are true. The resolver's precedence, template expansion
and error reporting are defined and tested. The process registry has a
lifecycle something actually runs. And RetroDB can launch games in a bundled
player built from the RetroArch fork, handing it a core and per-game
settings, with changes the user makes during play kept as that game's
settings.

## 2. Problem

The code cites a spec that was never written:
`services/launch_resolver.py` ("spec §Resolution algorithm"),
`services/launcher/registry.py` ("spec §Future work F1") and
`services/launcher/__init__.py::get_launcher` ("spec §F5"). Against the code
as it stands:

1. **Binary precedence is inverted.** `launch_resolver.py::_resolve_binary`
   returns the `retroarch_binary` setting before it reads the emulator row's
   `binary_path_override`. The AppImage scanner in
   `routes/launch_settings.py::api_emulators_detect` writes an override that
   therefore cannot affect a RetroArch launch, and reports it as applied.
2. **Launch arguments are editor-writable and unchecked** (PASS-59-53).
   `games.launch_args_override` is written by the `edit_metadata` branch of
   `routes/games.py::game_detail`, which needs `edit`, and
   `resolve_launch_context` splits it straight into argv. An appended
   `-L <path>` makes RetroArch load any shared object as the server user.
3. **Three template variables cannot work as documented** (PASS-59-54).
   Substitution is per token after `shlex.split`, so a multi-word value
   becomes one argv element, and an empty one becomes an empty-string
   argument. An unbalanced quote in an extra-args field raises an uncaught
   `ValueError`, which `@handle_api_errors` turns into a 500 on every launch.
4. **`{disc_paths}` is always empty.** `_disc_paths_for_game` queries a
   `bonus_discs` table that no migration creates, and its bare
   `except Exception` returns `[]`. Bonus discs are really linked by
   `games.parent_game_id` and `games.is_bonus_disc`.
5. **The registry never collects garbage** (PASS-59-55).
   `ProcessRegistry.gc` has no production caller, so `_entries` grows for
   the life of the process, and `active()` polls every entry ever launched.
6. **`launcher_backend = 'remote'` is accepted and breaks every launch.**
   `settings_validators._ALLOWED_LAUNCHER_BACKENDS` contains `'remote'`, and
   `get_launcher` raises `NotImplementedError` for it.
7. **There is no player mode.** RetroDB launches the user's own RetroArch
   with `-L <core> <rom>` and nothing else, so every per-game setting is the
   user's job, in RetroArch.

## 3. Scope decisions (agreed with the user)

All 2026-09-26, by the user unless marked otherwise.

1. **Platforms:** Linux, Windows and macOS. Only Linux is built and tested
   here; the Windows and macOS clauses are marked *unverified*.
2. **Player argv** is RetroArch's own command line (§4.4). Existing config
   keys are preferred over new flags or fork code.
3. **I/O:** stdin and stdout are null. A fatal player error ends with one
   plain-language stderr line. Exit code 0 means success. Process exit is
   the "game exited" signal.
4. **Closing content quits the player process**, never returning to its
   menu.
5. **Shutdown is per platform** (§4.6). The fork session's source reading
   refined the mechanism: SIGTERM on Linux only, RetroArch's network `QUIT`
   on macOS and Windows.
6. **Ownership:** RetroDB owns the player profile directory, including the
   cores directory. It is kept apart from the user's own
   `~/.config/retroarch`. The player writes its saves, states, remaps and
   menu choices there.
7. **BIOS** is read from the user's existing RetroArch system directory.
   RetroDB never writes it.
8. **RetroAchievements login belongs to the player.**
9. **Nothing flows back** beyond the exit code, the stderr tail, and the
   settings files §4.5 reads after a session.
10. **The bundled player gets its own name**, described as "based on
    RetroArch", with no RetroArch logo. The name is not chosen, so this spec
    calls it *the player*.
11. **Step 1 is the fork's normal build**; a slimmed build comes later. The
    command-line contract in §4.4 does not change when it does.
12. **RetroDB applies the best settings per game automatically; the user
    can change them.** The ranking and the presets are PASS-59-81's. This
    spec carries them to the player.
13. **Changes made in the player's menu during play are kept** as that
    game's settings, win over RetroDB's recommended ones from then on, mark
    the game *customised*, and are undone by *Reset to recommended*.
14. **`launch_args_override` is admin-only**, like every other argv input.
15. **The player is its own emulator row**, the default wherever it has a
    core. The user's own RetroArch row stays selectable and launches exactly
    as today.
16. **(Author, by deduction from §3.13:)** a game override, a
    content-directory override and a core override saved from the player's
    menu are all absorbed into the launched game's settings. §3.13 says
    in-game changes are kept *as that game's settings*. Applying a core or
    folder save to other games is left out.
17. **(Author, by deduction from §2.4:)** `{disc_paths}` is retired, not
    repaired. No seeded or live template uses it (`grep -c disc_paths
    data/emulator_seeds.json` → `0`; the live `emulators` table holds none),
    and multi-disc games launch through the `.m3u` files RetroDB creates.
18. **(Author, by deduction from §2.1:)** the most specific binary source
    wins: the row's `binary_path_override`, then `retroarch_binary` for
    RetroArch rows, then `PATH`.
19. **(Author, by deduction from §2.6:)** the remote backend (`§F5`) is
    not planned. `'remote'` leaves the allowlist. The registry stays
    in-process (`§F1`); RetroDB's server is one waitress process, so that is
    a stated limit, not a defect.

## 4. Design

### 4.1 Resolution

`services/launch_resolver.py::resolve_launch_context(game_id)` keeps its
shape and its steps. The changes:

- **Binary:** `_resolve_binary` applies §3.18's order. An override that
  is set but not executable still raises `LaunchResolutionError`.
- **Template variables.** Scalar: `{rom}`, `{rom_dir}`, `{rom_name}`,
  `{retroarch_core}`. List: `{system_extra_args}`, `{game_extra_args}`. A
  template token that is *exactly* a list variable expands to zero or more
  argv elements, `shlex.split` of the value. A list variable inside a larger
  token raises `LaunchResolutionError`. `{disc_paths}` is removed, so a
  template using it gets the existing "Unknown template variable" error.
- **Parse errors:** every `shlex.split` (template, `extra_args`,
  `launch_args_override`) converts `ValueError` into a
  `LaunchResolutionError` that names the field. `routes/launch.py` already
  maps that to 422.
- **Auto-append** of extra args when the template lacks the token is kept.

### 4.2 Who may write argv inputs

`games.launch_args_override` is written only by a caller holding
`manage_settings`. The `edit_metadata` branch of `routes/games.py::game_detail`
leaves the stored value unchanged when the caller lacks it, and the edit
modal hides the field. Emulator rows (`routes/emulators.py`) and the
`retroarch_*` settings are already admin-only and stay so.

### 4.3 Process registry

- `LocalLauncher.active()` calls `ProcessRegistry.gc()` first, so exited
  entries older than `post_exit_ttl_s` (3600 s) are dropped on the next
  nav-badge poll.
- `routes/launch.py::api_launch_game` uses
  `ProcessRegistry.find_running_by_game` through the launcher rather than
  re-implementing it. `ProcessRegistry.remove` has no caller and is
  deleted.
- `'remote'` is removed from `_ALLOWED_LAUNCHER_BACKENDS`; `get_launcher`
  loses its `remote` branch.

### 4.4 The player: profile, row and argv

**Profile.** A RetroDB-owned directory, `<BASE_DIR>/data/player/`:

```
data/player/
  retroarch.cfg          # base cfg: created by RetroDB, then the player's
  cores/                 # RetroDB-owned; PASS-59-81 fills it
  settings/system/<system folder>.cfg
  settings/game/<game_id>.cfg
  settings/game/<game_id>.opt
  config/                # the player's config_directory (its own files)
  saves/  states/  remaps/
```

`BASE_DIR` is `config.BASE_DIR`, which is writable in a frozen build too.

**Row.** A new `emulators` row for the player, marked by a new column
`is_player INTEGER NOT NULL DEFAULT 0` (migration 016). It is
`is_default = 1` in `system_emulators` for every system PASS-59-81 gives a
core. The user's RetroArch row is untouched: no profile and no
`--appendconfig`.

**Base cfg keys** RetroDB writes before every player launch, overwriting
whatever the player saved there:

```
config_save_on_exit       = "false"
auto_overrides_enable     = "false"
game_specific_options     = "false"
global_core_options       = "false"
quit_on_close_content     = "2"      # quit when launched from the CLI
confirm_quit              = "false"  # required: see §4.6
ui_companion_start_on_boot = "false"
rgui_config_directory     = "<profile>/config"
savefile_directory        = "<profile>/saves"
savestate_directory       = "<profile>/states"
input_remapping_directory = "<profile>/remaps"
libretro_directory        = "<profile>/cores"
system_directory          = "<the user's RetroArch system dir>"
```

Verified by the fork session in its `local/fixes-2026-09` source: with
`config_save_on_exit = "true"`, the player writes the merged settings,
including RetroDB's appended ones, into the base cfg at quit. With
`auto_overrides_enable = "true"`, RetroArch's own override files layer over
RetroDB's settings. With either `.opt` key true, a `.opt` in the config
directory beats `core_options_path`.

These keys would work in an appended layer too. `config_load_file` merges
every `--appendconfig` file into one config before it reads any setting, so
an appended key behaves exactly like a base-cfg key (fork session,
`configuration.c`). They stay in the base cfg because RetroDB rewrites it
before every launch.

On macOS and Windows the base cfg also sets `network_cmd_enable = "true"`
(§4.6). RetroDB never sets it anywhere the user's own RetroArch reads:
upstream RetroArch binds that UDP port on every interface, while the fork
binds loopback only.

Verified by the fork session in `local/fixes-2026-09` as well:
`quit_on_close_content = "2"` exits when a core or content was given on the
command line, so it applies to RetroDB's `-L` launches but not to the
player opened bare.

**Game cfg.** RetroDB writes `settings/game/<game_id>.cfg` before every
launch. It holds at least
`core_options_path = "<profile>/settings/game/<game_id>.opt"`, plus the
per-game settings PASS-59-81 recommends or the user chose.

**argv** (the contract the fork's player binds to):

```
<player> --config <profile>/retroarch.cfg
         --appendconfig "<settings/system/<folder>.cfg>|<settings/game/<id>.cfg>"
         -L <absolute core path> <absolute content path>
```

`--appendconfig` is RetroArch's `RARCH_PATH_CONFIG_APPEND`: a `|`-separated
list applied in order over `--config`, so game beats system beats base. A
system cfg that does not exist is left out of the list. That is hygiene,
not a requirement: RetroArch skips an unreadable appended file, logs
"Failed to append config", and carries on (fork session,
`config_load_file`). Every path is absolute. No path in the list may
contain `|`.

### 4.5 Keeping in-game changes

- **Core options** changed in the player's menu are written by the player
  to `core_options_path`, the game's `.opt`.
- **Other settings** saved from the menu land as override files under the
  player's `rgui_config_directory` D, in `D/<core>/`: `<content file name
  without extension>.cfg` (game), `<content's parent directory name>.cfg`
  (folder), `<core>.cfg` (core). `<core>` is the core's runtime
  `library_name`, which RetroDB does not predict. After a player session
  exits, RetroDB looks in every subdirectory S of D for
  `S/<content file name without extension>.cfg`,
  `S/<content's parent directory name>.cfg` and `S/<S's own name>.cfg`.
  D is inside the RetroDB-owned profile, so any such file came from the
  player. RetroDB merges whichever exist into
  `settings/game/<game_id>.cfg`, core first, then folder, then game (§3.16),
  and deletes them. A missing file means nothing to absorb. Verified by the fork session: the file holds only the
  user's changes relative to the settings loaded for that launch, never
  RetroDB's own values echoed back.
- **Customised.** RetroDB stores the SHA-256 of each game file it writes.
  After a session, a game file whose hash differs, or that received
  absorbed keys, marks the game *customised*. From then on RetroDB
  regenerates only the keys the user has not set.
- **Reset to recommended** deletes the game's `.cfg` and `.opt` and clears
  the mark. The next launch writes fresh ones.

### 4.6 Output and shutdown

Output is unchanged from `services/launcher/local.py::LocalLauncher`:
`stdin` and `stdout` are `DEVNULL`, and stderr is drained into a tail of
`_STDERR_TAIL_BYTES` (4096) shown to the user on exit.

Stopping a player, as the fork session read its source:

- **Linux:** one SIGTERM. RetroArch's handler sets a flag, and the next
  frame runs a normal quit that unloads content and writes SRAM. A
  **second** SIGTERM calls `exit(1)` with no save, and a third calls
  `abort()`. So `kill()` sends SIGTERM **at most once per process**. A
  repeated kill request for a process already signalled only waits out the
  remaining grace, then escalates to SIGKILL. That quit also writes RTC
  data: `path_init_savefile_rtc` puts the `.rtc` file in the same save list
  as SRAM (fork session, `save.c`). The 5 s grace is unmeasured (§15 Q3).
- **macOS:** the fork sets no signal handler, so SIGTERM ends the process
  without a save. RetroDB sends `QUIT` over UDP to `127.0.0.1` on the
  launch's `network_cmd_port`, waits the grace, then SIGKILL. *Unverified at
  runtime.* `QUIT` is the quit key, so it obeys `confirm_quit`. With
  `confirm_quit = "true"`, one `QUIT` only shows "press again to quit",
  which is why §4.4 requires it false (fork session, `command.h`). `QUIT`
  is acted on with the menu open and while paused, except for a few frames
  after the menu opens or closes, when input flushing drops it silently. So
  if the process is still alive 1 s after the first `QUIT`, RetroDB sends
  one more before the grace runs out. With `confirm_quit` false a second
  `QUIT` is harmless (fork session, `runloop_check_state`).
- **Windows:** the same `QUIT`, then `TerminateProcess`, which cannot flush.
  *Unverified.*
- The port is chosen free per launch and written into a third
  `--appendconfig` layer, `<profile>/run/<token>.cfg`, which is deleted
  after the session. Two players must not share one port. RetroArch reads
  an appended `network_cmd_port` like a base-cfg key and builds the command
  interface after loading settings (fork session, `input_driver.c`).
- Every other emulator row keeps today's SIGTERM, grace, SIGKILL.

## 5. Invariants

- **INV-1** — A RetroArch row with both `binary_path_override` and the
  `retroarch_binary` setting set launches the override.
  *Test:* `tests/test_launch_resolver.py` — both set, assert
  `ctx.binary` is the override.
  *Breaks when:* `_resolve_binary` consults the setting first, as it does
  today.

- **INV-2** — A caller without `manage_settings` cannot change
  `games.launch_args_override`.
  *Test:* `tests/test_routes_launch.py` — an editor posts `edit_metadata`
  with `launch_args_override=-L /tmp/x.so`; the stored value is unchanged.
  *Breaks when:* the `edit_metadata` branch writes the field for `edit`
  alone, as it does today.

- **INV-3** — A template token that is exactly `{game_extra_args}` or
  `{system_extra_args}` expands to one argv element per word, and to none
  when the value is empty.
  *Test:* `tests/test_launch_resolver.py` — `game_extra` of
  `--a --b` with template `{game_extra_args} "{rom}"` gives
  `[..., '--a', '--b', rom]`; empty gives `[..., rom]`.
  *Breaks when:* substitution runs per token without expansion, which
  yields one element `'--a --b'` or an empty-string element.

- **INV-4** — A malformed quote in a template or an extra-args field
  yields a 422 whose message names the field, never a 500.
  *Test:* `tests/test_routes_launch.py` — `launch_args_override` of
  `--renderer "vulkan`; POST launch returns 422 and the message contains
  `launch_args_override`.
  *Breaks when:* a `shlex.split` `ValueError` escapes the resolver.

- **INV-5** — A ROM path containing shell metacharacters reaches the child
  as exactly one argv element, with no shell involved.
  *Test:* `grep -c "shell=True" services/launcher/local.py` → `0`; and
  `tests/test_launch_resolver.py` asserts a `$(x);` path is a single
  element.
  *Breaks when:* `Popen` gains `shell=True`, or the resolver re-splits
  after substitution.

- **INV-6** — An entry that exited more than `post_exit_ttl_s` ago is gone
  from the registry after the next `active()` call.
  *Test:* `tests/test_launcher_registry.py` — register, mark exited with
  `exit_time` older than the TTL, call `LocalLauncher.active()`, assert
  `len(registry) == 0`.
  *Breaks when:* nothing in production calls `gc()`, as today.

- **INV-7** — `launcher_backend` accepts `'local'` only.
  *Test:* `tests/test_launch_settings_validators.py` —
  `validate_settings_value('launcher_backend', 'remote')` is rejected.
  *Breaks when:* `'remote'` stays in `_ALLOWED_LAUNCHER_BACKENDS`.

- **INV-8** — A player launch's argv is exactly
  `[player, '--config', base, '--appendconfig', layers, '-L', core, rom]`,
  with every path absolute and `layers` ending in the game cfg.
  *Test:* `tests/test_player_launch.py` — resolve a game whose default row
  is the player; assert the shape and `os.path.isabs` on every path.
  *Breaks when:* a relative core path, a missing game layer, or a system
  layer placed after the game layer.

- **INV-9** — Before every player launch, the base cfg holds every key in
  §4.4's base block with its stated value, whatever it held before.
  *Test:* `tests/test_player_launch.py` — write a base cfg with
  `config_save_on_exit = "true"`, resolve, and read it back as `"false"`.
  *Breaks when:* RetroDB writes the base cfg once only, and the player's
  menu "save configuration" turns a key back on.

- **INV-10** — A player launch whose profile path contains `|` is refused
  with a `LaunchResolutionError`, never spawned.
  *Test:* `tests/test_player_launch.py` — `BASE_DIR` monkeypatched to a
  path containing `|`; POST launch returns 422.
  *Breaks when:* the layer list is joined without the check, so RetroArch
  splits a path in two.

- **INV-11** — After a player session exits, the game's override file is
  merged into `settings/game/<game_id>.cfg` and deleted. No file means no
  change.
  *Test:* `tests/test_player_launch.py` — place an override holding
  `video_shader_enable = "true"`, run the post-exit hook, and assert the
  key is in the game cfg and the override is gone. Then run the hook again
  with no file and assert the game cfg is unchanged.
  *Breaks when:* the hook is not called on exit, or it overwrites the game
  cfg instead of merging.

- **INV-12** — A customised game keeps its user-set keys when RetroDB
  regenerates its recommended settings. *Reset to recommended* removes them.
  *Test:* `tests/test_player_launch.py` — mark a key as user-set,
  regenerate with a different recommendation, and assert the user value
  survives. Reset, regenerate, and assert the recommended value.
  *Breaks when:* regeneration rewrites the whole game cfg.

- **INV-13** — Launching the user's own RetroArch row writes nothing under
  the player profile and passes no `--config` or `--appendconfig`.
  *Test:* `tests/test_player_launch.py` — resolve a game on the RetroArch
  row; assert neither flag is in argv and the profile directory is not
  created.
  *Breaks when:* player handling keys on `is_retroarch` rather than
  `is_player`.

- **INV-14** — The launcher keeps at most 4096 bytes of a child's stderr,
  and `stdin` and `stdout` are null.
  *Test:* `grep -c "_STDERR_TAIL_BYTES = 4096" services/launcher/local.py`
  → `1`; `tests/test_launcher_local.py` covers the drain.
  *Breaks when:* the constant is raised without a cap, or `stdout` is
  piped and never drained, which blocks the child on a full pipe.

- **INV-15** — A player process receives SIGTERM at most once, however
  many kill requests arrive.
  *Test:* `tests/test_launcher_local.py` — a stub child that ignores
  SIGTERM and counts the ones it receives; call `kill()` twice with a short
  timeout; the child reports 1.
  *Breaks when:* each `kill()` call sends its own SIGTERM, as today's
  `LocalLauncher.kill` does whenever the process is still running.

- **INV-16** — `network_cmd_enable = "true"` is written only inside the
  player profile, and only on macOS and Windows.
  *Test:* `tests/test_player_launch.py` — resolve on each platform
  (monkeypatched `sys.platform`); assert the key appears only in the
  macOS and Windows base cfg; resolve on the RetroArch row and assert the
  user's RetroArch config directory is untouched.
  *Breaks when:* the key is set on the user's own RetroArch, or on Linux
  where nothing uses it.

## 6. Failure modes

- **Player binary missing or not executable** → 422 with `_FIX_HINT`, as
  for any row.
- **Core missing** → 422 naming the file. Downloading it is PASS-59-81's.
- **A settings file unwritable** (disk full, permissions) → 422 naming the
  path; nothing is spawned with a partial layer set.
- **Base cfg deleted by the user** → recreated before the next launch.
- **Player crashes** → non-zero exit; the stderr tail is shown; the
  post-exit hook still runs, because a menu save before the crash is still
  the user's choice.
- **Override file malformed** → the hook skips the keys it cannot parse,
  logs a warning, keeps the file, and does not mark the game customised.
- **Two sessions of one game** → prevented by `launch_concurrent_same_game`
  (`reject` by default). Under `kill_and_relaunch`, the killed session's
  hook runs before the new launch writes the game cfg.
- **SIGKILL after the grace** → SRAM may be lost. That is the stated cost
  of §4.6 when the player does not exit in time.

## 7. Tests

- `tests/test_launch_resolver.py` — INV-1, INV-3, the list-variable
  refusal, and INV-5's single-element path. Extends the existing file.
- `tests/test_routes_launch.py` — INV-2, INV-4.
- `tests/test_launcher_registry.py` — INV-6.
- `tests/test_launch_settings_validators.py` — INV-7.
- `tests/test_launcher_local.py` — INV-15, with a stub child that ignores
  SIGTERM and counts the signals it receives.
- `tests/test_player_launch.py` (new) — INV-8, INV-9, INV-10, INV-11, INV-12,
  INV-13 and INV-16, with the profile
  under `tmp_path` and a stub player binary. No real RetroArch runs in the
  suite.
- INV-5's and INV-14's grep halves run as written above.

Each new test is run red against the pre-change code before its fix lands.
No test here launches the fork's real player; the player-side behaviour
(§15) is checked by the fork session against its source.

## 8. Alternatives considered (and rejected)

- **Validate launch arguments with a filter instead of an admin gate**
  (PASS-59-53's first option). Rejected by the user: every other argv input
  is admin-only, and a filter is easier to get wrong than a permission.
- **Replace the RetroArch row with the player.** Rejected by the user: it
  removes the choice of launching one's own RetroArch.
- **Repair `{disc_paths}` from `parent_game_id`.** Rejected: nothing uses
  it, and `.m3u` already covers multi-disc launch. Re-adding it later is
  cheap. Carrying a dead variable is not.
- **Put the must-be-false keys in the appended layer** instead of the base
  cfg. Rejected, although an appended key would work: `--appendconfig`
  files merge before settings are read (§4.4). The base cfg is the one file
  the player can save over, and RetroDB rewrites it every launch (INV-9),
  so keeping the keys there leaves nothing for a menu save to undo.
- **Hand the player a temporary copy of the settings each launch.**
  Rejected: it discards in-game changes, and the user chose to keep them.
- **Slim the player now** to hide the override menu. Deferred, not rejected
  (§3.11). Step 1 needs no fork change.

## 9. Out of scope

- Which core runs a system, per-game presets, and core download —
  PASS-59-81.
- The player's name, its bundle kit (licence text, source link, modified
  notice) and its release channel — the fork's RETR-0004.
- The slim build — deferred; not yet queued.
- A remote or multi-process launcher backend — not planned (§3.19).
- `.lpl` playlists — RetroDB writes none.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_launch_resolver.py` (to add) |
| INV-2 | `tests/test_routes_launch.py` (to add) |
| INV-3 | `tests/test_launch_resolver.py` (to add) |
| INV-4 | `tests/test_routes_launch.py` (to add) |
| INV-5 | grep in §5 plus `tests/test_launch_resolver.py` (to add) |
| INV-6 | `tests/test_launcher_registry.py` (to add) |
| INV-7 | `tests/test_launch_settings_validators.py` (to add) |
| INV-8 | `tests/test_player_launch.py` (to add) |
| INV-9 | `tests/test_player_launch.py` (to add) |
| INV-10 | `tests/test_player_launch.py` (to add) |
| INV-11 | `tests/test_player_launch.py` (to add) |
| INV-12 | `tests/test_player_launch.py` (to add) |
| INV-13 | `tests/test_player_launch.py` (to add) |
| INV-14 | grep in §5 plus `tests/test_launcher_local.py` |
| INV-15 | `tests/test_launcher_local.py` (to add) |
| INV-16 | `tests/test_player_launch.py` (to add) |
| §4.4 base keys behave as described in the player | **Partial:** INV-9 proves RetroDB writes them; that RetroArch honours them is checked only by the fork session reading its source |
| §4.6 macOS and Windows `QUIT` shutdown | **nothing** — no macOS or Windows build here; marked unverified |

## 11. Cross-doc impact

- `docs/specs/settings.md` — `launcher_backend` loses `'remote'`; the
  default-set list gains nothing new.
- `docs/specs/auth.md` — the `edit` row notes that launch arguments need
  `manage_settings`.
- `docs/specs/migrations.md` — migration 016 (`emulators.is_player`).
- The module docstrings that cite "spec §…" are repointed at this file's
  sections.
- `data/changelog.yaml` — per release, as each PASS item implements its
  clauses.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-64-launcher-loop-log.md`.

## 13. Resource cost

- Registry: bounded by launches in the last `post_exit_ttl_s` (3600 s),
  each holding one `Popen` and at most 4096 bytes of stderr.
- Profile: two small text files per launched game plus the player's own
  saves and states. Cores are PASS-59-81's budget.
- No new Python dependency.

## 14. Migration / compatibility

- Migration 016 adds `emulators.is_player` (default 0), so existing rows
  are unaffected.
- **Behaviour change:** an install with both `retroarch_binary` and a
  RetroArch row override set now launches the override (§3.18). That row's
  Settings entry shows it.
- A template still using `{disc_paths}` now fails with "Unknown template
  variable" instead of passing nothing. No seeded or live template does.
- An install whose `launcher_backend` is `'remote'` could not launch at all;
  the validator now rejects that value, and the saved value is read as
  `'local'`.

## 15. Open questions

The fork session answered the first round from its `local/fixes-2026-09`
source on 2026-09-26; what it could not verify stays here.

- **Q1** — *Resolved:* `quit_on_close_content = "2"` (§4.4).
- **Q2** — *Retired:* RetroDB no longer predicts the override directory's
  name. It scans every subdirectory of the config directory (§4.5).
- **Q3** — *Partly resolved:* the SIGTERM quit writes RTC data (§4.6). How
  long it takes is unmeasured, so the 5 s grace is too.
- **Q4** — *Resolved from source:* `QUIT` obeys `confirm_quit`, and is
  acted on with the menu open and while paused, bar the flush window §4.6
  covers with one resend. macOS and Windows `QUIT` behaviour is untested at
  runtime.
- **Q5** — *Resolved from source:* every build enables `HAVE_NETWORK_CMD` —
  `configure` (`qb/config.libs.sh`), the MSVC projects, and the Xcode
  projects (`pkg/apple/BaseConfig.xcconfig`).
