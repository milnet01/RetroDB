<!-- ants-spec-format: 1 -->
# PASS-59-326 — Build a game's 3D box from its scraped scans

**Status:** accepted (2026-11-21).
**Kind:** feature.
**Source:** ROADMAP PASS-59-326 (user, 2026-11-21).
**Blocked by:** PASS-59-183.  **Blocker for:** PASS-59-325.
**Amends:** `docs/specs/PASS-59-142-box-file-import.md` §4.2 item 7, §4.6, INV-3.

Layman: every scraped game gets a turning 3D box that looks like its real
case, built from its cover scans, with no Slipcase work.

## 1. Goal

After this ships, a scrape that leaves a game with a cover builds the
game's `box_faces` record itself, on the real case for its console and
region: keep case with sleeve and rim, jewel case, cardboard box or
clamshell. The box matches the game's downloaded 3D box picture
(`boxart_3d`) where it can (§4.2); a spine found nowhere is generated.
Games scraped before this get
their box from a **Build 3D Boxes** tool in ROM Tools. A box imported from
Slipcase is never overwritten by a built one.

## 2. Problem

1. **Only an import writes faces.** `services/box_faces.py::import_box_file`
   is the one writer, so a game shows a turning box only after its owner
   makes one in Slipcase and imports it.
2. **The scans are already here.** `games.boxart`, `games.boxart_back` and
   the MobyGames record in `games.box_scans`
   (`services/box_scans.py`, kinds `front`, `back`, `spine`, `full`) hold
   the pictures a box needs.
