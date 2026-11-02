<!-- ants-spec-format: 1 -->
# PASS-59-217 — Identify games from the ROM file itself

**Status:** accepted (2026-11-02).
**Kind:** implement.
**Source:** ROADMAP PASS-59-217 (PASS-59-162 investigation, 2026-10-31).
**Pairs with:** PASS-59-208 (wrong-game matching by title), PASS-59-210 (RetroAchievements links).

Layman: RetroDB can now tell ScreenScraper and RetroAchievements exactly which file you own, so a scrape gets that game rather than one with a similar name, and the game page can say whether your copy will earn achievements.

## 1. Goal

A scrape asks ScreenScraper about the user's own file before it trusts a title search, and takes the answer only when the service confirms that exact file. An RA Refresh compares the file's hash with RetroAchievements' list on the systems that use a plain hash, links the game that list names, and records whether this copy can earn achievements.

## 2. Problem

1. All normal ScreenScraper matching is by title. `hybrid_scraper._fetch_screenscraper` and bulk scrape use `search_game`. No scrape reaches `get_game_info`, the checksum lookup, and its `parse_game_data` drops most of the record.
2. `scrape_screenscraper.calculate_checksums` hashes the zip as a whole. Most of the library is zip files.
3. `games.disc_serial` is stored and never sent. Files over 100 MB get no checksum.
4. The RetroAchievements badge rests on a title match (`achievement_linking.match_ra_game`). It says the game has achievements, not that this copy can earn them. `retroachievements.calculate_rom_hash` has no caller.

Trial, 2026-11-02, real library files against the live service:

- A zip member's CRC, read from the zip's own directory, returned the exact file for 31 of 32 cartridge games on 8 systems (`rom.romcrc` equal to the CRC sent). The other answer was a name match.
- A hit does not prove the file was recognised: *Mortal Kombat II (Japan)* came back as the USA/Europe file. `rom.romcrc` shows the difference.
- One exact hit was tagged as no game: *Ecco the Dolphin*'s CRC named a record called `ZZZ(notgame):#NONGAME`.
- `serialnum` with a made-up file name found 2 of 3 PS2 games. The same made-up name alone found nothing. It found 0 of 3 PS3 games. After the build, with each game's own serial, it found 4 of 4 PS1 and 2 of 2 PS2 games.
- The test account's limit is 50,000 requests a day.

## 3. Scope decisions (agreed with the user)

The user set the scraper work's order on 2026-10-31 and asked that no TheGamesDB call be made without asking (2026-11-02). The rest were chosen by the session from §2's trial, and the user may overrule them:

- ScreenScraper and RetroAchievements now. TheGamesDB's `ByGameHash` waits for a trial.
- A title match stays the fallback, so a file no service knows scrapes as it does today.
- A result a person ticked wins over the file.
- IGDB, RAWG and TheGamesDB still search by title. A wrong match there is not fixed by this.
- Up to one extra ScreenScraper request per game is accepted.

## 4. Design

### 4.1 Reading a file's identity — `services/rom_identity.py` (new)

```python
def file_identity(rom_path) -> dict | None:
    """{'name', 'size', 'crc'} of the game inside rom_path, or None."""
```

- `.zip`: ignore members ending `.txt`, `.nfo`, `.diz` or `/`. With exactly one left, return its name, size and stored CRC, from the zip's directory, without unpacking. With more than one, as in an arcade set, return None.
- A plain file up to 1 GiB, other than `.chd`, `.rvz`, `.wux`, `.m3u`, `.ps3`, `.ps4`, `.7z`: CRC read in pieces. Compressed disc formats would give a hash nobody else holds.
- Anything else, and any read error: None.
- `crc` is upper-case eight-digit hex. Nothing is stored; it is read again on each scrape.

### 4.2 Asking ScreenScraper — `scrape_screenscraper.identify_by_file`

```python
def identify_by_file(rom_path, system_folder, serial, username, password,
                     dev_id, dev_password) -> dict | None:
    """The raw `jeu` record for this exact file, or None."""
```

1. With a `file_identity`, call `jeuInfos` with `systemeid`, `romnom`, `romtaille` and `crc`. Accept the reply only when `rom.romcrc` equals the CRC sent, ignoring case.
2. Else, with a `serial`, call it with `serialnum` and `romnom` set to `<serial>.iso`, so that only the serial can match. Accept any record it returns.
3. Refuse a record whose `notgame` is true or whose name starts `ZZZ(notgame)`.
4. It sends through `_ss_request_with_retry`, so it obeys `service_limits` (PASS-59-215).

