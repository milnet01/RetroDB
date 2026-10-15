<!-- ants-spec-format: 1 -->
# PASS-59-91 — Zero-setup play: point at an emulator, RetroDB does the rest

**Status:** accepted (2026-10-15).
**Kind:** implement.
**Source:** ROADMAP PASS-59-91 (user request and decisions 2026-10-15).
**Blocked by:** PASS-59-53, PASS-59-54, PASS-59-55 (stage 1: building
PASS-59-64's fixes). **Pairs with:** PASS-59-64 (launch contract), PASS-59-81
(RetroArch core ranking and settings; not yet written).

Layman: you tell RetroDB where your emulators live, and it finds them, links
them to the right consoles, tells you which BIOS files are missing, puts a
Play button on every game card, and starts each PlayStation game with good
settings you can still change.

## 1. Goal

After this ships, a user adds one folder in Settings → Emulators and can
press Play on a library card. RetroDB finds each emulator in that folder (an
AppImage, a portable script or an installed Flatpak), maps it to the systems
it runs, and says which BIOS files are missing. For DuckStation, PCSX2 and
RPCS3, RetroDB also sets the scaling and aspect ratio for each game, in the
emulator's own per-game settings file, and whether it starts fullscreen. The
user can change these per system, and the file settings per game. Compatibility fixes stay the emulator's
own job, from its own game database.

## 2. Problem

Stage 1 (PASS-59-53 to 59-55) fixes the launch path itself, under PASS-59-64.
What is still missing, against the code as it stands:

1. **Finding an emulator is half manual.**
   `routes/launch_settings.py::api_emulators_detect` walks the
   `emulator_scan_paths` setting for `*.AppImage` and `*-portable.sh` files
   and matches their names against `_NAME_PATTERNS`. Flatpak is probed for
   RetroArch only (`_probe_retroarch_binary`). A Flatpak command cannot go in
   `emulators.binary_path_override`, because
   `services/launch_resolver.py::_resolve_binary` requires that path to pass
   `os.access(path, os.X_OK)`. `emulator_scan_paths` is shown in
   Settings → Emulators but cannot be edited there.
2. **Nothing maps a found emulator to its systems.** `system_emulators` rows
   come only from `data/emulator_seeds.json` through
   `services/emulator_seeder.py::seed_emulators_from_file`, which never
   updates an existing row. The per-system mapping section of
   `templates/settings_emulators.html` (`#mapping-body`) is never filled:
   `grep -c mapping-body static/js/emulators-settings.js` → `0`.
3. **Missing BIOS files are found only by launching.** No code in
   `services/` or `routes/` reads or reports BIOS files.
4. **Play exists on the game page only.** `#play-btn` lives in
   `templates/game_detail.html`, which alone loads `static/js/game-launch.js`.
   `AllGamesController.renderGameCard` in
   `static/js/all-games-controller.js` renders no play action, and the
   library (`/games`) and system pages (`/system/<id>`) both use it.
5. **Standalone emulators get no settings.** RetroDB passes argv only. Their
   per-game files are named by disc serial, and no column on `games` holds a
   serial.
6. **RetroArch Auto-detect fails on this page.**
   `static/js/emulators-settings.js` reads `out.data.binary.path`, but
   `api_retroarch_detect` returns `binary` and `cores_dir` at the top level,
   so the click shows "Detect failed".

## 3. Scope decisions (agreed with the user)

By the user on 2026-10-15 unless marked otherwise.

1. **The user only points RetroDB at an emulator's folder**; RetroDB does the
   rest, including the best settings per game (roadmap PASS-59-91).
2. **Per-game compatibility fixes come from each emulator's own game
   database**, not a list RetroDB curates. RetroDB sets per-system experience
   settings plus the user's per-game changes.
3. **RetroDB writes into the emulator's own per-game file**, touching only the
   settings it manages and never one the user set inside the emulator. Chosen
   over RetroDB-owned copies passed at launch, which DuckStation cannot take,
   and over launch flags only.
4. **The first build manages settings for DuckStation, PCSX2 and RPCS3.**
   Every emulator gets detection, mapping, BIOS status and Play buttons.
5. **Stage 1 builds from PASS-59-64 without a new spec.**
6. **(Author, by deduction from PASS-59-64 §3.7:)** RetroDB reads BIOS
   locations and never writes, copies or downloads a BIOS file.
7. **(Author, by deduction from §2.1:)** a Flatpak emulator is stored as the
   path of its exported launcher, which is executable, so PASS-59-64 §4.1's
   binary order and its executable check stay as written.
8. **(Author:)** an existing default mapping that resolves is never replaced
   by detection. The user's earlier choice wins over a guess.
9. **(Author:)** the RetroDB-managed settings are three: resolution scale,
   aspect ratio and fullscreen. That is what the user named; more are added
   as rows in the settings table of §4.6.
10. **(Author:)** settings files are written at launch only. Saving a choice
    in RetroDB records it in the database; nothing touches the emulator's
    folder until the next Play.

## 4. Design

### 4.1 Adapters

A new module, `services/emulator_adapters.py`, holds one `EmulatorAdapter`
per known emulator. It absorbs `_NAME_PATTERNS` and `_PORTABLE_BASE` from
`routes/launch_settings.py`, so names are matched in one place.

```python
@dataclass(frozen=True)
class EmulatorAdapter:
    binary_name: str                 # key: matches emulators.binary_name
    name_patterns: tuple[str, ...]   # regexes on a file name, case-insensitive
    flatpak_ids: tuple[str, ...]
    systems: tuple[str, ...]         # system folders it runs
    data_dirs: Callable[[Path], list[Path]]  # candidates, given the binary
    data_marker: str                 # file that proves a candidate is the data dir
    bios: BiosRule | None = None
    settings: SettingsTarget | None = None   # §4.6; three adapters only

ADAPTERS: dict[str, EmulatorAdapter]
def adapter_for(emu_row) -> EmulatorAdapter | None   # by binary_name
```

Matching on `binary_name` rather than `emulators.name` means a renamed row
still matches. Every emulator in `data/emulator_seeds.json` gets an adapter;
only DuckStation, PCSX2 and RPCS3 get `settings`.

**Data directory.** The first candidate holding `data_marker` wins. None →
the emulator has no data directory yet, and §4.6 is skipped (§6). Linux
candidates, in order:

| Adapter | Candidates | Marker |
|---|---|---|
| DuckStation | binary's dir if `portable.txt` is there; `<AppImage>.home/.local/share/duckstation`; `$XDG_DATA_HOME/duckstation`; `~/.var/app/org.duckstation.DuckStation/data/duckstation` | `settings.ini` |
| PCSX2 | binary's dir if `portable.txt` or `portable.ini` is there; `<AppImage>.home/.config/PCSX2`; `$XDG_CONFIG_HOME/PCSX2`; `~/.var/app/net.pcsx2.PCSX2/config/PCSX2` | `inis/PCSX2.ini` |
| RPCS3 | `<AppImage>.home/.config/rpcs3`; `$XDG_CONFIG_HOME/rpcs3`; `~/.var/app/net.rpcs3.RPCS3/config/rpcs3` | `config.yml` |

`$XDG_*_HOME` takes its XDG default when unset. For a `*-portable.sh`, the
binary's dir is the script's dir and `<AppImage>` is the AppImage beside it.
Verified on this machine: DuckStation's portable directory,
`pcsx2.AppImage.home/.config/PCSX2` and `RPCS3.AppImage.home/.config/rpcs3`
under `/mnt/Emulators`. The Flatpak and XDG rows are *unverified*: no
emulator Flatpak is installed here.

### 4.2 Pointing at a folder

Settings → Emulators gains an **Emulator folders** list, the editable form of
the existing `emulator_scan_paths` setting. Adding a folder runs detection on
it at once, with `apply=true`.

`POST /api/settings/emulators/detect` (admin, existing) keeps its query flag
`apply` and its response, and changes underneath:

- **Files:** the existing walk (`_walk_appimages`, its depth and entry caps),
  matched through `ADAPTERS`. A `*-portable.sh` still beats its AppImage.
- **Flatpak:** for each adapter's `flatpak_ids`, the exported launcher
  `/var/lib/flatpak/exports/bin/<id>` or
  `~/.local/share/flatpak/exports/bin/<id>`, whichever exists and is
  executable. That path is the suggestion, so `_resolve_binary` takes it
  unchanged (§3.7). RetroArch's own Flatpak probe is unchanged.
- **Each suggestion gains** `systems` (the adapter's system folders that
  exist in `systems`) and `data_dir` (§4.1, or `null`).
- **`apply=true`** writes `binary_path_override` as today, then wires every
  suggestion, whether or not its override changed (§4.3).

### 4.3 Wiring to systems

For each system in a suggestion's `systems`, `apply` upserts the
`system_emulators` row for that emulator, with `retroarch_core` and
`extra_args` left as they are. It makes the row the default only when the
system has no default row, or its default row does not resolve. Making a row
default clears the others, as
`routes/emulators.py::api_map_system_emulator` already does.

**A mapping resolves** when its emulator is enabled, `_resolve_binary`
returns a path that exists and is executable (or a `flatpak run <id>` command
whose id `flatpak info` accepts), and, for a RetroArch row, its core file
exists. `_resolve_binary` returns the `retroarch_binary` setting unchecked,
so not raising is not enough. §4.3, §4.5, the `resolves` field below and §6
all use this test.

The RetroArch adapter lists no `systems`. Which core runs a system is
PASS-59-81's, and a RetroArch row with no `retroarch_core` cannot launch, so
detection sets only RetroArch's binary.

A new `GET /api/system_emulators` (admin) returns every mapping, joined to
its system and emulator names, with `resolves` (bool) and `bios` (§4.4).
`static/js/emulators-settings.js` fills `#mapping-body` from it: one row per
mapping, a default radio per system, and the existing POST and DELETE routes
behind them.

The same file reads `api_retroarch_detect`'s top-level `binary` and
`cores_dir`, fixing §2.6.

### 4.4 BIOS status

```python
BiosRule = Callable[[Path, Path | None, Row], dict]
# (binary from _resolve_binary, data dir or None, system_emulators row) → status

def bios_status(emu_row, sys_emu_row) -> dict
# {"state": "ok" | "missing" | "unknown", "missing": [str], "checked": [str]}
```

| Emulator | Where | Satisfied when |
|---|---|---|
| DuckStation | `settings.ini` `[BIOS] SearchDirectory`, relative to the data dir; default `<data>/bios` | the directory holds a file of exactly 524288 bytes |
| PCSX2 | `inis/PCSX2.ini` `[Folders] Bios`, relative to the data dir, joined with `[Filenames] BIOS` | that file exists |
| RPCS3 | `<data>/dev_flash/vsh/module/vsh.self` | it exists (firmware installed) |
| RetroArch | the core's `.info` file beside the core; the `system_directory` of the RetroArch config RetroDB reads | every `firmwareN_path` whose `firmwareN_opt` is `"false"` exists under the system directory |

The RetroArch config is found from the binary `_resolve_binary` returns for
the row. Where that binary is an AppImage, or a `*-portable.sh` beside one,
and `<AppImage>.home/.config/retroarch/retroarch.cfg` exists, that file is
read; a `flatpak run` binary gives `unknown`; else
`~/.config/retroarch/retroarch.cfg`. A leading `~` in
`system_directory` is expanded against the same home. RetroArch needs no data
dir. A standalone adapter with no data dir, and an adapter with no rule,
return `unknown`.

BIOS status is shown in the mapping table and in the 422 text when a launch
fails. It never blocks a launch: the emulator gives its own error.

### 4.5 Play on cards and system pages

`routes/games.py::api_games` adds `can_launch` to each game it returns. It is
true when the caller holds the permission named by `launch_required_permission`
and the mapping the resolver would pick for it resolves (§4.3). That pick is
the game's `emulator_override_id` emulator with its system's row for that
emulator, else the system's default row, else its lowest-id row. Results are
cached per request by (system, emulator), so one resolve per distinct pair,
not per game.

`AllGamesController.renderGameCard` renders a Play button on a card whose
game has `can_launch`, carrying `data-game-id`. It calls `window.launchGame`
from `game-launch.js` with the button, which
`templates/all_games.html` and `templates/system_games.html` now load as
`game_detail.html` does. A click does not open the game page. A 422 shows its
message in a toast.

### 4.6 Per-game settings for DuckStation, PCSX2 and RPCS3

**Disc serial.** This spec's migration adds `games.disc_serial TEXT` and
`games.disc_crc TEXT`, both nullable. It takes the next number in
`services/migrations/__init__.py`'s list, where the position is the version;
PASS-59-64 plans 016 for its player row, and whichever lands second takes the
next number. `disc_serial` `NULL` means not read yet; `''` means read and none
found. `disc_crc` is set for ps2 only and is `NULL` otherwise. A rescan that
changes a game's `rom_path` sets both back to `NULL`.

`services/disc_serial.py`:

```python
def read_disc_ids(rom_path: Path, system_folder: str) -> tuple[str, str | None]
# → (serial, crc). serial is 'AAAA-NNNNN' or ''. crc is 8 upper-case hex
#   digits for ps2, else None. Raises nothing; any failure gives ('', None).
```

- **Sector source.** `.iso`: the file. `.cue` / `.bin`: the first data track,
  raw 2352-byte sectors. `.chd`: `chdman extractraw` over a byte range, with
  the user-data offset taken from `chdman info`'s first track type (`MODE1` 0,
  `MODE1_RAW` 16, `MODE2_RAW` 24). `.m3u`: its first entry. A PS3 folder
  game: `PS3_DISC.SFB` in the folder.
