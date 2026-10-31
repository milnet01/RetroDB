<!-- ants-spec-format: 1 -->
# PASS-59-155 — Cheats for the player, DuckStation and PCSX2

**Status:** built 2026-10-29 for 3.34.0. The manual run in each emulator
(§7) is still owed.
**Kind:** feature.
**Source:** ROADMAP PASS-59-155 (user asks and answers 2026-10-22 and
2026-10-23).
**Pairs with:** PASS-59-81 (player cores and settings), PASS-59-91
(standalone per-game settings).

Layman: the game page lists the cheats that exist for a game, each with an
on/off switch, and the game starts with the ones you switched on, whether
it plays in RetroDB's player, DuckStation or PCSX2.

## 1. Goal

After this ships, a user can press one button to download the free public
cheat packs, or import cheat folders they already have. The game page then
shows a Cheats panel listing every cheat RetroDB found for that game, with a
switch for each. Pressing Play starts the game with those cheats on: in the
player (RetroArch), in DuckStation and in PCSX2. A cheat switched on or off
inside the emulator during play shows the same way on the game page
afterwards.

## 2. Problem

1. **Nothing in RetroDB handles cheats.** No `.py`, `.html` or `.js` file
   sets a cheat key or writes a cheat file.
2. **The player cannot load a cheat file yet.** RetroArch loads
   `<cheat_database_path>/<core library name>/<content basename>.cht` at
   content load, and only applies it when `apply_cheats_after_load` is
   `"true"` (default false; found by the RetroArch fork session in
   `command.c` and `cheat_manager.c`). `services/player.py::_BASE_KEYS` sets
   neither key. RetroDB knows each core only by its id
   (`data/player_cores.json`), not by the library name RetroArch names the
   folder after.
3. **RetroArch matches no cheat file to a game.** The public pack is one
   folder per system, one file per title and cheat device, named like
   `007 - Die Welt ist nicht genug (Germany) (Xploder).cht`. RetroDB must
   pick the file.
4. **DuckStation and PCSX2 need a per-game switch list.** Both emulators
   read cheats only when the game's own settings file says so, and apply
   each named cheat only when it is listed there (§4.5).
5. **The user's existing cheats sit in five folders in four layouts**
   (recorded on the roadmap item), so no single copy step can take them.

## 3. Scope decisions (agreed with the user)

1. v4.0.0 covers the player, DuckStation and PCSX2. PPSSPP, RPCS3 and the
   user's own RetroArch come later (§9). (user, 2026-10-23)
2. RetroDB downloads the free public packs on request, and can also import
   the user's own folders. (user, 2026-10-23)
3. An import copies files into RetroDB's data folder once. The original
   folders are only read. Running the import again picks up new files.
   (user, 2026-10-23)
4. The game page lists every cheat with its own switch, and RetroDB sets up
   the emulator before launch. (user, 2026-10-23)
5. A cheat pauses achievement hardcore mode. The page warns; it does not
   grey anything out. (user, roadmap item, 2026-10-22)

## 4. Design

### 4.1 The cheat store

One folder under the app, two layers. `packs/` holds what a download
wrote and is replaced whole by the next download. `own/` holds imports and
is never touched by a download. A lookup reads `own/` first, so a file the
user imported wins over a pack file with the same name.

```
data/cheats/
  packs/retroarch/<libretro system folder>/<title>.cht
  packs/duckstation/<SERIAL>[_<hash>].cht
  packs/pcsx2/<SERIAL>_<CRC>.pnach | <CRC>.pnach
  own/retroarch/<libretro system folder>/<title>.cht
  own/duckstation/...
  own/pcsx2/...
  sources.json        # per pack: url, downloaded_at, file count
```

New module `services/cheats.py` owns the store, the matching, and the read
and write of each format. New route module `routes/cheats.py` holds the
API (§4.7).

### 4.2 Packs

| Pack | URL | Unpacks |
|------|-----|---------|
| `retroarch` | `https://buildbot.libretro.com/assets/frontend/cheats.zip` | every `*.cht` under its system folders |
| `duckstation` | `https://github.com/duckstation/chtdb/releases/download/latest/cheats.zip` | every `*.cht` |
| `pcsx2` | `https://github.com/xs1l3n7x/pcsx2_cheats_collection/archive/refs/heads/main.zip` | every `*.pnach` under `*/cheats/` |

