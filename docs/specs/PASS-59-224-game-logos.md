<!-- ants-spec-format: 1 -->
# PASS-59-224 — Game logos on the game page

**Status:** built (2026-11-03; contract gate cancelled for this project).
**Kind:** feature.
**Source:** ROADMAP PASS-59-224 (user, 2026-11-02; scope narrowed 2026-11-03).
**Pairs with:** PASS-59-142 (box faces sit beside the box art this pass may stand in for).

Layman: scraping now also saves each game's logo, the game's name drawn as art
on a clear background, and the game page shows it above the title and in place
of a missing box.

## 1. Goal

After this ships, a scrape fills a new `games.game_logo` field from ES-DE,
ScreenScraper, TheGamesDB, IGDB and Steam, fill-only like the other pictures.
The game page shows the logo above the title text, and shows it in the box
slot when the game has no box art. A logo keeps its transparent background. A
Fill Missing bulk scrape revisits a game whose only gap is its logo. An editor
can upload or clear a logo in the Edit window.

## 2. Problem

1. **Five sources send a logo and RetroDB keeps none.**
   - ES-DE: `scrape_esde.py` reads the gamelist `marquee` tag, and nothing
     uses it. `_ESDE_SINGLE_MEDIA` has no `marquees` row.
   - ScreenScraper: `scrape_screenscraper.py::parse_media` maps `wheel` and
     `wheel-hd`, and nothing reads them.
   - TheGamesDB: `scrape_thegamesdb.py::_fetch_game_images` asks for
     `screenshot,titlescreen,fanart` only.
   - IGDB: `scrape_igdb.py` asks for `artworks.url` with no type.
   - Steam: `scrape_steam.py` builds no logo address.
2. **IGDB fanart can be a logo.** `metadata_merger.py::apply_igdb_to_metadata`
   takes `artworks[0]` as fanart. IGDB files logos under artworks: its
   `artwork_types` endpoint lists 5 `game-logo-white`, 6 `game-logo-black` and
   7 `game-logo-color` (asked live 2026-11-03). A game whose first artwork is
   a logo gets that logo as its page background.
3. **A game with no box shows only a 🎮 placeholder**
   (`templates/game_detail.html`, `.game-boxart-empty`).

## 3. Scope decisions (agreed with the user)

- **Game page only in this pass** (user, 2026-11-03). The roadmap also asked
  for the logo on a full-screen play or loading screen. None exists:
  `static/js/game-launch.js::launchGameImpl` relabels the Play button and shows
  toasts. That screen is out of scope (§ 9).
- **The logo goes above the title, and the title stays text** (user,
  2026-11-02), because a logo can be hard to read.
- **The logo stands in for a missing box** (user, 2026-11-02).
- **Already-scraped games are filled by the Fill Missing bulk scrape** (user,
  2026-11-02, the bulk scrape held until this pass lands).

Chosen here, not by the user:

- The name `game_logo`, because `systems.logo` and `static/images/systems/`
  already hold console logos.
- Steam as a fifth source: `logo.png` exists for every app tried, and costs
  one download.
- The IGDB order: colour, then white, and never black (§ 4.4).

## 4. Design

### 4.1 Storage

- Migration `036_games_game_logo`: `_add_column_if_missing(cursor, 'games',
  'game_logo', 'TEXT')`, after `025_games_box_faces`' pattern. Listed in
  `services/migrations/__init__.py::MIGRATIONS`, `retrodb.spec`'s hidden
  imports and `docs/specs/migrations.md`'s table. NULL means no logo. The
  wishlist table does not get the column.
- Folder `<IMAGE_PATH>/game_logos/`, created in `app.py`'s startup list and
  `installer_core.py::DIRECTORIES`.
- Filenames `{game_id}_{source}_logo{ext}`, with source `esde`, `ss`, `tgdb`,
  `igdb`, `steam` or `custom`.

### 4.2 Image handling

- `game_logo` joins `_CONVERTIBLE_TYPES`. With `IMAGE_FORMAT` `webp` a logo is
  stored as WebP, which keeps alpha (`_save_image` checked 2026-11-03: a
  palette PNG with a transparent index saved to `.webp` reads back RGBA,
  corner pixel `(0, 0, 0, 0)`).
- With `IMAGE_FORMAT` `jpeg`, `preferred_image_extension('game_logo', ...)`
  returns `.png`. JPEG has no alpha.