- **Serial.** ISO9660: the primary volume descriptor at sector 16, then the
  root directory. PS1 and PS2: `SYSTEM.CNF`'s `BOOT` or `BOOT2` line, whose
  `SLUS_011.50` form becomes `SLUS-01150`. PS3: `PS3_DISC.SFB`'s `TITLE_ID`,
  already `BLUS-31024`.
- **CRC (PS2 only).** The XOR of every little-endian 32-bit word of the boot
  ELF named by `BOOT2`, as PCSX2 names its per-game files.
- **When.** At the first launch of the game through a settings adapter, or
  the first GET of its emulator settings (§4.6 Routes), whichever comes first;
  the result is stored. A missing `chdman` gives `''`.

Probe, 2026-10-15, on this machine's library: a scratch prototype of this
reader returned a serial for 40 of 40 `.chd` files picked by `shuf -n 40`
from `ROMS/psx` and 40 of 40 from `ROMS/ps2`, in 7.7 s and 10.8 s. Its CRC
for `ROMS/ps2/Extermination (USA).chd` was `0AE679AF`, matching the user's
existing PCSX2 file `SCUS-97112_0AE679AF.ini`.

**Settings table.** `data/standalone_settings.json`, keyed by adapter
`binary_name`, defines each managed setting: where it lives, the values
RetroDB offers, and the per-system default.

