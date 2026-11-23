<!-- ants-spec-format: 1 -->
# PASS-59-183 — Scrape game details and box scans from MobyGames

**Status:** built (2026-11-21).
**Kind:** implement.
**Source:** ROADMAP PASS-59-183 (user, 2026-10-29; scope 2026-11-21).
**Blocker for:** PASS-59-326, PASS-59-325.

Layman: with a MobyGames key saved in Settings, a scrape also asks
MobyGames, the last online source before the AI. It fills empty details
and keeps every scan of the game's real box, spine and disc or
cartridge, manual and leaflets included, for the 3D box to use.

## 1. Goal

MobyGames is a source in the scrape walk, after the other online
sources and before AI Fill. It fills empty fields as every source does
(`docs/specs/scrapers.md` §5). It also stores every scan of one real
release of the game in a new record, `games.box_scans`. PASS-59-326
builds the 3D box from that record, and PASS-59-325 shows what is
inside the box.

## 2. Problem

1. RetroDB has no MobyGames source. `scraper_manager.DEFAULT_SCRAPER_PRIORITY`
   names ScreenScraper, ES-DE, TheGamesDB, IGDB and RAWG only.
2. No source fills a spine, an inside cover, a manual page or a disc
   scan. The media fields `boxart` and `boxart_back` hold one front and
   one back. `games.box_faces` (PASS-59-142) holds only a box made in
   Slipcase and imported by hand.
3. MobyGames allows few requests. Its server answers this key with
   `ratelimit-policy: 0.2;w=1, 720;w=3600`, one request every five
   seconds and 720 an hour. That was checked twice on 2026-11-21 with
   the user's key. The plan page the user bought says one a second.
   `service_limits._DEFAULT_PACE` fixes a pace per service and has no
   hourly allowance.

## 3. Scope decisions (agreed with the user)

- **Take everything MobyGames offers**, spine scans included, so the
  box is built from the real box (user, 2026-11-21).
- **Order: the last online source, before AI Fill** (user, 2026-11-21).
- **A bulk scrape waits its turn for MobyGames.** It skips MobyGames
  only once the hour's allowance is spent (user, 2026-11-21: a game
  takes longer than five seconds to scrape anyway).
- **Skipped games catch up by themselves.** A game a scrape passed over
  because the hour was spent is asked about again after the reset, with
  no re-scrape by hand (user, 2026-11-21).
- **Read the pace from each reply**, not from a fixed number, so a
  faster allowance takes effect by itself (2026-11-21, after the user's
  plan page and the server disagreed).
- **This spec fetches and stores. It builds no box and shows nothing
  new.** Building the box is PASS-59-326 and opening it is PASS-59-325.
  The user put both into 4.0.0 (2026-11-21).
- **Fields from MobyGames' paid tiers above Hobbyist are not used.**
  They include alternate titles, critic and player scores, ratings and
  product codes. The Hobbyist reply leaves them out without an error,
  and no key of a higher tier exists to test with.

## 4. Design

### 4.1 The sender: `scraper/scrape_mobygames.py`

One endpoint, `GET https://api.mobygames.com/v2/games`, through
`base_scraper.http_get` (`scrapers.md` §10). The key goes as the
`api_key` query argument in `params`, so `requests` URL-encodes it.

```python
INCLUDE = ('title,moby_url,description,developers,publishers,genres,'
           'moby_score,official_url,platforms,release_date,covers,screenshots')

def search_games(title, system_folder=None, limit=10) -> list[dict]
    # One light request: title=, platform=<id>, include=SEARCH_INCLUDE.
def fetch_game_details(game_id, system_folder=None) -> dict | None
    # One request: id=<game_id>, platform=<id>, include=INCLUDE.
    # Each whole record is kept for 10 minutes, by game id.
PLATFORM_MAP: dict[str, int]   # system folder -> MobyGames platform id
```

- **Two requests per game found**: a light search, then the record by
  `id=`. Measured 2026-11-21: a search asking for whole records took 12
  to 50 seconds, a light search under a second, the record by id about
  one. Applying the record asks nothing more, and a record fetched in
  the last 10 minutes is not asked for again.