3. **The builder exists, in another app.** Slipcase (the user's MIT app)
   builds a box file's faces in `core/box_model.py::build_box_model`, from
   the case table `core/case_types.py::CASE_TYPES`, the overlays in
   `core/case_texture.py`, the jewel layout in `core/jewel.py` and the
   generated spine in `core/spine_generator.py`. RetroDB's viewer
   (`static/js/box-viewer.js`) already draws what that builder writes.

## 3. Scope decisions (agreed with the user)

- **Built at every scrape, and by a tool for games already scraped**
  (user, 2026-11-21). The tool sits in ROM Tools with the other tools that
  maintain scraped data (user, 2026-11-21), and runs only when pressed.
- **An imported Slipcase box always wins** (roadmap PASS-59-326).

Chosen here, not by the user: the PC rule in §4.3, which scans fill which
face (§4.2), and that Clear removes a built box (§4.6).

## 4. Design

### 4.1 Where the code lives

A new package, `services/box3d/`, ported from Slipcase at commit `a08a2a4`:

| RetroDB | Slipcase source |
|---|---|
| `services/box3d/cases.py` | `core/case_types.py`, whole |
| `services/box3d/overlays.py` | `core/case_texture.py`, whole |
| `services/box3d/spine.py` | `core/spine_generator.py` and `resources/case_colors.json` |
| `services/box3d/faces.py` | `core/box_model.py` |
| `services/box3d/jewel.py` | `core/jewel.py` |
| `services/box3d/image_ops.py` | the parts of `core/image_utils.py` the two above call |
| `services/box3d/build.py` | new: choosing inputs and case, storing |

The port keeps Slipcase's names and figures, so a later Slipcase fix can be
copied across. Two changes only:

- **No SciPy.** `image_utils._fold_band_means` calls
  `scipy.ndimage.uniform_filter1d`; the port computes the same running mean
  with numpy (`np.pad(..., mode='symmetric')` and a cumulative sum), which
  matches SciPy's default `reflect` mode.
- **Built at the stored size.** Slipcase builds faces up to 1600 px and the
  import then shrinks them to 1080. The port caps the front at
  `box_faces.TARGET_HEIGHT` (1080 px) tall from the start, and a jewel
  case's pixels per mm at `TARGET_HEIGHT / case height`, so no face is
  drawn larger than it is kept.

### 4.2 Choosing the pictures

`build.inputs(game_row)` returns each face's source file, or None:

| Face | First found wins |
|---|---|
| front | MobyGames `front`; MobyGames `full` (a wrap, split by Slipcase's `split_full_cover`); `games.boxart` |
| back | MobyGames `back`; `games.boxart_back` |
| spine | MobyGames `spine` whose caption is empty, `Left`, or names neither `Right`, `Top` nor `Bottom`; else cut from `boxart_3d`; else generated |
| edge, top, bottom | cardboard boxes only: MobyGames `spine` captioned `Right`, `Top`, `Bottom` |

**The 3D box picture** (PASS-59-331). `games.boxart_3d` shows the box as
it looks, so the built box follows it. `services/box3d/cut3d.py` cuts its
front and spine out and straightens them to the case's shape. It cuts only
a picture with a transparent background and the spine on the left; any
other, such as a cartridge box lying flat, is left alone. When the front
is a separate picture (not a `full` wrap):

- `cut3d.same_art` compares the cut front with the chosen front. Under
  `cut3d.SAME_ART` the chosen front is another release's artwork, so the
  cut front and spine replace it and any spine scan.
- Otherwise a game with no spine scan takes the cut spine.
- The back stays the one chosen above, whichever release it is.

A plastic case's edge, top and bottom are its plastic, as Slipcase draws
them. A game with no front gets no box. Every source is a file under
`IMAGE_PATH`, opened through `safe_path`; a symlink is skipped, as
`box_faces._face_path` does.

Before the build each picture is decoded once, reduced with Pillow's
`draft` and `reduce` to no more than twice the size it is drawn at, and
converted to RGB.

### 4.3 Choosing the case

`build.case_for_game(system_folder, region, packaging)` returns a
`cases.CaseType` or None (no box):

1. **Platform.** `build.PLATFORMS` maps a system folder to Slipcase's
   platform name: `psx` PS1, `ps2` PS2, `ps3`, `ps4`, `ps5`, `psp` PSP,
   `psvita` Vita, `xbox`, `xbox360`, `xboxone`, `xboxseriesx`, `gc`
   GameCube, `wii`, `wiiu`, `switch`, `nes`, `famicom`, `snes`, `snesna`,
   `sfc`, `n64`, `gb`, `gbc`, `gba`, `nds` DS, `n3ds` 3DS, `genesis`,
   `megadrive`, `megadrivejp`, `mastersystem`, `gamegear`, `atari2600`,
   `tg16`, `pcengine`, `saturn`, `saturnjp`, `segacd`, `megacd`,
   `megacdjp`, `dreamcast`, and the PC folders `pc`, `dos`, `windows`,
   `windows3x`, `windows9x`. Any other folder gets no box: arcade sets and
   home computers came in boxes Slipcase has no case for.
2. **Region.** A folder that names its region keeps it (`famicom`, `sfc`,
   `saturnjp`, `megacdjp`, `megadrivejp` NTSC-J; `megacd` PAL). Otherwise
   the first country code of the MobyGames group the scans came from, as
   it is the box that was scanned, else of
   `scraper/ss_regions.py::region_codes(games.region)`: `jp` is NTSC-J; a
   European code or one of `build._MORE_PAL` is PAL; anything else is NTSC-U. Then
   `cases.case_for(platform, region)`.
3. **Packaging**, the MobyGames group's `packaging` when there is one.
   `Jewel Case` on a platform whose case is not a jewel case gives
   `CD Jewel Case`, unless the scanned front's shape is nearer the
   platform's case: MobyGames calls a tall PAL Saturn box a jewel case. **A PC game is built only when the packaging is `Keep
   Case` (PC DVD Case) or `Jewel Case`**: most PC games came in a large
   cardboard box, which Slipcase has no case for.
4. **A jewel case's back card** picks the regional case it fits, as
   Slipcase's `jewel.card_case` does.
5. **A tall front or a release date** (PASS-59-329): a US PS1 front nearer
   the long box's shape than the jewel case's gets `PS1 Long Box`; a US
   NES game released from October 1985 to September 1987 gets the box
   with a hang tab. A year alone counts only when all of it falls inside.
6. **Discs, edition and title** (PASS-59-329 round 2), each over the one
   before: a PAL PS1 game with 3 or more discs, or 2 released by October
   1997, gets `PS1 Multiway Case (PAL)`, its disc count read from its
   `.m3u` playlist; words in `games.edition` pick an edition case
   (`build._EDITION_CASES`); a game every copy of which came in one
   colour picks it by title (`build._TITLE_CASES`).

### 4.4 The record

The record is PASS-59-142 §4.1's, with two more keys:

```json
{"version": 1, "source": "auto", "inputs": "3f9c0a21",
 "case": {...}, "colours": {...}, "faces": {...}, "shape": {...}}
```

- `source` is `"auto"` on a built record. An imported record has no
  `source` key. `box_faces.is_built(record)` reads it.
- `inputs` is the first 8 hex characters of the SHA-1 of the case name,
  each source file's name and size, the game's title and disc serial (the
  generated spine prints them), and `build.BUILD_VERSION`. A build
  whose `inputs` matches the stored record writes nothing.
- `shape` is written when the case has one (`cases.CaseType.shape`), with
  `box_faces.SHAPE_KEYS`' names.

Storing reuses `box_faces`' write path, split out of `import_box_file` as
`box_faces.store_faces(game_id, encoded, record, old)`: the faces are written
with a new token, the row is updated, then the old files are deleted.

### 4.5 When a box is built

`build.build_for_game(game_id) -> str` returns one of `built`,
`unchanged`, `imported`, `no_case`, `no_front`, `failed`:

- `imported` — `faces_for` reads a record without `source: auto`. Nothing
  is written.
- `unchanged` — the stored built record's `inputs` match.
- `failed` — any error. It is logged; the row and folder are unchanged.

It is called:

- **After a scrape saves**, in `hybrid_scraper`'s save block after
  `box_scans.drop_replaced`. It never raises into the scrape.
- **By `BoxBuildJob`** (`services/jobs/box_build.py`, job id
  `box-build`), which walks every game whose folder is in `PLATFORMS`,
  with a cover or box scans, and whose `box_faces` is NULL or built. One
  game at a time; it can be cancelled; its progress shows in the job
  toast as the image resizer's does. On Linux the job's thread lowers its
  own priority (`os.setpriority` on its native thread id, niceness 10),
  so the server stays quick while it runs.

### 4.6 What changes in PASS-59-142

- **Import over a built box asks nothing** (§4.2 item 7): `exists` is
  raised only when the stored record is an import.
- **Clear removes a built box** (§4.6): `clear_scraped_data` and the game
  page's Clear delete a built record and its files, since it is made from
  scraped pictures. An imported box stays.
- The Edit window names the case and says the box was built from the
  scans, or imported. **Remove** works on both; a removed built box comes
  back at the next scrape or tool run.

### 4.7 ROM Tools

A **Build 3D Boxes** card in `templates/rom_tools_hub.html`, admin-only
like the image resizer, confirms and calls
`POST /api/maintenance/box-build/start`. `GET .../status` and
`POST .../cancel` follow the image resizer's routes in
`routes/maintenance.py`.

## 5. Invariants

- **INV-1** — A build never writes over an imported box.
  *Test:* `tests/test_box_auto.py`, import a box, then `build_for_game`
  returns `imported`; the row and folder are unchanged.
  *Breaks when:* the build checks only that `box_faces` is NULL, or
  treats a record without `source` as built.

- **INV-2** — An import replaces a built box without `replace`.
  *Test:* `tests/test_box_auto.py`, build, then import with
  `replace=False`; the row holds the import and the built files are gone.
  *Breaks when:* the `exists` check ignores `source`.

- **INV-3** — A second build with the same inputs writes nothing; a
  changed input rebuilds.
  *Test:* `tests/test_box_auto.py`, two builds give `built` then
  `unchanged` with the folder's names the same; a new back cover gives
  `built` with new names and the old files deleted.
  *Breaks when:* `inputs` is not compared, or is computed from something
  that differs between two runs.

- **INV-4** — Clear removes a built box and keeps an imported one.
  *Test:* `tests/test_box_auto.py`, `clear_scraped_data` on two games, one
  of each.
  *Breaks when:* Clear skips `box_faces` whatever its source, or deletes
  both.

- **INV-5** — The case follows §4.3.
  *Test:* `tests/test_box_auto.py`, table cases: `ps2` USA → `PS2 DVD
  Case`; `psx` Europe → `PS1 Jewel Case (PAL)`; `sfc` → `Super Famicom
  Cartridge Box`; `pc` with no packaging → None; `pc` `Jewel Case` → `CD
  Jewel Case`; `pc` `Box` → None; `arcade` → None.
  *Breaks when:* the folder map, the region map or the PC rule changes.

- **INV-6** — Every built face is WebP, the front at most 1080 px tall.
  *Test:* `tests/test_box_auto.py`, a 2400 px tall front builds a front
  1080 px tall; a 600 px front is not enlarged.
  *Breaks when:* the build stores Slipcase's 1600 px faces, or enlarges.

- **INV-7** — A scanned spine is used; with none, one is generated.
  Amended by INV-11 and INV-12 (PASS-59-331): with none, the 3D box
  picture's spine comes before a generated one.
  *Test:* `tests/test_box_auto.py`, a solid-red spine scan gives a red
  stored spine; without it the spine is the generated one's colour.
  *Breaks when:* §4.2's caption rule picks the wrong scan, or ignores it.

- **INV-8** — A failed build leaves the row and the folder as they were,
  and a scrape still succeeds.
  *Test:* `tests/test_box_auto.py`, a write that raises gives `failed`,
  the row unchanged and no new file.
  *Breaks when:* the row is written before the faces, or the error reaches
  the scrape.

- **INV-9** — The port's running mean matches SciPy's `uniform_filter1d`.
  *Test:* `tests/test_box_auto.py`, random arrays at several window sizes,
  even and odd, compared to a stored SciPy result.
  *Breaks when:* the padding or the window's centre differs.

- **INV-10** — The job's routes refuse a non-admin, and its status route a
  signed-out visitor.
  *Test:* `tests/test_box_auto.py`.
  *Breaks when:* a decorator is dropped.

- **INV-11** — With no spine scan, a cut 3D box picture's spine is used.
  A picture that cannot be cut leaves the generated spine.
  *Test:* `tests/test_box_auto.py`, a 3D picture with a red spine and the
  cover's artwork gives a red stored spine; with an opaque background it
  does not.
  *Breaks when:* the cut is skipped, or a picture with no transparent
  background is cut.

- **INV-12** — A front that is another release's artwork gives way to the
  3D box picture's front.
  *Test:* `tests/test_box_auto.py`, a cover unlike the 3D picture's front
  stores a front that `same_art` matches to the 3D picture.
  *Breaks when:* the comparison is skipped, or `SAME_ART` is set where
  the same artwork falls under it.

- **INV-13** — A `Jewel Case` label follows the scanned front's shape.
  *Test:* `tests/test_box_auto.py`, a PAL Saturn front 513 × 800 gets
  `Sega Long Box`; a front 1.12 wide per 1 tall, or a wrap, gets
  `CD Jewel Case`.
  *Breaks when:* the label wins over the scan's shape, or a wrap's shape
  is used.

## 6. Failure modes

- **A source file is missing or unreadable**: that face falls back as §4.2
  says; no front means `no_front`.
- **Pillow cannot decode a picture**: `failed`, logged, nothing written.
- **No font found**: `spine._get_font` falls back to Pillow's own font,
  as in Slipcase.
- **The server stops mid-job**: the job ends; a rerun skips every game
  whose `inputs` already match.
- **A scrape and the job build one game at once**: the last write wins;
  the loser's files carry a live game's prefix and are leaked, as
  PASS-59-142 §6 says of two imports.

## 7. Tests

`tests/test_box_auto.py` covers INV-1 to INV-13, with pictures made in the
test under the conftest media isolation. Each test is seen failing before
its rule exists.

Port check, by hand, once: the same front, back and case through
Slipcase's `build_box_model` and through `services/box3d/faces.py`, at the
same size, give pictures whose mean difference is under 1 level.

Manual: build boxes for a PS2, a PS1 PAL, an SNES and a Genesis game, turn
each on the game page at desktop and ~375 px; run the tool, cancel it, run
it again.

## 8. Alternatives considered (and rejected)

- **Calling Slipcase as a program.** RetroDB ships to people without
  Slipcase, and the standalone build would have to carry it.
- **Building in the browser.** The viewer would redo the work on every
  page view, on every visitor's device.
- **Building when a game page first opens.** The first view waits about a
  second, and the work lands at an unplanned time.
- **Keeping SciPy.** A large dependency for one running mean.

## 9. Out of scope

- A PC big-box case — deferred; not yet queued.
- Opening the box — PASS-59-325.
- ScreenScraper's spine and full-cover media — deferred; not yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 to INV-13 | `tests/test_box_auto.py` |
| `cut3d.SAME_ART` | **nothing** automated — set from 279 library games (PASS-59-331); a new picture source would need measuring again |
| §4.1 port parity | **nothing** automated — the hand check in §7; Slipcase is not in RetroDB's tree |
| §4.5 thread priority | **nothing** — a server-speed effect no test measures |

## 11. Cross-doc impact

- `docs/specs/PASS-59-142-box-file-import.md`: §4.2 item 7, §4.6 and INV-3
  annotated, pointing here.
- `CLAUDE.md` § Media handling: the slipcase line says a scrape also
  builds faces.
- `retrodb.spec`: the `services.box3d` package and `case_colors.json`.
- `templates/help.html`: a sentence on built boxes and the tool, mirrored
  into each `help.<locale>.html`.
- `data/changelog.yaml`: an item in the open 4.0.0, and in each locale's.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-326-auto-3d-box-loop-log.md`.

## 13. Resource cost

- One game at a time, in memory only while it is built: a few decoded
  pictures at no more than twice 1080 px, and float32 overlays the size
  of a face.
- No new dependency. numpy and Pillow are already required.
- Disk: up to six WebP faces per game, as an import stores.
- No GPU work on the server; the viewer is unchanged.

## 14. Migration / compatibility

No migration: `games.box_faces` exists (025). A record without `source`
reads as imported, so every box stored before this stays protected. An
older release ignores the two new keys.
