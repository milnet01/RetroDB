<!-- ants-spec-format: 1 -->
# PASS-59-142 — Import a Slipcase box file onto a game

**Status:** accepted (2026-10-29).
**Kind:** feature.
**Source:** ROADMAP PASS-59-142 (user decisions 2026-10-23).
**Blocker for:** PASS-59-143 (the turnable 3D box viewer reads what this stores).

Layman: in a game's Edit window you pick the box file Slipcase saved, together
with its pictures, and RetroDB keeps those pictures for that game, ready for
the turnable 3D box.

## 1. Goal

After this ships, an editor in a game's Edit window can press **Import 3D box**, pick
a Slipcase `S.box.json` and its face pictures in one file dialog, and RetroDB
stores the faces for that game as WebP with the box's sizes and colours. A
game that already has faces keeps them unless the editor agrees to replace
them. The editor can remove them again. The game's `boxart_3d` picture is
never touched.

## 2. Problem

1. **Slipcase writes box files; RetroDB cannot read them.** The format is
   Slipcase `docs/specs/SLIP-0104-turnable-3d-box.md` § 4.1. Its reference
   reader is Slipcase `core/box_file.py::read_box_file`. No RetroDB file
   names `slipcase-box`.
2. **RetroDB has one 3D picture per game, `games.boxart_3d`**, a single
   flat image. A turnable box needs up to six faces plus the case's sizes, so
   PASS-59-143 has nothing to draw from.
3. **Slipcase's § 11 asks RetroDB for its own image checks**: at most 10 MB
   per image, a real image (Pillow verify and the decompression-bomb guard),
   re-encoded to WebP at 1080 px tall, no symlinks followed, fill-only unless
   the user asks to overwrite.

## 3. Scope decisions (agreed with the user)

- **Import starts in the game's Edit window, one box file per game** (user,
  2026-10-30; it first sat under the cover on the game page, user 2026-10-23).
  Bulk import is out of scope (§ 9).
- **The faces are stored alongside `boxart_3d` and do not replace it** (user,
  2026-10-23).
- **Format version 1 only, every optional face read** (Slipcase sessions,
  2026-10-21: SLIP-0106 keeps version 1 and adds `edge`; SLIP-0110 adds `top`
  and `bottom`).

Chosen here, not by the user: the editor picks the files in the browser
(§ 4.3), and every face is scaled by the one factor that brings the front to
1080 px tall (§ 4.2).

## 4. Design

### 4.1 What is stored

A new column, `games.box_faces` (TEXT, migration 025, NULL = no faces):

```json
{
  "version": 1,
  "case": {"name": "PS2 DVD Case", "width_mm": 135, "height_mm": 190, "depth_mm": 14},
  "colours": {"top": "#1C1C1C", "bottom": "#1C1C1C", "edge": "#1C1C1C"},
  "faces": {"front": "42_front_9f3a1c07.webp", "spine": "42_spine_9f3a1c07.webp",
            "back": "42_back_9f3a1c07.webp", "edge": null, "top": null, "bottom": null}
}
```

- `version` is RetroDB's own record version, not the box file's.
- `case` and `colours` copy the box file's values. Colours are stored in
  upper case.
- `faces` holds all six keys. A face the box file left null or absent is
  `null`.
- The files live in `<IMAGE_PATH>/box_faces/`, named
  `<game_id>_<face>_<token>.webp`. `token` is 8 random hex characters, the
  same for every face of one import. A new import gets new names, so a
  browser never shows a cached old face.

`services/box_faces.py::faces_for(game_row)` is the only reader. It returns
the parsed record with each non-null face turned into a URL under
`images/box_faces/`. It returns `None` when the column is NULL, does not
parse, or the front or spine file is missing on disk.

### 4.2 Checks and conversion

`services/box_faces.py::import_box_file(game_id, uploads, replace) -> dict`
runs every check below before it writes anything. `uploads` maps each
uploaded file's base name to its bytes or file object. Only the box file and
the pictures it names are read, each only up to its size cap plus one byte,
so an editor may pick a whole folder. It raises `BoxImportError(code,
detail)` on the first failure.

1. **Exactly one upload ends in `.box.json`**, at most 64 KB, and parses as
   a UTF-8 JSON object. Codes: `no_box_file`, `two_box_files`, `bad_json`.
2. **The box file passes SLIP-0104 § 4.1's reading rules**, as
   `read_box_file` applies them. `format` is `slipcase-box`. `version` is the
   integer 1. `case.name` is non-empty text. Each size is a number above 0
   and at most 1000. Each of the three colours matches `#RRGGBB` in either
   case. `front` and `spine` are not null. Unknown keys are ignored. Code:
   `bad_box_file`, with the rule in `detail`.