- `title=` matches part of a title: `Final Fantasy VII` also returns
  VIII and VII International. `match_scorer` gains
  `calculate_mobygames_score`, which scores like the other sources'
  scorers (§13 item 4).
- A system missing from `PLATFORM_MAP` gets `[]` without a request
  (`scrapers.md` §2, platform coverage). The map is built from
  MobyGames' `/v2/platforms` list, kept in the module.

### 4.2 The pace and the hourly allowance

`service_limits` gains `MOBYGAMES = 'mobygames'`, named `MobyGames`,
with a default pace of 5.5 seconds: the stated 5 plus `PACE_MARGIN`. After every reply the sender reads:

| Header or status | Effect |
|---|---|
| `ratelimit-policy`, first entry `<rate>;w=1` | `set_pace(MOBYGAMES, 1 / rate + PACE_MARGIN)`; half a second, since two requests sent exactly 5.0 s apart got a 429 (2026-11-22) |
| `ratelimit-remaining: 0` | `stop(MOBYGAMES, ratelimit-reset seconds)` |
| 429 | `stop(MOBYGAMES, retry-after seconds)`, else one hour |
| 401 or 403 | `stop(MOBYGAMES, 3600, KEY_REJECTED)`, worded as a refused key |
| No reply, or a 5xx | `stop(MOBYGAMES, 600, UNAVAILABLE)`, worded as not answering |

The gap runs from each reply's arrival (`service_limits.gap_from_now`), not from the send: a request 5.7 s after the last was sent, but 3.6 s after its slow reply, got a 429 (2026-11-22).

`http_get` is called with `retries=0`. Its 429 retry would wait up to
60 seconds, where the stop already says how long to wait.

Picture downloads from `cdn.mobygames.com` use none of the allowance.
Four downloads between two API requests left `ratelimit-remaining` one
lower, not five (tried 2026-11-21). They are not paced, like every
media download (`scrapers.md` §10).

A bulk scrape fetches its fallback sources on one thread each
(`scrapers.md` §4, PASS-59-132), so the wait for MobyGames' turn runs
while the other sources are asked. Once the hour is spent, `stopped()`
answers and the scrape carries on without MobyGames until the reset.

### 4.3 Wiring

The checklist in `scrapers.md` §13, plus:

- `hybrid_scraper._FALLBACK_FETCHERS` and `_FALLBACK_BREAKERS` gain
  `mobygames`. `_apply_fallback` gains a `mobygames` branch before its
  final `else`, which applies RAWG to anything unnamed.
- `DEFAULT_SCRAPER_PRIORITY` ends with `mobygames`. A saved priority
  list without it gets it just before `ai`, else at the end. The source is off until
  a key is saved.
- Settings: key field `mobygames_apikey` in
  `scraper_settings_validators._ALLOWED_API_KEY_FIELDS` and
  `routes/scraper.SECRET_API_KEY_FIELDS`. `api_check_scraper` gains a
  MobyGames check (one search for a known title).
- The Settings, setup and dashboard templates list it wherever they
  list the other sources. `templates/help.html` and the locale help
  files say what it fills and that it needs the user's own key.

### 4.4 What fills which field

`metadata_merger.apply_mobygames_to_metadata(metadata, data, db_game_id, result, fill_only=False)`,
fill-only as §13 item 2 requires:

| MobyGames | RetroDB |
|---|---|
| `title` | `title`, as primary only |
| `description` (HTML) | `description`, as text |
| `developers`, `publishers` | `developer`, `publisher`: only entries whose `platforms` list this platform |
| `genres`, category `Basic Genres` | `genre`, through `fill_labels` |
| `genres`, category `Perspective` | `perspective`, through `fill_labels` |
| `platforms[]` entry for this platform | `release_date` |
| `moby_score` | `moby_score` (new) |
| `game_id` | `mobygames_id` (new) |
| chosen cover group's `Front Cover` | `boxart` |
| chosen cover group's `Back Cover` | `boxart_back` |
| `screenshots[]` for this platform | `screenshots`, appended and deduplicated (§4 of `scrapers.md`) |
| chosen cover group, every image | `box_scans` (§4.5) |

