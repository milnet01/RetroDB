<!-- ants-spec-format: 1 -->
# PASS-59-106 — Regional versions of a game shown as one game

**Status:** accepted (2026-10-17).
**Kind:** implement.
**Source:** ROADMAP PASS-59-106 (user request and decisions 2026-10-17).
**Blocked by:** PASS-59-105 (shipped v3.29.0: region-tagged alternate
titles, a signal here). **Pairs with:** PASS-59-110 (RetroAchievements ids
shared by sequels; until it ships the RA id is not a signal, §4.5),
PASS-59-107 (AI summary of differences between versions).

Layman: when you own the same game from several regions, the Library shows
it once, opens the version from your preferred region, and lets you switch
to the others on the game page; RetroDB suggests which ROMs belong together
and you confirm them.

## 1. Goal

After this ships, two or more `games` rows on one system can be linked as
versions of one game. The Library and system pages show one card per linked
group, with a versions badge. The card opens and plays the preferred
version, chosen by the `default_region` setting. The game page lists every
version, compares them from stored data, and switches between them.
RetroDB suggests groups from strong signals into a review list; the user
confirms, rejects, links and unlinks. Nothing is ever linked without the
user. The page headers count games with ROMs beside them, and the Duplicate
Finder stops calling two linked versions duplicates.

## 2. Problem

1. **Every ROM is its own card.** `services/game_query.py::_build_games_query`
   builds one result row per `games` row; nothing links rows except bonus
   discs (`games.parent_game_id`, `routes/bonus_discs.py`), which mean "extra
   disc of", not "same game".
2. **The Duplicate Finder calls regional versions duplicates.**
   `routes/tools.py::api_duplicate_finder_scan` walks the filesystem and never
   reads the database. In `name` mode its local `normalize_name` strips
   region tags when the `ignore_region_tags` setting is on (default on), so
   `Rockman (Japan)` and `Mega Man (USA)`-style pairs that share a title are
   reported as duplicates.
3. **Counts are ROM counts.** The header counts in `routes/games.py::all_games`
   and `routes/systems.py::system_games`, and `total` from
   `routes/games.py::api_games`, count rows.
4. **The ids that would identify a game are not stored.** `games` has no IGDB
   or ScreenScraper id column:
   `sqlite3 -readonly database/roms.db "select count(*) from pragma_table_info('games') where name like '%igdb%' or name like '%screenscraper%'"`
   → `0`. The scraper holds them only in locals (`igdb_id`, `tgdb_id` in
   `scraper/hybrid_scraper.py`). `games.ra_game_id` is stored but wrong for
   sequels (PASS-59-110).
5. **Most rows have no stored region.**
   `sqlite3 -readonly database/roms.db "select count(*) from games where coalesce(region,'')=''"`
   → `3873` (live DB, 2026-10-17). Unscraped rows get one on scrape:
   `scraper/hybrid_scraper.py::_normalize_region` falls back to
   `default_region`. So a preferred-version rule on stored region alone would
   miss most of the library; the filename's region tag must count too.

## 3. Scope decisions (agreed with the user)

From the roadmap item, user, 2026-10-17:

- Versions stay separate `games` rows — each keeps its own ROM, launch
  settings, RetroAchievements set and ratings — linked as one game.
- One card per game, with a versions badge. Clicking opens the preferred
  region's version (`default_region`); the game page has a version switcher.
  The card's Play starts that version.
- RetroDB suggests groups from strong signals into a review list the user
  confirms. Manual link and unlink too. Never a silent merge.
- Counts show games with ROMs beside them: "1,204 games (1,530 ROMs)".
- The comparison uses stored data: title, date, publisher, file size and
  revision, languages from No-Intro tags, ratings, achievements support.
- Versions in one group are not duplicates.

Proposed by this spec and confirmed by the user, 2026-10-17:

- The RA id is left out of the signals until PASS-59-110 ships (§4.5).
- Filters apply before grouping: a card shows the best version among those
  that match the filter (§4.3).
- Analytics and the dashboard keep counting ROMs (§9).

## 4. Design

### 4.1 Schema

One migration, at the next free number in
`services/migrations/__init__.py::MIGRATIONS` (`docs/specs/migrations.md`
§11). Additive only.

```sql
CREATE TABLE IF NOT EXISTS version_groups (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);
ALTER TABLE games ADD COLUMN version_group_id INTEGER
    REFERENCES version_groups(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_games_version_group ON games(version_group_id);

-- "These two are not versions of each other": a suggestion never pairs
-- them again.
CREATE TABLE IF NOT EXISTS version_link_rejections (
    game_a     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    game_b     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (game_a, game_b),
    CHECK (game_a < game_b)
);

ALTER TABLE games ADD COLUMN igdb_id INTEGER;
ALTER TABLE games ADD COLUMN screenscraper_id INTEGER;
```