```json
{
  "duckstation-qt": {
    "resolution_scale": {"section": "GPU", "key": "ResolutionScale",
                         "values": {"1x": "1", "2x": "2", "3x": "3", "4x": "4", "5x": "5"},
                         "default": "4x"},
    "aspect_ratio":     {"section": "Display", "key": "AspectRatio",
                         "values": {"auto": "Auto (Game Native)", "4:3": "4:3", "16:9": "16:9"},
                         "default": "auto"},
    "fullscreen":       {"flag": {"on": "-fullscreen", "off": "-nofullscreen"},
                         "default": "on"}
  },
  "pcsx2-qt": { "resolution_scale": {"section": "EmuCore/GS", "key": "upscale_multiplier", "...": "..."},
                "aspect_ratio": {"section": "EmuCore/GS", "key": "AspectRatio", "...": "..."},
                "fullscreen": {"flag": {"on": "-fullscreen", "off": "-nofullscreen"}, "default": "on"} },
  "rpcs3":    { "resolution_scale": {"path": ["Video", "Resolution Scale"], "...": "..."},
                "aspect_ratio": {"path": ["Video", "Aspect ratio"], "...": "..."},
                "fullscreen": {"path": ["Miscellaneous", "Start games in fullscreen mode"], "...": "..."} }
}
```

