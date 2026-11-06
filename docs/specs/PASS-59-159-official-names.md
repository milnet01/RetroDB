<!-- ants-spec-format: 1 -->
# PASS-59-159 — AI proposes each game's official name; the user reviews it

**Status:** accepted (2026-10-23). Review run and page withdrawn (user, 2026-11-02); the title lock stands.
**Kind:** implement.
**Source:** ROADMAP PASS-59-159 (user request and decisions 2026-10-23).
**Pairs with:** PASS-59-106 (regional versions: a renamed game's old name
becomes a version-grouping signal, §4.6).

Layman: RetroDB asks the AI for each game's full official name, in the
ROM's own region; you see a list of old and new names, tick the ones you
want, and only those change. Names you accept or type yourself are no
longer overwritten by a re-scrape.

## 1. Goal

After this ships, an editor can start an "official names" run for one
system or all systems. A background job sends batches of titles to the
configured AI provider and stores one proposal per game. A review page
lists each proposal (old name, new name, the old name's region) with a
tick box. Accepting a proposal sets the title, regenerates the sort
title, keeps the old title as a region-tagged alternate title and locks
the title against scrapers. Rejecting one records it, so the same name
is not proposed again. A title typed in the edit window is locked the
same way.

## 2. Problem

1. **No source supplies an official, region-true name.** AI Fill reads
   `title` but never writes it: `title` is not in
   `scraper/scrape_ai.py::AI_FILLABLE_FIELDS`. Scrapers pick Western
   names; ScreenScraper's `get_localized` prefers `us`, `eu`, `wor`.
2. **Every scrape can overwrite a title the user chose.** The primary
   source applies with `fill_only=False` and writes `metadata['title']`
   (`scraper/metadata_merger.py::apply_igdb_to_metadata`,
   `apply_rawg_to_metadata`, `apply_screenscraper_to_metadata`), and
   every title write is `title = COALESCE(?, title)`:
   `scraper/hybrid_scraper.py::_save_game_row`,
   `scraper/scrape_igdb.py` and `scraper/scrape_thegamesdb.py` (and, until
   PASS-59-249 removed it, `scrape_esde.apply_esde_metadata`). Nothing marks a title
   as chosen: there is no lock or source column on `games`.
3. **AI calls are per game.** `scrape_ai.py::get_game_details` sends one
   game per call. One multi-item prompt exists:
   `scrape_ai.py::_build_versions_prompt`.

## 3. Scope decisions (agreed with the user)

From the roadmap item, user, 2026-10-23:

- A review list (old → new, tick to accept). Nothing changes until
  accepted.
- The name is the one used in the ROM's own region: a Japanese ROM keeps
  Rockman.
- The old title is kept as an alternate title.
- Built before the v4.0.0 translation step, so its screen is translated.

Proposed by this spec and chosen by the user, 2026-10-23:

- Accepted names **and** titles typed in the edit window survive every
  scrape, Full Re-scrape included (§4.3).
- The AI also names the region the old title belongs to; the old title
  is stored with that region, or untagged when the AI gives none (§4.6).
- A run covers one system or all systems, started from the review page,
  running in the background (§4.4).

Added by the user, 2026-10-27: AI Fill, during a single-game scrape, a
Bulk Scrape and from the AI Fill button, also asks for the official title
and renames the game to it straight away, without review. A locked title
is not asked about. See `docs/specs/scrapers.md` §12.

## 4. Design

### 4.1 Schema — migration `021_official_names`

```sql
ALTER TABLE games ADD COLUMN title_locked INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS title_proposals (
    game_id          INTEGER PRIMARY KEY,
    old_title        TEXT NOT NULL,   -- games.title when proposed
    proposed_title   TEXT NOT NULL,
    old_title_region TEXT,            -- CLDR code or NULL
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'rejected')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS trg_games_delete_title_proposal
AFTER DELETE ON games
BEGIN
    DELETE FROM title_proposals WHERE game_id = OLD.id;
END;
```

A trigger, not `ON DELETE CASCADE`, as `016_version_groups` does
(`trg_games_delete_version_rejections`): it fires on every connection,
whether or not that connection set `PRAGMA foreign_keys = ON`.

Additive; existing rows get `title_locked = 0`. Accepted proposals are
deleted, not kept: the change is recorded in `scrape_history` (§4.5).

### 4.2 The AI call

**Withdrawn** (user, 2026-11-02): Bulk AI Fill names games, so this was not needed separately. The code is in git history.

### 4.3 The title lock

`games.title_locked = 1` means no scraper writes `title` or
`sort_title`. Every scraper write of either becomes:

```sql
title      = CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END,
sort_title = CASE WHEN title_locked = 1 THEN sort_title ELSE COALESCE(?, sort_title) END
```

at the write site `_save_game_row` (and `apply_esde_metadata`, removed in PASS-59-249), in both normal and Full
Re-scrape modes. Scrapers still use a locked title for searching, as
they use any stored title today.

Who sets and clears it:

| Action | `title_locked` |
|---|---|
| Accept a proposal (§4.5) | set to 1 |
| Edit window saves a title different from the stored one (`routes/games.py::api_game_edit` and its form-POST twin) | set to 1 |
| Edit window: untick "Keep this title when scraping" | set to 0 |
| Per-game "Reset" (`routes/games.py`, which calls `reset_game_title_from_filename`) | set to 0 |
| Maintenance "Clear scraped data" (`services/game_cleanup.py::clear_scraped_data`) | unchanged; a locked title is not reset to the filename form |

The edit window shows the "Keep this title when scraping" tick box
beside the title, ticked when `title_locked = 1`.

### 4.4 The job

**Withdrawn** (user, 2026-11-02): Bulk AI Fill names games, so this was not needed separately. The code is in git history.

### 4.5 Review page and API

**Withdrawn** (user, 2026-11-02): Bulk AI Fill names games, so this was not needed separately. The code is in git history.

### 4.6 Effect on version grouping

`services/version_groups.py::suggest_groups` uses `file_title` (from the
ROM filename) for the `title` signal, so a rename does not change it.
The old title stored with a region becomes a regional alternate title
(`_regional_alt_names`). A Rockman (Japan) ROM renamed from "Mega Man"
gets alt "Mega Man" / US, and is then suggested with a USA ROM titled
"Mega Man". That is the intended effect: suggestions still need the
user's confirmation (PASS-59-106 §3). An untagged old title gives no
signal.

## 5. Invariants

- **INV-1** — No scrape changes `title` or `sort_title` of a game with
  `title_locked = 1`, in normal or Full Re-scrape mode.
  *Test:* `tests/test_official_names.py::test_locked_title_survives_scrape`,
  run against each write site with a source returning a
  different name.
  *Breaks when:* any write site keeps the bare `COALESCE(?, title)`.

- **INV-2** — A scrape of an unlocked game still writes the source's
  title, as today.
  *Test:* `tests/test_official_names.py::test_unlocked_title_still_scraped`.
  *Breaks when:* the lock condition is inverted or applied to every row.

- **INV-3** — Withdrawn 2026-11-02 with the review run.

- **INV-4** — Withdrawn 2026-11-02 with the review run.

- **INV-5** — Withdrawn 2026-11-02 with the review run.

- **INV-6** — A name rejected in the old tool stays refused: AI Fill and a
  scrape do not apply it. A different name for that game still applies.
  *Test:* `tests/test_ai_official_title.py::test_rejected_name_not_applied_by_ai_fill`.
  *Breaks when:* `get_game_details` stops reading `title_proposals`.

- **INV-7** — Withdrawn 2026-11-02 with the review run.

- **INV-8** — Saving a changed title in the edit window locks it; the
  per-game Reset unlocks it; Clear scraped data leaves a locked title
  alone.
  *Test:* `tests/test_official_names.py::test_lock_set_and_cleared`.
  *Breaks when:* any of the three table rows in §4.3 is not wired.

- **INV-9** — The Bulk AI Fill page refuses a non-editor.
  *Test:* `tests/test_official_names.py::test_page_needs_editor`.
  *Breaks when:* its route lacks `@editor_required`.

## 6. Failure modes

- **Game deleted** → its proposal row goes with it (the delete trigger, §4.1).

## 7. Tests

All in `tests/test_official_names.py`, against the conftest scratch
database, with the provider call stubbed. Each test is seen to fail
before its code lands (INV-1 against the bare `COALESCE` sites, the
others against a missing module or route).

| Test | Locks |
|---|---|
| `test_locked_title_survives_scrape` | INV-1 |
| `test_unlocked_title_still_scraped` | INV-2 |
| `test_rejected_name_not_applied_by_ai_fill` | INV-6 |
| `test_lock_set_and_cleared` | INV-8 |
| `test_page_needs_editor` | INV-9 |

## 8. Alternatives considered (and rejected)

- **Put `title` in `AI_FILLABLE_FIELDS`** — rejected: AI Fill applies
  without review, against the user's decision.
- **A `title_source` text column instead of `title_locked`** — rejected:
  the lock is the only behaviour anything reads; the source is already
  recorded in `scrape_history`.
- **Lock only accepted AI names** — rejected by the user: hand-typed
  titles are overwritten today for the same reason.
- **Keep accepted proposals as history rows** — rejected:
  `scrape_history` and the stored alternate title already record the
  change.
- **Tag the old title with the ROM's region** — rejected: the old title
  is usually the scraper's Western name, so the tag would be wrong and
  would create false version-group signals.

## 9. Out of scope

- Renaming ROM files — deferred; not yet queued.
- An editor for alternate titles — deferred; not yet queued.
- Non-Latin-script titles (kana, hangul) — deferred; not yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_official_names.py::test_locked_title_survives_scrape` |
| INV-2 | `tests/test_official_names.py::test_unlocked_title_still_scraped` |
| INV-6 | `tests/test_ai_official_title.py::test_rejected_name_not_applied_by_ai_fill` |
| INV-8 | `tests/test_official_names.py::test_lock_set_and_cleared` |
| INV-9 | `tests/test_official_names.py::test_page_needs_editor` |

## 11. Cross-doc impact

- `docs/specs/scrapers.md` — the primary's title overwrite (`fill_only=False`)
  and the `_save_game_row` SQL now carry the lock (§4.3). Amended in
  the commit that ships the lock, so it never describes unbuilt code.
- `docs/specs/migrations.md` — no change; `021_official_names` follows
  its additive pattern.
- `templates/help.html` and each `help.<locale>.html` — a paragraph for
  the review page and the lock tick box.
- `CLAUDE.md` § Scraper fill-only invariant — names the title lock as a
  second exception beside Full Re-scrape.
- `data/changelog.yaml` — the open release entry.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-159-official-names-loop-log.md`.