3. **Every non-null face name is one plain file name.** It contains no `/`
   or `\`, is not `.` or `..`, and does not start with `.`. Code:
   `bad_face_name`.
4. **Every named face was uploaded.** The match is on the exact base name.
   Uploads the box file does not name are ignored. This lets the editor pick
   the whole folder's pictures. Code: `missing_face`, with the face names.
5. **Each named picture is at most `MAX_IMAGE_SIZE` (10 MB)** and passes
   `services/game_media_service.py::_validate_image_bytes`, which runs
   Pillow's `verify()` under the `IMAGE_MAX_PIXELS` bomb cap. Codes:
   `face_too_large`, `bad_image`.
6. **The game exists.** Code: `not_found`.
7. **Fill-only.** When `faces_for` already returns a record for the game
   and `replace` is false, nothing is written. Code: `exists`.

Conversion, still before any write:

- Each picture is opened and loaded. One with transparency is flattened
  onto `colours.edge`, as Slipcase does. Otherwise it is converted to RGB.
- **One scale factor for every face:** `min(1, 1080 / front_height)`.
  Faces keep their relative sizes this way. Front, spine, back and edge
  share the front's height, so they come out 1080 px tall. Top and bottom
  are the case's depth tall, so they come out much shorter, and are not
  blown up to 1080. Faces are never enlarged. Resampling is Lanczos.
- Each face is encoded to WebP at quality 85, the value
  `services/image_utils.py` uses for stored WebP.

### 4.3 Writing

After every check passes:

1. Each face is already encoded in memory, and is written with
   `services/atomic_io.py::atomic_write_bytes` to its new name in
   `<IMAGE_PATH>/box_faces/`. If any write fails, the faces
   already written are deleted and the error is raised. The row is
   unchanged.
2. One `UPDATE games SET box_faces = ? WHERE id = ?` stores the record.
3. Only then are the previous import's files deleted. A name that is a
   symlink is skipped first, since `services/security.py::safe_path`
   resolves a link to its target. The rest is resolved with `safe_path`
   against the `box_faces` folder, and a name that escapes it is skipped
   and logged.

`remove_box_faces(game_id)` sets the column to NULL first, then deletes the
files the old record named, with the same `safe_path` and symlink rule.

**No symlink is ever followed on the way in.** The files arrive as upload
bytes, so RetroDB never opens a path the editor chose.

### 4.4 Routes

In `routes/games_media.py`, both `@editor_required`, both replying with
`services/api_helpers.py::success` / `error`:

```
POST   /api/games/<int:game_id>/box-faces   multipart: files (repeated), replace=0|1
       → success({"box_faces": <faces_for record>})
       → error(<translated message>, code=400|404|409, reason=<BoxImportError code>)
DELETE /api/games/<int:game_id>/box-faces
       → success({"removed": true|false})