Group rules, enforced in one module, `services/version_groups.py`:

- Every member of a group has the same `system_id`.
- A bonus disc (`is_bonus_disc = 1`) is never a member.
- A group has two or more members. An unlink that leaves one member deletes
  the group and clears that member's `version_group_id`. Deleting a game
  row that leaves one member does the same.
- Linking games already in different groups merges those groups into one.

### 4.2 The preferred version

The member a card shows and plays. Computed in SQL at query time, never
stored, so a change to `default_region` takes effect on the next page load.
Rank, lowest first, then `games.id`:

```
0  region matches default_region (case-insensitive), or region is empty
   and rom_path carries "(<default_region>" — so "(USA, Europe)" counts
1  same test for "World"
2  same test for each region_options entry, in list order
3  anything else
```

`USA` and `North America` are the same region for this test (12 live rows
store `North America`).

### 4.3 Library and system pages

`_build_games_query` gains grouping, used by the data, count and ids
queries alike:

```sql
WITH f AS (
  SELECT g.*, ROW_NUMBER() OVER (
           PARTITION BY COALESCE(g.version_group_id, -g.id)
           ORDER BY <rank §4.2>, g.id) AS version_rank
  FROM games g ... WHERE <existing filter conditions>
)
SELECT ... FROM f WHERE version_rank = 1
```

- Filters run first. A search for a Japanese title finds the Japanese
  version's card.
- Each card carries `version_group_id` and `version_count`, the group's
  whole size, not the filtered size. `build_game_card` adds both;
  `routes/games.py::api_games_card_data`, which has its own SELECT, adds
  them too.
- `api_games` adds `total_roms` beside `total`: the same filters without
  the grouping.
- `AllGamesController.renderGameCard` shows a badge when `version_count >
  1`. The card's link and `.card-play-btn` use the shown row's id, so Play
  needs no change; `_add_can_launch` runs on the shown rows.
- `/api/games/ids` returns the shown rows only, so a bulk action acts on
  what the user sees.
- The page headers show `(%(roms)s ROMs)` after the game count, only when
  the two differ.

### 4.4 Game page

`routes/games.py::game_detail` loads the group's members when
`version_group_id` is set. `templates/game_detail.html` gains a Versions
card near `.game-title-row`:

- One row per version: region name (via
  `services/i18n.py::region_display_name`), title, and a link to
  `/game/<id>`. The current version is marked.
- A comparison table from stored data: title, release date, publisher,
  file size, revision and languages, ratings, RetroAchievements support.
  Revision and languages come from the filename's No-Intro tags
  (`(Rev 1)`, `(En,Fr,De)`) through a new
  `services/game_utils.py::parse_dump_tags(rom_path)`.
- Editors see "Unlink this version" and "Link a version", which searches
  the same system.

### 4.5 Suggestions

`services/version_groups.py::suggest_groups()` pairs non-bonus games on the
same system, not already in one group, and not rejected, on any one signal:

1. Same `igdb_id`.
2. Same `screenscraper_id`.
3. Same title key: `derive_title_from_filename(rom_path)` lower-cased,
   with different region tags or revisions.
4. One game's title, or its title key, equals another's alternate title
   (`games.alternate_titles`, PASS-59-105), case-insensitive.

A pair whose filenames carry different disc numbers (`(Disc 1 of 2)`) is
never suggested: that is one game's discs. Pairs join into groups through
shared members. Each suggestion lists its members and the signals that
fired.

The RA id is not a signal: grouping live non-bonus rows by
`(system_id, ra_game_id)` gives 140 groups, and those read were sequels
(PASS-59-110).

`igdb_id` and `screenscraper_id` are filled from now on:

- The hybrid scraper writes them with the scraper fill-only rule
  (`COALESCE(?, igdb_id)`, CLAUDE.md "Scraper fill-only invariant").
- The Backfill Alternate Titles job
  (`services/jobs/alt_titles_backfill.py`) writes them when empty, from the
  same search results it already reads, so one run fills the signals for an
  existing library.

The review list is a ROM Tools page, `/tools/versions`. Each suggestion has
Link (all members, or the ones left ticked) and "Not versions" (writes a
rejection for each pair).

Routes, all `@editor_required`, shaped like `routes/bonus_discs.py`:

```
GET  /api/versions/suggestions          -> {success, suggestions:[{games:[...], signals:[...]}]}
GET  /api/versions/for-game/<id>        -> {success, versions:[...]}
POST /api/versions/link    {game_ids}   -> {success, version_group_id}
POST /api/versions/unlink/<id>          -> {success}
POST /api/versions/reject  {game_ids}   -> {success}
```