A download runs on the player downloads job's queue as `_cheats_<pack>`,
and follows `services/player_cores.py::install_shaders`: stream to a `.part` file under
a size cap, unpack into a staging folder, refuse any member whose path
resolves outside it, then swap the staging folder in with `os.replace`. The
pack's old folder goes only after the swap. No checksum is published for
any pack, so none is checked. Only files with the pack's own extension are
kept. Redirects are followed: GitHub serves both its packs from other
hosts. The download fails unless it ends on a libretro or GitHub host
(`services/cheats.py::_PACK_HOSTS`).

### 4.3 Import

`POST /api/cheats/import {path}` walks one folder, admin only. Each file is
sorted by what it is, not by where it sits:

| File | Goes to | Name kept when |
|------|---------|----------------|
| `.cht` holding a `cheats = N` line | `own/retroarch/<folder>/` | its parent folder is a libretro system folder or a core library name (§4.4), mapped to the system folder |
| `.cht` with `[name]` sections and no `cheats =` line | `own/duckstation/` | the name starts with a serial (`^[A-Z]{3,4}-\d{4,5}`; the pack also names discs such as `SLP-86051`) |
| `.pnach` | `own/pcsx2/` | the name is `SERIAL_CRC` or `CRC`; otherwise the first `gametitle=` line's `[SERIAL] [CRC]` names it |

A core library name that serves several system folders (Gambatte: Game
Boy and Game Boy Color) takes the one whose pack holds a file of the same
name; with none or several, the file is skipped. Any other file is skipped. The reply lists counts and each skipped file
with a reason. Re-importing a file that is already in `own/` with the same
bytes changes nothing. A different file with the same name replaces it.
The source folder is only read.

### 4.4 Which list belongs to a game

**Player.** `data/player_cores.json` gains two things. Each system entry
gains `"cheats": "<libretro system folder>"`, for example
`"psx": {"cheats": "Sony - PlayStation", ...}`. A new `"_library_names"`
object maps each core id to the library name RetroArch reports, read from
each core's `retro_get_system_info` source (2026-10-29). The `.info` file's
`corename` differs for `cap32`, `freeintv` and `same_cdi`. The `cheats` key
is read from the system's own entry, never through `same_as`: Game Boy
Color shares Game Boy's cores, not its cheats. A
system with no `cheats` key has no Cheats panel.

The candidates are the store files in that folder whose normalised name
equals the ROM file's normalised name. If none match, the game title is
tried. To normalise, drop every `(...)` and `[...]` group, lowercase, and
squash every run of non-letters and non-digits to one space. The default is
an exact name match first, then the candidate sharing the most bracket
tags with the ROM name, then the first by name. The user can pick another
candidate. The pick is stored as `cheat_source` in the game's player record
(`services/player.py::_record`).

Measured 2026-10-23 with a throwaway script over the user's library and
their RetroArch cheat folder: by normalised name, 54 of 82 Saturn games and
265 of 305 SNES games had a candidate, and 254 of the SNES games had more
than one. So the picker is needed.

**DuckStation.** `own/duckstation/` and `packs/duckstation/` files whose
name starts with the game's `games.disc_serial`.

**PCSX2.** Store files named `<serial>_<crc>*.pnach` or `<crc>*.pnach`,
from `games.disc_serial` and `games.disc_crc`. These are the names PCSX2
itself loads.

Serial and CRC are read with `services/standalone_settings.py::disc_ids`,
which reads the disc the first time and stores both.

### 4.5 Turning cheats on

**Player.** The game's own list lives at
`data/player/settings/game/<id>.cht`, a copy of its `cheat_source`, made
the first time the panel saves. A switch sets that cheat's
`cheatN_enable = "true"` or `"false"`. Two keys join `_BASE_KEYS` (and so
`_PROTECTED_KEYS`): `cheat_database_path` (the profile's `cheats/`) and
`apply_cheats_after_load = "true"`. At launch, `launch_args` copies the
game's `.cht` to
`<profile>/cheats/<library name of the chosen core>/<ROM basename>.cht`.
`after_session` copies that file back over the game's `.cht` (RetroArch
rewrote it with the in-game switches), then deletes it. Because each launch
copies again, a core change finds the right folder.