```

`exists` replies with 409. `not_found` replies with 404. Every other code
replies with 400.

### 4.5 The Edit window and the game page

- In the Custom Images section of `templates/_modals/edit_modal.html`, an
  editor sees an **Import 3D box** button. It opens a hidden
  `<input type="file" multiple accept=".json,.png,.webp,.jpg,.jpeg">` with no
  `name`, so the form never sends it. A tip tells the editor to pick the
  `.box.json` file and its pictures together, and that the import saves
  straight away, without Save Changes. Cancel does not undo it.
- On a 409 reply, `showConfirm` asks whether to replace the existing faces.
  Yes resends with `replace=1`.
- When `faces_for` returns a record, the same field says the 3D box is
  imported, names the case, and shows a **Remove** button.
- Under the cover in `templates/game_detail.html`, anyone sees a one-line hint
  that clicking the cover turns the 3D box. It shows only when the game has
  faces and a cover to click.
- The script is `static/js/game-box-faces.js`, loaded by its own `<script>`
  tag like `game-cheats.js`. Its strings use `t()`; `build_js.py` scans
  every `static/js/*.js` for them. Template strings use `_()`.

### 4.6 What else learns the folder

- `services/media_cleanup.py::find_orphaned_media` gains the `box_faces`
  folder. Its existing `<game_id>_` prefix rule then sweeps the faces of a
  deleted game.
- `clear_scraped_data` does not touch `box_faces`. The faces are imported by
  hand, not scraped.
- The image jobs (`image_resize`, `webp_migrate`, `upscale_queue`) do not
  learn the folder. The faces are already final WebP.
- `build_dist.py` ships only the `static/images/` subfolders on its
  whitelist, so user faces never enter a release zip.

## 5. Invariants

- **INV-1** — A box file that breaks any § 4.2 check writes no file and
  leaves `games.box_faces` unchanged.
  *Test:* `tests/test_box_faces.py`. One case per code, each changing one
  field of a valid fixture, asserting the code, an empty `box_faces` folder
  and an unchanged row.
  *Breaks when:* a check runs after the first write, or a write happens
  before the last check.

- **INV-2** — Every stored face is WebP. Front, spine, back and edge are
  `min(1080, original height)` px tall. All faces share one scale factor.
  *Test:* `tests/test_box_faces.py`, a 1600-px-tall front with a
  1600 × 118 top: the front comes out 1080 tall, the top
  `round(118 × 1080 / 1600)` tall. A 900-px front stays 900.
  *Breaks when:* faces are scaled one by one to 1080 tall, or small faces
  are enlarged.

- **INV-3** — Fill-only. An import onto a game with readable faces and
  `replace` false returns `exists`, and changes nothing on disk or in the
  row.
  *Test:* `tests/test_box_faces.py`, two imports in a row.
  *Breaks when:* the `exists` check is skipped or runs after the writes.

- **INV-4** — A replace leaves only the new import's files for that game,
  and the row names them.
  *Test:* `tests/test_box_faces.py`, replace, then list the folder.
  *Breaks when:* old files are left behind, or deleted before the UPDATE.

- **INV-5** — No delete reaches outside `<IMAGE_PATH>/box_faces/` or
  through a symlink, whatever the stored record names.
  *Test:* `tests/test_box_faces.py`. A record with `../boxart/x.webp`, and
  one with a symlinked face, are removed. The outside file and the symlink's
  target both survive.
  A third case: a symlink to another face inside the folder is not
  followed.
  *Breaks when:* a face name is joined without `safe_path`, or `islink` is
  checked only after `safe_path` has resolved the link.

- **INV-6** — `boxart_3d` is never read or written by import or removal.
  *Test:* `tests/test_box_faces.py`, a game with `boxart_3d` set is
  imported, replaced and removed. The column and its file are unchanged.
  *Breaks when:* import treats the front face as the 3D cover.

- **INV-7** — Both routes refuse a viewer: only an editor or an admin
  reaches them.
  *Test:* `tests/test_box_faces.py`, a viewer session gets the
  `editor_required` refusal on POST and DELETE.
  *Breaks when:* the decorator is dropped.

## 6. Failure modes

- **Disk full or I/O error during the writes**: the faces written so far are
  deleted, the row is unchanged, and the reply is a 400 with the reason
  `write_failed`.
- **UPDATE fails after the writes**: the new files are deleted. The old
  record and its files stay.
- **Deleting an old file fails after the UPDATE**: it is logged and left.
  Its `<game_id>_` prefix belongs to a live game, so the orphan sweep keeps
  it. It is a leak, not a broken reference.
- **A face file is deleted by hand**: `faces_for` returns `None` when front
  or spine is missing, so the page treats the game as having no faces. The
  next import then needs no `replace`.
- **The request is larger than `MAX_UPLOAD_BYTES`**: Werkzeug refuses it,
  as for every upload.
- **Two imports at once on one game**: the last UPDATE wins. The loser's
  files keep a live game's prefix and are leaked, not swept. An editor rarely
  does this, and the next replace deletes only what its own old record named.

## 7. Tests

`tests/test_box_faces.py` covers INV-1, INV-2, INV-3, INV-4, INV-5, INV-6
and INV-7. Fixtures are built in the
test with Pillow under the conftest media isolation (`RETRODB_IMAGE_PATH` set to a
test folder). `tests/test_pass48_media_cleanup.py` gains a case showing a
deleted game's faces are listed as orphans. Each test is seen failing
against the code before its rule exists.

Manual: in the browser, import a box file Slipcase wrote, at desktop and
~375 px. Then import it again and accept Replace. Then try a face over
10 MB. Then remove the faces.

## 8. Alternatives considered (and rejected)

- **A ZIP upload.** Slipcase writes loose files, so the editor would have to
  zip them first.
- **A server-side folder path.** It opens paths the editor types, so it would
  need the symlink and containment checks the upload route avoids. It also
  fails when the browser is on another machine.
- **Scaling every face to 1080 px tall.** A top face only the case's depth
  tall would be enlarged by about nine times, and the faces would no longer
  match each other.
- **One column per face.** It means six columns and six migrations' worth of
  plumbing for something only PASS-59-143 reads.

## 9. Out of scope

- Bulk import of many box files — deferred; not yet queued.
- Drawing the box — PASS-59-143.
- Version 2 box files — deferred; not yet queued. A version other than 1 is
  refused.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_box_faces.py` |
| INV-2 | `tests/test_box_faces.py` |
| INV-3 | `tests/test_box_faces.py` |
| INV-4 | `tests/test_box_faces.py` |
| INV-5 | `tests/test_box_faces.py` |
| INV-6 | `tests/test_box_faces.py` |
| INV-7 | `tests/test_box_faces.py` |
| § 4.6 orphan sweep | `tests/test_pass48_media_cleanup.py` |
| § 4.5 page behaviour | **nothing** automated — the manual run in § 7 |

## 11. Cross-doc impact

- `CLAUDE.md` § Media handling: a line on `games.box_faces` and its folder.
- `docs/specs/migrations.md` § 13: a row for 025. `retrodb.spec` lists the
  module so the standalone build bundles it.
- `templates/help.html`: a paragraph on importing a 3D box, mirrored into
  each `help.<locale>.html`.
- `data/changelog.yaml`: an item in the open 3.34.0.
- Slipcase: none. RetroDB reads the format; it does not change it.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-142-box-file-import-loop-log.md`.

## 13. Migration / compatibility

Migration 025 adds `games.box_faces` as TEXT, NULL for every row. Nothing is
backfilled. An older release opening the database ignores the column.