The section and key names above are the ones in the user's own
`settings.ini`, `inis/PCSX2.ini` and `config.yml`. The implementer fills in
the value lists from each emulator's options. A setting with `flag` is passed
on the command line. One with `section` or `path` is written into the file.

**Fullscreen flag.** PASS-59-64 §4.1's list variables gain
`{fullscreen_flag}`. It expands to the adapter's on or off flag, or to no
argv element for an emulator with no `flag` entry. The migration also
changes the seeded `args_template` of the DuckStation and PCSX2 rows from
`-batch -fullscreen "{rom}"` to `-batch {fullscreen_flag} "{rom}"`, only where
the stored value still equals the old seed exactly. `data/emulator_seeds.json`
changes to match.

**Which file.**

| Adapter | Per-game file |
|---|---|
| DuckStation | `<data>/gamesettings/<serial>.ini` |
| PCSX2 | the one existing `<data>/gamesettings/<serial>_*.ini`; else `<data>/gamesettings/<serial>_<crc>.ini` |
| RPCS3 | `<data>/custom_configs/config_<serial without '-'>.yml` |

A serial must match `^[A-Z]{4}-\d{5}$` and a CRC `^[0-9A-F]{8}$`, or nothing
is written. The resolved path must lie under `<data>`. When PCSX2 has two
or more `<serial>_*.ini` files, nothing is written and §6 applies.

**Choices** live in a new table, created by the same migration:

```sql
CREATE TABLE emulator_setting_choices (
  id          INTEGER PRIMARY KEY,
  emulator_id INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
  scope       TEXT NOT NULL CHECK (scope IN ('system', 'game')),
  scope_id    INTEGER NOT NULL,          -- systems.id or games.id
  setting     TEXT NOT NULL,             -- a key of the settings table
  value       TEXT NOT NULL,             -- a key of that setting's "values"
  UNIQUE (emulator_id, scope, scope_id, setting)
);
CREATE TABLE emulator_written_settings (
  id          INTEGER PRIMARY KEY,
  emulator_id INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
  file_path   TEXT NOT NULL,
  setting     TEXT NOT NULL,
  written     TEXT NOT NULL,             -- the raw value RetroDB last wrote
  UNIQUE (file_path, setting)
);
```

**At launch**, after resolving and before spawning, for a game whose
emulator has a settings adapter, for each file setting:

1. **The user's own.** The key is the user's, and is left alone, when it is
   in the file and either has no `emulator_written_settings` row or differs
   from that row's `written`. Values are compared as the text after `=`
   or `:`, trimmed. In a file RetroDB has never
   touched, like the user's existing `gamesettings/SLUS-00006.ini`, every key
   already there is the user's; managed keys it lacks are added (step 2).
2. **Otherwise RetroDB's value**, first found of: the game's choice, the
   system's choice, the table's `default`. It is written, and `written` is
   recorded.