**DuckStation** (source: `src/core/cheats.cpp`). It loads
`<cheats folder>/<SERIAL>*.cht` and its own built-in list. It applies a
cheat only where the game's `gamesettings/<SERIAL>.ini` has
`[Cheats] EnableCheats = true` and an `Enable = <cheat name>` line for that
cheat. A file on disk wins over a built-in cheat of the same name.

**PCSX2** (source: `pcsx2/Patch.cpp`). It loads
`<cheats folder>/<SERIAL>_<CRC>*.pnach` and `<CRC>*.pnach`. It applies a
named group only where the game's settings file has `[EmuCore]
EnableCheats = true` and a `[Cheats] Enable = <group name>` line. Lines
outside any `[group]` always apply while cheats are on.

For both, a switch on the page writes straight to the emulator's files:
1. It copies each matched store file into the emulator's cheats folder,
   unless a file of that name is already there. The emulator's own file is
   never overwritten.
2. It rewrites the `Enable` lines in the per-game settings file, through
   `services/standalone_settings.py`'s line-level editor, gaining a
   multi-line form of `write_value` (`write_values`). An enabled name the
   panel does not list, such as a DuckStation built-in cheat, stays on.
   Every other line stays as it was.
3. It sets `EnableCheats` to true while any cheat is on, else false.

The cheats folder is `[Folders] Cheats` in the emulator's main settings
file (DuckStation `settings.ini`, PCSX2 `inis/PCSX2.ini`), relative to the
data folder, else `cheats`. The settings file is the one `_target` already
names.

Each emulator's own files are the record of what is on. The panel reads
them every time it opens, so a switch flipped in the emulator's menu shows
there. RetroDB keeps no table of switches.

### 4.6 The Cheats panel

The panel sits in `templates/game_detail.html`, full width under the row
of cards that holds the Emulator settings panel, because a game can have
hundreds of cheats. Where the game's emulator is not the player on a system with a
`cheats` folder, DuckStation or PCSX2, it shows only the reason (PASS-59-197). Its script is
`static/js/game-cheats.js`. It starts folded and remembers open or folded across games, in the browser. Otherwise it holds:

- A list picker, player only, shown when there are two or more
  candidates. Changing it replaces the game's `.cht` after a confirm, which
  says the switches go back to the new file's defaults.
- One switch per cheat, by its name, in a list that scrolls inside the
  panel. Above twelve cheats a search box filters it. PCSX2's ungrouped lines appear as one
  locked row: "Always on while cheats are on".
- A hardcore note. Player: a cheat pauses RetroAchievements hardcore for
  that session. DuckStation and PCSX2: the emulator ignores cheats in
  hardcore mode.
- When nothing matched: a message, with a link to Settings → Emulators for
  admins.

Settings → Emulators gains a Cheats section. It has a Download button per
pack with that pack's date and file count, and an Import folder field.

### 4.7 API

```
GET  /api/games/<id>/cheats      view
  -> {emulator: "player"|"duckstation"|"pcsx2"|null,
      candidates: [{source, name}], source: str|null,
      cheats: [{name, enabled}], always_on: bool,
      reason: str|null}
PUT  /api/games/<id>/cheats      edit
  body {enabled: [name, ...], source?: str}
  (with source alone, the new list keeps its own switches)