### 4.6 Duplicate Finder

In `name` mode, files whose paths match `games.rom_path` rows in one
version group are not reported as duplicates of each other. Paths are
compared after `os.path.realpath`. The `hash` and `name|hash` modes are
unchanged: identical bytes are a duplicate whatever the grouping.

## 5. Invariants

- **INV-1** — A link of games on two systems, or including a bonus disc,
  is refused and writes nothing.
  *Test:* `tests/test_version_groups.py` (to add) — link a game from each
  of two systems; then a game and a bonus disc on one system; assert both
  refused and no `version_groups` row exists. The fixture's games are
  otherwise linkable, so only the system and bonus-disc rules can refuse.
  *Breaks when:* the system check is missing, or checks only the first
  pair.

- **INV-2** — No group ever has fewer than two members.
  *Test:* `tests/test_version_groups.py` (to add) — link three, unlink two
  one by one; assert the group is gone and no game points at it. Again,
  deleting a member's `games` row.
  *Breaks when:* unlink or delete leaves a one-member group.

- **INV-3** — Linking members of two groups merges them into one.
  *Test:* `tests/test_version_groups.py` (to add) — groups {A,B} and {C,D};
  link B and C; assert one group holds all four.
  *Breaks when:* link moves only the named games and strands the rest.

- **INV-4** — The Library shows one card per group: the preferred version
  by §4.2's rank, with `version_count` the group's whole size.
  *Test:* `tests/test_version_groups_query.py` (to add) — one group of a
  `(Japan)`, a `(USA, Europe)` with empty region, and a `(World)` file;
  `default_region` `USA`: assert one row, the USA/Europe one, count 3.
  Again with `default_region` `Japan`: the Japan one. Again with
  `Germany`: the World one.
  *Breaks when:* the rank reads stored region only, or `version_count`
  counts the filtered set.

- **INV-5** — Filters run before grouping.
  *Test:* `tests/test_version_groups_query.py` (to add) — the INV-4 group,
  searching the Japan version's title: assert one row, the Japan one.
  *Breaks when:* grouping runs first, so the USA card is hidden by the
  search and nothing shows.

- **INV-6** — `total` counts cards and `total_roms` counts rows, under the
  same filters.
  *Test:* `tests/test_version_groups_query.py` (to add) — INV-4 group plus
  one ungrouped game: `total` 2, `total_roms` 4.
  *Breaks when:* either count runs without the grouping change, or with
  different filters.

- **INV-7** — Suggestions never include a rejected pair, games already in
  one group, two discs of one game, or games on two systems.
  *Test:* `tests/test_version_suggestions.py` (to add) — one fixture per
  exclusion, each a pair that a signal would otherwise match; assert no
  suggestion. Each fixture breaks one exclusion only.
  *Breaks when:* any exclusion is missing.

- **INV-8** — Each of the four signals suggests a pair on its own.
  *Test:* `tests/test_version_suggestions.py` (to add) — four pairs, each
  sharing exactly one signal; assert four suggestions, each naming its
  signal.
  *Breaks when:* a signal is missing or needs another to fire.

- **INV-9** — Nothing links games except the link route.
  *Test:* `command grep -rn "version_group_id = \|version_group_id=" --include=*.py services routes scraper`
  lists only `services/version_groups.py` (run after implementation).
  *Breaks when:* a scraper or job writes a link.

- **INV-10** — The scraper fills `igdb_id` and `screenscraper_id` only when
  empty.
  *Test:* extend `tests/test_scrape_fill_only.py` — a row holding an
  `igdb_id`, a scrape returning another: assert it is kept.
  *Breaks when:* the UPDATE uses a bare `igdb_id = ?`.

- **INV-11** — In `name` mode the Duplicate Finder does not report two
  files of one version group as duplicates; in `hash` mode it still
  reports identical files.
  *Test:* `tests/test_duplicate_finder_versions.py` (to add) — two files
  `Game (USA).zip` and `Game (Japan).zip` under `tmp_path`, rows linked:
  name mode reports none. Unlinked: name mode reports them. Two identical
  linked files: hash mode reports them.
  *Breaks when:* the exclusion is missing, or also applies in hash mode.

- **INV-12** — The version routes refuse a viewer.
  *Test:* `tests/test_version_groups_routes.py` (to add) — a viewer
  session POSTs to link, unlink and reject: 403 each, nothing written.
  *Breaks when:* a route lacks `@editor_required`.

## 6. Failure modes

- **A member's ROM is deleted from disk.** The row stays and stays linked;
  the card may show a version that cannot launch. `can_launch` already
  hides Play for it. The game page's switcher reaches the others.
- **The preferred member is filtered out.** The next-ranked matching member
  shows (INV-5).