- `standardize_downloaded_image` returns early for `game_logo`. A logo is
  never resized or upscaled. No `-sm`/`-md` variants.
- `scraper/base_scraper.py`'s list of folders that get
  `finalize_downloaded_image` gains `game_logos`.
- ES-DE copies keep their source extension, as `copy_media` does for fanart.

### 4.3 Where each source's logo comes from

| Source | What is read | Where |
|---|---|---|
| ES-DE | gamelist `marquee` tag, else `downloaded_media/<system>/marquees/` | new `_ESDE_SINGLE_MEDIA` row `('game_logo', 'marquee', 'marquees', 'game_logos', 'esde_logo', 'esde_logos')` |
| ScreenScraper | `wheel-hd`, else `wheel`, nearest the game's region | `_pick_media(medias, ('wheel-hd',), 'png', own_region)`, then `('wheel',)`, in `apply_screenscraper_to_metadata` |
| TheGamesDB | `clearlogo` in the same Images request | `_fetch_game_images`' filter becomes `screenshot,titlescreen,fanart,clearlogo`; it returns a third list |
| IGDB | `artworks.artwork_type` 7, else 5 | both artwork queries (`scrape_igdb.py`, `hybrid_scraper.py`) add `artworks.artwork_type`; image size `t_original`, extension `.png` |
| Steam | `<ART_URL>/<app_id>/logo.png` | new `scrape_steam.py::logo_urls`, used by `apply_steam_to_metadata` |

TheGamesDB's reply shape was checked live 2026-11-03 (games 1 to 5):
`{"type": "clearlogo", "side": null, "filename": "clearlogo/1.png",
"resolution": "400x200"}`, joined to `base_url.original`.

IGDB's `.jpg` address drops transparency. The `.png` address at `t_original`
returned RGBA at the logo's own size (artwork `ar4dmn`, 508×268), where
`t_1080p` returned it upscaled to 1920 wide.

### 4.4 IGDB fanart and logo picks

```python
_IGDB_LOGO_TYPES = (7, 5)              # colour, then white; 6 (black) is never used
_IGDB_NOT_FANART = {5, 6, 7, 8, 12, 13, 14}   # logos, infographic, icons
```

Fanart takes the first artwork whose `artwork_type` is missing or not in
`_IGDB_NOT_FANART`. A black logo is invisible on the dark themes and is never
picked.

### 4.5 Scrape plumbing (`scraper/hybrid_scraper.py`)

- `game_logo` is in the initial `metadata` dict, the database pre-population,
  `_KEPT_MEDIA_FIELDS`, both `_media_dirs` maps, `_merge_esde`'s fill list,
  and `_save_game_row` as `game_logo = COALESCE(?, game_logo)`.
- The ES-DE half: `apply_esde_metadata`'s SELECT, `existing` map and UPDATE.
- `services/wishlist_scraper.py::_empty_metadata` has no `game_logo` key. A
  merger downloads a logo only for a record that has the key
  (`metadata_merger._wants_logo`), so the wishlist, which keeps none, fetches
  none (changed at build: with the key, every wishlist scrape downloaded
  logos it then dropped).
- `services/apply_progress.py::_MEDIA_KINDS` and `static/js/apply-progress.js`
  gain a `logo` kind, label `t('logo')`.
- `services/jobs/bulk_scrape.py`: the Fill Missing field list gains
  `game_logo`.

### 4.6 Media upkeep

- `services/media_cleanup.py`: `_media_layout`, `_collect_referenced_files`
  and `find_orphaned_media` all gain `game_logo` / `game_logos`, in one
  change. The SELECTs in `routes/maintenance.py` and
  `media_cleanup.clear_missing_media_refs` add the column.
- `services/game_cleanup.py`: `_SCRAPED_FIELDS` and the `delete_images`
  SELECTs gain it.
- Not added: `webp_migrate`, `image_resize`, `upscale_queue`,
  `ss_region_repair` (§ 9).

### 4.7 Edit window

`templates/_modals/edit_modal.html` gets a Logo row like Fanart's: file input
`custom_game_logo`, current name, Delete with `remove_game_logo`. In
`routes/games.py::game_detail`:

- `remove_game_logo` calls `remove_media_file(name, 'game_logo')`;
- the `_upload` allowlist becomes `('boxart', 'boxart_3d', 'fanart',
  'game_logo')`;
