<!-- ants-spec-format: 1 -->
# PASS-59-183 — Scrape game details and box scans from MobyGames

**Status:** spec draft (2026-11-21).
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

def search_games(title, system_name=None, limit=10) -> list[dict]
    # One request: title=, platform=<id>, include=INCLUDE.
    # Each result carries the whole record under '_record'.
def fetch_game_details(game_id, system_name=None) -> dict | None
    # The record a search already returned, else one request:
    # id=<game_id>, platform=<id>, include=INCLUDE.
PLATFORM_MAP: dict[str, int]   # system folder -> MobyGames platform id
```

- **One request per game found.** A search with `include=` returns
  whole records, and the fallback walk applies the record it found
  without asking again. `fetch_game_details` asks only for a game a
  person picked from an earlier search, whose record has left the
  10-minute cache (`scrapers.md` §11). `id=` returns the record by
  number (tried 2026-11-21).
- `title=` matches part of a title: `Final Fantasy VII` also returns
  VIII and VII International. `match_scorer` gains
  `calculate_mobygames_score`, which scores like the other sources'
  scorers (§13 item 4).
- A system missing from `PLATFORM_MAP` gets `[]` without a request
  (`scrapers.md` §2, platform coverage). The map is built from
  MobyGames' `/v2/platforms` list, kept in the module.

### 4.2 The pace and the hourly allowance

`service_limits` gains `MOBYGAMES = 'mobygames'`, named `MobyGames`,
with a default pace of 5.0 seconds. After every reply the sender reads:

| Header or status | Effect |
|---|---|
| `ratelimit-policy`, first entry `<rate>;w=1` | `set_pace(MOBYGAMES, 1 / rate)` |
| `ratelimit-remaining: 0` | `stop(MOBYGAMES, ratelimit-reset seconds)` |
| 429 | `stop(MOBYGAMES, retry-after seconds)`, else one hour |
| 401 or 403 | `stop(MOBYGAMES, 3600, KEY_REFUSED)` |

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
  list without it gets it appended at the end. The source is off until
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

- One key per source. Only `mobygames` exists after this spec; another
  source adds its own key. PASS-59-325 adds ScreenScraper's disc and
  cartridge pictures that way.
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
- Fill-only: written only while `box_scans` is NULL, or by Full
  Re-scrape (`scrapers.md` §3). `clear_scraped_data` and the edit
  modal's Clear empty it and delete its files.
  `media_cleanup.find_orphaned_media` learns the folder.

## 5. Invariants

- **INV-1** — A game MobyGames finds costs one API request.
  *Test:* `tests/test_scrape_mobygames.py`, a fallback run for one game
  with `http_get` replaced by a counter that returns a saved search
  reply; the counter reads 1.
  *Breaks when:* the apply step fetches the found game again by id.

- **INV-2** — The pace follows the reply. `0.2;w=1, 720;w=3600` sets a
  5-second gap and `1;w=1, 720;w=3600` a 1-second gap.
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

## 6. Failure modes

- **A refused key.** A 401 or 403 stops MobyGames for an hour. The
  Settings check says the key was refused. Other sources go on.
- **The hour spent mid-run.** Games after that get no MobyGames data in
  this run. A later scrape of the game fills them (§15, question 2).
- **No group for this platform, or no spine.** `box_scans` holds what
  there is. PASS-59-326 paints a spine where none was scanned.
- **A scan that fails to download.** It is left out of `items`. The
  record is still written when at least the front arrived. Otherwise it
  stays NULL, so a later scrape tries again.
- **MobyGames changes `type.name` values.** An unknown type is stored as
  `other` with its caption.

## 7. Tests

`tests/test_scrape_mobygames.py` is new and uses saved replies, with no
network. It locks INV-1, INV-2, INV-3, INV-5, INV-6 and INV-7.
`tests/test_scrape_fill_only.py`
locks INV-4. The security test gains MobyGames' downloads (INV-7). Each
test is seen failing before its code exists.

## 8. Alternatives considered (and rejected)

- **Search, then fetch the chosen game.** That is two requests and ten
  seconds per game. The search already returns the whole record.
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

## 14. Migration / compatibility

Migration 046 adds three nullable columns; existing rows read NULL. A
saved scraper priority list gains `mobygames` at its end. The source
stays off until a key is saved.

## 15. Open questions

1. **Keep MobyGames' scans as JPEG or convert to WebP?** The draft says
   WebP, as every other picture RetroDB keeps.
2. **Catching up after the hour runs out.** The draft fills a skipped
   game only on its next scrape. A later pass could remember skipped
   games and ask again after the reset.