`official_url` has no field and is not stored. Other genre categories
(Setting, Pacing, Art Style) have no field and are dropped.

### 4.5 The box scans record

Migration 046 adds `games.mobygames_id INTEGER`, `games.moby_score REAL`
and `games.box_scans TEXT` (NULL = none). The record:

```json
{"version": 1,
 "mobygames": {"group": 7590, "countries": ["uk"],
               "packaging": "Jewel Case",
               "items": [{"kind": "front", "caption": null,
                          "file": "1234_front_0_ab12cd.webp",
                          "width": 804, "height": 800}]}}
```

- One key per source. Besides `mobygames`, `screenscraper` (its
  `support-2D`) and `esde` (its `physicalmedia` folder) each hold one
  `media` item, the disc or cartridge, written only while no source has
  a `media` item (PASS-59-328). The open box shows one disc: from
  `mobygames` if its file is on disk, else the next source in
  `box_scans.SOURCES`.
- `kind` comes from the image's `type.name`: Front Cover `front`,
  Back Cover `back`, Spine/Sides `spine`, Media `media`, Manual
  `manual`, Inside Cover `inside`, Full Cover `full`, Extras `extras`,
  Other `other`. `caption` is kept as MobyGames gives it: spine
  captions differ by release (`Left 1`, `Back Cover - Spine Left`).
- Files live in `<IMAGE_PATH>/box_scans/`, named
  `<game_id>_<kind>_<n>_<token>.webp`, downloaded through
  `_download_and_finalize`. At most 40 items per game.
- **Choosing one cover group.** Every item comes from one group, so the
  front, spine and back belong to the same box. Keep the groups whose
  `platforms` include this platform. Drop packaging `Electronic` and
  `Promotional`. Rank the rest by their countries with
  `ss_regions.rank_order(own_region)`. MobyGames' country codes are
  ScreenScraper's except `es` (`sp`) and `ww` (`wor`). On a tie, take
  the group with a `Spine/Sides` image, then the one with more images,
  then the first listed.
- **Matching the 3D box picture** (PASS-59-331). When the game has a
  `boxart_3d` picture and the scrape will download from MobyGames, the
  best-ranked group whose front `cut3d.same_art` matches the picture's
  front wins. At most `_MOBY_GROUP_PROBES` groups are tried, in rank
  order, by downloading each one's front thumbnail; each is deleted once
  compared. With no match, the best-ranked group stays.
- Fill-only per source: a source's key is written only while the
  record has none, merged into what other sources wrote, or by Full
  Re-scrape (`scrapers.md` §3), which deletes the old record's files
  once the new one is saved. `clear_scraped_data` and the edit modal's
  Clear empty it and delete its files; Clear leaves `box_faces` and its
  files alone. `media_cleanup.find_orphaned_media` learns the folder.

### 4.6 Catching up after the hour runs out

Migration 046 also adds `mobygames_pending (game_id INTEGER PRIMARY KEY
REFERENCES games(id) ON DELETE CASCADE, added_at TEXT)`.

- A fallback run that finds MobyGames stopped for `LIMIT_REACHED` or
  `UNAVAILABLE` adds
  the game. A stop for any other reason, such as a refused key, adds
  nothing: waiting will not help.
- A background job, `MobyGamesCatchUpJob`, takes pending games in
  `added_at` order once the stop ends. For each it runs the scrape with
  MobyGames as its only source (`only_source='mobygames'`), so the
  same fill-only save. It waits out a later hour's stop and carries on,
  so a long list empties by itself. It ends when the list is empty,
  when MobyGames refuses the key, or at shutdown.
- It starts when a scrape ends with games pending
  (`game_metadata_service.apply_hybrid_metadata_to_game`), and when the
  app starts with games pending. Only one runs at a time.