GET  /api/cheats/packs           manage_settings
POST /api/cheats/packs/<pack>    admin  (queues the download job)
POST /api/cheats/import          admin  body {path}
```

`source` is a path relative to `data/cheats/`, and the server checks it is
one of the game's candidates. Errors use the project's usual
`error(_('...'))` reply.

## 5. Invariants

- **INV-1** — The player loads the game's switches. After a panel save and
  a launch, the file at `<profile>/cheats/<library name>/<ROM
  basename>.cht` matches the game's `.cht`, and the base cfg holds
  `apply_cheats_after_load = "true"`.
  *Test:* `tests/test_cheats_player.py` — launch_args on a fixture game.
  *Breaks when:* the folder uses the core id instead of the library name;
  or the key is missing from `_BASE_KEYS`.

- **INV-2** — In-game changes are kept. After `after_session`, the game's
  `.cht` equals the launch copy RetroArch rewrote, and the launch copy is
  gone.
  *Test:* `tests/test_cheats_player.py` — a fixture flips one `enable`
  line in the launch copy, then calls `after_session`.
  *Breaks when:* `after_session` skips the copy-back, or copies in the
  wrong direction.

- **INV-3** — Every core in `data/player_cores.json` has a library name,
  and every `cheats` folder value names a folder in the RetroArch pack.
  *Test:* `tests/test_cheats_data.py` (the folder half reads a fixed list
  in the test, taken from the pack when this ships).
  *Breaks when:* a core is added without a library name.

- **INV-4** — RetroDB never overwrites an emulator's cheat file. A file of
  the same name already in DuckStation's or PCSX2's cheats folder keeps
  its bytes after a panel save.
  *Test:* `tests/test_cheats_standalone.py` — a pre-seeded file with
  different content.
  *Breaks when:* the copy uses `shutil.copy` without an existence check.

- **INV-5** — A save writes exactly the switched-on names and leaves every
  other line alone. After a save turning on cheats A and C, the settings
  file has `Enable = A`, `Enable = C` under `[Cheats]` and nothing else
  changed. `EnableCheats` is under `[Cheats]` (DuckStation) or `[EmuCore]`
  (PCSX2). An enabled name the panel does not list stays (2026-10-29).
  *Test:* `tests/test_cheats_standalone.py` — fixture inis with a
  `[Patches] Enable = Widescreen 16:9` line and a `[GPU]` block, both
  emulators.
  *Breaks when:* the writer replaces only the first `Enable` line, or
  writes into `[Patches]`.

- **INV-6** — The panel shows what the emulator will do. A GET after a
  hand edit of the emulator's settings file reports the hand-edited
  switches.
  *Test:* `tests/test_cheats_standalone.py`.
  *Breaks when:* switches are cached in RetroDB.

- **INV-7** — A pack or import cannot write outside `data/cheats/`. A zip
  member `../x.cht`, or an absolute path, fails the download, and the old
  pack stays in place.
  *Test:* `tests/test_cheats_store.py` — a crafted zip.
  *Breaks when:* the resolved-path check is dropped.

- **INV-8** — A download never touches `own/`, and an import never touches
  the source folder.
  *Test:* `tests/test_cheats_store.py` — hash both trees before and after.
  *Breaks when:* the swap replaces `data/cheats/` instead of
  `packs/<pack>/`.

- **INV-9** — The import sorts files by content. A RetroArch `.cht` in a
  folder named by a core library name (e.g. `Snes9x/`) lands under that
  core's system folder; a DuckStation `.cht` named `SLUS-00433.cht` lands in
  `own/duckstation/`; a `.pnach` named only by title is named from its
  `gametitle=` line.
  *Test:* `tests/test_cheats_store.py`.
  *Breaks when:* sorting goes by extension alone.

- **INV-10** — `source` from the client must be one of the game's
  candidates. `../../config.py` is refused with a 400.
  *Test:* `tests/test_cheats_api.py`.
  *Breaks when:* the PUT joins `source` to the store path unchecked.

- **INV-11** — A cheat problem never stops a launch. With a missing store,
  an unreadable `.cht` or no write access, the game still launches without
  cheats, and a warning is logged.
  *Test:* `tests/test_cheats_player.py`.
  *Breaks when:* the launch path raises from the cheat copy.

## 6. Failure modes

- **No serial or CRC can be read.** The panel gives `_target`'s reason,
  and there are no switches.
- **The emulator's data folder is not found.** The panel says to run the
  emulator once, as the Emulator settings panel does.
- **Two PCSX2 settings files for one game.** Use `_target`'s refusal,
  shown in the panel.
- **A pack URL moves or returns non-zip.** The job fails with the HTTP
  status or "not a zip", and the old pack stays.
- **A cheat name with a leading or trailing space, or an `=`.** Names are
  written as the file has them, after `strip()`. A name containing `=` is
  shown but locked, since the ini line cannot hold it. (DuckStation and
  PCSX2 read `Enable = name` by splitting at the first `=`.)
- **The user changes the player core between launches.** §4.5's copy at
  each launch handles it.
- **RetroArch is killed and never rewrites the `.cht`.** The copy-back
  reads an unchanged file, so nothing is lost.
- **The `.cht` copy RetroDB made is missing at `after_session`.** Nothing
  is copied back, and the game's `.cht` stays.

## 7. Tests

| Test file | Locks |
|-----------|-------|
| `tests/test_cheats_player.py` | INV-1, INV-2, INV-11 |
| `tests/test_cheats_data.py` | INV-3 |
| `tests/test_cheats_standalone.py` | INV-4, INV-5, INV-6 |
| `tests/test_cheats_store.py` | INV-7, INV-8, INV-9 |
| `tests/test_cheats_api.py` | INV-10 |

All use the conftest media and DB isolation. None reaches the network; the
download tests serve a zip from a temporary file. Each test is seen to fail
before its code exists. A manual run in DuckStation, PCSX2 and the player
confirms each emulator applies a switched-on cheat. That step cannot be
automated here.

## 8. Alternatives considered (and rejected)

- **Read the user's folders in place.** Rejected by the user: cheats vanish
  when a drive is unmounted.
- **A RetroDB table of switches.** Two records of one fact, and the
  emulator's menu would drift from it. The emulator's files are the record.
- **A symlink instead of the player copy.** RetroArch rewrites the file on
  exit, and the item records "copies, never symlinks".
- **Take the library name from each core's `.info` file.** Rejected
  2026-10-29: three cores report another name in their source.
- **Read the library name from the core binary with `ctypes`.** Loads
  native code into the web server process. A data entry, pinned by
  INV-3, does the same job.
- **One "Cheats on" switch per game.** Rejected by the user: per-cheat
  switches on the page.

## 9. Out of scope

- PPSSPP cheats (the user has a PSP database) — tracked by PASS-59-171.
- RPCS3 game patches (`patch.yml`), research first — tracked by
  PASS-59-172.
- Cheats when a game runs in the user's own RetroArch rather than the
  player — tracked by PASS-59-173.
- Searching memory for new cheats, or editing cheat codes in RetroDB.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1, INV-2, INV-11 | `tests/test_cheats_player.py` |
| INV-3 | `tests/test_cheats_data.py` |
| INV-4, INV-5, INV-6 | `tests/test_cheats_standalone.py` |
| INV-7, INV-8, INV-9 | `tests/test_cheats_store.py` |
| INV-10 | `tests/test_cheats_api.py` |
| Each emulator applies an enabled cheat | **nothing** automated — the manual run in §7; real emulators cannot run in the suite |

## 11. Cross-doc impact

- `CLAUDE.md`: the new route module, template panel, script and settings
  section (Mandatory Workflow step 7).
- `templates/help.html` and each `help.<locale>.html`: a Cheats paragraph.
- `data/changelog.yaml`: the v3.34.0 entry.
- `docs/specs/PASS-59-81-player-cores-and-settings.md`: the two new
  `player_cores.json` keys.
- `docs/specs/PASS-59-64-launcher.md`: the two new base keys.
- `docs/specs/PASS-59-91-zero-setup-play.md`: the multi-line ini writer.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-155-cheats-loop-log.md`.

## 13. Resource cost

- Packs: the RetroArch zip is about 35 MiB to download
  (`curl -r 0-0` Content-Range, 2026-10-23). Unpacked, it is capped at
  1 GiB like the shader pack. The other two are smaller.
- A panel open lists one system folder (player), or globs one serial
  (standalone). Nothing is cached or indexed.

## 14. Open questions

1. Whether RetroArch's rewrite of the `.cht` on exit keeps cheats it could
   not apply. If it drops them, INV-2's copy-back loses them. To check in
   the manual run.
