# PASS-59-162: what each scraper source offers that RetroDB does not use

Dated record of the investigation on 2026-10-31. Counts were measured then, on one library.
The fixes and additions it led to are roadmap items that name PASS-59-162 as their source.

Each table comes from reading the code, the service's documentation and, for ScreenScraper,
IGDB, TheGamesDB, RAWG, HowLongToBeat, RetroAchievements and Steam, real replies for up to
three games. Xbox had no real reply. "Finding" numbers point to the fuller working notes, which
stay on the maintainer's computer because they quote a private library.

## ScreenScraper

The sample key is in `screenscraper_*_search.json` unless the row says jeuInfos. "Doc" means `https://www.screenscraper.fr/webapi2.php`.

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| Dates per region | `dates[]` (`us`, `jp`, `eu`, `br`) | The Release Dates list on the game page, without paying for AI. The `release_dates` column exists and only the AI fills it (390 rows) | **Yes.** Free and already in the reply | S |
| `box-2D-back` | `medias[]`, 7 regions on Sonic 2 | Back of the box | **Yes**, needs a place to show it | M |
| `box-2D-side`, `box-texture` | `medias[]` | Spine and full wrap. These could fill the slipcase box faces (PASS-59-142) with no manual import | **Maybe.** `box_faces.py` is the only writer today, so that contract would have to change | M |
| `sstitle` | `medias[]`, region `wor` | The real title screen. The app takes one `ss` shot and nothing else | **Yes.** A cheap extra true screenshot | S |
| `wheel`, `wheel-hd`, `wheel-carbon`, `wheel-steel` | `medias[]` | The game's logo on a clear background, good for list and big-picture views | **Maybe.** No column for it | M |
| `mixrbv1`, `mixrbv2` | `medias[]` | Ready-made composite of box, screen and logo | Maybe, for one list layout | S |
| `screenmarquee`, `screenmarqueesmall` | `medias[]` | Arcade marquee strip | Maybe, arcade only | S |
| `support-2D`, `support-texture` | `medias[]` (`support` key gives the disc number) | Picture of the cartridge or disc | Maybe | M |
| `bezel-16-9` | `medias[]` | Screen surround for RetroArch | Maybe, ties in with launch overlays | M |
| `steamgrid` | `medias[]` | Tall grid artwork | No, duplicates box art | S |
| `figurine` | `medias[]` | Character cut-out | No | S |
| `themehs` | `medias[]`, a zip | HyperSpin theme | No | S |
| `pictomonochrome`, `pictocouleur`, `pictoliste` | `medias[]`, parents `genre`, `note`, `editeur`, `joueurs` and others | Small icons for genre, score and so on | No | S |
| `background` | jeuInfos sample only | Another background picture | No, `fanart` covers it | S |
| Other types in the doc, absent from samples: `flyer`, `maps`, `box-scan`, `support-scan`, `overlay`, `marquee`, `wheel-tarcisios`, `themehb`, `video*` and `ss*` table variants | Doc media list | Arcade flyers are the real gain: for arcade games the "box" is often a flyer. Skyscraper uses `flyer` as the arcade cover | **Yes for `flyer`**, no for the rest | S |
| `medias[].crc`, `md5`, `sha1`, `size` | Every media entry | Check a download arrived whole. Skip one already held (the doc's CRCOK and MD5OK replies) | **Maybe.** Saves quota on re-scrapes | S |
| Synopsis in other languages | `synopsis[]` (`de`, `es`, `fr`, `it`, `pt`) | German, French and other users could read a description in their own language. The app ships those languages and always takes English | **Maybe.** Needs a per-locale store | L |
| Genre names in other languages | `genres[].noms[]` | Not needed: labels are translated by RetroDB | No | - |
| `genres[].principale`, `parentid`, `nomcourt` | `genres[]` | Tells main genre from sub-genre, and allows a stable mapping by id rather than by English words | **Yes**, it would fix finding 4 better than a word list | M |
| `classifications` of type `SS`, `JV`, `Tectoy` | `classifications[]` (GT4 has `SS` 7 and `JV` "+7 ans" and no PEGI or ESRB) | An age guide for games with no official rating | **Maybe.** `JV` could feed the cross-map, `SS` is the site's own | S |
| `note` count | Not offered | `user_score_count` stays empty | No | - |
| `rotation` | Top level, `"0"`; doc says arcade only | Vertical arcade games flagged for launch or display | Maybe | S |
| `controles`, `couleurs` | Search reply top level. Doc: `couleurs` entries hold `id`, `controle`, `hexa` | Arcade control and button colour data. The samples only show `"6"` and `"0"`, so the search-reply meaning is unclear | No, until understood | - |
| `topstaff` | Top level; doc: included in the ScreenScraper staff top list | A "staff pick" tag | No | S |
| `notgame` | jeuInfos sample, `"false"`; absent from search replies | Stops demos and applications being treated as games | Maybe, ROM lookup only | S |
| `tips` | jeuInfos sample; mostly French on Sonic 2 | Cheats and hints | **Maybe.** Language mix is poor | M |
| `actions` | jeuInfos sample; per-move controls with Recalbox text | "How to play" moves on the game page | **Maybe** | M |
| `roms[]` (228 on Sonic 2): `romcrc`, `rommd5`, `romsha1`, `romsize`, `regions`, `langues`, `beta`, `demo`, `proto`, `trad`, `hack`, `unl`, `alt`, `best`, `retroachievement`, `romnumsupport`, `romtotalsupport`, `nbscrap` | jeuInfos sample | Exact identification of the user's file. Marks hacks, betas and translations. Finds disc numbers. Shows which of the user's ROMs work with RetroAchievements | **Yes**, for identification (finding 8) | L |
| `rom` (singular): `romserial`, `romregions`, `romlangues`, `romsupporttype` | Doc only; samples lack it because no file was sent | The real region and language of the user's own file | **Yes**, same work | with above |
| `serialnum` request parameter | Doc | Finds a disc game by its serial. `games.disc_serial` already holds these | **Yes.** Discs over 100 MB are never checksummed today | S |
| `systeme.id`, `editeur.id`, `developpeur.id` | Top level | Stable company ids, so "SEGA" variants could merge | Maybe | M |

## IGDB

"Docs only" means the field is in the documentation but absent from the samples.

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| `release_dates[]` (date, y, m, `date_format`, `platform`, `release_region`) | all samples | The real date for this console and region, and how exact it is. Also real data for the regional dates box, which only the AI fills today | **Yes**: fixes F1 and F2 and replaces AI guesses with data | M |
| `game_localizations` (name, cover, region) | `igdb_ps2.json`: "グランツーリスモ 3: A-spec", region 3 | Official regional title and a regional cover | **Yes** for titles. Maybe for covers | M |
| `collections` | ps2, zxspectrum samples | Series name when no franchise is set | **Yes**: fixes F5 | S |
| `game_type` | all samples: 0 main game, 5 mod, 11 port | Keeps ROM hacks, DLC and bundles from being matched | **Yes**: F13 | S |
| `porting` on `involved_companies` | zxspectrum: Probe Software | Credits the studio that made this port | **Yes**: F7 | S |
| `multiplayer_modes`: `platform`, `offlinecoop`, `offlinecoopmax`, `onlinecoop`, `onlinecoopmax`, `lancoop`, `dropin`, `splitscreenonline` | ps2 sample | Correct player count per console, and true modes such as co-op, online and LAN | **Yes**: F10, F11 | M |
| `multiplayer_modes`: `onlinemax`, `campaigncoop`, `splitscreen` | already requested, then dropped | Same as above | **Yes**: free, already downloaded | S |
| `game_time_to_beats` endpoint (`hastily`, `normally`, `completely`, `count`) | Docs only; I confirmed it through a web search, not by reading that docs section | Fills the empty "playtime" field. The code comment says IGDB dropped this, but it moved to its own endpoint | **Yes**: one extra request per game | M |
| `version_title` | Docs only | Edition name, for the `edition` column the AI fills today | Maybe: rarely set | S |
| `platforms` (other platforms) | all samples; already requested | Real data for `other_platforms`, which the AI fills today | Maybe: IDs need mapping to RetroDB's names | S |
| `external_games` | ps2 sample: GiantBomb, Twitch | Links to other sites, and possibly Steam ids | Maybe | S |
| `websites` | ps2, zxspectrum: Wikipedia, official site | Links on the game page | Maybe: needs new storage and UI | M |
| `themes` | all samples: Action, Non-fiction | A second way to browse | Maybe: overlaps genre | M |
| `keywords` | megadrive, ps2 | "split-screen multiplayer", "rom hack" | Maybe: noisy. The "rom hack" keyword could help matching | M |
| `language_supports` | megadrive, zxspectrum | Which languages a game supports | Maybe: no column today | M |
| `ports`, `remakes`, `remasters`, `parent_game`, `expansions`, `dlcs`, `bundles`, `expanded_games` | Samples and docs | "Related versions" links | Maybe: only useful for games in the library | L |
| `videos[].video_id` | ps2, zxspectrum; already requested, then dropped | A YouTube trailer link | Maybe: the `video` column holds other sources' videos | M |
| `total_rating`, `total_rating_count` | ps2 sample | A blend of critic and user scores | No: both parts are already stored | S |
| `age_ratings`: `rating_content_descriptions`, `synopsis`, `rating_cover_url` | ps2 sample; rest docs only | Why a game got its rating | No: RetroDB ships its own badges | M |
| `game_status`, `hypes`, `follows`, `tags`, `checksum`, `created_at`, `updated_at` | Samples and docs | Nothing useful for a ROM library. `updated_at` could guide re-scrapes | No | S |
| `slug`, `url` | all samples | A link to the IGDB page | Maybe: helps with attribution (see Terms) | S |
| `game_engines` | ps2 sample; already requested, then dropped | Trivia | No: stop requesting it | S |
| `similar_games.cover.url` | requested, then dropped | Nothing | No: stop requesting it | S |
| Company details, characters, platform logos and other endpoints | Docs only, not studied in detail | Logos, cast lists | No, not for v4.0.0 | L |

## TheGamesDB

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| `alternates` (other titles) | sample `alternates`: `["Gran Turismo 3"]`, `["OutRun"]`. Never requested by RetroDB | Other names for a game on its page and in search; better matching ("Out Run" against "OutRun") | Yes. `alternate_titles` already exists | S |
| `region_id` to a real name | sample `region_id`; `/v1/Regions` (no sample) | The right region preference when picking a record. See Finding 4 | Yes. Needed for the fix | S |
| `country_id` | sample `country_id` (13 Germany, 18 UK, 28 Japan, per game pages); `/v1/Countries` | Tells which release a record is, and hints at its language | Yes, with region | S |
| `filter[region_id]`, `filter[country_id]` | spec, `/v1.1/Games/ByGameName` | Ask for the user's region first | Maybe. Costs a second call if the first finds nothing | S |
| `/v1/Games/ByGameHash` | spec: `hash`, `filter[type]` (`md5`, `crc`). No sample | Identify a ROM by its file, not its name | Maybe. Hash coverage is unknown; needs a trial | M |
| `/v1/Games/ByGameUniqueID` | spec: `uid`. No sample | Look up by a unique id. The spec does not say which id, so a disc-serial match is a guess | Maybe. Needs a trial with `games.disc_serial` | S |
| `/v1/Games/Videos` | spec, `GameVideo` model. No sample | Video clips hosted by TGDB | Maybe. Fills empty `video` if coverage is real | M |
| `youtube` | sample key, empty in all three | A trailer link | Maybe. Empty in every sample | S |
| Back of box | sample `include.boxart.data`, `side: "back"` (ids 122566, 130176) | A back-cover picture | Maybe. No column; `box_faces` is import-only by contract, so this needs a decision | M |
| `titlescreen` images | spec, `/v1/Games/Images` `filter[type]`. No sample | Title screen pictures among the screenshots | Yes. One word in the filter, no new call | S |
| `clearlogo` images | same | Game logo art | Maybe. No column | M |
| `banner` images | same | Wide banner art | Maybe. No column | M |
| Other image sizes (`small`, `thumb`, `medium`, `large`) | sample `base_url` | Nothing; RetroDB makes its own sizes | No | - |
| `resolution` | sample image records, often null | Could prefer the sharpest cover | No. Mostly null | - |
| `coop` | sample key, `"No"` in all three | A co-op entry under game modes | Maybe. Cheap, but no sample shows "Yes" | S |
| `last_updated` | sample key | Could tell that a record changed | No | - |
| `os`, `processor`, `ram`, `hdd`, `video`, `sound` | sample keys, null in all three | PC system requirements | No. Null here, and no column | - |
| `/v1/Games/Updates` | spec. Wrapper exists, nothing calls it | Refresh only the games TGDB changed | No for v4.0.0. See Finding 17 | L |
| `/v1/Games/ByPlatformID` | spec. Wrappers exist, nothing calls them | List all games of a platform | No | - |
| Platform data and images | spec, `/v1/Platforms*`. Wrappers exist, nothing calls them | Console facts and pictures | No. RetroDB has its own system data | - |
| `/v1/API/Limit` | spec: "Does not count against your allowance." | A free allowance check | Yes. See Finding 16 | S |
| Comma lists in `id` and `games_id` | spec, ByGameID and Images | Many games for one call | Yes for bulk scrapes. See Finding 12 | M |
| TGDB game id | sample `id` | Re-scrape without searching, saving one call a game | Yes. `_save_source_ids` stores only IGDB and ScreenScraper | S |

## RAWG

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| Per-platform release date | `details.platforms[].released_at` | The date for this system, not the game's first date. OutRun on PC says 2024-12-13, the record says 1989-09-01 | Yes, see finding 8. It is usually a copy of the main date | S |
| Per-platform Metacritic score | `details.metacritic_platforms[]`; docs `GamePlatformMetacritic`. Empty in all three samples | A critic score for this system instead of any system | Yes, see finding 4. Needs one reply with data first: the samples cannot show its shape | S |
| Metacritic page link | `details.metacritic_url` (docs example; empty in samples) | Link to the reviews | Maybe: only if the game page gains source links | S |
| RAWG game page link | `details.slug`, `details.id` (read, then dropped; no `rawg_id` column) | A link back to RAWG. This is what the terms ask for | Yes, see finding 3. Needs a place to store it | S |
| Other platforms list | `details.platforms[].platform` (read, never stored) | "Also on" list for the `other_platforms` column | Maybe: other sources may already fill it; RAWG's lists are broad | S |
| Vote breakdown | `details.ratings[]` (exceptional, recommended, meh, skip, with counts) | A small bar of how players voted | Maybe: nice on the game page, not retro-specific | M |
| Top vote | `details.rating_top` | Most common vote | No: the breakdown covers it | S |
| Reaction counts | `details.reactions` | Unlabelled numbers in the sample | No: the keys have no documented meaning | S |
| Popularity | `details.added`, `added_by_status` (owned, beaten, dropped...) | "1622 people have this; 488 finished it" | Maybe: fun, but for the whole game, not this version | S |
| Average playtime | `details.playtime` (read at `scrape_rawg.py:341`, never stored) | Hours to play. Docs: Steam average | No: 0 for two of three samples, and HLTB fills `playtime_estimate` better | S |
| Official website | `details.website` (read at `scrape_rawg.py:342`, never stored). Empty in all samples | Link to the game's site | No for retro; no column; also low cost to drop the read | S |
| Where to buy | `/games/{id}/stores`, sample `stores.results[].url` | Links to Steam or PlayStation Store. Could seed `steam_app_id` | Maybe: useful on the wishlist page. Sample links can point at a different release | M |
| Trailers | `/games/{id}/movies`, `details.clip`. Empty in all samples | A video where none exists | Maybe: docs list it, samples have none, so it likely helps newer games only | M |
| Quick screenshot list | `search_result.short_screenshots` | Preview in search results without another call | Maybe: would save one request per game; includes the background image | S |
| Screenshot size | `screenshots.results[].width`, `height` | Choose the sharpest, or skip tiny ones. Sonic has 500x370 and 320x224 | Maybe: could help tell a real console-sized shot (320x224) from others | S |
| Screenshot deleted flag | `screenshots.results[].is_deleted` | Skip shots RAWG has withdrawn | Maybe: all false in samples, cheap to honour | S |
| Achievements | `/games/{id}/achievements`; sample shows "Silver Episode" for Sonic, from another release | Achievement list | No: RetroAchievements is the right source; these belong to modern re-releases | M |
| Additions | `/games/{id}/additions` | Related editions. Sonic lists "Sonic The Hedgehog (GG/SMS)" | Maybe: see finding 8; helps pick the correct record | M |
| Parent games | `/games/{id}/parent-games` (docs; not in samples) | The base game of an edition | Maybe: same use | S |
| Series list | `/games/{id}/game-series` (fetched, used only for a name guess) | "Other games in this series" links | Maybe: more honest than the franchise guess, see finding 2 | M |
| Development team | `/games/{id}/development-team`, `details.creators_count` (docs; not in samples) | Named people: composer, designer | Maybe: no column today; credits across all releases | L |
| Tags other than play modes | `details.tags[]` | Themes such as "Pixel Graphics", "Retro" | No: OutRun's tags include "Horror", "Demons" (apparently from another game merged into its record) | M |
| Reddit data | `/games/{id}/reddit`, `details.reddit_*`. Empty in samples | Community links | No: little for retro | S |
| Suggested games, Twitch, YouTube | `/games/{id}/suggested`, `/twitch`, `/youtube`. Docs: business and enterprise only | Similar games, videos | No: paid plans only | M |
| Dominant colour | `details.dominant_color`, `saturated_color`. "0f0f0f" in all samples | Page tint | No: same value everywhere | S |
| Counts | `screenshots_count`, `movies_count`, `reviews_count`, `twitch_count`, `youtube_count`, `suggestions_count` and similar | Nothing a user needs | No | S |
| Original name | `details.name_original` | The native title | No: equal to `name` in all samples | S |
| To-be-announced flag | `details.tba` | Marks unreleased games | No: not retro; maybe for the wishlist | S |
| Last updated | `details.updated` | Tell whether a re-scrape would find news | No | S |
| PC requirements | `details.platforms[].requirements` | Minimum PC specs | No: PC only | S |
| Top-level families | `details.parent_platforms` | Nothing beyond `platforms` | No | S |
| Lookup lists | `/genres`, `/tags`, `/platforms`, `/stores`, `/developers`, `/publishers`, `/creators` | Could verify `PLATFORM_MAP` | No for users; yes as a one-off check of `PLATFORM_MAP` | S |

---

## ES-DE

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| `rating` (0 to 1, half-star steps) | gamelist, 4,659 rows; INSTALL.md "gamelist.xml reference" | A user score where no other source gave one. 1,759 library games have this rating and no `user_score` | Yes. Multiply by 100 to match the 0-100 `user_score`, fill-only. ES-DE does not record who set it (a scraper or the person), so rank it below IGDB and RAWG | S |
| `backcovers/` | downloaded_media, 39 systems, about 4,650 files | Back of the box on the game page | Maybe. No `games` column; slipcase faces (`box_faces`) are owned by an editor's import only, so this needs a design decision | M |
| `marquees/` | downloaded_media, 40 systems, about 5,290 files | The game's logo, for lists or headers | Maybe. Needs a new column and a place in the UI | M |
| `physicalmedia/` | downloaded_media, 39 systems, about 4,850 files | Picture of the cartridge or disc | Maybe. Nice for collectors; needs a column and UI | M |
| `miximages/` | downloaded_media, 40 systems, about 5,370 files | ES-DE's ready-made collage | No. It is a composite, and the code rightly refuses it as box art | - |
| `sortname` | INSTALL.md; absent from these gamelists | Keeps a sort title the person set in ES-DE | Maybe. Cheap: fill `sort_title` | S |
| `completed` | INSTALL.md; absent here | Carries "finished" over to `completion_status` | Maybe. The setting is per library, so it needs care | S |
| `playcount`, `playtime`, `lastplayed` | Gamelist, 113 / 108 / 113 rows. `playcount` and `lastplayed` are parsed, then dropped; `playtime` is not parsed | Play history imported from ES-DE | Maybe. Only as a one-off import. Not scrape data | M |
| `favorite` | Gamelist, 2 rows; parsed, dropped | Carries favourites over | Maybe. Same one-off import | S |
| `hidden`, `kidgame` | INSTALL.md; absent here; parsed, dropped | Hides games, or marks child-friendly ones | No. Per-frontend choices; RetroDB has age ratings | - |
| `broken` | INSTALL.md; absent here | Flags a game that does not work | Maybe. No column today | S |
| `controller` | Gamelist, 1 row | A controller badge | No. Curated defaults always win here, and it is almost never set | - |
| `altemulator` | INSTALL.md; absent here | Keeps a per-game emulator choice | No. ES-DE's emulator labels do not map to RetroDB's emulator table | - |
| `collectionsortname`, `nogamecount`, `nomultiscrape`, `hidemetadata`, `screen`, `folderlink` | INSTALL.md; absent here | ES-DE's own display settings | No | - |
| `<folder>` rows | INSTALL.md; 0 here | Details for a folder of files | No, not until RetroDB treats a folder as one game | - |
| Custom media folder (`MediaDirectory` in `es_settings.xml`) | INSTALL.md | Finds the media without a setting | No. RetroDB's `esde_downloaded_media_path` setting covers it | - |

## HowLongToBeat

All come from the search reply (`samples/hltb_*.json`). HLTB has no public API, so this is everything the samples show.

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| Review score | `review_score` (72 for Sonic), `count_review` | A player score out of 100 | Maybe. RetroDB already has `user_score`; this adds one more opinion on the same scale | S |
| Sample sizes | `comp_main_count`, `comp_plus_count`, `comp_100_count`, `comp_all_count` | "Based on 613 players", so a time from 3 players looks less certain | Yes. Cheap, and it also helps reject shaky matches | S |
| All-styles time | `comp_all` | A single "typical" time | Maybe. Handy for one-number displays | S |
| Co-op and multiplayer time | `invested_co`, `invested_mp` and their counts | Time for co-op or versus games | Maybe. Most retro rows are 0 | S |
| Which play styles exist | `comp_lvl_sp`, `comp_lvl_co`, `comp_lvl_mp`, `comp_lvl_combine` | Whether the game has solo, co-op or versus times | No. RetroDB's `modes` field covers this | S |
| HLTB game ID | `game_id`. Read, and kept only in the review queue | A link to the game's HLTB page, and a repeat lookup without guessing the title | Yes. It removes title guessing on refresh | S |
| Other names | `game_alias` ("3D Out Run, Sega Ages: Outrun") | Better matching, and more alternate titles | Yes, for matching. Same fix area as H2 | S |
| Release year | `release_world`. Read, but only shown by search | A check that the matched game is from the right year | Yes. See H4 | S |
| Same-name marker | `game_name_date` (1 for Sonic) | Warns that another game has the same name | Yes, with the year check | S |
| Game type | `game_type` | Tells a full game from a DLC or mod | Maybe. Could stop DLC matches; every sample says "game" | S |
| Cover image | `game_image` | Box art fallback | No. Other sources are better, and using it is a rights risk | S |
| Popularity counts | `count_comp`, `count_speedrun`, `count_backlog`, `count_playing`, `count_retired`, `profile_popular` | How much the game gets played | No. Little value for a ROM library | S |

## RetroAchievements

Samples cover only `API_GetGame`, `API_GetGameExtended` and `API_GetGameHashes`. `API_GetGameList`, which RetroDB relies on, was not captured; I used its documentation. Docs: https://api-docs.retroachievements.org/

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| ROM hashes | `API_GetGameList` with `h=1`, `API_GetGameHashes.Results[].MD5` | "Your copy of this game works with achievements", tested on the real file | Yes. See R8; the refresh already downloads them and discards them | M/L. RA hashes many systems in its own way |
| Compatible file names | `Results[].Name`, `Labels` | Tells the user which dump to get | Yes, with hashes | S |
| Patches | `Results[].PatchUrl` | Link to a patch that makes a dump compatible | Maybe | S |
| Median time to beat, complete, master | `API_GetGameProgression` (docs only): `MedianTimeToBeat`, `MedianTimeToComplete`, `MedianTimeToMaster` | Real play times from RA players. A second source where HLTB is wrong or empty | Yes. A true per-platform figure, which HLTB lacks | M |
| Box art, title and in-game images | `ImageBoxArt`, `ImageTitle`, `ImageIngame`, `ImageIcon` | Fill-only art for games with none. `/Images/112941.png` in the sample | Maybe. Small images; other sources are better | M |
| Publisher, developer | `Publisher`, `Developer` | Fill empty fields | Maybe. Good quality; only for games with a set | S |
| Genre | `Genre` ("2D Platforming") | Fill empty genre | No. Needs mapping to canonical genres, and others supply it | S |
| Release date and its precision | `Released`, `ReleasedAtGranularity` ("day") | Fill an empty date, knowing if it is only a year | Maybe | S |
| Player counts | `NumDistinctPlayers`, `NumAwarded`, `NumAwardedHardcore` | "63,563 players" and how rare each achievement is | Yes for rarity on the achievement page | S |
| Weighted points | `TrueRatio` | Shows how hard an achievement really is | Maybe | S |
| Hardcore progress | `NumAwardedToUserHardcore`-style fields (only `DateEarnedHardcore` is read) | Hardcore progress on the Library badge | Maybe | S |
| Leaderboard count | `NumLeaderboards` (docs) | Shows a game has leaderboards | Maybe. Already in the list reply | S |
| Change date | `DateModified` (docs) | Refresh only what changed | Maybe | S |
| Guide link | `GuideURL` (null in sample) | Link to a guide | Maybe | S |
| Parent game | `ParentGameID` | Marks subsets; would help R6 | Maybe | S |
| Forum link | `ForumTopicID` | Link to the discussion | No | S |
| RA game page title | `Title` from the list. Read and logged, not stored | Lets a person see which RA game was linked, and catches wrong links | Yes. R1 could not be diagnosed by title because this is missing | S |
| Rich presence, claims, author, memory data | `RichPresencePatch`, `Claims`, `Author`, `MemAddr`, `Flags`, `IsFinal` (deprecated) | Nothing for a player | No | - |

## AI Fill

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| Source links for each answer | Gemini `groundingMetadata`, Claude `citations` on text blocks (platform.claude.com web search page), OpenAI `annotations` (OpenAI not checked this session). All are thrown away: `_call_gemini`, `_call_openai` and `_claude_answer_text` keep only the text | A sales figure or score you can check by clicking its source | Yes. It is the only real check on invented figures, and terms may require it (see Terms) | M |
| "Where this came from" mark on a stored value | No column. `scrape_history` is the only record | The page could say "AI estimate" beside a rating, score or sales figure | Yes (see finding A2) | M |
| The ROM file name and region for ordinary fields | Already known. Sent only for `official_title` (`_build_prompt`) | The AI would answer for the user's actual copy, not a guessed one | Yes (finding A1) | S |
| Release year, developer or other identifying facts in the prompt | Prompt has only title and platform | Fewer mix-ups between games with the same name | Yes | S |
| `playtime_estimate` | Column exists, not in `AI_FILLABLE_FIELDS` | A rough play time when How Long to Beat has none | No. A made-up number; 4,108 rows already have one | S |
| `alternate_titles` for every game | Column exists; AI adds one only when renaming | Search finds a game by its other regional names | Maybe. Useful, but needs a check that the names are real | S |
| Description in the user's language | Prompt is always in English | Translated descriptions | Maybe. RetroDB ships in several languages, but this costs one call per language | M |
| Languages in the game, composer, series order | No column | More facts on the game page | No. No column, and easy for a model to invent | M |
| Media | None. The file header says text only | None | No | n/a |

## Steam

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| `short_description`, `detailed_description`, `about_the_game` | sample | A description straight after import | Yes. Needs HTML stripped; the sample has `&quot;` and `<br>` | S |
| `developers`, `publishers` | sample | Exact credits | Yes | S |
| `release_date.date` (`18 Apr, 2011`) | sample | Release date | Yes. Words depend on store language, so parse carefully | S |
| `genres[]` | sample | Genre. Coarse (`Action`, `Adventure`) | Yes, through `normalize_genre` | S |
| `categories[]` | sample | Modes: `Single-player`, `Online Co-op`, `Shared/Split Screen Co-op` | Yes, an exact source for `modes` | S |
| `metacritic.score`, `.url` | sample (95) | A real critic score with its link | Yes | S |
| `recommendations.total` | sample (392,574) | Popularity | Maybe. Not a score | S |
| Review summary (appreviews `query_summary`) | https://partner.steamgames.com/doc/store/getreviews (docs) | A real user score and count | Yes. It would replace AI guesses for Steam games | M |
| `header_image`, `capsule_image`, `capsule_imagev5` | sample | Artwork. Landscape, not box-shaped | Yes for grid art; portrait art is a separate URL not in the reply | M |
| `screenshots[].path_full` | sample (12) | Screenshots | Yes | S |
| `movies[]` (`hls_h264`, `dash_h264`, `dash_av1`) | sample (17) | Trailers. Streams, not MP4 files | Maybe. RetroDB would have to convert them | L |
| `background`, `background_raw` | sample | Fanart | Maybe | S |
| `ratings.usk`, `.dejus`, `.steam_germany`, `.igrs` | sample | Real board ratings. USK and Brazil map to existing columns | Yes. Real, not invented | S |
| `required_age` | sample (0) | Age gate | No. Ratings are better; here it is 0 while USK says 12 | S |
| `content_descriptors` | sample (empty) | Content warnings | Maybe. No column | M |
| `controller_support`, controller categories | sample (`full`) | Controller note | Maybe. The column holds controller names, not levels | S |
| `supported_languages` | sample | Language list, with spoken-audio marks | Maybe. No column | M |
| `platforms` | sample (Windows and Linux) | Whether it runs natively on Linux | Yes, for a Linux audience (see S4) | S |
| `pc_requirements`, `mac_requirements`, `linux_requirements` | sample | PC specs | Maybe. No column | M |
| `website`, `support_info` | sample | Links | Maybe | S |
| `dlc`, `packages`, `package_groups`, `price_overview`, `is_free` | sample | DLC and prices | No. Prices go stale | n/a |
| `achievements.total`, `.highlighted` | sample (51) | A count before syncing | No. The sync gets this | S |
| `playtime_forever`, `rtime_last_played` | read by `api_steam_fetch_library`, shown, then dropped at import | Time played and last played on the game page | Yes | M |
| `playtime_2weeks`, per-platform play time | GetOwnedGames (docs) | Recent play | Maybe | S |
| Achievement rarity (`GetGlobalAchievementPercentagesForApp`) | ISteamUserStats (docs) | "Only 3% of players have this" | Maybe | S |
| `hidden` achievement flag | GetSchemaForGame (docs) | Hides spoilers | Yes | S |

## Xbox

| Field or media | Where it is | What it would give a user | Worth adding | Size |
|---|---|---|---|---|
| `detail.description`, `.shortDescription` | Decoration `detail` (library model). RetroDB asks only for `achievement,image` | A description at import, at no extra call | Yes. Add one word to the URL | S |
| `detail.developerName`, `.publisherName` | same | Exact credits | Yes | S |
| `detail.genres` | same | Genre | Yes, through `normalize_genre` | S |
| `detail.releaseDate` | same | Release date | Yes | S |
| `detail.minAge` | same | Age | Maybe. Not a board rating | S |
| `detail.capabilities`, `.attributes` | same | Modes, perhaps. Values unknown | Maybe, after a live reply | M |
| `images[]` | Used for a preview only, then dropped | Box art at import | Yes | S |
| `displayImage` | Library model. Code uses `images[]` | Fallback picture | Maybe | S |
| `titleHistory.lastTimePlayed` | Library model | Last played | Yes | S |
| Decoration `stats` | Library model | Perhaps minutes played. Contents unknown | Maybe, after a live reply | M |
| Decoration `gamepass` | Library model | Game Pass flag | No | S |
| `achievement.currentAchievements`, `.totalAchievements`, `.progressPercentage` | Library model. Code reads gamerscore only | "12 of 40" in the import table | Yes | S |
| `type`, `mediaItemType` | Library model | Tell games from apps (see X4) | Yes | S |
| `modernTitleId`, `pfn`, `bingId`, `isBundle`, `serviceConfigId` | Library model | IDs and bundle flag | No, except `isBundle` maybe | S |
| Achievement `rarity`, `isSecret` | Achievements reply; from memory, not checked | Rarity and spoiler hiding | Maybe | S |

## Columns no source fills

"Source" means a scraper in the merge walk: ES-DE, TGDB, IGDB, RAWG or ScreenScraper. Rows are non-empty counts out of 5,685.

| Column | Rows | What writes it | Worth a source filling it? |
|---|---|---|---|
| `rating` | 10 | No hybrid write. Only `scrape_igdb.py:692` and `scrape_thegamesdb.py:958`, the single-source paths | No. It is a leftover from before the separate rating boards; retire it |
| `steam_app_id` | 0 | Platform import only (`routes/platform_import.py`) | Maybe. IGDB's external ids could supply it (not checked; IGDB lane) |
| `xbox_title_id` | 0 | Platform import only | No |
| `psn_npwr_id` | 175 | Platform import | No |
| `save_type` | 3,399 | AI, or folder guess | Maybe; no source was found offering it |
| `china_rating` | 3,289 | AI, cross-map, inference | No; no Western source has it (documented) |
| `dimension` | 5,089 | AI only | No. `scrapers.md` §4 wrongly says the mergers write it |
| `game_structure` | 5,072 | AI only | No. Same doc error |
| `edition` | 5,111 | AI only; 4,996 rows say "Standard Edition" | Low value: it tells a user nothing on 98% of filled rows |
| `campaign` | 5,124 | AI only | No. Same doc error |
| `other_platforms` | 5,118 | AI only, though IGDB's platform list is already fetched and thrown away | **Yes**, from IGDB. It would give real data in place of a guess |
| `units_sold` | 42 | AI only (documented) | No |
| `release_dates` | 390 | AI only (documented) | **Yes**. ScreenScraper's `dates` is per region and is reduced to one value today |
| `playtime_estimate` | 4,108 | HowLongToBeat service; the hybrid IGDB value is always `None` (`hybrid_scraper.py:313`) | Dead branch in the merge; low |
| `hltb_match_*` | 4,788 | HowLongToBeat service | Not a merge field |
| `has_retroachievements`, `ra_*` | 2,391+ | RetroAchievements tail step and jobs | Not a merge field |
| `clz_title` | 141 | CLZ import | Not a merge field |
| `box_faces`, `disc_serial`, `disc_crc`, `file_size`, `last_viewed`, `completion_status`, `version_group_id`, `parent_game_id`, `is_bonus_disc`, `title_locked`, `emulator_override_id`, `launch_args_override`, `last_bulk_scraped`, `created_at`, `updated_at` | varies | App state, not metadata | No |