- A game leaves the list once asked, whether MobyGames found it or not.
  A game deleted from the library leaves with its row.

## 5. Invariants

- **INV-1** — A game MobyGames finds costs two API requests: a light
  search and the record by id. Applying it, or fetching it again within
  10 minutes, costs none.
  *Test:* `tests/test_scrape_mobygames.py`, a fallback run and apply
  for one game with `http_get` replaced by a counter that returns a
  saved reply; the counter reads 2, and a second fetch leaves it at 2.
  *Breaks when:* the search asks for whole records, or the apply step
  or a repeat fetch asks again.

- **INV-2** — The pace follows the reply. `0.2;w=1, 720;w=3600` sets a
  5.5-second gap and `1;w=1, 720;w=3600` a 1.5-second gap (`PACE_MARGIN` added).
  *Test:* `tests/test_scrape_mobygames.py`, both headers fed to the
  reply reader, `service_limits._pace['mobygames']` read after each.
  *Breaks when:* the pace stays at the default whatever the header says.

- **INV-3** — `ratelimit-remaining: 0` stops MobyGames for the reply's
  reset time, and the next scrape of another game makes no MobyGames
  request while the other sources still answer.
  *Test:* `tests/test_scrape_mobygames.py`, a reply with remaining 0 and
  reset 600, then a fallback run with a counting `http_get`.
  *Breaks when:* the stop is not set, or a stop ends the whole scrape.

- **INV-4** — Every MobyGames write is fill-only: a stored value, a
  stored medium or a stored `box_scans` stays, except under Full
  Re-scrape.
  *Test:* `tests/test_scrape_fill_only.py`, `apply_mobygames_to_metadata`
  added to its media and field cases.
  *Breaks when:* a branch writes without `if not metadata[...]`.

- **INV-5** — Every item in `box_scans.mobygames` comes from one cover
  group, a group for this platform whose packaging is neither
  `Electronic` nor `Promotional`.
  *Test:* `tests/test_scrape_mobygames.py`, the saved Final Fantasy VII
  reply (41 groups across Windows, PlayStation and others) for a
  PlayStation game tagged `(Europe)`: the chosen group is a PlayStation
  jewel case from a European country.
  *Breaks when:* items are taken across groups, or a Windows group wins.

- **INV-6** — The key never reaches a log, a reply or the page.
  *Test:* `tests/test_scrape_mobygames.py`, a logged request is checked
  for the key's text, and `GET /api/scraper/settings` returns it masked.
  *Breaks when:* a log line prints the full URL with `api_key`, or the
  field is missing from `SECRET_API_KEY_FIELDS`.

- **INV-7** — Scan downloads pass the SSRF gate, and nothing deletes
  outside `<IMAGE_PATH>/box_scans/`.
  *Test:* `tests/test_pass40_9_16_security.py` gains MobyGames'
  downloads. `tests/test_scrape_mobygames.py` clears a record naming
  `../boxart/x.webp`, and that file still exists afterwards.
  *Breaks when:* a download skips `_download_and_finalize`, or a clear
  joins a record's name without the folder check.

- **INV-8** — A game skipped because the hour was spent is asked about
  once after the stop ends, and then leaves the list. A game skipped for
  a refused key is not listed.
  *Test:* `tests/test_scrape_mobygames.py`: stop MobyGames with
  `LIMIT_REACHED`, run a fallback, and `mobygames_pending` holds the
  game. Clear the stop and run the job with a counting `http_get`: one
  game's two requests (INV-1), and the list is empty. Repeat with `KEY_REJECTED`, and the
  list stays empty.
  *Breaks when:* the job never runs the pending game, runs it twice, or
  lists a game whose key was refused.

- **INV-9** — The cover group whose front the 3D box picture shows wins
  over a better-ranked one, and the probes leave no file.
  *Test:* `tests/test_box_auto.py`, three groups whose second matches:
  the second is chosen after two probes and `box_scans/` is empty. With
  no match, or no 3D picture, the first is chosen, and with no picture
  nothing is fetched.
  *Breaks when:* a probe is not deleted, the probes run past a match, or
  a game with no 3D picture fetches thumbnails.