- the UPDATE gains `game_logo = NULLIF(?, '')`;
- the reset action NULLs it with the other media.

`api_game_detail` returns `game_logo`.

### 4.8 Game page

```html
{# above <h1 class="game-page-title"> in .game-title-row #}
{% if game.game_logo %}
<img src="{{ url_for('static', filename='images/game_logos/' + game.game_logo) }}"
     alt="" class="game-page-logo" decoding="async"
     data-on-error="hide">
{% endif %}
```

- `alt=""`: the title text below says the same, so a screen reader hears it
  once.
- In the box slot's `{% else %}` (no `boxart`, no `boxart_3d`), a game with a
  logo shows it in `.game-boxart-empty` instead of 🎮.
- CSS in `static/css/pages/` (exact file chosen at build): `max-height` and
  `max-width` from `core/variables.css`, `object-fit: contain`, no box or
  shadow behind it.
- On a load error the image hides (the existing `hide` action) and the page
  is as it is today.

## 5. Invariants

- **INV-1** — A scrape that finds no logo leaves a stored `game_logo` as it
  was, Full Re-scrape included; Full Re-scrape with a new logo replaces it,
  unless *Keep existing media* is ticked and the file is on disk.
  *Test:* `tests/test_scrape_fill_only.py` (extended) and
  `tests/test_pass59_133_keep_media.py` (the kept-media dict gains
  `game_logo`).
  *Breaks when:* `_save_game_row` writes `game_logo = ?`, or
  `_KEPT_MEDIA_FIELDS` omits it.

- **INV-2** — A logo with transparency keeps it after
  `finalize_downloaded_image(path, 'game_logo')`, in both `IMAGE_FORMAT`
  modes, and keeps its pixel size.
  *Test:* `tests/test_game_logo.py::test_logo_keeps_alpha_and_size`, a 40×20
  palette PNG with a transparent corner, run with `webp` and `jpeg`.
  `standardize_downloaded_image` is stubbed to record its call, so the GPU
  library is never loaded.
  *Breaks when:* jpeg mode maps the logo to `.jpg`, or standardisation runs
  on `game_logo`.

- **INV-3** — IGDB fanart never takes an artwork of type 5, 6 or 7, and the
  IGDB logo is type 7 when there is one, else type 5, never type 6.
  *Test:* `tests/test_game_logo.py::test_igdb_picks`: artworks `[7, 1]` give
  logo 7 and fanart 1; `[6, 5]` give logo 5; `[6]` gives no logo.
  *Breaks when:* fanart keeps taking `artworks[0]`. The first fixture fails
  only on that rule, because its type-1 artwork is second.

- **INV-4** — TheGamesDB still costs one Images request per game, and its
  `clearlogo` comes back with it.
  *Test:* `tests/test_pass59_216_extra_data.py` (updated for the third list):
  a stubbed `_tgdb_request` records one call whose `filter[type]` contains
  `clearlogo`, and the reply's clearlogo URL is in the third list.
  *Breaks when:* logos are fetched by a second request.

- **INV-5** — A file in `game_logos/` that a row names is never reported as
  orphaned; one no row names is.
  *Test:* `tests/test_pass48_media_cleanup.py` (extended).
  *Breaks when:* `find_orphaned_media` lists `game_logos` but
  `_collect_referenced_files` does not read `game_logo`. That is the case
  where a cleanup deletes live logos.

- **INV-6** — In Fill Missing mode, a game whose only empty field is
  `game_logo` is scraped, not skipped.
  *Test:* `tests/test_game_logo.py::test_fill_missing_visits_logo_gap`.
  *Breaks when:* the bulk job's field list omits `game_logo`.

- **INV-7** — The game page shows the logo above the title with `alt=""`.
  The `<h1>` still holds the title text. With no box art the logo replaces 🎮,
  and with no logo the page renders as before.
  *Test:* `tests/test_game_logo.py::test_game_page_logo`, rendering a game
  with each of: logo and box, logo and no box, no logo.
  *Breaks when:* the logo replaces the `<h1>`, or shows when `game_logo` is
  NULL.

- **INV-8** — Delete in the Edit window removes the logo file and NULLs the
  column. An upload is saved under `game_logos/` as `custom`.
  *Test:* `tests/test_game_logo.py::test_edit_window_logo`.
  *Breaks when:* `remove_game_logo` is ignored, or the `_upload` allowlist
  refuses `game_logo`.

