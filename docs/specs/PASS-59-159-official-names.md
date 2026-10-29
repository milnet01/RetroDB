<!-- ants-spec-format: 1 -->
# PASS-59-159 — AI proposes each game's official name; the user reviews it

**Status:** accepted (2026-10-23).
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
   `scraper/scrape_igdb.py`, `scraper/scrape_thegamesdb.py` and
   `scraper/scrape_esde.py::apply_esde_metadata`. Nothing marks a title
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

### 4.2 The AI call — `scraper/scrape_ai.py`

```python
def propose_official_names(system_name, games):
    """games: [{'title': str, 'rom_file': str, 'region': str|None}].
    Returns one dict per input, same order:
    {'official_title': str|None, 'old_title_region': str|None}.
    Raises on provider error; the caller decides whether to stop."""
```

- One call per batch of `OFFICIAL_NAMES_BATCH = 25` games, through the
  same provider path as `get_game_details` (`_get_active_provider`, the
  `_call_*` map, `rate_limit`).
- Each game is sent as its index, current title, ROM filename (basename
  only, no path) and region. The region comes from the filename's tag
  (`scrape_esde.extract_region_from_filename`), else `games.region`, else
  none. Every string goes through `_sanitize_prompt_input`.
- The prompt asks for the full official title as released in that
  region, in Latin script as the region's own release uses it, and the
  region the *current* title belongs to (`USA`, `Europe`, `Japan`,
  `World`, or null when unsure). It asks for JSON only:
  `{"games": [{"i": 0, "official_title": "...", "old_title_region": "Japan"}]}`.
  An object, not a bare array (2026-10-27): OpenAI's JSON mode returns
  objects only, so the array the first version asked for never arrived
  and every run suggested nothing. The parser also reads a bare array, a
  list under another key, and JSON with prose around it.
- The reply is parsed like `_parse_differences`: an entry with a missing
  or out-of-range `i`, a non-string title, a title over 200 characters,
  or control characters is dropped (that game gets `None`). Titles run
  through `metadata_normalizer.normalize_title`, so the
  `article_placement` setting applies. The old title's region maps
  through `metadata_normalizer.alt_title_region`; anything that maps to
  no code becomes `None`.

### 4.3 The title lock

`games.title_locked = 1` means no scraper writes `title` or
`sort_title`. Every scraper write of either becomes:

```sql
title      = CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END,
sort_title = CASE WHEN title_locked = 1 THEN sort_title ELSE COALESCE(?, sort_title) END
```

at the four write sites listed in §2 item 2, in both normal and Full
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

### 4.4 The job — `services/jobs/official_names.py`

`OfficialNamesJob`, shaped like `services/jobs/alt_titles_backfill.py::AltTitlesBackfillJob`:
singleton, `start(system_id=None)`, `cancel()`, `get_status()`,
`acquire_job_singleton_lock`, crash recovery through `persist_job_*`,
registered in `services/jobs/__init__.py` and the shutdown list.

Games it asks about, per system in system order: every game with a ROM,
**except** games with `title_locked = 1` and games with a `pending`
proposal. A `rejected` proposal does not exclude its game; §4.5 decides
what a new answer does.

For each answer:

- `official_title` is `None`, or equals the current title → no row.
- It equals a `rejected` row's `proposed_title` → no change.
- Otherwise → upsert a `pending` row with `old_title` = current title.

Status reports games done, total, proposals made, and the current
system. A provider error stops the job with the error in its status;
proposals already stored stay.

### 4.5 Review page and API — `routes/official_names.py`

Page `/tools/official-names` (template `official_names_review.html`,
`static/js/official-names.js`, page-specific like
`static/js/versions.js`). All routes are `@editor_required`.

```
GET  /api/official-names/proposals?system_id=
     → {proposals: [{game_id, system_id, system_name, rom_file,
                     old_title, proposed_title, old_title_region}]}
     pending rows only, ordered by system then old_title
POST /api/official-names/accept   {game_ids: [int]} → {accepted, skipped}
POST /api/official-names/reject   {game_ids: [int]} → {rejected}
POST /api/official-names/run      {system_id: int|null}
GET  /api/official-names/status
POST /api/official-names/cancel
```

The page has a system picker (one system or all), a Run button with
progress, and the list. Each row has a tick box (ticked by default), the
ROM filename, old → new, and the old name's region. Buttons: Accept
ticked, Reject ticked, tick all, tick none.

Accept, per game, in one transaction:

1. Skip (count in `skipped`) when `games.title` no longer equals
   `old_title`: the title changed since the proposal. Delete the row.
2. `title = proposed_title`,
   `sort_title = generate_sort_title(proposed_title)`, `title_locked = 1`.
3. `alternate_titles = merge_alt_titles(existing, [alt_title_entry(old_title,
   region=old_title_region, source='official_names')], primary_title=proposed_title)`,
   then drop any existing entry equal (case-insensitive) to
   `proposed_title`: `merge_alt_titles` keeps such entries.