## 6. Failure modes

- **A server not answering.** On 2026-11-21 the API answered 502, 504
  and 60-second timeouts for a while. A timeout or a 5xx pauses
  MobyGames for 10 minutes, so later games do not each wait out the
  timeout; the game goes on the catch-up list (§4.6).
- **A refused key.** A 401 or 403 stops MobyGames for an hour. The
  Settings check says the key was refused. Other sources go on.
- **The hour spent mid-run.** Games after that get no MobyGames data in
  this run. The catch-up job fills them after the reset (§4.6).
- **The app stops during a catch-up.** The list is in the database, so
  the job carries on at the next start.
- **No group for this platform, or no spine.** `box_scans` holds what
  there is. PASS-59-326 paints a spine where none was scanned.
- **A scan that fails to download.** It is left out of `items`. The
  record is still written when at least the front arrived. Otherwise it
  stays NULL, so a later scrape tries again.
- **MobyGames changes `type.name` values.** An unknown type is stored as
  `other` with its caption.

## 7. Tests

`tests/test_scrape_mobygames.py` is new and uses saved replies, with no
network. It locks INV-1, INV-2, INV-3, INV-5, INV-6, INV-7 and INV-8.
`tests/test_scrape_fill_only.py`
locks INV-4. The security test gains MobyGames' downloads (INV-7).
`tests/test_box_auto.py` locks INV-9. Each test is seen failing before
its code exists.

## 8. Alternatives considered (and rejected)

- **One search that returns whole records.** One request per game,
  but it took 12 to 50 seconds where a light search and a fetch by id
  took about two (measured 2026-11-21), so fewer games an hour.
- **Skip MobyGames in every bulk scrape.** The user rejected it: a game
  takes more than five seconds anyway (2026-11-21).
- **A fixed pace of five seconds.** It would keep RetroDB slow after
  MobyGames grants the allowance the user paid for.
- **Store spines and inside covers as new media columns.** The number
  of scans differs per release, and captions say which side a spine is.
  One record keeps them together, with the group they came from.

## 9. Out of scope

- Building the 3D box from the scans — tracked by PASS-59-326.
- Opening the box, and ScreenScraper's disc and cartridge pictures —
  tracked by PASS-59-325.
- MobyGames' paid-tier fields — deferred; not yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_scrape_mobygames.py` |
| INV-2 | `tests/test_scrape_mobygames.py` |
| INV-3 | `tests/test_scrape_mobygames.py` |
| INV-4 | `tests/test_scrape_fill_only.py` |
| INV-5 | `tests/test_scrape_mobygames.py` |
| INV-6 | `tests/test_scrape_mobygames.py` |
| INV-7 | `tests/test_pass40_9_16_security.py`, `tests/test_scrape_mobygames.py` |
| INV-8 | `tests/test_scrape_mobygames.py` |
| INV-9 | `tests/test_box_auto.py` |
| Help text names the source in every locale | **nothing** — read by hand |

## 11. Cross-doc impact

- `docs/specs/scrapers.md`: §2 inventory row, §4 default order, §10
  service-limits row.
- `docs/specs/migrations.md`: migration 046.
- `CLAUDE.md` Schema section: `box_scans` and who writes it.
- `templates/help.html` and the locale help files.
- `data/changelog.yaml` and the locale changelogs: one line.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-183-mobygames-source-loop-log.md`.

## 13. Resource cost

Scans are about 800 px tall and up to 40 per game. No new dependency.
Matching the 3D box picture costs up to `_MOBY_GROUP_PROBES` thumbnail
downloads per scrape.

## 14. Migration / compatibility

Migration 046 adds three nullable columns and the empty
`mobygames_pending` table; existing rows read NULL. A
saved scraper priority list gains `mobygames` just before `ai`, else at its end. The source
stays off until a key is saved.

## 15. Open questions

None. Scans are stored as WebP, as every other picture RetroDB keeps.