The trust boundary is unchanged. Every new download goes through the existing
`_download_and_finalize` / `download_ss_media` / `_download_tgdb_image` paths,
with their size caps and Pillow decompression-bomb guard. ES-DE copies go
through `_allowed_esde_roots`. Uploads go through `_upload`'s existing checks.

## 6. Failure modes

- **A source has no logo**: the field stays empty and the next source tries.
  The page looks as it does today.
- **The download fails or is not an image**: the existing pipeline drops it
  and the field stays empty.
- **ES-DE arcade marquees** are clear logos, not cabinet strips: every file
  in the local `mame/marquees/` folder has a transparent background, and a
  sample looked at by eye showed only logos (checked at build, 2026-11-03).
  The editor can still clear one.
- **A black or dark logo on a dark theme** may be hard to see. IGDB's black
  type is skipped; the other sources' logos are taken as they come. The title
  text stays readable either way.
- **TheGamesDB allowance spent**: `_tgdb_request` returns None, as for
  screenshots, and the other sources fill the logo.
- **The file is deleted from disk**: pre-population's stale-file check clears
  the name, so the next scrape refills it. That needs `game_logos` in
  `_media_dirs` (§ 4.5).

## 7. Tests

Each test listed in § 5 is seen failing before its half of the code lands.
Tests that reach ES-DE copying or `finalize_downloaded_image` stub
`services.image_utils.standardize_downloaded_image`. Tests that pin field
lists gain `game_logo`:

- `tests/test_pass38_save_game_row_helper.py::_COLUMNS`
- `tests/test_metadata_merger.py::_METADATA_KEYS`
- `tests/test_pass59_205_esde_merge.py`'s media table
- `tests/conftest.py`'s media subfolders
- `tests/test_pass54_media_integrity.py`

`tests/test_spec_migration_sync.py` checks `retrodb.spec` lists migration 036.
Migration count tests use `latest_version()` and need no change.

## 8. Alternatives considered (and rejected)

- **Store the logo in `box_faces`.** Rejected: only `services/box_faces.py`
  writes that column, and only from a Slipcase import (PASS-59-142).
- **A separate "Fill Logos" job.** Rejected: Fill Missing already finds a gap
  per field, and a second job would repeat its source order and limits.
- **Column name `logo`.** Rejected: `systems.logo` and the
  `static/images/systems/` folder already mean console logos.
- **Use IGDB's black logo when it is the only one.** Rejected: invisible on
  the default dark themes. A white or colour logo from another source is
  likelier than a readable black one.
- **ScreenScraper `screenmarquee`.** Rejected: an arcade marquee strip, not a
  clear logo.

## 9. Out of scope

- A full-screen play or loading screen that shows the logo — deferred; not
  yet queued (queued when this pass is filed as shipped).
- Logos in game lists and cards — deferred; not yet queued.
- The wishlist keeping logos — deferred; not yet queued.
- WebP migration, resize, upscale queue and regional repair for logos —
  deferred; not yet queued.
- Translating the help manual's new paragraph — tracked by PASS-59-223.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_scrape_fill_only.py`, `tests/test_pass59_133_keep_media.py` |
| INV-2 | `tests/test_game_logo.py::test_logo_keeps_alpha_and_size` |
| INV-3 | `tests/test_game_logo.py::test_igdb_picks` |
| INV-4 | `tests/test_pass59_216_extra_data.py` |
| INV-5 | `tests/test_pass48_media_cleanup.py` |
| INV-6 | `tests/test_game_logo.py::test_fill_missing_visits_logo_gap` |
| INV-7 | `tests/test_game_logo.py::test_game_page_logo` |
| INV-8 | `tests/test_game_logo.py::test_edit_window_logo` |
| Logo looks right at desktop and ~375px | **nothing** automatic — a browser walk at build |
| Trust boundary unchanged (§ 5) | **Partial:** the existing download and upload tests; nothing checks a new path skips them |

## 11. Cross-doc impact

- `CLAUDE.md` § Media handling: the media field list gains `game_logo`.
- `docs/specs/scrapers.md` and `docs/specs/image-pipeline.md`: the media
  lists, and `game_logo` skipping standardisation.
- `docs/specs/migrations.md`: row 036.
- `templates/help.html`: a sentence on logos under the game page and the
  Edit window. Locales wait on PASS-59-223.
- `data/changelog.yaml`: the open 3.35.4 entry.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-224-game-logos-loop-log.md`.