4. Append a `scrape_history` entry naming the source `official_names`
   and the field `title`.
5. Delete the proposal row.

Then `invalidate_filter_cache()` and `invalidate_analytics_cache()`.

Reject sets `status = 'rejected'`.

A link to the page sits in the Tools menu beside Regional Versions.

The page also carries a second card, Fill empty fields with AI: a bulk
AI Fill with its own system picker, outside this spec's invariants. It
writes straight to the games through `services/ai_fill.fill_game`, the
game page's AI Fill; nothing on it goes through `title_proposals`. Its
job and routes are in `docs/specs/jobs.md` and `routes/official_names.py`.

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
  run against each of the four write sites with a source returning a
  different name.
  *Breaks when:* any write site keeps the bare `COALESCE(?, title)`.

- **INV-2** — A scrape of an unlocked game still writes the source's
  title, as today.
  *Test:* `tests/test_official_names.py::test_unlocked_title_still_scraped`.
  *Breaks when:* the lock condition is inverted or applied to every row.

- **INV-3** — Nothing changes `games.title` from a proposal until the
  user accepts it.
  *Test:* `tests/test_official_names.py::test_run_changes_no_title` (job
  run with a stubbed provider; every `games` row is byte-identical
  afterwards).
  *Breaks when:* the job writes titles directly.

- **INV-4** — Accept sets the title, regenerates the sort title, locks,
  and stores the old title as an alternate title with the proposal's
  region; an alt equal to the new title is removed.
  *Test:* `tests/test_official_names.py::test_accept_applies`.
  *Breaks when:* any of the four effects is missing.

- **INV-5** — Accept skips a game whose title changed after the proposal
  was made.
  *Test:* `tests/test_official_names.py::test_accept_skips_stale`.
  *Breaks when:* accept writes without comparing `old_title`.

- **INV-6** — A rejected name is not proposed again; a different name for
  the same game replaces the rejected row as a pending one.
  *Test:* `tests/test_official_names.py::test_rejected_not_reproposed`.
  *Breaks when:* the job upserts without reading `status`.

- **INV-7** — Model output is untrusted: an entry with a bad index, a
  non-string or over-length title, or control characters is dropped,
  and no other game's answer shifts.
  *Test:* `tests/test_official_names.py::test_parse_rejects_bad_entries`.
  *Breaks when:* parsing pairs answers by position instead of by `i`.

- **INV-8** — Saving a changed title in the edit window locks it; the
  per-game Reset unlocks it; Clear scraped data leaves a locked title
  alone.
  *Test:* `tests/test_official_names.py::test_lock_set_and_cleared`.
  *Breaks when:* any of the three table rows in §4.3 is not wired.

- **INV-9** — Every official-names route refuses a non-editor.
  *Test:* `tests/test_official_names.py::test_routes_need_editor`.
  *Breaks when:* a route lacks `@editor_required`.

## 6. Failure modes

- **Provider not configured** → Run refuses with the same message AI
  Fill gives; no job starts.
- **Provider error mid-run** → job stops, status carries the error,
  stored proposals stay, and a re-run skips games with pending rows.
- **Malformed reply** → that batch's bad entries are dropped (INV-7);
  the rest of the batch is stored.
- **Server restart mid-run** → crash recovery resumes the job; pending
  rows prevent re-asking finished games.
- **Game deleted** → its proposal row goes with it (the delete trigger, §4.1).
- **Title edited after the proposal** → accept skips it (INV-5).
- **AI proposes a wrong game's name** → the user sees old → new and
  rejects it; nothing was written.

## 7. Tests

All in `tests/test_official_names.py`, against the conftest scratch
database, with the provider call stubbed. Each test is seen to fail
before its code lands (INV-1 against the bare `COALESCE` sites, the
others against a missing module or route).

| Test | Locks |
|---|---|
| `test_locked_title_survives_scrape` | INV-1 |
| `test_unlocked_title_still_scraped` | INV-2 |
| `test_run_changes_no_title` | INV-3 |
| `test_accept_applies` | INV-4 |
| `test_accept_skips_stale` | INV-5 |
| `test_rejected_not_reproposed` | INV-6 |
| `test_parse_rejects_bad_entries` | INV-7 |
| `test_lock_set_and_cleared` | INV-8 |
| `test_routes_need_editor` | INV-9 |

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
| INV-3 | `tests/test_official_names.py::test_run_changes_no_title` |
| INV-4 | `tests/test_official_names.py::test_accept_applies` |
| INV-5 | `tests/test_official_names.py::test_accept_skips_stale` |
| INV-6 | `tests/test_official_names.py::test_rejected_not_reproposed` |
| INV-7 | `tests/test_official_names.py::test_parse_rejects_bad_entries` |
| INV-8 | `tests/test_official_names.py::test_lock_set_and_cleared` |
| INV-9 | `tests/test_official_names.py::test_routes_need_editor` |

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