- **A wrong suggestion is linked.** Unlink on the game page restores the
  rows exactly; nothing else changed.
- **`default_region` names no member's region.** Rank falls to World, then
  `region_options`, then lowest id (INV-4).
- **The Duplicate Finder scans a path not under any `rom_path`.** No row
  matches, so nothing is excluded: today's behaviour.
- **A backfill search matched the wrong game.** It writes a wrong
  `igdb_id`, and a wrong suggestion may follow. The user rejects it. The
  job already applies a score floor (`score < 100` is skipped).

## 7. Tests

- `tests/test_version_groups.py` (to add): INV-1, INV-2, INV-3.
- `tests/test_version_groups_query.py` (to add): INV-4, INV-5, INV-6.
- `tests/test_version_suggestions.py` (to add): INV-7, INV-8.
- `tests/test_scrape_fill_only.py` (to extend): INV-10.
- `tests/test_duplicate_finder_versions.py` (to add): INV-11.
- `tests/test_version_groups_routes.py` (to add): INV-12.
- INV-9 is a grep, run by hand after implementation.

Each new test must fail against the code before this change. No browser
test exists in the suite: the badge, the switcher and the review page are
checked by hand, desktop and 375 px, per CLAUDE.md.

## 8. Alternatives considered (and rejected)

- **Merge versions into one row.** Rejected by the user: each version has
  its own ROM, launch, achievements and ratings.
- **Reuse `parent_game_id`.** It means "bonus disc of", and its queries
  (`bonus_count`, the "Part of:" header) would show versions as bonus
  discs.
- **Store each group's preferred member.** It goes stale when
  `default_region`, `region_options` or a member's region changes, and
  each of those would need to recompute it.
- **Use the RA id now.** It would suggest sequels as versions
  (PASS-59-110).

## 9. Out of scope

- An AI summary of how versions differ — tracked by PASS-59-107.
- The RA id as a signal — after PASS-59-110.
- Analytics, the dashboard and the Systems list keep counting ROMs —
  deferred; not yet queued.
- A per-user preferred region (`default_region` is global) — deferred; not
  yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_version_groups.py` (to add) |
| INV-2 | `tests/test_version_groups.py` (to add) |
| INV-3 | `tests/test_version_groups.py` (to add) |
| INV-4 | `tests/test_version_groups_query.py` (to add) |
| INV-5 | `tests/test_version_groups_query.py` (to add) |
| INV-6 | `tests/test_version_groups_query.py` (to add) |
| INV-7 | `tests/test_version_suggestions.py` (to add) |
| INV-8 | `tests/test_version_suggestions.py` (to add) |
| INV-9 | the grep in §5, by hand; nothing runs it automatically |
| INV-10 | `tests/test_scrape_fill_only.py` (to extend) |
| INV-11 | `tests/test_duplicate_finder_versions.py` (to add) |
| INV-12 | `tests/test_version_groups_routes.py` (to add) |
| §4.3 badge, §4.4 switcher, review page | **nothing** automated — no browser harness; checked by hand |

## 11. Cross-doc impact

- `docs/specs/migrations.md` §13 — the new migration's row.
- `docs/specs/api-contracts.md` — the `/api/versions/*` routes; `total_roms`,
  `version_group_id` and `version_count` on `/api/games`.
- `docs/specs/auth.md` — the new routes' permission.
- `docs/specs/scrapers.md` — `igdb_id` and `screenscraper_id` written by the
  hybrid scraper.
- `CLAUDE.md` — the new route file, template and ROM Tools page.
- `templates/help.html` and each `help.<locale>.html` — the versions
  feature and the review page.
- `data/changelog.yaml` — the release.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-106-regional-versions-loop-log.md`.

## 13. Resource cost

- One window function over the filtered rows per Library page request.
  Unmeasured; measure `api_games` on the live library before and after,
  and say the result in the pass's commit.
- Suggestions run on request over one system's or the whole library's
  non-bonus rows. Unmeasured.
- Two small tables and three nullable columns. No new dependency.

## 14. Migration / compatibility

- The migration adds empty tables and nullable columns. No row is linked,
  so every page behaves as today until the user links something.
- `igdb_id` and `screenscraper_id` start empty; scrapes and the backfill
  fill them.

## 15. Open questions

- **Q1** — How many groups the id signals find is unknown until a backfill
  fills `igdb_id` and `screenscraper_id`. The title signal alone finds
  little in the live library: non-bonus rows sharing
  `(system_id, derive_title_from_filename(rom_path).lower())` form 8
  groups (`python3 -c` over `database/roms.db`, read-only, 2026-10-17).
  Those read were a ROM beside its own unpacked folder, or two discs of
  one game. Measure the suggestions after the first backfill, and if they
  are few, say so to the user before building the review page further.
