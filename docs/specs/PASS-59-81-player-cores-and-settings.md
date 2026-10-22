<!-- ants-spec-format: 1 -->
# PASS-59-81 — Best core, core download and recommended settings for the player

**Status:** accepted (2026-10-19; user answered §15 Q1 to Q3, Q4 checked).
Built in v3.31.0 (2026-10-22) against a stub player; only Linux is tested.
**Kind:** implement.
**Source:** ROADMAP PASS-59-81 (user decisions 2026-09-26, relayed with
`retroarch-f5`).
**Blocked by:** the fork's player build (RETR-0004), for anything a user
can run. PASS-59-64's player clauses are built (v3.31.0). **Pairs with:** PASS-59-64 (launch
contract), PASS-59-91 (zero-setup play; its §4.6 choices table and settings
routes are reused here).

Layman: when you press Play on a game that needs a RetroArch core, RetroDB
picks the best core for that console, downloads it if you do not have it,
and starts the game with good settings; you can pick another core or other
settings for a whole console or for one game.

## 1. Goal

After this ships, the player (PASS-59-64 §4.4) can run every system in
`data/player_cores.json` with no setup. RetroDB ranks the cores for each
system, downloads the chosen one from the libretro buildbot for the host
platform, and writes recommended settings for the system before launch.
The user can choose another core and other values for the managed settings,
per system or per game. Nothing changes for the user's own RetroArch row
beyond its core file names matching the host platform.

## 2. Problem

1. **Core names are Linux-only.** All 12 `retroarch_core` values in
   `data/emulator_seeds.json` end in `_libretro.so` (`grep -c
   '"retroarch_core"' data/emulator_seeds.json` → `12`; `grep -o
   '"retroarch_core": "[^"]*"' data/emulator_seeds.json | grep -vc
   '_libretro\.so"'` → `0`). Windows needs `.dll`, macOS `.dylib`.
2. **One core per system, fixed.** The seeds name one core per system and
   nothing ranks alternatives or lets a game use another.
3. **No downloader.** No Python file mentions the buildbot (`grep -rl
   buildbot --include=*.py .` → no output). PASS-59-64 §4.4 leaves the
   player's `cores/` directory empty and assigns filling it to this item,
   and its §6 answers a missing core with 422.
4. **No recommended settings.** PASS-59-64 §4.4's game cfg holds "the
   per-game settings PASS-59-81 recommends", and nothing defines them.

## 3. Scope decisions (agreed with the user)

1. **(User, 2026-09-26)** Users should not have to set up cores or adjust
   settings. RetroDB picks the core and the settings per system, refined per
   game, and applies them at launch. The user can change any of them per
   system or per game.
2. **(User, 2026-09-26)** This is a spec of its own, so PASS-59-64's
   launch contract is not held up by it.
3. **(Author)** Cores come from the libretro **nightly** buildbot, one zip
   per core. The stable channel offers one all-cores `RetroArch_cores.7z`
   per platform, no per-core index, and no macOS per-core files (§8,
   checked live 2026-10-19).
4. **(Author)** Installed cores are never updated by a launch. An admin
   updates them on request (§4.5). A core changing under a game can break
   its save states.
5. **(Author, open: §15 Q1)** "Refined per game" means the user's own
   per-game choices plus PASS-59-64 §4.5's kept in-game changes. RetroDB
   ships no curated per-game list. This mirrors PASS-59-91 §3's decision
   that per-game fixes come from the emulator, not from RetroDB.
6. **(Author, open: §15 Q2)** Pressing Play may download a missing core for
   anyone allowed to launch. An admin can turn this off with the setting
   `player_core_downloads` (default on).
7. **(Author)** The player becomes a system's default only where that
   system has no default mapping that resolves. This amends PASS-59-64
   §4.4, which made the player the default for every system it has a core
   for; that would have taken over systems the user set up with a
   standalone emulator under PASS-59-91.

## 4. Design

### 4.1 The core table

`data/player_cores.json`, keyed by system folder (`systems.folder`):