The caller passes `games.disc_serial`. For `psx` and `ps2` with no stored serial, the caller reads one with `services.disc_serial.read_disc_ids` and saves it, as `standalone_settings` does. `ps3` is not asked by serial, from §2's trial.

The raw record goes through `apply_screenscraper_to_metadata`, the same as a search result, so no field is lost. `get_game_info` and `parse_game_data` are not used by this and stay as they are.

### 4.3 Where a scrape uses it — `scraper/hybrid_scraper.py`

- `_fetch_screenscraper`: unless `lookup['user_ticked']`, try `identify_by_file` first, ahead of a secondary source's id and ahead of `search_game`.
- `primary_source == 'screenscraper'`: the same, except when the caller says a person chose this record. A person's pick from the game page keeps it; a bulk scrape's automatic pick does not.
- A hit adds `matched by file (ScreenScraper)` to `result['filled_fields']`, so the scrape's history says so.
- A hit also sets `metadata['_ss_by_file']`. `_save_source_ids` then replaces a stored `screenscraper_id` with the file's. This is a sixth exception to fill-only for ids. A person's pick and a title match stay fill-only.

### 4.4 Region — `ss_regions.own_region`

An exact file's `rom.romregions` counts as the copy's region only when the file name has no region tag. Its first code is used. A name-only reply's region is never used.

### 4.5 RetroAchievements — `services/achievement_linking.py`, `services/jobs/ra_refresh.py`

`fetch_ra_game_list` adds `h=1`, so each game carries `Hashes`. The largest list measured grew to about 245 KB (Game Boy Advance, 2026-11-02), well under the existing cap.

`PLAIN_MD5_FOLDERS`, in `achievement_linking`, holds the `RA_CONSOLE_MAP` folders of the systems RetroAchievements' identification page says use a whole file's MD5 with no special rule: Atari 2600, Atari Jaguar, WonderSwan and Color, ColecoVision, Channel F, Vectrex, Odyssey 2, Intellivision, Game Boy, Color and Advance, Pokemon Mini, Virtual Boy, 32X, Game Gear, Master System, Mega Drive, SG-1000, Neo Geo Pocket and Color, Supervision, Mega Duck. NES, SNES, N64 and disc systems are left out, because their hashes have special rules.

For a game in those folders with a `file_identity` no larger than 64 MiB, `match_ra_game_for_file` computes the MD5 of that member or file. Every link check uses it, so a scrape cannot undo what a refresh found.

- The hash is in a game's `Hashes`: link that game, over any title match, and set `games.ra_copy_fits = 1`.
- The hash is in no game's list and the title match found a game: keep that link and set `ra_copy_fits = 0`.
- Otherwise, or on another system: `ra_copy_fits` is NULL, meaning not known.

Migration `032_games_ra_copy_fits` adds the column. `save_ra_link` is its only writer, and an unlinked game holds NULL.

### 4.6 What the user sees — `templates/game_detail.html`

Beside the RetroAchievements link:

- `ra_copy_fits = 1`: "Your copy earns achievements".
- `ra_copy_fits = 0`: "RetroAchievements does not list your copy, so it may not earn achievements".
- NULL: nothing, as today.

The wording is cautious because the page RetroDB follows was last edited about two years ago.

## 5. Invariants

- **INV-1** — A zip with one game inside gives that member's name, size and stored CRC, and the zip is not unpacked.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_zip_identity_reads_the_directory`.
  *Breaks when:* the code reads the member's data, or hashes the zip itself.
- **INV-2** — A zip holding several game files gives no identity, so an arcade set is never named by one of its parts.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_a_zip_of_many_files_has_no_identity`.
  *Breaks when:* the largest member is taken.
- **INV-3** — A reply counts as the file only when `rom.romcrc` equals the CRC sent, ignoring case.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_a_name_match_is_not_the_file`.
  *Breaks when:* any record the service returns is accepted, as with *Mortal Kombat II (Japan)*.
- **INV-4** — A record marked as no game is refused, and the title search runs.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_notgame_is_refused`.
  *Breaks when:* a `ZZZ(notgame)` record reaches the merge.
- **INV-5** — A serial lookup sends a made-up file name, so only the serial can match.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_serial_lookup_cannot_match_by_name`.
  *Breaks when:* the real file name is sent as `romnom`.