Files are edited line by line: only the managed keys change, every other line
and comment stays, a missing section is appended, and the new file replaces
the old with `os.replace` from a temporary file in the same directory.
RPCS3's YAML is edited the same way, never loaded and dumped: the `path`'s
first part is a top-level `Name:` line, the second a two-space-indented
`  Key: value` line inside that block. PyYAML reads the user's unquoted
`Aspect ratio: 16:9` as the integer `969` (YAML 1.1 base-60) and would write
`969` back.

**Routes.**

- `GET /api/games/<game_id>/emulator-settings` (`view`) →
  `{supported, reason, candidates, emulator, serial, file, settings:
  [{setting, value, source, values}]}`. `reason` is `null` when `supported`
  is true, else a plain-language string (§6). `candidates` lists the PCSX2
  files when there are two or more, else `[]`. `source` is `game`, `system`,
  `default` or `emulator` (the user's own, read from the file). A `NULL`
  `disc_serial` is read and stored before the GET answers.
- `PUT` the same path (`edit`), body `{setting: value | null}`; `null`
  removes the game choice. A `flag` setting is refused with 400: it is an
  argv input, admin-only under PASS-59-64 §3.14, so it is set per system
  only. The game page gains an **Emulator settings** panel built on these.
- `GET` and `PUT /api/systems/<system_id>/emulator-settings/<emulator_id>`
  (`manage_settings`), the system level, shown in the mapping table.

Compatibility fixes are not in the table: DuckStation, PCSX2 and RPCS3 apply
their own game databases to every launch without RetroDB (§3.2).

### 4.7 RetroArch

The user's own RetroArch row launches as PASS-59-64 says (its INV-13).
Settings for RetroArch games are the player's (PASS-59-64 §4.4) and
PASS-59-81's. For RetroArch rows this spec adds BIOS status (§4.4) and
binary detection (§4.2) only.

## 5. Invariants

- **INV-1** — A folder holding `DuckStation-x64.AppImage` and `portable.txt`
  yields a DuckStation suggestion with that AppImage as the path, the system
  `psx`, and the folder as `data_dir`.
  *Test:* `tests/test_emulator_autodetect.py` — build the folder and a
  `settings.ini` under `tmp_path`; call `_detect_emulators`.
  *Breaks when:* matching still keys on `emulators.name`, or the data-dir
  candidates skip the portable check.

- **INV-2** — An installed Flatpak's exported launcher is suggested as the
  binary, and `_resolve_binary` returns it.
  *Test:* `tests/test_emulator_autodetect.py` — an executable stub at
  `<fake home>/.local/share/flatpak/exports/bin/org.duckstation.DuckStation`;
  assert the suggestion's path, then resolve a psx game on that row.
  *Breaks when:* the suggestion is a `flatpak run …` command, which
  `_resolve_binary`'s executable check rejects.

- **INV-3** — `apply` makes a newly found emulator a system's default only
  when that system's default does not resolve.
  *Test:* `tests/test_emulator_autodetect.py` — psx default on a resolving
  RetroArch row: apply DuckStation and assert RetroArch stays default. Again
  with RetroArch's `retroarch_binary` setting naming a deleted file: assert
  DuckStation is default and one default row exists.
  *Breaks when:* apply always sets the new row default, or never does, or
  "resolves" means only that `_resolve_binary` did not raise.

- **INV-4** — BIOS status reports a missing DuckStation BIOS and an existing
  one, and the check writes nothing.
  *Test:* `tests/test_bios_status.py` — data dir with `[BIOS] SearchDirectory`
  pointing at an empty dir → `missing`; add a 524288-byte file → `ok`; assert
  the dir's listing is otherwise unchanged.
  *Breaks when:* the search directory is not read from `settings.ini`, or the
  size test is dropped so any file passes.

- **INV-5** — A RetroArch mapping's BIOS status lists each non-optional
  firmware file in the core's `.info` that the system directory lacks, and no
  optional one.
  *Test:* `tests/test_bios_status.py` — an `.info` with one `opt "false"` and
  one `opt "true"` entry, neither file present → `missing` names the first
  only.
  *Breaks when:* `firmwareN_opt` is ignored.

- **INV-6** — The mapping section of Settings → Emulators is filled from
  `GET /api/system_emulators`.
  *Test:* `grep -c "mapping-body" static/js/emulators-settings.js` → `1` or
  more (today `0`); `tests/test_emulator_registry_routes.py` — the route is
  admin-only and returns each mapping with `resolves` and `bios`.
  *Breaks when:* the JS never fills the table, as today.

- **INV-7** — `api_games` marks `can_launch` true only for a caller with the
  launch permission and a game whose system is in §4.5's set.
  *Test:* `tests/test_api_games_can_launch.py` — two systems, one resolving and one
  not; as a player assert true and false; as a viewer assert false for both.
  A game on the resolving system with `emulator_override_id` naming a
  disabled emulator → false.
  *Breaks when:* `can_launch` ignores the permission, ignores the game's
  override, or is true for a mapping that does not resolve (§4.3).

- **INV-8** — A library card with `can_launch` has a Play button that starts
  the game without leaving the page.
  *Test:* manual — on `/games` and `/system/<id>` at desktop and 375 px width,
  press Play on a card; the "Launched" toast shows, the game appears in the
  `#launch-indicator` popover in `templates/base.html`, and the URL is
  unchanged.
  Press it on a game whose ROM is missing; a toast shows the 422 message.
  *Breaks when:* the button calls `window.location` or the page lacks
  `game-launch.js`.

- **INV-9** — `read_disc_ids` returns the serial from `SYSTEM.CNF`, and the
  PS2 CRC as the XOR of the boot ELF's 32-bit words.
  *Test:* `tests/test_disc_serial.py` — a minimal ISO9660 image built in
  `tmp_path` holding `SYSTEM.CNF` (`BOOT2 = cdrom0:\SLUS_123.45;1`) and an
  8-byte file `SLUS_123.45` of words `0x11111111`, `0x22222222` →
  `('SLUS-12345', '33333333')`. The same image with `SYSTEM.CNF` renamed →
  `('', None)`.
  *Breaks when:* the reader greps raw bytes instead of reading the directory
  (the prototype's first version missed 13 of 25 PS2 discs that way), or the
  CRC is a CRC32.

- **INV-10** — A `.chd` is read through `chdman` with the user-data offset of
  its first track's type.
  *Test:* `tests/test_disc_serial.py` — stub `chdman` reporting `TYPE:MODE1`
  and then `TYPE:MODE2_RAW` over the same fixture sectors laid out for each;
  both give the serial. No `chdman` on `PATH` → `('', None)`.
  *Breaks when:* one fixed offset is used, which breaks every `MODE1` PS2
  CHD (the prototype's second version read 2 of 25).

- **INV-11** — After a launch, the per-game file differs from before only in
  managed keys.
  *Test:* `tests/test_standalone_settings.py` — a DuckStation file with a
  comment, `[TextureReplacements] EnableTextureReplacements = true` and no
  `[Display]` section; launch; assert every original line is still there and
  the only additions are `[Display]` with `AspectRatio` and `[GPU]`
  `ResolutionScale`.
  *Breaks when:* the file is round-tripped through `configparser`, which
  drops comments, or rewritten from RetroDB's keys alone.

- **INV-12** — A key the user set inside the emulator survives every launch.
  *Test:* `tests/test_standalone_settings.py` — launch once (RetroDB writes
  `ResolutionScale = 4`); edit the file to `2`; change the system choice to
  `5x`; launch again; assert `2`. Separately, a pre-existing file holding
  `ResolutionScale = 3` with no record keeps `3`.
  *Breaks when:* RetroDB rewrites keys it did not last write, or treats a
  file with no record as its own.

- **INV-13** — RetroDB's value is the game choice, else the system choice,
  else the default.
  *Test:* `tests/test_standalone_settings.py` — default `4x`; system `3x`
  → `3`; game `2x` → `2`; game `null` → `3`.
  *Breaks when:* the system choice beats the game choice, or a removed game
  choice leaves its value in place.

- **INV-14** — Each adapter writes the file named in §4.6's file table.
  *Test:* `tests/test_standalone_settings.py` — serial `SLUS-20001`, CRC
  `67454C1E`: DuckStation → `gamesettings/SLUS-20001.ini`; PCSX2 with
  `SLUS-20001_67454C1E.ini` present → that file, with none present → the
  same name, created; RPCS3 serial `BLUS-31024` →
  `custom_configs/config_BLUS31024.yml`.
  *Breaks when:* PCSX2 creates a second file beside an existing one, or RPCS3
  keeps the dash.

- **INV-15** — Nothing is written outside the adapter's data directory, and
  a malformed serial writes nothing.
  *Test:* `tests/test_standalone_settings.py` — `disc_serial` of
  `../../evil` and of `SLUS-2000`; launch; assert no file is created and the
  launch still spawns.
  *Breaks when:* the serial is joined into the path unchecked.

- **INV-16** — A launch never fails for a settings reason: an unreadable
  serial, no data dir, or two PCSX2 candidates each still spawn, and the
  game's emulator-settings view says why nothing was written.
  *Test:* `tests/test_standalone_settings.py` — each case; assert the
  launcher's `launch` was called and the GET's `supported` is false with a
  `reason`.
  *Breaks when:* a settings error is raised as `LaunchResolutionError`.

- **INV-17** — `{fullscreen_flag}` expands to the adapter's flag for the
  effective choice, and to no argv element for an emulator with no flag.
  *Test:* `tests/test_launch_resolver.py` — DuckStation with fullscreen off →
  argv holds `-nofullscreen` and no `''`; Dolphin with a template using the
  variable → no element.
  *Breaks when:* it is a scalar variable, which leaves an empty-string
  argument (PASS-59-64 §2.3).

- **INV-18** — The migration changes a seeded DuckStation or PCSX2
  `args_template` only where it still equals the old seed exactly.
  *Test:* `tests/test_migrations.py` — one row at the old seed, one edited to
  `-batch "{rom}"`; migrate; assert the first holds `{fullscreen_flag}` and
  the second is unchanged.
  *Breaks when:* the migration matches by emulator name alone.

- **INV-19** — Detection, wiring and system-level settings are admin-only;
  the folder walk keeps its depth and entry caps.
  *Test:* `tests/test_emulator_autodetect.py` — an editor gets 403 from
  `POST /api/settings/emulators/detect`, `GET /api/system_emulators` and the
  system-level PUT; an editor's game-level PUT of DuckStation's `fullscreen`
  gets 400; a tree deeper than the cap yields no suggestion from below it.
  *Breaks when:* a new route takes `login_required` alone, as
  `GET /api/emulators` does today, or the game PUT accepts a `flag` setting.

- **INV-20** — Writing RPCS3's `resolution_scale` leaves every other line of
  the file byte-identical.
  *Test:* `tests/test_standalone_settings.py` — a `config_BLUS31024.yml`
  holding `Video:` with `  Aspect ratio: 16:9` and `  Resolution Scale: 100`;
  write `resolution_scale`; assert the `Aspect ratio` line still reads `16:9`
  and only the `Resolution Scale` line changed.
  *Breaks when:* the file is round-tripped through PyYAML, which writes
  `Aspect ratio: 969`.

## 6. Failure modes

- **No data dir found** (emulator never run) → no file written; the panel
  says "Run <emulator> once so it creates its settings, then play again."
- **Serial unreadable** (`chdman` missing, unknown format, no `SYSTEM.CNF`)
  → `disc_serial = ''`; no file written; the panel says so. A rescan that
  changes the ROM path retries.
- **Two PCSX2 files for one serial** → nothing written; the panel names both.
- **Settings file unwritable or unparsable** → nothing written, a warning
  logged, the launch goes ahead.
- **The emulator rewrites its file during play**, as DuckStation and PCSX2
  do when the user saves per-game settings → the next launch sees the
  changed keys as the user's (§4.6 step 1).
- **The emulator renames a key in a later version** → RetroDB writes a key
  the emulator ignores; the user's settings are unharmed. The table is
  updated in a release.
- **BIOS directory unreadable** → `unknown`, never `missing`.
- **Flatpak removed after detection** → the launcher path no longer exists;
  `_resolve_binary` raises its existing error, and the mapping shows
  `resolves: false`.
- **The user deletes a mapping** → its choices stay in
  `emulator_setting_choices` and apply again if it is re-added.

## 7. Tests

- `tests/test_emulator_autodetect.py` (extends) — INV-1, INV-2, INV-3, INV-19.
- `tests/test_bios_status.py` (new) — INV-4, INV-5.
- `tests/test_emulator_registry_routes.py` (extends) — INV-6's route half.
- `tests/test_api_games_can_launch.py` (new) — INV-7.
- `tests/test_disc_serial.py` (new) — INV-9, INV-10, with ISO fixtures built
  in `tmp_path` and a stub `chdman`. No real disc image is read.
- `tests/test_standalone_settings.py` (new) — INV-11, INV-12, INV-13, INV-14,
  INV-15, INV-16 and INV-20, with data
  dirs under `tmp_path` and a stub launcher.
- `tests/test_launch_resolver.py` (extends) — INV-17.
- `tests/test_migrations.py` — INV-18.
- INV-6's grep half runs as written. INV-8 is the manual recipe in §5.

Each new test is run red against the pre-change code before its code lands.
No test launches a real emulator, so none proves an emulator honours the keys
it is given; §10 says so.

## 8. Alternatives considered (and rejected)

- **RetroDB-owned settings copies passed at launch** (`-gamecfg` on PCSX2,
  `--config` on RPCS3). Rejected by the user: DuckStation has no such flag,
  and both replace the user's own per-game file rather than layering on it.
- **Launch flags only.** Rejected by the user: scaling and aspect ratio have
  no flag on DuckStation or PCSX2.
- **A RetroDB-curated list of per-game fixes.** Rejected by the user: each
  emulator's database is maintained upstream and larger.
- **Writing the per-system settings into the emulator's global config.**
  Rejected (author): that file holds the user's own global choices, and one
  emulator can serve two systems.
- **Storing `flatpak run <id>` in `binary_path_override`.** Rejected
  (author): it fails PASS-59-64 §4.1's executable check and would need that
  clause changed; the exported launcher needs nothing.
- **Reading the serial from the emulator's game-list cache.** Rejected
  (author): the cache format is private to each emulator and exists only
  after the emulator has scanned the folder.
- **Matching against a Redump DAT by the CHD's SHA1.** Rejected (author):
  RetroDB would have to ship and update the DATs; reading the disc needs
  nothing.
- **Reading every serial at scan time.** Rejected (author): about a quarter
  second per disc on this library's sample, spent on games never launched.

## 9. Out of scope

- Settings for RetroArch games — PASS-59-64 (player) and PASS-59-81.
- Settings adapters for PPSSPP, Dolphin and other emulators — deferred; not
  yet queued.
- Downloading or copying BIOS files — not planned (§3.6).
- Windows and macOS data-directory candidates — deferred; not yet queued.
- Reading the serial at scan time, or as a bulk job — deferred; not yet
  queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_emulator_autodetect.py` (to add) |
| INV-2 | `tests/test_emulator_autodetect.py` (to add) |
| INV-3 | `tests/test_emulator_autodetect.py` (to add) |
| INV-4 | `tests/test_bios_status.py` (to add) |
| INV-5 | `tests/test_bios_status.py` (to add) |
| INV-6 | grep in §5 plus `tests/test_emulator_registry_routes.py` (to add) |
| INV-7 | `tests/test_api_games_can_launch.py` (to add) |
| INV-8 | **nothing** automated — manual recipe in §5; no browser harness in the suite |
| INV-9 | `tests/test_disc_serial.py` (to add) |
| INV-10 | `tests/test_disc_serial.py` (to add) |
| INV-11 | `tests/test_standalone_settings.py` (to add) |
| INV-12 | `tests/test_standalone_settings.py` (to add) |
| INV-13 | `tests/test_standalone_settings.py` (to add) |
| INV-14 | `tests/test_standalone_settings.py` (to add) |
| INV-15 | `tests/test_standalone_settings.py` (to add) |
| INV-16 | `tests/test_standalone_settings.py` (to add) |
| INV-17 | `tests/test_launch_resolver.py` (to add) |
| INV-18 | `tests/test_migrations.py` (to add) |
| INV-19 | `tests/test_emulator_autodetect.py` (to add) |
| INV-20 | `tests/test_standalone_settings.py` (to add) |
| §4.6 the emulators honour the keys RetroDB writes | **nothing** — no test runs an emulator; key names were read from this machine's config files, not from each emulator's source |
| §4.1 Flatpak and XDG data-dir candidates | **nothing** — no emulator Flatpak installed here; marked unverified |

## 11. Cross-doc impact

- `docs/specs/PASS-59-64-launcher.md` §4.1 — the list variables gain
  `{fullscreen_flag}` (§4.6). An addition; no clause there changes. Its
  "migration 016" becomes the next free number if this spec's migration lands
  first (§4.6).
- `docs/specs/migrations.md` — this spec's migration.
- `docs/specs/api-contracts.md` — `GET /api/system_emulators`, the
  emulator-settings routes, `can_launch` on `/api/games`, and the detect
  response's new fields.
- `docs/specs/auth.md` — the new routes' permissions.
- `CLAUDE.md` — `game-launch.js` is loaded by `all_games.html` and
  `system_games.html` too (page and asset wiring).
- `templates/help.html` and each `help.<locale>.html` — the Emulators help
  section.
- `data/changelog.yaml` — per release, as each stage lands.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-91-zero-setup-play-loop-log.md`.

## 13. Resource cost

- `can_launch`: one `_resolve_binary` per mapped emulator per `/api/games`
  request, not one per game.
- Serial reading: about a quarter second per disc on first launch (§4.6
  probe), once per game, then stored.
- Database: two small tables; rows grow with games the user has launched
  and choices made.
- No new Python dependency. `chdman` is an existing system tool, optional:
  without it CHD games get no per-game settings.

## 14. Migration / compatibility

- The migration adds two nullable `games` columns and two tables. Existing
  rows are unaffected.
- DuckStation and PCSX2 rows still at their seeded template change to use
  `{fullscreen_flag}`; the default choice is `on`, so a launch starts
  fullscreen as before.
- In the user's existing per-game files every key already there counts as
  the user's and is kept; RetroDB only adds managed keys they lack (§4.6
  step 1).

## 15. Open questions

- **Q1** — PCSX2's portable-mode marker files (`portable.txt`,
  `portable.ini`) are taken from its documentation's description of
  `-portable` and not checked against its source. The user's PCSX2 runs from
  `pcsx2.AppImage.home`, which is verified.
- **Q2** — Whether DuckStation or PCSX2 rewrite a value in another form when
  the user saves per-game settings (`4` as `4.000000`, say) is unmeasured.
  If they do, step 1 hands that key to the user for good. Settle it by saving
  a per-game setting in each over a file RetroDB wrote and diffing the file.