```json
{
  "snes": {
    "cores": ["snes9x", "bsnes"],
    "settings": {"aspect_ratio": "core", "integer_scale": "off",
                 "shader": "none", "latency": "1"}
  },
  "sfc": {"same_as": "snes"},
  "_settings": {
    "aspect_ratio":  {"values": {"core": {"aspect_ratio_index": "22"},
                                 "4:3":  {"aspect_ratio_index": "0"}}},
    "integer_scale": {"values": {"off": {"video_scale_integer": "false"},
                                 "on":  {"video_scale_integer": "true"}}},
    "shader":        {"values": {"none": {"video_shader_enable": "false"},
                                 "crt":  {"video_shader_enable": "true",
                                          "video_shader": "<shaders>/crt/crt-easymode.slangp"},
                                 "lcd":  {"video_shader_enable": "true",
                                          "video_shader": "<shaders>/handheld/lcd-grid-v2.slangp"}}},
    "latency":       {"values": {"off": {"run_ahead_enabled": "false"},
                                 "1":   {"run_ahead_enabled": "true", "run_ahead_frames": "1",
                                         "run_ahead_secondary_instance": "false"}}}
  },
  "_options": {}
}
```

- `cores` is ranked, best first. A core id is the libretro file stem
  without `_libretro` (`snes9x` for `snes9x_libretro.so`).
- `same_as` points a folder at another entry and carries nothing else.
- `settings` gives the system's default value for each managed setting.
  A setting it omits is not written for that system.
- `_settings` maps each value to the RetroArch cfg keys it writes.
  `<shaders>` is `<profile>/shaders` (§4.5). The key names and the
  `aspect_ratio_index` values were checked in RetroArch's source (§15).
- `_options` maps a core id to core options (`.opt` keys) RetroDB
  recommends for every game on that core. It ships empty. A key is added
  only after it is read from the core's source or from a `.opt` the core
  wrote, with that source cited in the commit.

**Initial ranking** (accepted by the user 2026-10-19, every id checked present in the
2026-10-19 `linux/x86_64` index):

| Folders | Cores, best first | Default latency |
|---|---|---|
| nes, famicom | mesen, nestopia, fceumm | 1 |
| snes, sfc | snes9x, bsnes | 1 |
| n64 | mupen64plus_next, parallel_n64 | off |
| gb, gbc | sameboy, gambatte | 1 |
| gba | mgba | off |
| nds | melondsds, melonds, desmume | off |
| megadrive, genesis, mastersystem, segacd | genesis_plus_gx, picodrive | 1 |
| sega32x | picodrive | off |
| saturn | mednafen_saturn, yabasanshiro | off |
| dreamcast | flycast | off |
| psx | mednafen_psx_hw, swanstation | off |
| psp | ppsspp | off |
| neogeocd | neocd | off |
| atari2600 | stella | off |
| atari5200 | a5200, atari800 | off |
| atari7800 | prosystem | off |
| atari800 | atari800 | off |
| atarilynx | handy | off |
| atarijaguar | virtualjaguar | off |
| atarist | hatari | off |
| c64 | vice_x64sc | off |
| amstradcpc | cap32 | off |
| msx | bluemsx | off |
| zxspectrum | fuse | off |
| colecovision | gearcoleco | off |
| intellivision | freeintv | off |
| cdimono1 | same_cdi | off |

Every system's default `aspect_ratio` is `core`, `integer_scale` `off` and
`shader` `none`. Systems with a standalone emulator in the seeds (psx, psp,
gb, gbc, gba, nds) keep that emulator as default under §3.7; the player
row is added beside it.

### 4.2 Platform

`services/player_cores.py`:

```python
def core_file_name(core: str) -> str
# 'snes9x' → 'snes9x_libretro.so' on Linux, '.dll' on Windows, '.dylib' on macOS.

def buildbot_dir() -> str | None
# 'linux/x86_64', 'linux/aarch64', 'windows/x86_64',
# 'apple/osx/x86_64' or 'apple/osx/arm64' from platform_utils and
# platform.machine(); None for anything else.
```

The index is `https://buildbot.libretro.com/nightly/<dir>/latest/.index-extended`.
Each line is `<YYYY-MM-DD> <8 hex digits> <file>.zip`. A core is
`https://buildbot.libretro.com/nightly/<dir>/latest/<core_file_name>.zip`.
The index is fetched at most once an hour and kept in memory.

### 4.3 Which core runs

For a game on a system with a `data/player_cores.json` entry, the player's
core is the first of:

1. the game's choice (`emulator_setting_choices`, scope `game`, setting
   `core`);
2. the system's choice (scope `system`, setting `core`);
3. the first core in the system's `cores` list that the platform's index
   lists. When the index cannot be fetched, the first one already
   installed, so a launch works offline.

A choice must be in the system's `cores` list; any other value is refused
on write (400) and ignored on read. The table PASS-59-91 §4.6 creates holds
the choices, with `emulator_id` the player's row. PASS-59-64 §4.4's player
branch takes its `-L` path from this rule instead of from
`system_emulators.retroarch_core` alone. The installer still writes that
column (§4.4), so the Settings mapping table shows the system's core.