- **INV-6** — A result a person ticked is used, and no file lookup is sent.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_a_ticked_pick_wins`.
  *Breaks when:* the file lookup runs ahead of `user_ticked`, or a game-page primary pick is replaced.
- **INV-7** — When the file lookup finds nothing, the scrape goes on to the title search and otherwise behaves as before.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_a_miss_falls_back_to_search`.
  *Breaks when:* a miss, a spent limit or a read error ends the source's turn with nothing.
- **INV-8** — A file match replaces a stored `screenscraper_id`. A title match does not.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_file_match_replaces_the_id`; `tests/test_scrape_fill_only.py::test_source_ids_fill_only`.
  *Breaks when:* the file's id is dropped by `COALESCE`, or a title match overwrites.
- **INV-9** — On a plain-hash system, a hash in RetroAchievements' list links that game and sets `ra_copy_fits = 1`, whatever the title says.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_ra_hash_beats_the_title`.
  *Breaks when:* the title match runs first and wins.
- **INV-10** — On a system with special hash rules, `ra_copy_fits` stays NULL and no hash is computed. A plain MD5 there would call a good copy wrong.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_special_rule_systems_are_not_judged`.
  *Breaks when:* NES, SNES or a disc system joins `PLAIN_MD5_FOLDERS`.
- **INV-11** — A zip's member name is never used as a path, and nothing is written to disk. The zip is untrusted input.
  *Test:* `tests/test_pass59_217_identify_by_file.py::test_a_hostile_member_name_is_only_text`.
  *Breaks when:* a member is extracted, or `../x` reaches the filesystem.

## 6. Failure modes

- **A broken or encrypted zip:** no identity; the title search runs.
- **The file is missing or the drive is gone:** no identity; the title search runs.
- **ScreenScraper's limit is spent:** `service_limits` says no, `identify_by_file` returns None, and the search returns nothing as it does today.
- **A service error on the file lookup:** the same as a miss. The scrape goes on.
- **`Hashes` makes the game list too big:** `fetch_ra_game_list`'s size cap returns nothing, so the refresh reports the system failed. Measure the largest list before raising the cap.
- **A list with no `Hashes`:** every game on that system gets NULL, never 0.

## 7. Tests

`tests/test_pass59_217_identify_by_file.py` holds the test each of INV-1, INV-2, INV-3, INV-4, INV-5, INV-6, INV-7, INV-8, INV-9, INV-10 and INV-11 names, and `tests/test_scrape_fill_only.py` the second half of INV-8. Replies are faked from the shapes in §2's trial. Each test is seen to fail before its behaviour exists. One live trial of each lookup is run after the build and recorded on the roadmap.

## 8. Alternatives considered (and rejected)

- **Skip the search with a stored id.** A stored id may be wrong from before PASS-59-208, and asking by id costs the same one request.
- **Store the CRC.** Reading a zip's directory costs less than a database column to keep true.
- **Send MD5 and SHA1 as well.** The trial needed only the CRC, and those mean unpacking every zip.
- **Hash whole discs.** It takes many minutes per game, and compressed formats would not match anyway. Serials do this job.
- **Hash every RetroAchievements system.** Each special rule is its own code, and a mistake tells the user a good copy is bad.

## 9. Out of scope

- TheGamesDB `ByGameHash` — deferred; not yet queued. It needs calls the user has not agreed to, and it has no sample.
- `.7z` files — deferred; not yet queued. RetroDB has no library that reads them.
- RetroAchievements systems with special rules — deferred; not yet queued.
- IGDB, RAWG and TheGamesDB wrong matches — PASS-59-208 owns title matching.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| Each invariant | The test it names in §5 |
| Live reply shapes | **nothing** — replies are faked in tests; the post-build trial is one run |

## 11. Cross-doc impact

- `docs/specs/scrapers.md`: the ScreenScraper match order, and the id exception in § 5.
- `CLAUDE.md`: the fill-only exceptions, if the id exception is listed there.
- `docs/specs/migrations.md` and `retrodb.spec`: migration 032.
- `data/changelog.yaml`.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-217-identify-by-file-loop-log.md`.

## 13. Resource cost

Up to one extra ScreenScraper request per game on a scrape, and a miss costs one more than today. A file up to 1 GiB may be read once per scrape. RetroAchievements' game lists grow by their hashes, kept in the existing bounded cache. No new dependency.