### 4.4 Installing a core

```python
def install(core: str) -> Path
# Downloads, checks and installs <profile>/cores/<core_file_name(core)>.
# Raises CoreInstallError(reason) and leaves any existing file untouched.
```

1. The URL is built from the fixed host, `buildbot_dir()` and
   `core_file_name(core)` only. `core` must be an id in
   `data/player_cores.json`.
2. The zip streams to `<profile>/cores/.<file>.zip.part`, capped at
   256 MiB. A larger body, or a non-200 answer, fails.
3. The extracted core's CRC-32 (the zip member named in step 4, not
   the zip) must equal the index's 8 hex digits for that file (§15 Q4).
4. Exactly one member is read: the one named `core_file_name(core)`, with
   no directory part. Missing → fail. Other members are ignored.
5. It is written to a temporary file in `<profile>/cores/`, made
   executable on Linux and macOS, and moved into place with `os.replace`.
   The `.part` file is deleted on every path.
6. `<profile>/cores/installed.json` records `{core: {"crc", "date"}}` from
   the index line.

**After an install for a system**, in one transaction:

- the player's `system_emulators` row for the system exists with
  `retroarch_core = core_file_name(core)`;
- it is made the default only when the system has no default row that
  resolves (PASS-59-91 §4.3's test), and then every other row for the
  system gets `is_default = 0` (PASS-59-64 §4.4);
- `<profile>/settings/system/<folder>.cfg` is written (§4.6).

A launch whose core is installed but whose system has no player row (a
`same_as` folder sharing another's core) writes the row the same way.

**Jobs.** Installs run in one background job,
`services/jobs/player_cores.py`, under `acquire_job_singleton_lock`, with
the progress shape of the other jobs. A request for a core already queued
joins it.

### 4.5 When downloads happen

- **At Play.** `POST /api/launch/<game_id>` resolves the player for a game
  whose system has no default mapping that resolves and has a table entry,
  or whose default is the player. If the chosen core's file is missing and
  `player_core_downloads` is on, it starts the install and answers
  `202 {success: true, installing: {core, bytes, job_id}}`, spawning
  nothing. `bytes` comes from a `HEAD` of the zip, or is `null`. The Play
  buttons (game page, Library and system cards) show
  "Downloading the <system> core…", poll
  `GET /api/player/cores/status`, and send the launch again when the job
  finishes. With the setting off the answer stays PASS-59-64 §6's 422.
- **Shaders.** The first install of a core whose system's chosen `shader`
  is not `none` also downloads
  `https://buildbot.libretro.com/assets/frontend/shaders_slang.zip`
  (54,282,230 bytes on 2026-10-19) into `<profile>/shaders/`, under the
  same rules as §4.4 steps 2 and 5 (no CRC is published for it).
- **Settings → Emulators** (admin): *Install cores for my systems* installs
  the chosen core for every system with games and a table entry.
  *Update cores* re-downloads every core in `installed.json` whose index
  CRC has changed. `POST /api/player/cores/install` and
  `POST /api/player/cores/update`, gated on `manage_settings`.

### 4.6 Settings RetroDB writes

For each managed setting (`aspect_ratio`, `integer_scale`, `shader`,
`latency`) the value is the first of: the game's choice, the system's
choice, the table's system default. Choices live in the same table as
§4.3, setting names as in `_settings`.

- **System cfg** `<profile>/settings/system/<folder>.cfg`: the keys of the
  system's choice, else the table default, for every managed setting the
  system has. Rewritten before each player launch.
- **Game cfg** `<profile>/settings/game/<game_id>.cfg` (PASS-59-64 §4.4):
  the keys of each game choice, written before each launch. Keys the user
  set in the player's menu stay theirs (PASS-59-64 §4.5): a game cfg key
  marked user-set in the game's `.json` is not rewritten. A choice made in
  RetroDB's panel for that setting removes the mark for its keys, so the
  latest decision wins whichever side made it.
- **Core options** from `_options[core]` go into the game's `.opt` under
  the same user-set rule.
- Only the keys in `_settings` and `_options` are written. Every other line
  in these files is kept.

**Routes.** PASS-59-91 §4.6's `GET`/`PUT /api/games/<game_id>/emulator-settings`
and the system-level pair serve the player too, with `serial` `null`,
`file` the game cfg, and `settings` listing `core` plus the managed
settings. `core` may be set per game by `edit`: its value comes from a
closed list RetroDB installed, not free text, so PASS-59-64 §3.14's
admin-only argv rule does not reach it (author's choice).

### 4.7 The user's own RetroArch row

`services/emulator_seeder.py::seed_emulators_from_file` writes
`retroarch_core` with the host's suffix (`_libretro.so` becomes
`core_file_name(stem)`). It inserts with `INSERT OR IGNORE`, so rows
already stored keep their value; the Settings mapping table edits them.

## 5. Invariants

- **INV-1** — `core_file_name` gives `.so` on Linux, `.dll` on Windows and
  `.dylib` on macOS.
  *Test:* `tests/test_player_cores.py` — monkeypatch
  `platform_utils` for each platform and assert the three names for
  `snes9x`.
  *Breaks when:* the suffix is hard-coded, or macOS falls through to `.so`.
- **INV-2** — The automatic core for a system is the first table core the
  platform's index lists.
  *Test:* `tests/test_player_cores.py` — fake index without
  `mesen`; `nes` resolves to `nestopia`; with an empty index it resolves to
  none and the launch answers 422.
  *Breaks when:* ranking ignores the index, so a core with no build for the
  platform is chosen.
- **INV-3** — A download URL holds nothing but the fixed host, the
  platform directory and a core id from the table.
  *Test:* `tests/test_player_cores.py` — `install('../x')` and
  `install('notacore')` raise without a request; the fake HTTP layer
  records no call.
  *Breaks when:* `install` builds the URL from a request field or a
  stored choice without the table check.
- **INV-4** — A download whose extracted core's CRC-32 differs from the
  index, or whose zip lacks the core member, installs nothing and leaves an existing core file
  byte-identical.
  *Test:* `tests/test_player_cores.py` — an existing core file,
  then a fake zip with a wrong CRC, then one with the member under a
  directory; the file's bytes are unchanged after each, and no `.part`
  file remains.
  *Breaks when:* the old file is deleted before the new one is checked, or
  a member with a path is extracted.
- **INV-5** — An install makes the player the default only for a system
  with no default mapping that resolves.
  *Test:* `tests/test_player_cores.py` — system A with a
  resolving standalone default, system B with none; install for both; A's
  default is unchanged, B's is the player.
  *Breaks when:* PASS-59-64 §4.4's unconditional default is kept.
- **INV-6** — Play with the core missing and `player_core_downloads` on
  answers 202 with `installing`, and spawns nothing; with it off, 422.
  *Test:* `tests/test_player_launch.py` — stub player, no core
  file, fake install job; assert 202 and no registry entry; flip the
  setting; assert 422.
  *Breaks when:* the launch spawns the player before the core exists, or
  downloads while the setting is off.
- **INV-7** — A launch never downloads a core that is already installed.
  *Test:* `tests/test_player_launch.py` — core file present,
  index CRC changed; launch spawns, and the fake HTTP layer records no core
  request.
  *Breaks when:* the launch path compares CRCs and updates.
- **INV-8** — A managed setting's written value is the game choice, else
  the system choice, else the table default, and lands in the game cfg or
  the system cfg accordingly.
  *Test:* `tests/test_player_cores.py` — table default `latency`
  `1`; system choice `off`; game choice `1` on one game; the system cfg
  says `run_ahead_enabled = "false"`, that game's cfg `"true"`, another
  game's cfg has no `run_ahead_enabled`.
  *Breaks when:* the table default overrides a choice, or a game choice is
  written to the system cfg.
- **INV-9** — A game's `core` choice is used for `-L` and must be in the
  system's list.
  *Test:* `tests/test_player_launch.py` — game choice
  `bsnes` on `snes`; argv's `-L` ends `bsnes_libretro.so`; a `PUT` of
  `core: "mame"` answers 400.
  *Breaks when:* the player branch reads only `system_emulators.retroarch_core`.
- **INV-10** — A key the user set in the player's menu is not rewritten,
  until a RetroDB choice for that setting is saved.
  *Test:* `tests/test_player_cores.py` — game `.json` marks
  `aspect_ratio_index` user-set with `"0"`; a launch leaves it `"0"`; a
  `PUT` of `aspect_ratio: core` then writes `"22"` and drops the mark.
  *Breaks when:* RetroDB regenerates user-set keys, or a panel choice can
  never win back a key.
- **INV-11** — Install and update routes refuse a caller without
  `manage_settings`; a viewer cannot `PUT` a choice.
  *Test:* `tests/test_player_cores.py` — editor `POST`s to both
  routes → 403; viewer `PUT` → 403; nothing written.
  *Breaks when:* a route is added without its permission decorator.
- **INV-12** — The seeder writes `retroarch_core` with the host's suffix.
  *Test:* `tests/test_emulator_seeder.py` — seed on a fake
  Windows platform; the `snes` RetroArch row reads `snes9x_libretro.dll`.
  *Breaks when:* the seeder copies the `.so` name through.
- **INV-13 (trust boundary)** — Downloaded code comes only from
  `https://buildbot.libretro.com`, over HTTPS, and is installed only into
  `<profile>/cores/` or `<profile>/shaders/`. A redirect to another host
  fails the install.
  *Test:* `tests/test_player_cores.py` — fake response that
  redirects to `http://example.invalid/`; assert `CoreInstallError` and no
  file written.
  *Breaks when:* redirects are followed off-host, or the destination path
  is built from the zip member's name.

## 6. Failure modes

- **No network, buildbot down, or a non-200 answer** → the job fails with
  "Could not download the <system> core. Check the internet connection and
  try again."; the launch answer the UI is polling turns into that error.
  Nothing is installed.
- **Index lacks every core for the system** → no automatic core; the
  launch is PASS-59-64 §6's 422, worded "No core for <system> is built for
  this computer."
- **Unknown platform or CPU** (`buildbot_dir()` is `None`) → downloads are
  off for this install; Settings says so beside the buttons.
- **Disk full while writing** → the job fails, `.part` and temporary files
  are removed, the old core stays.
- **Body over 256 MiB** → fails; the largest core checked, `mame`, was
  116,311,065 bytes on 2026-10-19.
- **The core installs but crashes the player** → PASS-59-64 §6's crash
  path. The user picks the next core in the list per system or per game.
- **Shader pack missing when a game needs it** → the shader keys are left
  out of that launch's cfg and the pack download starts; the game runs
  without a shader this once.
- **macOS refuses an unsigned downloaded `.dylib`** → *unverified*; §15 Q5.

## 7. Tests

- `tests/test_player_cores.py` (new) — INV-1, INV-2, INV-3, INV-4, INV-5,
  INV-8, INV-10, INV-11, INV-13. A fake HTTP layer serves a small index and
  hand-built zips from `tmp_path`; no test reaches the network.
- `tests/test_player_launch.py` (extend PASS-59-64's) — INV-6, INV-7,
  INV-9, with the stub player binary.
- `tests/test_emulator_seeder.py` (extended) — INV-12.

Each test is run red before its code lands. No test downloads a real core
or starts a real player.

## 8. Alternatives considered (and rejected)

- **Stable channel.** One `RetroArch_cores.7z` per platform and version,
  no per-core files, no index, and nothing for macOS (`/stable/1.22.2/`
  checked 2026-10-19). A whole-set download for one game, and a 7z reader
  as a new dependency.
- **Automatic updates at launch.** A nightly changes daily, and a changed
  core can refuse a game's existing save states.
- **A RetroDB-curated per-game table.** Costly to keep true across cores
  and versions; PASS-59-91 made the same call for standalone emulators.
  Open to the user (§15 Q1).
- **A second choices table for the player.** PASS-59-91 §4.6's table has
  the same shape, scope and routes; two tables would give two panels.
- **Download inside the launch request.** `mame` is over 100 MB; a
  request thread would hold the server's worker for minutes.
- **Install every core up front.** Most libraries use a few systems, and
  the full set runs to gigabytes.

## 9. Out of scope

- The player binary, its name and its bundle — the fork's RETR-0004.
- BIOS files — read from the user's RetroArch system directory
  (PASS-59-64 §3.7); RetroDB never downloads them.
- BIOS status from each core's `.info` firmware list — deferred; not yet
  queued.
- Standalone emulators' settings — PASS-59-91.
- Systems with no libretro core in the table (ps2, ps3 and later, Wii U,
  Xbox, Windows games) — not planned here.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_player_cores.py` |
| INV-2 | `tests/test_player_cores.py` |
| INV-3 | `tests/test_player_cores.py` |
| INV-4 | `tests/test_player_cores.py` |
| INV-5 | `tests/test_player_cores.py` |
| INV-6 | `tests/test_player_launch.py` |
| INV-7 | `tests/test_player_launch.py` |
| INV-8 | `tests/test_player_cores.py` |
| INV-9 | `tests/test_player_launch.py` (argv), `tests/test_player_cores.py` (the `PUT`) |
| INV-10 | `tests/test_player_cores.py` |
| INV-11 | `tests/test_player_cores.py` |
| INV-12 | `tests/test_emulator_seeder.py` |
| INV-13 | `tests/test_player_cores.py` |
| The ranking in §4.1 is the best choice per system | **nothing** — a preference call (§15 Q3) |
| `_settings` keys have the effect named in the player | **Partial:** INV-8 proves RetroDB writes them; that the player honours them is checked by the fork session |
| Windows and macOS installs | **nothing** — no build here; marked unverified |

## 11. Cross-doc impact

- `docs/specs/PASS-59-64-launcher.md` — §4.4: the player becomes default
  only where no default resolves (§3.7), and the player branch takes its
  core from §4.3. Its migration, planned as 016, takes the next free
  number when it is built: 016 and 017 are taken. This spec adds no
  migration.
- `docs/specs/PASS-59-91-zero-setup-play.md` — §4.6: the choices table and
  settings routes also serve the player row.
- `docs/specs/settings.md` — `player_core_downloads` (bool, default on,
  admin).
- `docs/specs/api-contracts.md` — the three `/api/player/cores/*` routes
  and the 202 launch answer.
- `docs/specs/jobs.md` — the core install job.
- `templates/help.html` — the Emulators section explains automatic cores.
- `data/changelog.yaml` — per release.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-81-player-cores-and-settings-loop-log.md`.

## 13. Resource cost

- Disk: one core per system used, from under 1 MB (`snes9x`, 917,066 bytes
  zipped) to 116 MB (`mame`) on 2026-10-19; the shader pack 54 MB once.
- Memory: the index (11,359 bytes for `linux/x86_64`) per platform, for an
  hour. Downloads stream to disk, never into memory.
- No new Python dependency: `zipfile`, `zlib.crc32` and `requests`.

## 14. Migration / compatibility

- No schema change. `installed.json` and the profile's `shaders/` are new
  files.
- Existing `system_emulators` rows keep their stored core names (§4.7).
- An install that had RetroArch rows only, on Windows or macOS, gains
  correct core names on a fresh seed only.

## 15. Open questions

- **Q1 (user)** — Should RetroDB ship its own per-game recommendations
  (for example, a different core for games one core runs badly)?
  **Decided** (user, 2026-10-19): no, not for now (§3.5).
- **Q2 (user)** — Should any user who can press Play trigger a core
  download, or admins only? **Decided** (user, 2026-10-19): anyone who can
  launch, with the admin switch (§3.6); the URL and file are fixed by
  RetroDB, not by the user.
- **Q3 (user)** — The §4.1 ranking and default latency. **Decided**
  (user, 2026-10-19): build with them as drafted; the user changes them
  per system later.
- **Q4 (build)** — Does the index's CRC cover the zip or the extracted
  core? **Checked** 2026-10-19 on `nightly/linux/x86_64`: the index line
  for `snes9x_libretro.so.zip` read `e211e6cb`, the zip's own CRC-32 was
  `82667a0c`, and the extracted `snes9x_libretro.so` was `e211e6cb`. The
  index covers the extracted core (§4.4 step 3).
- **Q5 (fork session)** — Does macOS load a downloaded unsigned `.dylib`
  in the player without a quarantine prompt? Unverified.
- **Q6 (fork session)** — Which video driver does the player use, and does
  it load `.slangp` presets? The `shader` values assume a slang-capable
  driver.

Checked live on 2026-10-19: `HEAD` answers 200 for `snes9x` under
`nightly/linux/x86_64`, `linux/aarch64`, `windows/x86_64`,
`apple/osx/x86_64` and `apple/osx/arm64`; the `linux/x86_64`
`.index-extended` (250 lines, format above) lists every core in §4.1;
`stable/1.22.2/` has `RetroArch_cores.7z` for Linux and Windows and
nothing for macOS; `assets/frontend/shaders_slang.zip` answers 200;
`crt/crt-easymode.slangp` and `handheld/lcd-grid-v2.slangp` exist in
`libretro/slang-shaders` master. RetroArch master's `configuration.c`
holds `run_ahead_enabled`, `run_ahead_frames` and
`run_ahead_secondary_instance`; its `retroarch.cfg` documents
`aspect_ratio_index` (20 config, 21 1:1, 22 core provided),
`video_scale_integer`, `video_shader` and `video_shader_enable`; and
`gfx/video_defines.h` starts the aspect enum at `ASPECT_RATIO_4_3 = 0`.
