<!-- ants-roadmap-format: 1 -->

<!-- Generated from the Ants Terminal roadmap store. Edit it with roadmap_log; hand edits are discarded by the next write. -->
<!-- ants-roadmap-id-high-water: PASS-12=5 PASS-14=2 PASS-2=9 PASS-38=8 PASS-39=12 PASS-40=16 PASS-41=14 PASS-42=9 PASS-43=6 PASS-45=20 PASS-46=3 PASS-47=6 PASS-48=5 PASS-49=9 PASS-50=4 PASS-51=2 PASS-52=3 PASS-53=13 PASS-54=2 PASS-55=4 PASS-56=2 PASS-57=10 PASS-58=6 PASS-59=304 PASS-60=6 -->

# RetroDB Roadmap

Tracking file for refactoring, security, performance, and quality work
identified in successive reviews (2026-04-21 onwards). Items are ordered so
that earlier passes establish the patterns used by later ones (service-layer
carve-outs, response helpers, etc.).

> **Find an item:** every item starts with its id in brackets, so `grep -n "PASS-59-113" roadmap.md` finds it. For history use `git log --grep "PASS-59-113"`.

## Table of contents

Open work, by the version it ships in:

- [4.0.0 — The last web version](#400--the-last-web-version) — the PASS-59-113 plan and every fix before release
- [4.0.x — Security and data-loss fixes](#40x--security-and-data-loss-fixes-for-the-web-version) — the web version after 4.0.0
- [4.1.0 — Desktop app: browse and play](#410--desktop-app-browse-and-play) — the native app's first piece
- [4.2.0 — Desktop app: edit and scrape](#420--desktop-app-edit-and-scrape)
- [4.3.0 — Desktop app: tools, cheats and statistics](#430--desktop-app-tools-cheats-and-statistics)
- [4.4.0 — Desktop app: looks and languages](#440--desktop-app-looks-and-languages)
- [4.5.0 — The Android app](#450--the-android-app)
- [5.0.0 — The full desktop app](#500--the-full-desktop-app) — the native app does everything
- [Ideas, not planned](#ideas-not-planned) — considered or dropped

Reference:

- [Done index](#done-index) — landed passes up to 3.6.x, by version
- [Scope notes — considered and dropped](#scope-notes--considered-and-dropped)
- [Audit hygiene](#audit-hygiene)
- [Periodic Independent Review](#periodic-independent-review) — cadence and procedure for the multi-agent audit
- [Notes](#notes) — standing conventions for working this file

Finished items from released versions are in `docs/roadmap/`, one file
per minor version (for example `docs/roadmap/3.5.md`). Finished items
whose version is not known are in `docs/roadmap/unversioned.md`. The notes from the old "Active" section are in
[docs/history/roadmap-old-active-notes.md](docs/history/roadmap-old-active-notes.md).

## 4.0.0 — The last web version

Everything in the PASS-59-113 plan, every fix the reviews found, and the work finished since 3.35.4. RetroDB is a web app up to here, and 4.0.0 stays downloadable after the desktop app ships.

- 📋 [PASS-59-113] **v4.0.0 release plan: what ships before the major bump (HIGH, L)**
  - **Why**: the user set the v4.0.0 scope on 2026-10-17. v4.0.0 ships when
    every theme below is done; then the trailer is remade (PASS-59-112).
  - **Order**: items stay filed where they are; work them in this order.
    1. Known serious bugs: PASS-59-50, PASS-59-51, PASS-59-52, PASS-59-56,
       PASS-59-57, PASS-59-67, PASS-59-69.
    2. Achievements you trust: PASS-59-110, PASS-59-58, PASS-59-111.
    3. One game, many versions: PASS-59-106, then PASS-59-107.
    4. Play out of the box: PASS-59-91 (remaining stages), PASS-59-81.
    5. Easier everyday use: PASS-53-1, PASS-53-2, PASS-53-7, PASS-53-8,
       PASS-53-10, PASS-53-11; then PASS-59-159 (AI official names,
       added by the user 2026-10-23).
    5a. Play in RetroDB's own RetroArch (user, 2026-10-23: v4.0.0 needs
       something bigger): PASS-59-139 (ship RetroArch, or at least a
       download link, set up next to RetroDB with its own settings
       folder), then PASS-59-155 (cheats).
    5b. Turnable 3D box art (user, 2026-10-23): PASS-59-142 (import
       Slipcase box faces), then PASS-59-143 (the 3D viewer), then PASS-59-231
       (real case shape, added by the user 2026-11-03; waits for
       Slipcase's SLIP-0125 spec).
    5c. Scraper data, complete and correct (user, 2026-10-23): PASS-59-162
       investigation done 2026-10-31; the user chose every group for
       v4.0.0, in this order: PASS-59-201 to PASS-59-214 (wrong data),
       PASS-59-215 (service limits), PASS-59-216 and PASS-59-217 (extra
       data, identifying by file), PASS-59-218 (Steam and Xbox), then PASS-59-224 (game logos, added by the user 2026-11-02).
       PASS-59-219 (leftovers) goes alongside. PASS-59-161 (screenshots
       true to their system) ships in this step.
    6. Stricter browser security: PASS-60-1, after the template changes
       above, so inline scripts move once.
    7. Fully translated: PASS-52-1, PASS-59-109, PASS-57-6, PASS-59-93,
       PASS-59-61, PASS-59-62, PASS-59-115; last, once every new string has landed.
    8. Full code review, the last thing done before v4.0.0 (user,
       2026-10-17): the 14-agent audit (CLAUDE.md Periodic Independent
       Review), run once everything above has shipped.
    9. Fix everything the review finds, translating any new strings the
       fixes add.
    10. Release v4.0.0, then PASS-59-112.
  - **Status**: todo. Lanes: release.
  - **Source**: user, 2026-10-17.
  - **Progress** (2026-11-02): Xbox held (user, 2026-11-02): the Azure portal refuses a personal
    account with "The ability to create applications outside of a
    directory has been deprecated". A directory needs an Azure sign-up or
    the M365 Developer Program, and a February 2026 Microsoft Q&A reply
    says XboxLive.signin needs Xbox developer enrolment; a hobby plugin
    guide says otherwise. Nothing tested. So PASS-59-162's findings X1 to
    X7 stay unconfirmed, and Xbox goes out with v4.0.0 untested. Settings
    now says this.
  - **Progress** (2026-11-04): step 8 done. 15 lanes ran (the 14-lane
    partition was stale); raw reports in
    `docs/reviews/2026-11-04-independent-audit.md`. Step 9 is these
    passes, in this order: data safety PASS-59-237, PASS-59-238,
    PASS-59-239, PASS-59-240; silent failures PASS-59-241; user edits
    PASS-59-242; jobs PASS-59-243; updates PASS-59-244; access
    PASS-59-245; translation PASS-59-246; scrapers PASS-59-247;
    hardening PASS-59-248; small fixes PASS-59-249; docs PASS-59-250;
    the second-look review PASS-59-251 last. PASS-59-252 (Slipcase
    recess keys) goes with PASS-59-231.
  - **Progress** (2026-11-09): PASS-59-271 joins step 9 (user,
    2026-11-09): 4.0.0 is the last web version, and its updater must
    know a desktop release before it ships.

  ---
  **Layman:** The list of what must be finished before RetroDB 4.0.0 is released.
  Kind: implement.
  Lanes: release.

- 🚧 [PASS-52-1] **Translate JS-driven toasts / dialogs — the last i18n seam (I18N, M)**
  - **Status**: in-progress (raises the priority of the Pass 49.x deferral now that
    v3.14.0 ships ten UI locales, two of them Chinese).
  - **Problem**: the UI catalogs cover templates and Python, but user-facing
    strings emitted from JavaScript — `showNotification()` / `showConfirm()` /
    `showModal()` toast + dialog copy — are largely hard-coded English string
    literals. ~365 such call-sites exist across the templates; the Pass 49.x
    deferral estimated ~138 literal strings (~20 templates) can't currently route
    through gettext. Result: a fully-translated interface that still pops up
    English "Saved" / "Are you sure?" / "Scrape complete" messages. Each new locale
    (now Simplified + Traditional Chinese) makes the seam more visible.
  - **Plan** (per `docs/specs/i18n.md` §6): the JS translation path is `t('...')`
    with **string literals only**; `python3 build_js.py` regenerates
    `services/js_i18n_strings.py` (the runtime manifest + `_()` bridge anchors that
    carry JS msgids into the catalog via the Python extractor — there is no
    `[javascript:]` babel mapping). Sweep the inline `<script>` blocks + bundled
    JS, wrap the literal user-facing strings in `t()`, rebuild JS, run the
    `pybabel extract`/`update` + `gen_pseudolocale` + `compile` chain, translate
    the new msgids across all ten locales, and gate with
    `scripts/check_i18n_fresh.py`. Respect the §7 canonical multi-value exclusions
    — never wrap genre/perspective/dimension/modes/game_structure values.
  - **Est.**: M — mechanical sweep, but ~138 strings × 10 locales plus a
    build + catalog round-trip. Supersedes the Pass 49.x inline-`<script>` deferral.
  - **Progress** (2026-11-03, commit e1769b3): pop-up text wrapped in 34
    templates and four static/js files. Templates use `{{ _('...')|tojson }}`
    (PASS-49-6's choice); `t()` only fills in values there. Screenshot
    Review and the game page called `t('...')` in a template, which is never
    collected; fixed. Guard: `tests/test_js_popup_strings.py`. Walked on
    :5001 in the pseudolocale: 26 pages, no script errors.
    **Still owed**: translating the new strings into the 20 locales, in the
    v4.0.0 end batch (PASS-59-113 step 7). Not wrapped: button labels and
    other non-pop-up text set from JS.
  **Layman:** Pop-up messages and dialogs show in your own language, not English.
  Kind: implement.

- 📋 [PASS-59-111] **Make renewing the PSN sign-in painless (MEDIUM, M)**
  - **Target**: the PSN setup in `templates/_settings_tabs/account.html`
    (NPSSO wizard, Copy NPSSO bookmarklet, paste auto-detect) and
    `services/jobs/psn_keepalive.py`, which renews a live session daily but
    only while RetroDB runs.
  - **Why**: the user wants renewing the token to be as easy as possible.
    A session left alone for about two months while RetroDB is off expires,
    and the user goes through the whole wizard again.
  - **Plan**: first walk the flow end to end as a new user (`verify-delivery`),
    starting with the PASS-59-71 rotation, and list every rough step. Then fix
    what the walk finds. No design until the walk is done.
  - **Status**: todo. Lanes: psn, ui.
  - **Source**: user, 2026-10-17.
  - **Idea** (user, 2026-10-22): open Sony's sign-in from RetroDB and
    collect the token automatically once the user has signed in. Not yet
    tested against Sony's site: a sign-in page shown inside RetroDB likely
    fails, since login pages usually refuse to be framed and a page cannot
    read another site's cookies. Two shapes that can work: guided paste
    (buttons open Sony's sign-in, then its token page, and the user pastes
    the one-line reply whole), or a browser window RetroDB drives, which
    only works on the machine running RetroDB and may meet Sony's bot
    checks. Try guided paste first, during this item's walk.
  - **Progress** (2026-11-03): walk started with the PASS-59-71
    rotation. Found and fixed (commit 5d37d4a): a new token went unused
    while the cached session lived, and Save & Test reported the old
    session as working. Rough steps seen so far, not fixed: Paste &
    Detect raises Brave's clipboard permission prompt; the wizard's
    messages in `psnQuickSaveAndTest` (templates/settings.html) are
    English-only; the steps never say to sign out first, which a
    rotation needs.
  - **Correction and finding** (2026-11-03, from the log): the user's
    first Save & Test at 20:13 signed in via the NPSSO; signing out of
    Sony had already killed the cached session, so the fallback ran.
    Commit 5d37d4a's message is wrong to call that a passing old
    session; the flaw it fixes is real only while the old session still
    works. **Sony's refresh token now lasts 10 days**
    (`refresh_token_expires_in` 863999, seen twice today), not about
    two months, and using it does not move its expiry. A lapsed session
    re-signs from the NPSSO on the next request, but the keep-alive never
    falls back to the NPSSO (INV-9). So the Settings banner counts down a
    10-day session the user need not act on. Next: show what the user
    must act on (the NPSSO's own expiry, which Sony does not report),
    and reword the banner. The comment "valid ~2 months" in
    `create_psn_client` and trophies spec §4.5 assume the old lifetime.
  - **Fixed** (2026-11-03, user chose both designs): the Settings banner
    no longer counts down Sony's 10-day session. It is green while a
    session is cached and red only once Sony refuses the saved NPSSO,
    which `create_psn_client` now records as `npsso_refused_at`; the
    dashboard notice shows only that refusal. Paste here focuses the box
    for Ctrl+V instead of reading the clipboard. Step 1 says to sign out
    first when replacing a working token. `psnQuickSaveAndTest` and its
    neighbours are translatable. The stale "two months" text in
    `create_psn_client`, trophies spec §4.5, the help page and the
    keep-alive header is corrected. Walked headless at 1280 and 375 px on
    a scratch DB, with Sony's replies faked. Still open: the server's own
    sign-in error ("PSN authentication failed...") is English-only; the
    guided-paste idea; translations of the new strings and of the two help
    paragraphs (step 7).

  ---
  **Layman:** Renewing your PlayStation Network sign-in takes a few clicks instead of a hunt for a token.
  Kind: implement.
  Lanes: psn, ui.

- 📋 [PASS-59-155] **Cheats for games played in the player, and later the standalone emulators (MEDIUM, M).**
  - **Status**: todo
  - **Ask** (user, 2026-10-22): handle cheats for the emulators, worked
    out with the RetroArch fork session.
  - **Player mechanism** (retroarch-a4, from local/fixes-2026-09 source):
    no CLI flag. At content load `command_event_init_cheats` (command.c)
    loads `<cheat_database_path>/<core library_name>/<rom basename>.cht`
    (`cheat_manager_get_game_specific_filename`, cheat_manager.c) and
    applies it only when `apply_cheats_after_load = "true"` (default
    false). So the appended cfg layer carries those two keys and RetroDB
    writes the `.cht`; no fork change. The folder is the core's display
    name (e.g. `Snes9x`), not its file name.
  - **Format**: `cheats = N` is required (0 or missing fails the load);
    per cheat `cheatN_desc`, `cheatN_code`, `cheatN_enable`, plus optional
    handler and memory-search keys.
  - **Write-back**: on exit `event_save_files` (save.c) rewrites that
    `.cht` with every cheat's on/off state, so the file is the player's
    after a launch. RetroDB copies (never symlinks) and reads state back.
  - **Source**: libretro-database `cht/` is per system, named by title;
    RetroArch matches nothing, so RetroDB must match game to file. Pack
    layout unverified; check `assets/frontend/cheats.zip`.
  - **Limits**: handler 0 cheats need the core's `retro_cheat_set`; cores
    that stub it ignore them silently (which ones: unverified). Netplay and
    BSV replay skip cheats. An applied cheat pauses RetroAchievements
    hardcore for the session (`cheat_manager_pause_cheevos`), so the page
    warns rather than greys out. The slim build (RETR-0004) must keep
    HAVE_CHEATS.
  - **Open**: standalone emulators (DuckStation, PCSX2, PPSSPP, Dolphin)
    each have their own cheat format; not researched. Whether this needs
    a spec: likely yes (a contract with the fork, new UI, a download).
  - **In v4.0.0** (user, 2026-10-23), after PASS-59-139 (PASS-59-113
    step 5a).
  - **Scope** (user, 2026-10-23): cheats must also work for DuckStation
    and PCSX2 in v4.0.0, not later. The user has many cheat files
    downloaded already (ask where before starting); more need online
    research for sources. The cheat engine may be an additional download.
    RPCS3 cheats are game patches (patch.yml), far more complex; the user
    is unsure how to handle them, so research before deciding — not
    committed to v4.0.0.
  - **Cheat sources** (user, 2026-10-23): use all of these as the
    existing collection: `/mnt/Emulators/Cheats` (PSP / PPSSPP),
    `/mnt/Emulators/Sony_PlayStation_2/Cheats` (PCSX2 collection and
    tools), `/mnt/Emulators/Sony_PlayStation_1/DuckStation/cheats`,
    `/mnt/Emulators/retroarch-config/cheats` and
    `/mnt/Emulators/.harvested_cheats`.
  - **Design answers** (user, 2026-10-23): v4.0.0 covers the player,
    DuckStation and PCSX2 only; PPSSPP and RPCS3 become later items.
    Sources: RetroDB downloads the free public packs on request (the
    libretro cheat pack, the PCSX2 community collection) and can import
    the user's own folders. Import copies into RetroDB's data folder once;
    originals are never touched; re-run to pick up new files. The game
    page lists each cheat with its own on/off switch, and RetroDB sets up
    the emulator before launch.
    - **Found** (2026-10-23): `games.disc_serial` / `disc_crc` already
    exist (migration 018); `standalone_settings.apply_for_launch` is the
    pre-launch hook; the player knows only the core id, not the display
    name RetroArch uses for the `.cht` folder. Serials are filled only for
    standalone launches today. Existing PCSX2 files are named
    `SERIAL_CRC.pnach` or `CRC.pnach`; DuckStation's are `SERIAL.cht`.
  - **Built** (2026-10-29, in the open 3.34.0): `services/cheats.py`,
    `routes/cheats.py`, the game page's Cheats panel and Settings >
    Emulators' Cheats section, per the spec (fold-back in its loop
    log). Tests: `tests/test_cheats_*.py`. Browser walk on :5001 with a
    scratch DB: Bully (PS2) listed its PCSX2 cheats, a save wrote
    `[Cheats] Enable` (file restored after), the PCSX2 pack downloaded.
    **Still owed**: the manual run in the player, DuckStation and PCSX2
    (spec §7), and §14's question on RetroArch's exit rewrite.
  - **Progress** (2026-11-03): the user ran cheats in the player,
    DuckStation and PCSX2 in the last week of October and says they
    work. Still open: spec §14 (does RetroArch's exit rewrite of the
    `.cht` keep cheats it could not apply).

  ---
  **Layman:** Turn cheats on for a game before you play it.
  Kind: implement.

- 🚧 [PASS-59-161] **Screenshots must come from the game's own system, never another platform's version (FEATURE, M).**
  - **Status**: in-progress
  - **Request** (user, 2026-10-23): screenshots shown for a system must be
    true to that system. Seen: screenshots from a more colourful system
    attached to ZX Spectrum games. The user knows ZX Spectrum and C64
    graphics well and will judge the result.
  - **Likely cause** (read 2026-10-23): IGDB (scraper/scrape_igdb.py,
    `screenshots.url`) and RAWG (scraper/scrape_rawg.py,
    `games/{id}/screenshots`) return screenshots per game, not per
    platform, so a multi-platform game gets every version's pictures.
    ScreenScraper (per ROM system), TheGamesDB (per-platform entries) and
    ES-DE (local files) are tied to one platform.
  - **Plan**:
    1. Take screenshots only from platform-tied sources (ScreenScraper,
       TheGamesDB, ES-DE). Use IGDB/RAWG shots only when that game exists
       on this one platform alone.
    2. A check for fixed-palette systems: every pixel of a real shot
       falls near the system's own palette (ZX Spectrum 15 colours with
       its attribute-cell limit, C64 16, Game Boy 4 shades, and so on)
       and the image has the system's native shape (ZX 256x192 plus
       border, C64 320x200 plus border). A shot that fails is refused.
    3. A review screen for screenshots already in the library that fail
       the check, with remove: the user decides, nothing is deleted
       silently.
  - **Verify**: re-scrape a ZX Spectrum game also released on C64 and
    Amiga: only Spectrum screenshots land; a C64 shot fed to the check is
    refused; the review screen lists existing wrong shots.
  - **Source**: user, 2026-10-23.
  - **Progress** (2026-10-30): Plan step 1 built 2026-10-30, in the open 3.34.1:
    `base_scraper.on_one_platform` gates IGDB and RAWG screenshots on the
    game listing exactly one platform. Tests:
    `tests/test_pass59_161_screenshots_own_system.py`,
    `tests/test_scrape_fill_only.py`. Not run against the live IGDB or
    RAWG services. Screenshots already in a library are unchanged. Steps 2
    (the palette check) and 3 (the review screen) are still to do; the
    user judges the palette results on ZX Spectrum and C64.
  - **Progress** (2026-10-31): **Progress** (2026-10-31): Plan steps 2 and 3 built, in the open 3.34.1, with step 2 changed by a survey. Measured on stored shots: all ZX Spectrum, all Game Boy, a sample of C64. Exact palettes wrongly flag real games, because emulators show colours differently and stored shots are lossy and upscaled.
    User decisions 2026-10-31: refuse a new shot only when certain; review list covers ZX Spectrum, C64 and Game Boy.
    Built: `services/screenshot_fit.py` refuses an unscaled lossless original with far more exact colours than the machine shows, before finalizing. ScreenScraper, TheGamesDB, IGDB and RAWG downloads go through it; ES-DE copies and manual uploads do not. ROM Tools > Screenshot Review ranks stored shots by how badly they fit the machine's colour count; only an editor's Remove deletes. Tests: `tests/test_pass59_161_screenshot_fit.py`. Page walked on a scratch copy.
    Limits: the ranking is uneven. It worked best on Game Boy, was mixed on C64, and on ZX Spectrum real OutRun shots ranked above wrong ones while orange Duggy shots ranked low. A shot judged real is listed again on the next scan.
    Still to do: try the refusal on real downloads (originals are not kept, so the rule has only met test pictures); the user judges the ZX Spectrum and C64 results.
  - **Progress** (2026-10-31): **Plan step 1 narrowed** (2026-10-31, user decision): the rule cut
    multi-platform games to 1 or 2 shots (scrape of 2026-10-30: Colin
    McRae Rally 3, 04 and 2005, Burn Zombie Burn! got no IGDB or RAWG
    shots). It now applies only to 8-bit and 16-bit systems,
    `screenshot_fit.EIGHT_AND_SIXTEEN_BIT`; other systems take IGDB and
    RAWG shots again and may show another version's pictures. Arcade
    folders are left out. Games scraped under the wider rule need
    re-scraping to get the shots back.
  - **Progress** (2026-10-31): **Refusal narrowed to Game Boy** (2026-10-31): tested on ES-DE's
    original files, in `downloaded_media` under
    `/mnt/Emulators/Multi-System/ES-DE`. The rule as first shipped would
    have refused 113 of 314 countable C64 originals and 29 of 145 ZX
    Spectrum ones, and the samples viewed were nearly all real shots: real
    originals hold up to thousands of colours. A redraw-fit test on the
    same originals overlaps Mega Drive, SNES, NES and Game Boy Color
    shots, so no certain test exists there yet. Game Boy separates: real
    originals hold 4 shades. No refusal had been logged before the change.
    This corrects the earlier note that the rule had met no originals.

  ---
  **Layman:** A game's screenshots come from its own console, not from a version on another console.
  Kind: implement.

- 📋 [PASS-59-169] **RetroDB updates itself from GitHub Releases (FEATURE, L).**
  - **Status**: implemented in 3.33.0, not yet tried against a real
    published release.
  - **Asked** (user, 2026-10-27): a self-updater. Decided the same day:
    check plus one-click install (never unattended), GitHub Releases as
    the source, source and standalone installs both, spec then straight
    to code with the code as the review.
  - **Spec**: `docs/specs/PASS-59-169-self-updater.md`.
  - **Shape**: `services/updater.py` checks
    `releases/latest` (drafts stay invisible until published, so
    publishing is the switch), downloads the asset for this install,
    checks it against the release's SHA-256 file and unpacks it safely.
    Install backs up the database and starts the NEW version's helper
    (`updater_apply.py`, or `retrodb --apply-update`), which swaps files
    after RetroDB exits, restarts, waits for `/health` to report the new
    version and otherwise rolls files and database back. Settings >
    System > Updates and an admin dashboard banner (`static/js/updates.js`).
  - **Verify (still to do on real releases)**: publish a release after
    this one ships, then update a source install and a standalone on
    Linux and Windows from it; break one (a release whose program exits
    at once) and see the rollback bring the old version back.

  ---
  **Layman:** RetroDB can download and install its own updates.
  Kind: implement.

- 🚧 [PASS-59-218] **Steam and Xbox imports keep what the services already send (enhancement, M).**
  - **Status**: in-progress
  - **Source**: PASS-59-162, 2026-10-31. Notes: ai_steam_xbox S1 to S7, X1 to X7. The library has no Steam or Xbox rows, and Xbox has no real reply, so the Xbox claims are unproven.
  - **Problem**: `get_app_details` has no callers, so imports stay nearly empty. A title match never links the Steam ID, so no achievements. Play time is fetched then dropped. Xbox may stop at 100 games, and phone and PC titles may be filed as Xbox One.
  - **Needs**: one real Xbox sign-in to test. Steam store data has real board ratings and a Metacritic score.
  - **Decided** (user, 2026-11-02): Steam first, tested with the user's
    own Steam account against a scratch database. Then the user is guided
    through Microsoft's app registration and one Xbox sign-in;
    `xbox_client_id` and `xbox_client_secret` are empty, so registration
    comes first. Xbox fixes wait for real replies.
  - **Progress** (2026-11-02): Steam built and run against the user's real account on a scratch database (8 games). `SteamSyncJob` fills empty fields once per game from the store, keeps play time in `platform_play_time`, and a Steam or Xbox title match now links its ID. Steam's date and genre are left out: DOOM 3 is dated 2007, its Steam release, and 7 of 8 genres are only Action. Also fixed: an admin's Fetch Library sent Steam the masked key.
    - **Not done**: Steam's review summary (`appreviews?json=1`) answered with a web page, not data, so no user scores. S6 (achievement language) and the `hidden` flag are left. The S3 note's example was wrong: `generate_sort_title` pads numbers and does not move "The".
    - **Next**: Xbox X1 to X7, after the user registers a Microsoft app and signs in once.
  - **Progress** (2026-11-09): **Progress** (2026-11-09): X1-X7 carried out in PASS-59-261 (OpenXBL).
    A live Xbox reply is still owed there.

  ---
  **Layman:** Steam and Xbox imports keep the extra details those services already send.
  Kind: implement.

- 🚧 [PASS-59-261] **Xbox import signs in with a free OpenXBL key, not an Azure app (feature, M).**
  - **Status**: in-progress
  - **Why**: the user tried to link Xbox and was asked for an Azure
    account (2026-11-05). Microsoft app registration needs an Azure
    account since June 2024. The current redirect is built from
    `request.host_url` (`routes/platform_import.py`), and Microsoft only
    accepts http redirects to localhost, so LAN installs cannot sign in.
  - **Decided** (user, 2026-11-05): OpenXBL per-user free key
    (https://xbl.io, 150 requests an hour, no card). A shipped public
    client with device-code sign-in stays a later option. Borrowing
    Microsoft's own Xbox app id was rejected (impersonation).
  - **Do**: a per-user OpenXBL key in Profile, stored like other platform
    tokens; library and achievements through the OpenXBL API, paced under
    `service_limits`; remove the client id and secret settings and the
    OAuth routes. Carries PASS-59-218's X1 to X7.
  - **Source**: research 2026-11-05 (Home Assistant, xbox-webapi-python,
    Microsoft Entra docs, xbl.io pricing).
  - Carried from PASS-59-249 group E (audit 2026-11-04, 2026-11-06): the
    OpenXBL rewrite must not repeat three lows in the code it replaces.
    `XBOX_PLATFORM_MAP` has no `PC` device, so PC titles may file as Xbox
    One; Xbox 360 achievements read with contract 2 may come back empty
    and count as 0/0; title history stops at 1000 and returns a partial
    list on errors with no warning (`scraper/scrape_xbox.py`). Not fixed
    in place: that code goes with this item.
  - **Progress** (2026-11-09): **Progress** (2026-11-09): built in the open 4.0.0 (commits cea95e44,
    ee45243f). Per-user OpenXBL key in Settings > My Profile
    (`/api/xbox/key` saves only a key OpenXBL accepts; the key is never
    sent back); client id/secret settings, setup guide and OAuth routes
    removed; migration 042 drops old sign-in rows. X1-X6 fixed, X7 gone
    with OAuth. A 429 is never retried and stops that key for the hour;
    the bulk sync takes never-synced games first. Tests:
    `tests/test_xbox_openxbl.py`; headless walk at 1400 and 375 px on a
    scratch DB. **Still owed**: one real OpenXBL key, to confirm the base
    URL (`https://api.xbl.io/v2`) and the reply shapes, which are
    Microsoft's and not yet seen through OpenXBL.

  ---
  **Layman:** Xbox import works with a free key from OpenXBL instead of a Microsoft developer account.
  Kind: implement.

- 📋 [PASS-59-227] **MAME games show their real names, and scrape by them, with the file names left alone (enhancement, M).**
  - **Target**: `games.title` for the MAME system comes from MAME's own list: the set name (`dyger`) to its description (`Dyger (Korea set 1)`), year and manufacturer. `rom_path` never changes. Scrapers then search by the real name.
  - **Why**: 6,291 MAME rows are titled by short name and 2 are scraped (2026-11-02), so a scrape searches for `dyger` or `peps0275`. Hold them out of the bulk Fill Missing until this lands.
  - **Data** (MAME Curator session, measured 2026-11-02): the title from the 0.284 non-merged DAT, which holds all 6,291 zips; other fields from `listxml-0.287.xml`, joined by set name, which lacks 10 of them. Keep the full description, since 627 zips share a base title. A shipped feature needs the user to point at their own file; RetroDB cannot assume these paths.
  - **Sources**: arcadeDB is keyed by set name; libretro-thumbnails by description. ScreenScraper's romnom with a set's zip name is untested. Read each one's terms first.
  - **Open**: gambling, slot, handheld, computer, tabletop and board-game sets per catver.ini, and BIOS sets, are in the same folder. Whether they show is the user's call.
  - **Status**: todo. Lanes: scraper, services.
  - **Source**: user, 2026-11-02.
  - **Progress** (2026-11-02): Built 2026-11-02: naming tool, category filter, BIOS hidden, search by
    title, ScreenScraper lookup by zip name, reports refuse a rename.
    Still to do when worthwhile: arcadeDB and libretro-thumbnails as
    sources, after reading their terms. A scrape of a named game through
    every source has not been run.

  ---
  **Layman:** Arcade games show their real names and are looked up by them, while their files keep the names MAME needs.
  Kind: implement.
  Lanes: scraper, services.

- 📋 [PASS-59-252] **The box viewer reads Slipcase's two new finger-recess keys (enhancement, S).**
  - **Status**: todo
  - **Why**: the Slipcase session, 2026-11-04 (SLIP-0130, Slipcase commit
    4de187b, SLIP-0125 § 4.1 amended). Box file version stays 1.
  - **Keys** in `shape`:
    - `recess_end_radius_mm`: 0 square ends; half `recess_height_mm` round
      (missing means half, the old look); at most half.
    - `recess_offset_mm`: slot middle above the opening side's middle,
      negative below; missing 0. Limit: `recess_length_mm + 2*|offset| <
      height_mm - 2*max(corner_radius_mm, lip_width_mm)`.
    - A shape breaking either limit is ignored whole.
  - Ignoring the keys still draws a round, centred slot, so nothing breaks
    today. Xbox One and Series X cases are newly shaped.
  - **Source**: Slipcase session, 2026-11-04.

  ---
  **Layman:** The 3D box viewer reads two new settings from Slipcase for the finger hole in a case.
  Kind: implement.

- 📋 [PASS-59-170] **Verify release signatures before an update installs (SECURITY, M).**
  - **Status**: todo
  - **Why**: PASS-59-169 checks downloads against the SHA-256 file
    published in the same release, which catches corruption and a
    swapped file on the way, but not a release whose files and checksums
    were both replaced. `release.yml` already signs every zip with cosign
    (keyless, GitHub OIDC); checking that signature would tie a download
    to the repository's own release workflow.
  - **Do**: verify the `.cosign.bundle` beside each asset (the `sigstore`
    package, identity = this repository's `release.yml` on a `v*` tag)
    before unpacking; the standalone `-Standalone.zip` assets need
    signing in the `build-standalone` job first.
  - **Verify**: a tampered zip with a matching checksum file is refused.

  ---
  **Layman:** An update is checked for a genuine signature before it installs.
  Kind: implement.

- 📋 [PASS-59-174] **A failed update rolls back packages and keeps writes made after its backup (MEDIUM, M).**
  - **Why**: `updater_apply.py::install_dependencies` runs pip into the
    shared interpreter before the health check, and rollback never
    reverts it, so old code can restart against upgraded packages. The
    pre-update DB backup (`services/updater.py::install`) is taken
    before the job drain, and rollback restores it even when the new
    version never opened the DB, losing writes made in between.
  - `services/updater.py::UpdateJob._download` and `host_platform()`
    duplicate `services/player_install.py`'s capped download and host
    detection.
  - **Status**: todo. Lanes: updater.
  - **Source**: code review of PR #23, 2026-10-29.

  ---
  **Layman:** If an update fails, RetroDB goes back to how it was without losing anything saved since.
  Kind: implement.
  Lanes: updater.

- 📋 [PASS-59-168] **Move Get RetroArch to the next stable release and bind network commands to 127.0.0.1 (MEDIUM, S).**
  - **Status**: planned; waits on upstream's next stable release.
  - **Why**: official 1.22.2 binds network commands on every interface
    while a player launch has them on (all launches on Windows and
    macOS, .m3u games on Linux). Upstream b5172edaa1 adds
    `network_cmd_bind_address`; no release tag holds it yet (checked
    2026-10-23). The RetroArch fork session tells RetroDB when one does.
  - **Do**: bump `VERSION` and the three SHA-256 pins in
    `services/player_install.py`; write `network_cmd_bind_address =
    "127.0.0.1"` in the run layer; amend PASS-59-64 §4.4.
  - **Verify**: a fresh Get RetroArch installs the new version; `ss
    -ulnp` shows the player's port on 127.0.0.1 only; Next disk works.

  ---
  **Layman:** Get RetroArch downloads a newer version, and its remote-control commands only listen on this computer.
  Kind: implement.

- 📋 [PASS-59-275] **Keyboard and screen readers: the remaining controls with no focus or no name (accessibility, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **After**: PASS-59-274, which adds the standard these follow.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - M `static/css/pages/game-list.css:155-158`: Checked scrape-mode toggle's box-shadow beats the focus rule, so focusing the default-checked toggle…
  - M `static/css/pages/game-list.css:392; pages.css:2366-2376`: Search clear button and museum controller image actions are opacity 0, so Tab lands on invisible…
  - M `static/js/all-games-controller.js:1188,1191,1197,1202,1206`: Filter-tag remove × is a span with no focus or name, so keyboard users cannot drop a single filter value.
  - M `static/js/all-games-controller.js:757`: Bulk-select checkbox has no label, so screen readers announce 'checkbox' with no game name.
  - M `static/js/all-games-controller.js:865-878,897`: Source and Rating filter options are divs, unlike the generic button form, so keyboard users cannot pick…
  - M `static/js/game-modals.js:1370-1376`: Tag remove × in quick edit is a <span> with no tabindex, role or name, so keyboard and screen-reader…
  - M `templates/_settings_tabs/account.html:20,52,60`: Avatar wrapper, avatar choices and upload zone are unfocusable clickable divs, so the avatar cannot be…
  - M `templates/_settings_tabs/library.html:64-119`: Theme radiogroup options are divs with no role=radio, tabindex or aria-checked, so themes cannot be…
  - M `templates/edit_modal.html:458`: Label for='edit_emulator_override' names a non-existent id, so the Emulator override select has no…
  - M `templates/game_detail.html:2198-2200,2220`: Screenshot delete button is shown only on hover, so keyboard and touch users land on or miss an…
  - M `templates/settings.html:1576,1586,3041,3433,3228,1953`: Naming-builder, remove controls, controller expander and bonus-disc parent picker are spans/divs…
  - M `templates/steam_achievements.html:72; xbox_achievements.html:72…`: Game search inputs and progress filter selects have no label or aria-label; placeholder is not an…
  - M `templates/wishlist.html:552-558,586`: While anything is scraping, every wishlist card is rebuilt every 3 s, dropping keyboard focus to <body>.
  - Low: static/js/utils.js:1130; static/js/global-search.js:125-129; static/js/apply-progress.js:50-75…; templates/changelog.html (Load More script); static/js/game-modals.js:548,1215; templates/game_detail.html:4113 (and other tag renderers); templates/game_detail.html:598-602; static/js/all-games-controller.js:1276-1278; templates/setup.html:35; templates/login.html:251…; templates/rom_tools_settings.html:462,501; templates/archive_scanner.html:1285-1286,1350; templates/archive_scanner.html:1312,1366,1597; templates/achievements_system.html:158; templates/reports.html:359-447; templates/reports.html:966,967,1086,1087…; templates/analytics.html (chart canvases); templates/dashboard.html:29,37; modals.css:97-107,184-187; buttons.css:27-31,164-167…; static/css/features/manual-reader.css:50-53
  - Open questions (answer first): static/js/main.js:861-864; static/js/utils.js:549; templates/base.html:707; static/js/toast-controller.js:1052; static/js/game-modals.js (_createTag); templates/base.html (showConfirm)…; docs/RETRODB_DESIGN_STANDARDS.md §11; ModalFocusTrap; templates/archive_scanner.html (archive and…; templates/logs.html (level/view/filter/category toggle…; templates/psn_trophies.html (platform buttons); templates/psn_trophies.html (syncTrophies, startBulkRefresh); templates/reports.html (batchRenameModal onescape); templates/systems.html:26-41; pages.css:915,929; _tab_bar.html:29-31; reports.html:287-296

  ---
  **Layman:** The last buttons a keyboard can't reach, or a screen reader can't name, get fixed.
  Kind: implement.

- 📋 [PASS-59-278] **Translate the page scripts still in English: Lists, settings, achievements, trophies, reports, dashboard (i18n, L).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Do**: wrap per CLAUDE.md step 8 and `docs/specs/i18n.md` §6; regenerate the catalogs.
  - **Follows**: PASS-59-246 (shipped). Number formats are PASS-59-256.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `templates/lists.html:4-79,339,354,358-359,369-370,391-392`: The Lists page is almost wholly untranslated (title, placeholders, modal labels, English plural logic)…
  - M `static/css/components/tags.css:223`: CSS content 'None selected' is English text that can never be translated; it shows in the edit modal's…
  - M `static/js/bulk-edit.js:81,109,137,165`: Bulk-edit genre/structure/perspective/dimension options show canonical English instead of tField labels.
  - M `static/js/game-modals.js:1406-1408,1487-1489,1568-1570,1893-1895,1975-…`: Quick-edit dropdown options show raw canonical English and placeholders/optgroup labels are hardcoded…
  - M `static/js/toast-controller.js:1055,1125,1237,795-800,1361`: Job names are English literals outside t() and are concatenated with translated fragments, which i18n §6…
  - M `templates/_settings_tabs/scraping.html, system.html, library.html…`: Large blocks of settings, login and password-change text and role names are hardcoded English, not…
  - M `templates/achievements_system.html, achievement_game.html…`: Many script and markup strings on achievement pages are hardcoded English, including relative-time text…
  - M `templates/base.html:578-579,596,599,628,635,637,642-643,649`: Folder-browser strings in a template script stay English in every locale, and counts skip formatNumber.
  - M `templates/collector_trophies.html:99`: earned_at UTC string cut to 10 chars, so users outside UTC see the wrong day near midnight.
  - M `templates/dashboard.html:1146,1288,1292,1300,1310,1317,1336,1339`: Dashboard script strings are hardcoded English with English-only plurals, overwriting translated banner…
  - M `templates/duplicate_finder.html, screenshot_dedup.html…`: Many user-facing strings on maintenance pages are hardcoded English, including an English-only plural.
  - M `templates/game_detail.html:4021-6032 (many, listed in report)`: Many hardcoded English strings in the inline script: rename errors, placeholders, optgroups…
  - M `templates/game_detail.html:5707,5750-5763,5977`: JS overwrites server-translated labels (Lookup HLTB, HLTB labels, Screenshots heading) with English…
  - M `templates/game_imports.html:928`: Dates use a hardcoded en-US locale ('Mar 15, 2024') instead of the required YYYY-MM-DD via DateUtils.
  - M `templates/psn_trophies.html, psn_trophy_detail.html…`: Many script strings on trophy pages are hardcoded English, some overwriting translated labels after one…
  - M `templates/reports.html (many lines)…`: Report and export script strings are hardcoded English, permanently replacing translated button labels…
  - M `templates/settings.html:1307-4889 (many, listed in report)`: Large blocks of user-facing English in the settings script never go through {{ _()|tojson }}.
  - M `templates/systems.html:727,734-744,776,780,783,917`: Systems page script strings (spec labels, empty text, 'Showing X of Y') are hardcoded English.
  - M `templates/xbox_achievement_game.html:104,212…`: UTC ISO strings cut at 16 chars show a literal 'T' in UTC, ignoring user timezone and the date format…

  ---
  **Layman:** The Lists, Settings, achievements, trophies, reports and dashboard pages show in your language.
  Kind: implement.

- 📋 [PASS-59-279] **Translation follow-ups: small untranslated strings, plurals and dates (i18n, S).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **After**: PASS-59-278.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - Low: static/js/utils.js:885-888,643,60; static/js/main.js:1501,1623; static/js/main.js:1660; static/js/utils.js:860; static/js/updates.js:37; templates/_macros/breadcrumb.html:15…; static/js/game-modals.js:2330,137,384,391,2238-2239…; templates/game_detail.html:46; templates/game_detail.html:265; static/js/all-games-controller.js:706-710,715,720…; templates/all_games.html:155…; templates/museum.html:4,11,37-39,131…; templates/lists.html:487-494…; templates/settings.html:2643,5073,2641-2647; templates/archive_scanner.html, chd_verify.html…; templates/archive_scanner.html:1304,1279; templates/game_imports.html:838; templates/achievements_system.html:16-24,88,104,297,342,469…; templates/local_trophy_detail.html:261,299; templates/psn_trophy_detail.html:6,195…; templates/psn_trophies.html:132-141; templates/analytics.html:2691,2748,2735,2810; templates/systems.html:11; templates/dashboard.html:236,300; templates/systems.html:78; install.py; install_gui.py:45-54; routes/launch_settings.py:65-91…
  - Open questions (answer first): templates/game_detail.html:46; docs/specs/i18n.md §6; templates/_bulk_edit_modal.html:30; static/js/emulators-settings.js:644; templates/chd_converter.html:75; templates/achievements_system.html:421; templates/dashboard.html:303; templates/systems.html:83; docs/specs/i18n.md; docs/specs/i18n.md

  ---
  **Layman:** Small leftover English words, plurals and dates get translated.
  Kind: implement.

- 📋 [PASS-59-280] **Python: emulator setup on Windows and macOS, installer safety, and the GPU helpers (audit-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `services/upscale_worker.py:38,120,140-148; services/rembg_worker.py:96`: The 600s watchdog counts a slow first model download as a crash, so on slower links background removal…
  - M `install.py:149; install_gui.py:435`: Fallback Pillow install is unpinned and unhashed, bypassing the --require-hashes lock exactly when the…
  - M `install.py:166; install_gui.py:457`: copy2 gives config.py, scraper settings and PSN credentials file 0644, readable by every local user.
  - M `install_gui.py:586; install.py:249`: Installer opens/prints a hard-coded localhost:5000 after 2.5s, ignoring the saved port and slow first…
  - M `installer_core.py:135-137`: Installer silently retries with --break-system-packages, installing pinned packages into the distro…
  - M `installer_core.py:52; start.bat:23`: MIN_PYTHON (3,8) passes interpreters the dependencies can't install on, giving a pip resolver error…
  - M `routes/emulators.py:246-259`: Clearing is_default runs outside a transaction with unvalidated ids; a failed upsert leaves the system…
  - M `routes/launch_settings.py:28-38,129-136,163,167-169…`: Emulator Detect uses Linux-only paths and file patterns, so it finds nothing on Windows (.exe) or macOS…
  - M `services/disc_files.py:19,89,96`: Playlist rewrite is in place: a failed read writes an empty .m3u, and non-UTF-8 disc names are corrupted…
  - M `services/disc_files.py:36`: Absolute or ../ track names in .cue/.gdi escape the sheet folder, so CHD conversion can delete files…
  - M `services/emulator_adapters.py:65-81`: DuckStation and PCSX2 data-folder lists are Linux-only, so per-game settings and BIOS status never work…
  - M `services/rembg_worker.py:77-79`: ROCm provider is used without the spec's /dev/kfd R/W check, so AMD users outside the render group lose…
  - M `services/rembg_worker.py:99-106`: Any rembg error, even a non-image upload, is treated as GPU failure, switching to CPU for good and…
  - M `services/upscale_worker.py:167-171`: One failed first model download marks AI upscaling unavailable until restart; jobs silently fall back to…
  - Low: install.py:162-166; install_gui.py:453-457; install_gui.py:576-581; install_gui.py:553-558; install_gui.py:245; install_gui.py:339-341; installer_core.py:69-81; install.py:23-25; .gitleaks.toml; routes/emulators.py:110,113-114,146-147,152; services/player_cores.py:378-383,429-432; services/player_cores.py:470-476; services/launcher/local.py:64-75; routes/emulators.py:258-259; services/emulator_seeder.py:59-69; services/player_cores.py:191-205; services/upscale_worker.py:132,136-137,150-156; services/upscale_worker.py:232-240; services/upscale_worker.py:197-198
  - Open questions (answer first): install.py; install_gui.py; installer_core.py; requirements.lock; routes/launch_settings.py; services/player_cores.py:401; services/standalone_settings.py (write_lines, _target); routes/emulators.py; services/upscale_worker.py:167-171; services/upscale_worker.py:120,140-148; services/upscale_worker.py:211-213,245; services/upscale_worker.py (Popen pipes)

  ---
  **Layman:** Fixes for emulator setup on Windows and macOS, the installer, and the image helpers that use the graphics card.
  Kind: implement.

- 📋 [PASS-59-281] **Text contrast and brand colours: raise --text-muted, and name the brand colours (accessibility, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **User decisions 2026-11-10**: (1) raise `--text-muted` in the six failing themes and drop the "documented acceptable" note in `docs/theme_contrast.md`; (3) brand colours (Steam, Xbox, PSN, rating boards, system badges) become named tokens, with a written exemption from "no hard-coded colours".
  - **Then**: rerun `scripts/audit_contrast.py`. Fixed cyan is PASS-59-255.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `static/css/core/variables.css:41; themes.css:46,148,249,352,559`: --text-muted is under 4.5:1 in six themes incl. the default, on small hints, placeholders, nav titles…
  - H `trophies.css:633,704-707,750; hltb.css:189; game-modals.css:380…`: --text-muted (~3.6:1) and --neon-gray (~3.7:1) are used for small informative text, failing 4.5:1 on the…
  - M `game-list.css:1057-1060; settings.html:888-891`: White text on PEGI green (~2.0:1) and grey 'unknown' system badge (~3.6:1) fail 4.5:1 for small text.
  - M `game_detail.html:3912-3914,3926-3928; game-modals.css:226-227`: White on cyan rename button (~1.9:1), white on orange RA badge (~2.2-3.2:1) and error text (~3.6:1) fail…
  - Low: themes.css (Christian); cards.css:280; utilities.css:158…; game-list.css:1384-1388; pages.css:589-594,1274-1277
  - Open questions (answer first): static/css/components/badges.css:116-246; static/css/core/variables.css:41; game-list.css:1086-1179,1288-1320,1464-1555; core/variables.css (--text-muted, --neon-gray); game_detail.html:1232-1266,2058-2061,2090-2093

  ---
  **Layman:** Faint grey text becomes easier to read in every theme.
  Kind: implement.

- 📋 [PASS-59-282] **Layout: phone gaps, hidden sticky headers and duplicated CSS (ux, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Check**: desktop and 375px after each fix.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `templates/systems.html:1017-1019,589-596`: Masonry inline grid-row styles override the <=480px auto-rows rule, adding thousands of px of empty…
  - M `pages.css:1489-1569; game-list.css:796-866`: .alphabet-nav exists in two drifted copies, so library pages get a mix of both and other pages a…
  - M `static/css/components/tables.css:86-88`: Sticky table headers use top:0, so between 601 and 992px they stick under the fixed phone header and are…
  - M `static/css/pages/game-list.css:807`: A-Z strip assumes the filter bar is <=80px; at <=768px the bar wraps taller and the strip likely slides…
  - M `static/css/pages/pages.css:1076`: Unscoped .tag rule under detail-page styles overrides the tags component on every page.
  - M `templates/game_detail.html:2897-2898`: Scrape modal overlay offsets by the 260px sidebar width, so with a collapsed sidebar a ~190px strip…
  - M `templates/game_detail.html:983-3938`: Game page inline <style> redeclares many external classes (.hltb-*, .game-hero, .stat-value, .modal…
  - Low: static/js/utils.js:967-970; static/js/main.js:153; static/js/theme.js:189; templates/changelog.html (.version-badge); templates/game_detail.html:4470; templates/tags.html:142,54; templates/wishlist.html:623; templates/lists.html:262,209…; templates/rom_tools_settings.html:192-193,197…; static/js/log-viewer.js:284; templates/logs.html:508-513; templates/logs.html:470; templates/screenshot_dedup.html:149-151; templates/analytics.html:2477; templates/systems.html:621,642-643…; static/css/core/typography.css:7; responsive.css:122; forms.css:383-387; static/css/pages/game-list.css:1097,1114,1156; static/css/pages/game-list.css:319,316; settings.html:156-168,400-410,527-530; static/css/pages/game-list.css:877; static/css/pages/pages.css:2097; game_detail.html:2181 vs 2874/2880; 1698 vs 2474; 1715 vs…; trophies.css:220-233; filters.css:198-207; game-modals.css:375-383; game_detail.html:1925
  - Open questions (answer first): templates/game_detail.html:64; static/css pages.css:2092-2101; templates/settings.html (~958, .confirm-modal-message); templates/archive_scanner.html:346; templates/achievements_system.html:690,743,774; templates/achievement_game.html:391-394; templates/analytics.html:1529-1530; static/css/components/tables.css:86-88; pages.css:1778; typography.css:111; game-cards.css:248; stat-boxes.css:47; achievements.css:16…

  ---
  2026-11-11 (user): also on a 375px phone the Settings page overflows
  sideways; a `.detail-value` span is wider than the screen.
  **Layman:** Fixes for empty gaps and hidden headers on phones, and for duplicated page styles.
  Kind: implement.

- 📋 [PASS-59-287] **Docs and comments the review found out of step with the code (doc-fix, S).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - Low: static/js/utils.js:74; services/template_filters.py:38; static/js/theme.js:141; templates/base.html:17-19; static/js/main.js:1362; static/js/all-games-controller.js:1615; templates/settings.html:1075,1114; docs/specs/rom-tools.md §4.3-4.4; routes/tools.py:412-421; static/js/achievements.js; templates/help.html:731,872,900-915,988,1377; templates/help.html:360,373; templates/help.html:1818; docs/RETRODB_DESIGN_STANDARDS.md §8; .claude/rules/distribution.md; .semgrep.yml:35,106,109,118
  - Open questions (answer first): static/js/utils.js:280-284; docs/reviews/2026-11-04-independent-audit.md; roadmap.md; static/js/toast-controller.js…; static/js/toast-controller.js:1397,1400; templates/game_detail.html:5027-5134; templates/help.html:1869,121,1695; templates/help.html:233,511,561; docs/RETRODB_DESIGN_STANDARDS.md §8,§20…; .semgrep.yml

  ---
  **Layman:** Help pages and code notes that no longer match the app get corrected.
  Kind: implement.

- 📋 [PASS-59-289] **Tests: clean up shared test state, and keep the player profile out of reach (test, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **User decision 2026-11-10**: the player-profile gap (H) tightens the shipped PASS-59-239 isolation work.
  - **Related**: the Steam-key flake fixed 2026-11-09 was this class.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `tests/test_player_cores.py:73`: Player profile isolation rests on a config.BASE_DIR monkeypatch alone (also player_install:31…
  - M `tests/test_etag_and_gzip.py:111`: Clears force_password_change on seeded admin id 1 in the shared DB on every run and never…
  - M `tests/test_log_redactor.py:118`: Strips SecretRedactor from the root logger (also :155) and never restores it for later tests…
  - M `tests/test_mame_names.py:167`: Fixture leaks a 'mame' systems row, and the job's counts depend on no other test leaving…
  - M `tests/test_observability.py:112`: factory_snapshot restores the record factory but not _request_id_installed, so request_id…
  - M `tests/test_pass46_frozen_paths.py:171`: reloaded_app restores only app and config; modules first imported in the reload (e.g.…
  - M `tests/test_pass54_media_integrity.py:136`: clear_missing_media_refs sweeps every row in the shared DB, so leftover rows break the count…
  - M `tests/test_pass59_118_trophies.py:75`: Inserts users row id 2 ('other-stub') and the finally never deletes it; it stays in the shared…
  - M `tests/test_pass59_133_keep_media.py:10`: Relies on conftest's shared IMAGE_PATH/screenshots being empty; a leftover file flips the…
  - M `tests/test_pass59_248_hardening.py:21`: _make_user commits admin users and user_settings rows to the shared DB and never deletes them…
  - M `tests/test_pass59_249_gpu_env.py:42`: delenv(raising=False) on an absent var records no restore, so the 10.3.0 set by the code leaks…
  - M `tests/test_pass59_268_ra_queue.py:60`: Fixture clears ra_queue _items but leaves the watcher thread alive, so it can call…
  - M `tests/test_password_floor.py:52`: Posting /api/setup renames the shared seeded admin to 'boss' and changes its password; nothing…
  - Low: tests/test_bulk_scrape_race.py:115; tests/test_fresh_install_schema.py:102; tests/test_pass45_security.py:1897; tests/test_pass59_118_trophies.py:157; tests/test_pass59_119_rom_tools.py:91; tests/test_pass59_241_silent_failures.py:97; tests/test_pass59_240_secrets.py:46; tests/test_pass59_238_media.py:79; tests/test_pass59_frontend.py:243; tests/test_psn_new_npsso.py:25; tests/test_rpcs3_compat.py:24; tests/test_shutdown_route.py:64
  - Open questions (answer first): tests/_versions_util.py; tests/test_etag_and_gzip.py:111; tests/test_fresh_install_schema.py; tests/test_log_redactor.py:118; tests/test_log_redactor.py:118; tests/test_observability.py:112; tests/test_observability.py:112; tests/test_pass38_region_helper.py:51; tests/test_pass41_security.py:667; tests/test_pass46_frozen_paths.py:171; tests/test_pass46_frozen_paths.py:171; tests/test_pass46_frozen_paths.py:1; tests/test_pass59_133_keep_media.py:10; tests/test_pass59_rom_tools.py:174; tests/test_pass59_118_trophies.py:135; tests/test_pass59_133_keep_media.py:10; tests/test_pass59_206_canonical_labels.py:1; tests/_versions_util.py:1; tests/test_pass59_249_gpu_env.py:42; tests/test_pass59_248_hardening.py:21; tests/test_pass59_268_ra_queue.py:60; tests/test_pass59_268_ra_queue.py:60; tests/test_password_floor.py:52; tests/test_player_launch.py:36; tests/test_psn_new_npsso.py:25; tests/test_player_cores.py:73; tests/test_pass59_rom_tools.py:175; tests/test_scan_library_rom_path.py:215

  ---
  **Layman:** Tests clean up after themselves so one test can't change another's result.
  Kind: implement.

- 📋 [PASS-59-291] **Tests that check too little to catch the bug they are named for (test, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **After**: PASS-59-290.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - M `tests/test_auth_hardening.py:142`: Nothing checks the planted session key is gone, and the refused login never…
  - M `tests/test_auth_hardening.py:395`: Only checks words before the token survive; a redactor that wipes every long…
  - M `tests/test_emulator_autodetect.py:297`: _walk_appimages sorts dirnames, so both mine_first cases walk the same order; the…
  - M `tests/test_fresh_install_schema.py:99`: Runs its own copy of the upsert SQL, so a regression in the routes/trophies.py…
  - M `tests/test_graceful_shutdown.py:18`: _SINGLETON_NAMES omits museum_images_job and ai_fill_bulk_job, so their cancel is…
  - M `tests/test_hltb_alt_titles.py:160`: lookup_playtime returns None on any exception, so 'result is None' (also :99)…
  - M `tests/test_input_hardening_app.py:59`: Named for rate limits but only asserts three view functions exist; removing every…
  - M `tests/test_input_hardening_museum.py:60`: Sends no upload; compares two config constants, so the route could stop checking…
  - M `tests/test_metadata_merger.py:420`: assert meta['genre'] passes for any non-empty value, including the char-iteration…
  - M `tests/test_observability.py:207`: SLOW_REQUEST_MS=0 returns before the probe exemption is checked, so deleting the…
  - M `tests/test_official_names.py:174`: Asserts only title != LOCKED_NAME; a Reset that blanks the title or restores the…
  - M `tests/test_pass35_36_hardening.py:90`: Checks init_database's pragma, but FK pragma is per-connection; deleting get_db's…
  - M `tests/test_pass38_region_helper.py:63`: The first match is also the first part, so the test passes with region matching…
  - M `tests/test_pass39_supply_chain.py:76`: Compares total pin and hash counts, so one unhashed pin passes; marker-bearing…
  - M `tests/test_pass45_security.py:839`: Image.MAX_IMAGE_PIXELS is one Pillow-wide global, so neither test can tell which…
  - M `tests/test_pass48_media_cleanup.py:85`: No -sm/-md fanart files exist, so wrongly deleting fanart variants would still…
  - M `tests/test_pass59_119_rom_tools.py:204`: Proves a paused task stops by sleeping 0.3 s; a slow worker passes on broken…
  - M `tests/test_pass59_216_extra_data.py:235`: Return of queue_stored_suspects() is ignored; if nothing is queued, approve_all…
  - M `tests/test_pass59_217_identify_by_file.py:42`: Checks for escaped.bin in tmp_path.parent, where a ../../ escape cannot land; the…
  - M `tests/test_pass59_237_disc_files.py:114`: deleted == 0 can come from 'not in scan results' or the playlist guard; groups…
  - M `tests/test_pass59_237_disc_files.py:64`: Poll gives up after ~4 s without failing and returns empty groups, so the…
  - M `tests/test_pass59_247_scrapers.py:179`: Assertion only inside the loop; an empty suggest_groups result passes, so 'kept…
  - M `tests/test_pass59_auth_api.py:125`: Forced-change form check accepts any 200 page with '<form' or 'password', so it…
  - M `tests/test_pass59_auth_api.py:57`: 'still masks unexpected errors' checks only status 500; a regression leaking…
  - M `tests/test_pass59_rom_tools_js.py:30`: Node catch swallows any load-time error except 't is not defined', so an early…
  - M `tests/test_rembg_worker.py:97`: Compares against prior 'rembg' in sys.modules; if an earlier test imported rembg…
  - M `tests/test_review_fixes_gamepage.py:109`: Response unchecked and no record that the injected failing() raised; assertions…
  - M `tests/test_routes_launch.py:173`: Override 'unchanged' is also what an unprocessed POST shows; the only co-field…
  - M `tests/test_server_port.py:183`: Both sides resolve to default 5000 from inherited temp settings, so a CLI…

  ---
  **Layman:** Tests that check too little to catch their bug get stronger checks.
  Kind: implement.

- 📋 [PASS-59-292] **Tests: check behaviour instead of source text, and stop depending on the working folder (test, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `tests/test_pass40_9_16_security.py:386`: Source window around 'Cleared' includes a comment holding 'AND ' and ' = ?', so the check is always true.
  - M `tests/test_auth_hardening.py:82`: A negative string match on one spacing of 'password_hash = None' stands in for checking non-admins get…
  - M `tests/test_pass37_a11y.py:215`: The <h4> guard reads only the settings.html shell; tab content moved to _settings_tabs partials is…
  - M `tests/test_pass38_template_macros.py:208`: Scans only settings.html; a raw tab-subnav class re-added in a _settings_tabs partial is not caught.
  - M `tests/test_pass41_security.py:1561`: Claim that api_track_view no longer writes games.last_viewed is checked only by a comment marker in…
  - M `tests/test_pass41_security.py:317`: Two tests check only that 'get_request_db' appears in the file; the import satisfies it, so reverting…
  - M `tests/test_pass45_security.py:904`: Computes open_count but never compares it; extra Image.open sites with no bomb catch pass if four…
  - M `tests/test_pass59_208_wrong_game.py:247`: Checks only that the DEFAULT_SCRAPER_PRIORITY name appears in four files; its value (rawg last) is never…
  - M `tests/test_pass59_245_focus.py:22`: Globs at :22 and :55 are CWD-relative; from outside the repo root they match nothing and pass; CSS glob…
  - M `tests/test_pass59_destructive_ops.py:337`: Claims batch_create_m3u honours delete_archives but only checks a substring in its source; dead or…
  - M `tests/test_pass59_packaging.py:62`: Positive checks (also :105, :179, :423) search raw source incl. comments; a comment naming the call…
  - M `tests/test_sidebar_nav.py:91`: Greps the template for the tabs macro call; passes inside a comment or dead branch and never checks the…
  - M `tests/test_units_sold.py:44`: Two tests check SQL/name substrings in source for fill-only and integer storage; comments or dead code…
  - Low: tests/test_ai_fill_bulk.py:192; tests/test_input_hardening_uploads.py:38; tests/test_mame_names.py:240; tests/test_modal_plain_text.py:50; tests/test_pass29_frontend.py:47; tests/test_pass39_supply_chain.py:247; tests/test_pass35_36_hardening.py:328; tests/test_pass41_security.py:1731; tests/test_pass45_security.py:2427; tests/test_pass45_security.py:795; tests/test_pass59_258_a11y.py:15; tests/test_pass59_scrapers.py:87; tests/test_release_dates.py:58; tests/test_scraper_settings_cache.py:105; tests/test_sidebar_nav.py:92
  - Open questions (answer first): tests/test_ai_fill_bulk.py:192; tests/test_pass35_36_hardening.py:290; tests/test_pass40_9_16_security.py:386; tests/test_pass59_scrapers.py:87; tests/test_units_sold.py:44

  ---
  **Layman:** Tests check what the app does, not how its code is written.
  Kind: implement.

- 📋 [PASS-59-293] **Tests: fixed waits, slow waits and other test hygiene (test, S).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Related**: PASS-59-221 holds the two slowest tests.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - M `tests/test_bulk_scrape_race.py:225`: A fixed 0.3 s wait before asserting one live worker can fail falsely under load and miss a late…
  - M `tests/test_emulator_autodetect.py:160`: fake_home moves only $HOME, so a system-wide Flatpak under /var/lib/flatpak changes results at :160…
  - M `tests/test_i18n_longform.py:58`: Three tests (:58, :69, :90) each re-parse every changelog YAML, about 9.7 s together.
  - M `tests/test_pass59_132_parallel_fallbacks.py:53`: Finish order rests on a 0.2 s sleep and a 2 s Barrier timeout; under -n 4 load the order flips or the…
  - M `tests/test_pass59_243_jobs.py:81`: Fixed 0.3 s wait assumes the old worker reached its pause; under load it fails without a regression or…
  - M `tests/test_pass59_268_ra_queue.py:133`: time.sleep(2.5) costs 2.5 s and buys nothing; the property is already proven and the negative assert…
  - M `tests/test_pass59_268_ra_queue.py:94`: Waits out the real POLL_SECONDS = 2 (2.01 s measured) though _watch reads the global each loop.
  - Low: tests/test_auth_hardening.py:410; tests/test_game_logo.py:133; tests/test_launcher_local.py:169; tests/test_migrations.py:320; tests/test_pass38_region_helper.py:71; tests/test_pass59_244_recover.py:13; tests/test_pass59_249_database.py:121; tests/test_pass59_auth_api.py:155; tests/test_pass59_frontend.py:271; tests/test_rembg_worker.py:119; tests/test_rembg_worker.py:128; tests/test_shutdown_route.py:142; tests/test_updater.py:297; tests/test_xbox_openxbl.py:231
  - Open questions (answer first): tests/test_emulator_autodetect.py:160; tests/_bulk_scrape_fixtures.py; tests/test_game_logo.py:133; tests/test_migrations.py:320; tests/test_museum_job.py; tests/test_pass59_161_screenshot_fit.py:21; tests/test_pass59_243_jobs.py:81; tests/test_pass59_auth_api.py:155; tests/test_pass59_trophy_dataloss.py:71; tests/test_launch_resolver.py:10; tests/test_upload_image_pipeline.py:34; tests/test_upload_image_pipeline.py:34; tests/test_upload_limits.py:29
  **Layman:** Tests stop waiting longer than they need to.
  Kind: implement.

- 📋 [PASS-59-255] **Every theme colours the whole page: the remaining fixed cyan becomes theme colours (ux, M).**
  - **Status**: todo
  - **Why**: component CSS still names the cyberpunk cyan directly
    (`rgba(76, 201, 240, …)`, `#4cc9f0`), so those parts stay cyan in the
    Matrix, Amber and other themes. PASS-59-245 moved the focus rings and
    focus glows; `docs/specs/themes.md` §1 now says the rest are not done.
  - **Fix**: replace each with a theme colour, for example
    `color-mix(in srgb, var(--primary-cyan) 15%, transparent)`, and look at
    every theme at desktop and 375px. Then drop the caveat from themes.md.
  - **Find them**: `grep -rnE "rgba\(76, ?201, ?240|#4cc9f0" static/css/*/`.
  - **Progress** (2026-11-10): PASS-59-251 review 2026-11-09 adds these places (lanes 05, 15, 16,
    17). Medium: `static/css/components/buttons.css:63-67` and the other
    components, with the `*-bg` tokens in `variables.css`; `pages.css`
    tabs, alphabet nav and panels, with `game-list.css` and settings
    selects; `progress.css:312`, `toasts.css:54-61` (duplicate rules, some
    dead); the game page's inline styles in `game_detail.html`. Low:
    `templates/all_games.html:260,281-282`; `game_detail.html:2255`
    against `hltb.css:45`; `game_detail.html:2078-2081` against
    `trophies.css:364-367`. Contrast and brand colours: PASS-59-281.

  ---
  **Layman:** Every theme colours the whole page, with no leftover fixed blue-green.
  Kind: implement.

- 📋 [PASS-59-256] **Numbers and sizes are written the way the reader's language writes them (i18n, S).**
  - **Status**: todo
  - **Why**: `formatNumber` (thin-space thousands) and `formatBytes` in
    `static/js/utils.js`, and the Jinja `format_number` filter, ignore the
    language, so a German reader sees English decimal points.
  - **Fix**: format with the page's locale (`Intl.NumberFormat` from the
    `<html lang>`; Babel's `format_decimal` on the server), keeping the thin
    space where a locale has no grouping rule of its own.
  - Not done in PASS-59-246, which wrapped text only.
  - **Progress** (2026-11-10): PASS-59-251 review 2026-11-09 adds (lanes 01-14). Medium:
    `templates/analytics.html:1529`, where Chart.js formats numbers in the
    browser's own way. Low, counts shown without `formatNumber`:
    toast-controller, game-modals, all-games-controller, mame-names,
    museum, settings, the CHD and archive pages, hltb_review, reports,
    dashboard. Also: `static/js/utils.js:74` puts separators into the
    decimal part (0.12345 becomes 0.12 345), while the Jinja copy
    truncates to a whole number; `game_detail.html:840` uses
    `filesizeformat` (English units). Full list: the PASS-59-251 triage
    ledger.

  ---
  **Layman:** Numbers and file sizes are written the way your language writes them.
  Kind: implement.

- 📋 [PASS-59-221] **The slowest test runs real image work: speed up test_screenshot_duplicates_are_dropped (test, S).**
  - **Status**: todo
  - **Source**: measured 2026-10-31, while aligning the local gate with GitHub CI.
  - **Problem**: in the gate's environment, which has the CPU onnxruntime from the lockfile, `tests/test_upload_image_pipeline.py::test_screenshot_duplicates_are_dropped` took 66 to 148 s of a suite that takes 79 to 198 s, depending on machine load. The whole suite on the system Python took 61 s. `test_fu1_csp.py::test_every_action_is_defined` is next, at 37 to 55 s.
  - **Fix**: find what makes it slow; a duplicate check should not need a real upscale. Every push and both GitHub Python versions run it, so this is the largest saving available in the gate.
  - **Progress** (2026-11-10): PASS-59-251 review 2026-11-09 found both slow tests (High, test lane
    T17). `tests/test_upload_image_pipeline.py:34`: `_get_upscaler` is not
    stubbed, so two tests start the real upscaler; stubbing it took the
    file from 50.0 s to 1.3 s (measured by the review).
    `tests/test_fu1_csp.py:234`: `test_every_action_is_defined` took 24.4
    s, running three regex scans over all source for each action and
    reading files twice. Other slow and timing tests: PASS-59-293.

  ---
  **Layman:** The slowest test runs faster.
  Kind: implement.

- ✅ [PASS-59-262] **Auto-link leaves alone a disc the user unmarked as a bonus disc (audit-fix, S).**
  - **Status**: todo
  - **Why**: `unlink_bonus_disc` (routes/bonus_discs.py) sets
    `is_bonus_disc = 0`, and `auto_detect_bonus_discs` reads 0 as never
    judged, so the next auto-link marks the disc again.
  - **Fix**: a new column (a migration) recording that a person said "not
    a bonus disc"; unlink sets it, a manual link clears it, detection skips
    it. Not a new `is_bonus_disc` value: every game list reads any value
    other than 0 or NULL as hidden.
  - **Not fixed in PASS-59-249** because it needs a schema change; the loop
    half of the same finding shipped there.

  ---
  Shipped 2026-11-11 in the open 4.0.0: migration 043 adds
  games.not_bonus_disc; unlink and unmark set it, a manual link or mark
  clears it, auto-detect skips it. Tests:
  tests/test_pass59_249_bonus_discs.py, tests/test_migration_043.py. No
  changelog line: the web UI has no unlink or unmark button, so only the
  API routes reached the bug.
  **Layman:** Auto-link stops re-marking a disc you said is not a bonus disc.
  Kind: implement.

- 📋 [PASS-59-156] **A hung GPU upscale holds the GPU until the server restarts (MEDIUM, M).**
  - **Status**: todo
  - **Seen 2026-10-22**: at 17:01 `_gpu_run` timed out ("GPU inference
    gave no result in 120s") and the breaker in `_upscale_image` moved to
    CPU. 1.5 h later rocm-smi showed GPU use 99%, VRAM 99% (7.9 GB held
    by the :5000 server), two server threads in `kfd_wait_on_events`,
    CPU idle. No amdgpu error in the kernel log. Only a restart frees it.
  - **Where**: services/image_utils.py `_gpu_inference_worker` /
    `_gpu_run`. The timeout stops the wait, not the `session.run`, and
    nothing in-process can cancel a wedged ROCm kernel.
  - **Plan**: run GPU inference in a child process the server can kill
    on timeout (killing it frees the card), then fall back to CPU as now.
    Check first whether onnxruntime's RunOptions.terminate reaches a
    running ROCm kernel; if it does, that is the smaller fix.
  - **Verify**: force a hang (a test hook that blocks in the child); after
    the timeout the child is gone and rocm-smi shows the VRAM released.

  ---
  **Layman:** A graphics-card upscale that hangs lets go of the card without a server restart.
  Kind: implement.

- ✅ [PASS-59-160] **Library filter "Action" also matches "Action-Adventure", so the window's count and the result disagree (LOW, S).**
  - **Status**: todo
  - **Seen** 2026-10-23 on the live library copy: the Genre window says
    Action (755 or 795 depending on version grouping), the filter
    returns 935.
  - **Why**: services/game_query.py `_build_games_query` matches each
    multi-value field with `LIKE '%value%'`, a substring. The window's
    counts (`_get_filter_options`) split the comma lists into whole
    values.
  - **Plan**: match whole comma-separated values, e.g. compare against
    `',' || REPLACE(field, ', ', ',') || ','` with `'%,value,%'`, for
    the IS and IS NOT branches alike. Check publisher/developer values
    that contain a comma themselves before choosing.
  - **Verify**: count of `?genre=Action` equals the window's Action count
    under the same grouping; a test pins Action vs Action-Adventure.

  ---
  - **Shipped** (2026-11-10, in 4.0.0): services/game_query.py
    whole_value_sql / whole_value_param match one whole comma-separated
    value, used by the Library filter, /api/filter-games and Similar
    games. On the live library every filter value's count now equals the
    window's, apart from case twins ("Doom" and "DOOM"): the filter
    ignores case, the window counts each spelling. Test:
    tests/test_pass59_160_whole_value_filter.py.
  **Layman:** The Library's "Action" filter shows the same number of games as its count says.
  Kind: implement.

- 📋 [PASS-59-166] **On an achievements system page, the console tabs scroll under the section tabs (FIX, S).**
  - **Status**: todo
  - **Seen 2026-10-23** (Firefox, 500px, /achievements/system/8): the
    `.tool-tabs.achievement-tabs` bar and the `.system-tabs` bar are both
    sticky with the same `top`, so the second sits under the first when
    scrolled. `.system-tabs` is also taller than the screen there when
    its consoles wrap. Same at desktop before PASS-59-165 (both `top: 0`).
  - **Verify**: scroll the page at 500px and desktop; no bar covers another.

  ---
  **Layman:** On an achievements console page, the console tabs stop sliding under the section tabs.
  Kind: implement.

- 📋 [PASS-59-167] **On a phone, some sticky filter bars fill a third or more of the screen (UX, S).**
  - **Status**: todo
  - **Seen 2026-10-23** (Firefox, 500x900): sticky bar heights at phone
    width were Library filter bar 273px plus alphabet bar 61px, Logs
    toolbar 384px, Systems filter bar 199px, ROM Tools tabs 130px. With
    the phone header and bottom bar, little page is left on a real phone.
  - **Plan**: decide per bar whether it stays sticky on a phone, or
    collapses there.
  - **Verify**: scroll each page at phone width; the content keeps most
    of the screen.

  ---
  **Layman:** On a phone, filter bars stop taking up a third of the screen.
  Kind: implement.

- ✅ [PASS-59-175] **Edit-form uploads stop blocking the request, and media removals wait for the save (MEDIUM, S).**
  - **Why**: each uploaded screenshot or fanart runs
    `finalize_downloaded_image` (upscaling included) inside the edit
    POST (`services/game_media_service.py`), so several small
    screenshots can take minutes. The remove_boxart / remove_boxart_3d /
    remove_fanart / remove_video checkboxes in `routes/games.py::game_detail`
    still delete files before the games UPDATE; uploads now wait.
  - **Status**: todo. Lanes: routes, media.
  - **Source**: code review of PR #25, 2026-10-29.

  ---
  Shipped 2026-11-11. Removals and replaced files are deleted after the
  games UPDATE; boxart, 3D boxart and screenshot uploads defer upscaling
  via upscale_queue.defer_for and list the game after the UPDATE. Tests:
  tests/test_pass59_175_edit_media.py.
  **Layman:** Saving the edit form with uploaded pictures stops being slow, and removed pictures go only when you save.
  Kind: implement.
  Lanes: routes, media.

- ✅ [PASS-59-176] **Game page follow-ups: one RPCS3 label table, console missing-metadata count per group (LOW, S).**
  - **Why**: the RPCS3 status labels are written twice, in
    `templates/game_detail.html` and `static/js/game-modals.js`
    (`rpcs3CompatBadgeHtml`). The console page's missing-metadata header
    (`routes/systems.py::system_games`, `total_missing`) counts rows,
    while its Unscraped filter and the Systems page count version groups.
  - **Status**: todo. Lanes: ui, routes.
  - **Source**: code review of PR #25, 2026-10-29.

  ---
  Shipped 2026-11-11 in b65ce2b6: total_missing counts version groups
  (Library and console page); RPCS3 label and hover text come from
  services/rpcs3_compat.status_for_game, printed by game_detail.html and
  rpcs3CompatBadgeHtml.
  **Layman:** Small tidy-ups on the game page and the console page's missing-details count.
  Kind: implement.
  Lanes: ui, routes.

- ✅ [PASS-59-177] **Translation catalogs: drop obsolete duplicates that msgfmt rejects (LOW, S).**
  - **Why**: `msgfmt --statistics` fails on every
    `translations/*/messages.po` with duplicate definitions: obsolete
    `#~` copies of active msgids ("Loading…", "(not set)", "Apply").
    Some active entries are empty while their obsolete copy holds a
    translation (German "Apply"). Already on main before the PR merge
    of 2026-10-29.
  - **Status**: todo. Lanes: i18n.
  - **Source**: found while merging PRs, 2026-10-29.

  ---
  Shipped 2026-11-11: already done by 1359721e (dropped obsolete catalog
  entries). Checked: msgfmt -c passes on every
  translations/*/messages.po, no #~ entries remain, German "Apply" reads
  "Anwenden".
  **Layman:** Old duplicate entries are removed from the translation files.
  Kind: implement.
  Lanes: i18n.

- ✅ [PASS-59-178] **Library-import duplicate check reads only the systems it matches (LOW, S).**
  - **Why**: `routes/platform_import.py::_DuplicateIndex` normalises every
    game title in the library on each fetch-library request; before
    PR #21 it read only the target system.
  - **Status**: todo. Lanes: routes.
  - **Source**: code review of PR #23, 2026-10-29.

  ---
  Shipped 2026-11-11 in the open 4.0.0: `_DuplicateIndex(field,
  system_ids)` reads and normalises titles of the import's target
  systems only; platform-ID matches still search the whole library.
  Test: tests/test_review_routes_core.py. No changelog line.
  **Layman:** The duplicate check on Game Imports looks only at the consoles it needs, so it is faster.
  Kind: implement.
  Lanes: routes.

- 📋 [PASS-59-179] **Settings > System maintenance tools are wrapped for translation (LOW, S).**
  - **Status**: todo
  templates/_settings_tabs/system.html has "Clear Scraped Data" as bare
  text, and the maintenance JS in templates/settings.html (CLEAR SCRAPED
  DATA FUNCTIONS: preview text, confirm title, button reset, the
  "Failed to refresh logos" error) uses bare string literals. Wrap them
  with _() / t(), check the rest of that tab for the same, regenerate
  the catalogs and translate the new msgids into every locale.

  ---
  **Layman:** The maintenance tools in Settings can be translated.
  Kind: implement.

- 📋 [PASS-59-188] **Popups placed inside a page's content can sit under the sidebar and phone bars (LOW, S).**
  - **Status**: todo
  `.content-wrapper` has `position: relative; z-index: 1` (layout.css,
  since the first commit, reason unrecorded). That caps the z-index of
  everything inside it, so a `position: fixed` popup in a page's content
  paints under the sidebar (z 1000) and the phone header and bottom bar.
  The screenshot viewer (PASS-59-63) and the cover zoom (2026-10-29) were
  each fixed by moving the popup to body level. Unchecked: the popups in
  local_trophies, psn_trophies, reports, settings account and
  customization tabs, rename/manual-reader modals, select_filter_modal.
  Choose one route: drop the wrapper's z-index (one rule, every page;
  re-check fanart and other negative z-index backgrounds), or move each
  popup to body level. A phone-only `z-index: auto` was proved to fix
  the cover zoom in Firefox before being reverted for the local fix.

  ---
  **Layman:** Pop-ups stop appearing under the sidebar or the phone's top bar.
  Kind: implement.

- 📋 [PASS-59-189] **Tell the user when the AI service refuses a scrape's request (UX, S).**
  - **Problem**: since 2026-10-23 Gemini has answered every scrape's AI
    gap-fill with HTTP 402 (logs/scraping_*.log: "Gemini API error:
    402"). `scraper/hybrid_scraper.py::_run_ai_fallback` logs "AI
    fallback: no results" and the scrape reports missing fields. The
    user saw no error, only empty sales figures, release dates,
    Dimension and Game Structure, and asked why.
  - **Target**: a refused AI request (401, 402, 403, 429, or a
    circuit-breaker trip) shows the user what happened and what to
    check (key, billing, quota), on the scrape result and in bulk
    jobs. One notice per job, not one per game.
  - **Related**: PASS-53-12 (lasting error state on the item).
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** RetroDB tells you when the AI service refuses a scrape, instead of failing silently.
  Kind: implement.

- 📋 [PASS-59-254] **Syncing one PlayStation game asks Sony about that game only (perf, S).**
  - **Status**: todo
  - **Why**: `routes/trophies.py::api_psn_sync_game` pulls the user's whole
    trophy-title list (`client.trophy_titles()`) to find one game, then
    downloads every trophy icon one at a time, all inside the request.
  - **Fix**: ask for the one game (`trophy_groups_summary(npwr_id,
    platform)` or `trophy_titles_for_title`), and fetch icons in the
    background or in parallel.
  - **Hazard**: those calls return another shape than `TrophyTitle`, which
    `_psn_trophy_counts` reads. Needs a live PSN account to test, so it was
    not done untested in PASS-59-243.

  ---
  **Layman:** Syncing one PlayStation game asks Sony about that game only, so it is faster.
  Kind: implement.

- ✅ [PASS-59-272] **Regroup the roadmap into version blocks and archive finished items (chore, M).**
  - **Why**: the user, 2026-11-09: align with roadmap-format.md §3.2
    (version blocks) and archive what is finished.
  - **Agreed** (user, 2026-11-09): blocks v4.0.0 (last web version, the
    PASS-59-113 plan), v4.0.x (security and data-loss fixes), v4.x.0
    (desktop/Android app pieces), v5.0.0 (full desktop release). Open
    feature ideas outside the 4.0.0 plan go to the desktop app. Finished
    items move to an archive file, word for word. PASS ids stay.
  - **First**: check which "open" items already shipped (PASS-59-169,
    PASS-59-142, PASS-59-143, PASS-59-186, PASS-59-227 look done).
  - **Blocked-by**: ANTS-6724 (Ants MCP: convert a pass-headings roadmap
    to ants-v1, keeping PASS ids). No hand edits: the store reverts them.
  - **Status**: todo.
  - **Progress** (2026-11-09): **Progress** (2026-11-09): checked the five. Shipped: PASS-59-142 and
    PASS-59-143 (every locale translates the box-face strings),
    PASS-59-186 (commits c0c13e61 to 446b991e). PASS-59-227: core built
    2026-11-02; arcadeDB and libretro-thumbnails as sources remain
    optional. PASS-59-169: built, but its Verify needs a real published
    release, so it is not done until 4.0.0 ships. Agreed with
    ants-terminal for ANTS-6724/6725: PASS ids kept (prefix PASS-59,
    explicit ids on append). A shipped item's version comes from (a) its
    own status text, then (b) the oldest data/changelog.yaml entry citing
    it, then (c) the earliest tag containing a commit citing it; unknown
    goes to a "Shipped, version not known" archive block. Scratch-run
    counts come to RetroDB before any real convert.
  - **Progress** (2026-11-10): ants-terminal reported ANTS-6725 option 2 shipped
    (commit_evidence:false); the convert is ready. Order, all in one
    session after /mcp reconnects (session_orient server_build 0e6e5bdb or
    5b24a45d): (1) project_settings: set id_format, prefix PASS, pattern
    PASS-\d+(?:-\d+)*(?:-[A-Z])?. (2) roadmap_migrate convert: dry run,
    then real (it snapshots the store first). (3) roadmap_log
    op:"place_by_release" dry_run:true, unknown_section:"Shipped, version
    not known", commit_evidence:false. (4) Apply with its plan_id in the
    same session; a plan does not survive a server restart. Expected from
    its scratch run: placed 117, moved to "Shipped, version not known"
    213, unreleased 34 (likely 35 now: c084e5de shipped PASS-59-251 with
    no tag yet), 10 status-vs-changelog disagreements (status wins). If
    counts differ otherwise, send them to ants-terminal. Full scratch
    JSON: /mnt/Games/tmp/ants-6725-proto/pbr-retrodb-nocommit.json.

  ---
  - **Progress** (2026-11-10, later): open work regrouped. Blocks 4.0.0
  (93 items: the plan, every review fix, and the work finished but not
  released), 4.0.x (empty for now), 4.x.0 (26), 5.0.0 (PASS-59-270),
  "Ideas, not planned" (14 considered or dropped). User, 2026-11-10: the
  small web bugs outside the plan and the update-safety items
  (PASS-59-168, 170, 174) ship before 4.0.0. PASS-59-236 goes to 4.x.0
  (user, 2026-11-04: after v4.0.0). PASS-59-142, 143 and 186 flipped to
  shipped. Every open item got a Layman line. The old Active headings
  were removed; their notes are word for word in
  docs/history/roadmap-old-active-notes.md. Left: moving finished
  release blocks to an archive file.
  - **Progress** (2026-11-10, archive): the user chose a separate archive
    (2026-11-10). rotate_minor moved every released minor (3.4 to 3.34)
    into docs/roadmap/<minor>.md; the table of contents points there.
    Left: "Shipped, version not known" has no archive op yet; requested
    from ants-terminal (RetroDB_Ants_MCP_Feedback.md, 2026-11-10).
  - **Progress** (2026-11-10, split): the user asked to split 4.x.0 by
    release. One version per port-plan phase: 4.1.0 browse and play,
    4.2.0 edit and scrape, 4.3.0 tools, cheats and statistics, 4.4.0
    looks and languages, 4.5.0 Android. Each item went to the phase that
    builds its screen; the 4.x.0 heading was removed.
  - **Blocked-by** (2026-11-10): ANTS-6737, roadmap_log op:"archive_section"
    for "Shipped, version not known". It waits on a roadmap-format.md
    § 3.9 change (slug-named archive files) sent to claude-config.
  - **Shipped** (2026-11-11): ANTS-6737 landed; archive_section moved
    "Shipped, version not known" to docs/roadmap/unversioned.md. Every
    finished block is now archived.
  **Layman:** The roadmap is grouped by version, like other projects.
  Kind: implement.

- 📋 [PASS-59-112] **Remake the trailer for v4.0.0, with a disclaimer (MEDIUM, M)**
  - **Target**: new clips for the Hub website session, which builds the
    trailer (recipe in memory `trailer-footage-owed`).
  - **Why**: the current trailer skips achievements and trophies and much
    else. The user wants one new trailer once v4.0.0 ships.
  - **Plan**: cover achievements and trophies, Play from the library,
    scraping and AI Fill, tools and stats, and regional versions. End on the
    disclaimer card the user approved 2026-10-17 (text in memory
    `trailer-v4-plan`): RetroDB supplies no games, ROMs or BIOS files and does
    not condone piracy; trademarks belong to their owners; online services
    need your own account, some limit free use or charge, AI services charge
    per use.
  - **Status**: todo; blocked by the v4.0.0 release (PASS-59-113).
    Lanes: marketing.
  - **Source**: user, 2026-10-17.

  ---
  **Layman:** A new trailer for 4.0.0, with a disclaimer.
  Kind: implement.

- ✅ [PASS-59-142] **Import Slipcase box files: front, spine and back faces for a game (FEATURE, M).**
  - **Status**: todo
  - **Contract**: Slipcase repo, `docs/specs/SLIP-0104-turnable-3d-box.md`
    § 4.1 (box-file format, `"version": 1`, approved by RetroDB
    2026-10-15) and § 4.2 / INV-11 (2026-10-21: the case texture is baked
    into the face PNGs; shading is not).
  - **RetroDB's checks** (§ 11): each image at most 10 MB; a real image
    (Pillow verify plus the decompression-bomb guard); re-encoded to WebP
    at 1080 px tall; no symlinks followed; fill-only unless the user asks
    to overwrite.
  - **Open for the user**: where import starts (game page, bulk, or a
    watched folder) and whether the faces replace `boxart_3d`.
  - **Verify**: import a Slipcase box file; the three faces land as WebP
    for that game; a symlinked or oversized face is refused.
  - **Progress** (2026-10-21): 2026-10-21, Slipcase session: the box file format may move to v2
    (SLIP-0106, per-system and per-region cases: second spine, per-region
    sizes, case plastic). Build the importer on v1's current fields only
    until Slipcase sends its spec for format review. v1 files stay
    readable.
  - **Progress** (2026-10-21): 2026-10-21, Slipcase SLIP-0106 phase 1 (Slipcase commit ee8b3d5): the
    format stays version 1, so the hold above is lifted. SLIP-0104 § 4.1
    gains an optional fourth face, edge (S.edge.png, the opening side, on
    the front's right). Null or absent means fill it with colours.edge,
    and a named but missing file is refused. Run edge through the same
    image checks as the other faces. Jewel-case fronts now include a tray
    hinge strip, so never reuse the front face as a flat cover. Case sizes
    vary by region and arrive through the existing case keys.
  - **Format update** (Slipcase session, 2026-10-21; SLIP-0110): box files
    (still version 1) may carry optional `faces.top` / `faces.bottom`
    (S.top.png / S.bottom.png, or null). Only a PS1 PAL jewel case has
    them today. Same rule as edge: a non-null name is a plain file name
    and the file must exist; otherwise use `colours.top` /
    `colours.bottom`. Contract: Slipcase
    `docs/specs/SLIP-0104-turnable-3d-box.md` § 4.1. Import them when
    present.
  - **Decided** (user, 2026-10-23): import starts on the game's own
    page (one box file per game); bulk import may follow later. The
    faces are stored alongside `boxart_3d`; they do not replace it.
  - **Built** (2026-10-29, in the open 3.34.0; commit e2f2b14): spec
    `docs/specs/PASS-59-142-box-file-import.md` (fold-back in its loop
    log). `services/box_faces.py`, migration 025 (`games.box_faces`),
    POST/DELETE `/api/games/<id>/box-faces`, the Import 3D box line under
    the game page's cover, the orphan sweep's `box_faces` folder. Tests:
    `tests/test_box_faces.py`. Browser walk on :5001 with a scratch DB and
    a box file from Slipcase's `write_box_file`: import, replace, a
    missing-picture error and Remove all worked. **Still owed**: the 20
    locale translations of the new strings and help line.

  ---
  Shipped (confirmed 2026-11-09, PASS-59-272 check):
  services/box_faces.py; every locale translates the box-face strings.
  Kind: implement.

- ✅ [PASS-59-143] **Turnable 3D box viewer for games with Slipcase faces (FEATURE, M).**
  - **Status**: todo
  - **Contract**: SLIP-0104 (Slipcase repo) § 4.2 / INV-11 and INV-12.
    Show the face images as-is (the case overlay is already baked in; do
    not add one); apply lighting in the viewer; paint nothing outside the
    box, so it sits on the page background.
  - **Plan**: CSS 3D transforms, no new dependency; uses the faces
    imported by PASS-59-142.
  - **Verify**: a game with imported faces shows a box that turns with
    drag and keyboard, has a transparent background, and falls back to
    the flat cover without faces.
  - **Format update** (Slipcase session, 2026-10-21; SLIP-0110): draw
    `faces.top` / `faces.bottom` when present, else fill with
    `colours.top` / `colours.bottom`. Orientation: seen from outside,
    spine on the left; the top's picture has the back at its top edge,
    the bottom's has the front at its top edge. Contract: Slipcase
    `docs/specs/SLIP-0104-turnable-3d-box.md` § 4.1.
  - **Zoom behaviour** (user, 2026-10-23): when the player zooms the
    cover, a game with only a 2D box shows the 2D box; one with only a
    3D box picture shows that picture; one with the full set of faces
    shows the turnable 3D box.
  - **Built** (2026-10-29, in the open 3.34.0; commit 4771a8b):
    `static/js/box-viewer.js` in the cover zoom
    (`templates/_modals/boxart_zoom_modal.html`), CSS in
    `components/modals.css`. Browser walk on :5001 with a scratch DB: a
    labelled six-face box matched SLIP-0104 § 4.1's orientation on every
    face; nothing painted behind the box; 2D-only and 3D-only games zoom
    to their pictures; Remove and re-import update the zoom without a
    reload. **Still owed**: a real mouse drag by eye (only keys were
    driven); the 20 locale translations of the two new strings.
  - **Progress** (2026-11-03): the user dragged the box with a real
    mouse and it turns correctly. Still owed: the 20 locale
    translations of the two new strings.

  ---
  Shipped (confirmed 2026-11-09, PASS-59-272 check):
  static/js/box-viewer.js, commit 4771a8be.
  Kind: implement.

- ✅ [PASS-59-186] **Claude API as an AI provider (FEATURE, M).**
  - **Target**: AI Fill and the other AI features can use Anthropic's
    Claude with the user's API key.
  - **Note**: the key goes in the settings store the other AI keys
    use, never a tracked file. Default to the newest Claude models.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  Shipped (confirmed 2026-11-09, PASS-59-272 check): commits c0c13e61 to
  446b991e; tests/test_ai_claude_provider.py.
  Kind: implement.

- ✅ [PASS-59-71] **ACTION REQUIRED — rotate the PSN NPSSO token that standalone builds shipped (HIGH, S)**
  - **Target**: the live PSN NPSSO credential (`docs/psn-npsso.env`, gitignored).
    Not a code task: `a5e0939` already closed the leak path.
  - **Why**: `retrodb.spec` carried `('docs', 'docs')`, and PyInstaller's
    directory form takes the whole tree with no per-file filter, so every
    standalone build embedded the real token. Confirmed against a bundle already
    on disk built 2026-04-27 — `dist/retrodb/_internal/docs/psn-npsso.env` was
    byte-identical to the live file, so this was shipped, not theoretical. The
    source ZIPs were never affected (the file is gitignored and `build_dist.py`
    excludes it by name); only the PyInstaller path, which keeps its own
    whitelist. `gitleaks` could not have caught it: it is scoped to
    `git ls-files`, so an untracked secret a build step copies into an artifact
    is invisible to it.
  - **Plan**: the code fix has landed and the local `dist/` was deleted. What
    remains is the credential itself. **Rotate it if any standalone build was
    ever shared** — Patreon release, a zip sent to a tester, anything off this
    machine. If no bundle ever left the machine, no rotation is needed; record
    that conclusion here so the question is not reopened.
  - **Verify**: a fresh `--standalone` build contains no `docs/` tree
    (`tests/test_pass58_standalone_docs.py` pins it); then the old token no
    longer authenticates.
  - **Resolution** (2026-11-03): rotated. The user signed out of
    PlayStation, signed in again and saved the new token in Settings. The
    saved token differs from the one in `docs/psn-npsso.env` (compared
    by equality, never printed). One sign-in with the old token: Sony
    refused it (PSNAWPAuthenticationError). One with the new token:
    accepted, as the user's PSN name. RetroDB reads the token from
    Settings only; `docs/psn-npsso.env` is an installer template copy.
  - **Status**: done (2026-11-03). Lanes: security, packaging.
  - **Source**: in-session 2026-09-01 (`a5e0939`); filed 2026-09-02 because it
    existed only in a session handoff, which is not somewhere the next session
    will find it.
  - **Progress** (2026-09-26): the user is not sure whether a standalone
    build ever left the machine, and chose to rotate the token. Waiting on the
    user. The v3.23.12 bundle built today contains no `docs/` tree and no
    `psn-npsso` file.
  - **Progress** (2026-10-23): the user got a new token and saved it in
    docs/psn-npsso.env. A session then printed that file, so the new
    token is exposed in a conversation log. Get one more token, enter
    it in Settings and in that file, then check the app signs in.
  - **Progress** (2026-11-03): still open; the user chose to get the
    new token later.

  ---
  Kind: implement.
  Lanes: security, packaging.

- ✅ [PASS-59-209] **HowLongToBeat: right game, right platform, and minutes counted as minutes (fix, M).**
  - **Resolution** (2026-11-02): Done 2026-11-02, opening 3.35.2. Limits: Check Saved Play Times (ROM
    Tools) still has to be pressed on the live library; 244 saved matches
    were flagged on a copy (233 platform, 11 title), and some are fine
    because HowLongToBeat does not list every system. Stored rows cannot
    be checked by year: no year is stored for a match. A title spaced so a
    Roman numeral stands alone ("Super Spike V' Ball") still scores as a
    sequel, so it goes to review. `gp32` has no platform filter, and
    `pcfx`'s "NEC PC-FX" was not confirmed: two guessed searches found
    nothing. Requests are a second apart here until PASS-59-215 gives a
    shared pace. HowLongToBeat's terms were not read (its page refused the
    fetch).
  - **Status**: done
  - **Source**: PASS-59-162, 2026-10-31. Notes: hltb_ra H1 to H8.
  - **Problem**: `app.py`, `routes/collector_trophies.py` and `services/analytics.py` read `Main: 36 mins` as 36 hours, so totals are far too high. The bulk job ignores `platform_mismatch`. A sequel can pass the 95% bar. The year is never passed, and `Game Boy` is found inside `Game Boy Advance`.
  - **Fix**: one shared time parser or numeric columns; queue mismatches for review; numbers must agree; pass the year; compare whole platform names. Send affected stored rows to the review queue.
  - **Walked** 2026-11-04 (headless Chrome, scratch DB, game 1829
    Sonic the Hedgehog 3, 1400 px and 375 px): empty box warns; lookup,
    Cancel, Save and reload work; no console errors; no sideways scroll
    at 375 px.
    - **Found**: a typed title HLTB does not know still falls back to the
    game's stored alternate titles (`HLTBLookupService.search` loads
    them by `game_id`), so nonsense text offered "Sonic 3 A.I.R" (2019,
    PC/Mobile, 78%) with Save. The via-notice and "Platform not found"
    show. Open: use alternates only when the box holds the game's own
    title. Ask the user.
    - **Found**: the year shows after Save but not after a reload; no
    column stores it.
  - **Fixed** 2026-11-04 (584117d, user's choice): stored alternate
    titles are tried only when the box holds the game's own title.
    - **Owed**: the help manual's "How Long to Beat" steps say "Select the
    correct match from the results"; the page shows one match with Save
    and Cancel. Fix with the translations step (all help files).

  ---
  Kind: implement.

- ✅ [PASS-59-223] **The translated help manuals catch up with older English sections (doc-fix, M).**
  - **Resolution** (2026-11-03): Shipped 2026-11-03 in 419ae7e, into the open 4.0.0 entry. All 20
    manuals match help.html by section structure, <code>/<pre> text, ids,
    hrefs and Jinja. Also fixed: the Back label meant "go back" in af, de,
    es; help.html's stale Official Names mention. Left for the PASS-59-113
    translation step: "MAME Names" is still English in the nb and it
    catalogs. Gap: test_i18n_longform compares hrefs as sets, so it missed
    the lost in-text #ai-fill link.
  - **Status**: done
  - **Problem**: found while translating 3.35.0. The translated `help.<locale>.html` files lack two English sections, Search Anywhere and Keeping a Title, and some older paragraphs lag the English, such as Backfill Alternate Titles. In xh and zu, Custom Images and Fill Missing appear under older labels in older text.
  - **Fix**: compare each locale's sections with `help.html` and translate what is missing. Do it before v4.0.0.
  - **Progress** (2026-11-02): Also missing from the translated manuals: the MAME Names section
    (2026-11-02). New strings for the MAME Names page and the Xbox wording
    in Settings wait on translation too.
  - **Progress** (2026-11-03): 2026-11-03: help.html gained a "Back of the box" item on the game page
    list, and "box back" in Media Handling and Custom Images (PASS-59-225).
    The new UI strings for the Back button and Edit window wait on
    translation too.

  ---
  Kind: implement.

- ✅ [PASS-59-228] **A full-screen play screen that shows the game's logo while it starts (feature, M).**
  - **Target**: when you press Play, a full-screen screen shows the game's logo while the emulator starts.
  - **Why**: PASS-59-224 asked for the logo on a play or loading screen too. None exists: `static/js/game-launch.js::launchGameImpl` relabels the Play button and shows toasts (PASS-59-224 spec §3, §9). Split out when PASS-59-224 shipped, as the user asked (2026-11-03).
  - **Needs**: a design first: when it shows, how it closes, what it shows for a game with no logo.
  - **Shipped** (2026-11-03, 478a00f, in the open 4.0.0): the screen
    lives in `static/js/game-launch.js`, its styles in
    `components/launch-indicator.css`. It also closes 15 s after the
    start, because a game started from another device's browser never
    takes that browser's focus. Walked in headless Chrome on :5001 with
    launch replies faked. **Still owed**: one real Play on the user's
    desktop to see it close as the game window opens; the 20 locale
    translations of its two strings.
  - **Status**: done.
  - **Source**: user, 2026-11-02.
  - **Decided** (user, 2026-11-03): the game's logo, large, on its
    background art. It closes by itself once the emulator opens; Esc or
    a click closes it sooner. A game with no logo shows its title in
    big text instead. Design done; ready to build.

  ---
  Kind: implement.

- ✅ [PASS-59-229] **Some tests pass or fail by run order: they read removed_screenshots from a test database nothing has migrated (test, S).**
  - **Target**: every test file passes when run alone and in any order.
  - **Why**: the push gate's docs check runs in random order and failed once on `tests/test_pass59_217_identify_by_file.py::test_the_history_says_the_file_matched`. That test fails when its file runs alone, before PASS-59-224 as well as after. ScreenScraper merge tests in `test_pass59_216_extra_data.py`, `test_metadata_merger.py` and `test_scrape_fill_only.py` fail the same way alone; the full suite passes.
  - **Cause (likely)**: `get_existing_screenshot_hashes(..., game_id)` reads `removed_screenshots` (migration 035) from the session test database, which has its tables only once some test has imported `app`.
  - **Fix idea**: migrate the session test database in `tests/conftest.py`, or point the affected tests at a migrated fixture.
  - **Shipped** (2026-11-03, e915e1f): a session fixture in
    `tests/conftest.py` migrates the test database before any test runs.
    The four files that failed alone now pass alone; full suite and
    `ci_local.sh --docs` pass.
  - **Status**: done.
  - **Source**: build of PASS-59-224, 2026-11-03.

  ---
  Kind: implement.

- ✅ [PASS-59-231] **The 3D box viewer draws a real case shape: rounded corners and edges, a raised lip, a side seam (FEATURE, M).**
  - **Shipped** (2026-11-03): built to SLIP-0125 § 4.1 as of Slipcase
    52dbd6f (slot centred on the seam, half-round ends). The import keeps
    a valid `shape`; a bad one imports flat. The viewer draws on WebGL2
    (no WebGL2: the flat picture); its geometry equals Slipcase's
    `box_patches` exactly for six test shapes. The depth buffer settles
    the concave solid, so nothing is sorted.
    - **Owed**: the user's own look, after importing a box file from a
    Slipcase build that writes `shape` (the stored Final Fantasy VII
    Rebirth box has none yet). A figure change in Slipcase needs no
    RetroDB change; a geometry change needs boxPatches ported again.
  - **Status**: done; waits for Slipcase's SLIP-0125 spec (PS5 first).
  - **Why**: the user chose real shape plus painted faces, and put it
    in v4.0.0 (user, 2026-11-03).
  - **Agreed with Slipcase (2026-11-03, RetroDB's answer)**: shape as
    a few named mm parameters in an optional `shape` section of box
    file version 1; absent or zero means flat. Released importers
    refuse any version but 1 and ignore unknown keys. Face images
    unchanged (INV-11).
  - **Work**: `services/box_faces.py` keeps `shape` in the record;
    `static/js/box-viewer.js` draws it (CSS 3D first: rounded face
    corners, thin strips for lip and bevel). A box imported before
    this needs importing again to gain its shape.
  - **Progress** (2026-11-03): Slipcase's spec arrived:
    `Slipcase/docs/specs/SLIP-0125-keep-case-shape.md` § 4.1. An optional
    `"shape": {"corner_radius_mm", "edge_radius_mm"}` in box file v1;
    each zero applies on its own (RetroDB agreed); a bad shape draws the
    box flat. Slipcase dropped the raised lip: it makes the solid concave
    at the hinge. The lip stays painted in the face pictures. Unblocked.
  - **Decided** (user, 2026-11-03): no raised lip as a 3D shape; it
    shows only in the face pictures. Build to SLIP-0125 § 4.1.
  - **Decided again** (user, 2026-11-03, later): the real lip shape,
    replacing the no-lip answer above. SLIP-0125 § 4.1 was amended: new
    optional `lip_width_mm`, `lip_height_mm`, `seam_width_mm`,
    `seam_depth_mm` (missing means 0); no lip or seam on the spine side;
    the solid is concave, so check depth sorting in the viewer. Slipcase
    no longer paints the lip's inner wall into the pictures.
  - **Spec update** (Slipcase, 2026-11-03, its commit 95bee0b): SLIP-0125
    § 4.1 (e) adds a finger recess on the opening side, asked for by the
    user: optional `recess_length_mm`, `recess_height_mm`,
    `recess_depth_mm` (missing means 0; any 0 means no recess), with
    their own limits. On the spine side the seam strip is flat and shows
    the spine picture. Which half the recess cuts waits on the user.

  ---
  Kind: implement.

- ✅ [PASS-59-232] **Move Refresh RetroAchievements out of Settings to where weekly jobs live (UX, S).**
  - **Target**: the Refresh RetroAchievements button and its Clear RA
    controls in `templates/_settings_tabs/system.html`.
  - **Why** (user, 2026-11-03): it is a job run about once a week, not a
    setting; Settings holds what changes how the app is used.
  - **Open**: where it goes. Recommendation: the Achievements page, next
    to Refresh Progress. Ask the user before building.
  - **Shipped** 2026-11-03 (366650f): the button is Find Games with
    Achievements on the RetroAchievements page, in a card where every
    button has a line saying what it does; Clear RA Data for all systems
    moved with it; an admin with no linked games gets an empty page with
    the Find button. Settings keeps a link. Owed: translations of the
    new strings; the user's own look after Restart.
  - **Status**: done.
  - **Decided** (user, 2026-11-03): the Achievements page. That page
    also has Sync and Refresh Progress buttons, so each button must say
    plainly what it does (label and a short line under it), so no one
    mixes them up.

  ---
  Kind: implement.

- ✅ [PASS-59-237] **ROM tools never delete or overwrite a working ROM or playlist (audit-fix, M).**
  - **Resolution** (2026-11-04): Done 2026-11-04 in cb6f0b86. New services/disc_files.py; fixes in
    routes/tools.py, routes/reports.py, routes/games_media.py,
    scraper/rom_tools.py; tests in tests/test_pass59_237_disc_files.py.
    Premise corrections: the live Duplicate Finder and CHD scan are in
    routes/tools.py (the DuplicateFinder and CHDConverter classes in
    scraper/rom_tools.py are unused, left for PASS-59-251); the Create M3U
    staging move already repointed rom_path (PASS-59-137). Not done: a
    browser walk of the Duplicate Finder and Screenshot Dedup pages.
  - **Status**: done
  - **Why**: the 2026-11-04 audit (`docs/reviews/2026-11-04-independent-audit.md`,
    lanes 9 and 10). Confirmed in code 2026-11-04 for the first three.
  - **Fix**:
    - Duplicate Finder name mode groups by stem only, so `Game.cue` and
      `Game.bin` are duplicates (`scraper/rom_tools.py` name grouping).
      Group by stem plus extension.
    - `delete_duplicates` unlinks any path sent. Check each is under the ROM
      root, in a found group, and that one copy survives.
    - Hash mode can delete an audio-track `.bin` two releases share, and
      leaves `games.rom_path` stale.
    - Organize Multi-Disc (`routes/reports.py`) writes over an existing
      `.m3u`, and `shutil.move` replaces a same-named file. Refuse both, as
      `rom_tools` Create M3U does.
    - Organize and the Create M3U staging move leave `games.rom_path` on
      the old place, so Clean missing ROMs then deletes those games.
    - Organize puts `.bin` tracks next to their `.cue` in the playlist.
    - CHD convert with delete originals lists `.bin` and `.cue` both and
      deletes only the file chdman got; a `.m3u` naming the `.cue` is not
      updated.
    - `zip -d` matches names as patterns (`[!]`); pass `-nw` and check the
      removed set against the request.
    - Renaming a `.bin` breaks its `.cue`; renaming a disc in a playlist
      folder breaks the `.m3u`.
    - Screenshot-dedup delete (`routes/tools.py`) does not check the file
      belongs to the game or keep one copy.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-238] **Media files are never lost: wishlist pictures, screenshot lists, partial downloads (audit-fix, M).**
  - **Resolution** (2026-11-04): Shipped 2026-11-04 in 71ff0a97, all eight parts, tests in
    tests/test_pass59_238_media.py. Deleting a game removes its media only
    from the two hand deletes (one game, one wishlist item); Clean missing
    ROMs and Clear CLZ imports still leave files to the orphan sweep, so a
    game whose ROM is only briefly missing keeps its pictures.
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 3, 6 and 8. The first two confirmed in
    code 2026-11-04.
  - **Fix**:
    - The orphan sweep (`services/media_cleanup.py`) keeps only digit
      prefixes, so wishlist files `w<id>_...` are deleted. Keep wishlist
      rows' files.
    - The game page and modal (`routes/games.py`) clear `screenshots` for
      any file not found, on every view, by any user. With `IMAGE_PATH`
      unmounted every viewed game loses its list. Clear only when the
      folder is healthy, or only in scans as CLAUDE.md says.
    - `metadata_merger._download_and_finalize` leaves `.dl_*` temp files
      on early returns; use `finally`.
    - Video and manual downloads write straight over the file the row
      uses; write to a temp file and rename.
    - `webp_migrate`: no `safe_path` containment; a file two rows share is
      deleted by the first conversion and the second row keeps a dead
      name. Run the adopt check before the missing check.
    - The background upscaler can write an old picture over a newer
      download of the same name; compare mtime or inode in `still_wanted`.
    - `_atomic_save` leaves new images at 0600; `_save_image` swallows save
      errors, so failed saves count as done.
    - Deleting a game or a wishlist item leaves its media files.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-239] **Tests can never reach the live database, media or settings files (test, S).**
  - **Resolution** (2026-11-04): Shipped 2026-11-04 in b69b9111. Every listed gap closed; conftest also
    refuses to run if config resolves a live path outside the temp root.
  - **Status**: done
  - **Why**: audit 2026-11-04, lane 14. Confirmed in `tests/conftest.py`
    2026-11-04. A test once wiped a live library (memory
    test-media-isolation).
  - **Fix**:
    - Outside xdist, conftest keeps an inherited `RETRODB_DB_PATH` or
      `RETRODB_IMAGE_PATH`. Always make temp dirs under pytest, or refuse
      any path outside the temp root.
    - `RETRODB_STATIC_PATH` is set only when `RETRODB_IMAGE_PATH` is unset.
    - `settings_manager.SETTINGS_FILE` and `SCRAPER_SETTINGS_FILE` are not
      redirected; `admin_test_client` stubs load but not save.
    - `test_media_path_isolation` checks config equals the env var, not
      that it is a temp dir.
    - `scripts/ci_local.sh` import smoke isolates the DB only.
  - **Source**: audit 2026-11-04.
  - **Progress** (2026-11-10): The PASS-59-251 test review found one more gap. The player
    tests (`tests/test_player_cores.py:73`, `test_player_install.py:31`,
    `test_player_launch.py:36`) are kept away from the live player folder
    only by a `config.BASE_DIR` patch, and conftest does not pin that
    folder. The user decided it joins this isolation work as a tightening;
    it is tracked in PASS-59-289.

  ---
  Kind: implement.

- ✅ [PASS-59-240] **Sign-ins and keys stay out of logs, backups and shared emulator files (security, M).**
  - **Resolution** (2026-11-05): Shipped 2026-11-05 in 20401036. Fixed: redactor (cheevos cfg lines,
    JSON Token), saved job errors and PSN errors redacted, PSN status
    hides error from non-owners, player clears base-cfg sign-in and sweeps
    run layers, user delete/deactivate signs out of RA emulators, backups
    0600 and atomic, migration 038 removes .migrated-015 files. Checked
    and left: scraper check routes, RA sync and Gemini never send a
    credential URL to the browser.
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 1, 2, 3, 7, 9 and 15. Old scrape logs
    already held ScreenScraper sign-ins (memory redact-scrape-logs).
  - **Fix**:
    - Failure logs print full URLs with credentials:
      `metadata_merger.py` ScreenScraper media; `routes/scraper.py` check
      routes (`sspassword`, `devpassword`, TGDB `apikey`, Gemini `key=`);
      `jobs/ra_sync.py` RA key. Log the error type, or redact the URL.
    - Check where the `log_redactor` filter is attached; add `cheevos_token`
      and a JSON `"Token":` key.
    - `services/player.py`: `cheevos_*` keys can be saved into the base
      `retroarch.cfg` by RetroArch's Save Current Configuration; strip them
      before each launch. Sweep stale `data/player/run/*.cfg` at startup.
    - Deleting or deactivating a user leaves their RA token in DuckStation
      and PCSX2 files (`routes/auth.py`); call `ra_standalone.sign_out`.
    - DB backups are written at 0644 then chmod; write them 0600 and
      atomically (`services/database.py::backup_database`).
    - Migration 015 leaves `.migrated-015` token files.
    - Task logs with exception text are readable by any signed-in user.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-241] **Features that silently do nothing: HLTB auto-apply, RA Refresh hash match, per-user tags, PSN links (fix, M).**
  - **Resolution** (2026-11-05): Shipped in 597a2edb (2026-11-05).
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 5, 7, 10 and 12. First two confirmed
    in code 2026-11-04.
  - **Fix**:
    - `jobs/hltb_bulk.py` auto-apply UPDATE has 7 placeholders and 5 values;
      every auto-apply fails.
    - `jobs/ra_refresh.py` passes `game.get('folder')`; rows hold
      `system_folder`, so the hash match never runs.
    - Tags: `name` is still UNIQUE across users (001 baseline); a second
      user's same-named tag fails with a 500. Migrate to `(owner_id, name)`.
    - A full PSN sync's COALESCE replaces a link the user set by hand, and
      its substring match links "Doom" to "Doom Eternal".
    - PSN import never links an existing game by title, unlike Steam and
      Xbox.
    - `toast-controller.js` reads `wasActive` after `updateToasts` sets it,
      so job-end messages and the restart poll never fire.
    - Xbox: a refresh drops the gamertag and nothing fetches it again; any
      failed refresh, even a timeout, deletes the tokens.
    - Steam credentials fall back to the shared settings file for a user
      with none (`jobs/platform_sync.py`), so one person's library lands
      under another.
    - Non-admins can never refresh their RPCS3 trophies.
  - **Source**: audit 2026-11-04.
  - **Done** (2026-11-05): all nine fixed, each with a test run red
    first (tests/test_pass59_241_silent_failures.py; the HLTB and RA
    tests sit in test_pass59_209_hltb.py and test_pass59_210_ra_links.py).
    Tags: migration 039 rebuilds tags with UNIQUE(owner_id, name).
    PSN matching reuses the RA subtitle rule in place of the substring
    test. Xbox clears tokens only on HTTP 400/401. Steam: the shared key
    in Settings now serves admins only.
    - **Follow-up**: per-member Steam boxes in Profile are PASS-59-253,
    waiting on the user.

  ---
  Kind: implement.

- ✅ [PASS-59-242] **Scrapes and AI Fill keep what the user typed (audit-fix, M).**
  - **Resolution** (2026-11-05): Shipped in 97f77776 (2026-11-05).
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 3, 4, 8 and 10. Fill-only is a project
    contract (CLAUDE.md, `docs/decisions/`).
  - **Fix**:
    - `canonicalize_metadata` runs on stored values, so a stored genre, mode
      or perspective not in the lists becomes `''` and overwrites the column;
      players reconciliation rewrites a stored `players`.
    - A scrape writes back every field it read at its start, so an edit made
      during it is lost. Re-read the row before the save.
    - `ai_fill.py` compares raw text before normalizing, so an unchanged
      value (`4` vs `1-4`, reordered genres) is recorded as replaced by the
      AI.
    - AI Fill replaces hand-edited values in `VALIDATE_FIELDS`; the user
      decides whether it may.
    - The system-default controller replaces a typed `controller_support`.
    - The form edit route sets every field it was not sent to NULL.
    - Reset says all metadata is cleared but leaves eight fields and the
      caches.
    - CLZ import stores a year as `YYYY-01-01`.
    - A rating cross-mapped from an AI guess is not marked as a guess.
    - Clear Scraped Data leaves `perspective`, `dimension`, `game_structure`.
  - **Source**: audit 2026-11-04.
  - **Decided** (user, 2026-11-04): AI Fill leaves hand-edited values
    alone; it replaces only scraped values in `VALIDATE_FIELDS`.
  - **Done** (2026-11-05): all ten fixed, each with a test run red first
    (tests/test_pass59_242_user_edits.py). The scrape's save re-reads the
    row (`_what_to_write`): an unchanged field or one edited meanwhile is
    sent as None. `canonicalize_metadata(keep=...)` renames stored labels
    but never empties them. Hand edits are now credited for every
    `VALIDATE_FIELDS` field and `controller_support`, so AI Fill and the
    system-default controller leave them alone. A cross-mapped rating is
    a guess when all its possible sources are guesses.

  ---
  Kind: implement.

- ✅ [PASS-59-243] **Background jobs survive restarts, swaps and one bad game (audit-fix, M).**
  - **Resolution** (2026-11-05): Done 2026-11-05 in four commits by subject: 595e2ee8 (one bad game),
    63151f2c (bulk-scrape queue: displaced jobs saved, run token, writes
    outside the lock, resume claim), eeb37be7 (startup only in the serving
    process, migration version re-read, core downloads drained, wishlist
    stuck/duplicate scrapes), 6c099f0b (PSN sign-in outside the lock,
    keep-alive threshold 2 days). Tests: tests/test_pass59_243_jobs.py.
    Dismissed with reasons in the commit bodies: the service-limit stop
    message (shown since PASS-59-215) and loops after SIGTERM
    (request_shutdown cancels them). Queued: PASS-59-254 (one game's PSN
    sync pulls the whole list; needs a live account).
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 2, 7, 10 and 11.
  - **Fix**:
    - A demoted or swapped scrape, and a resume queued while one runs, are
      queued in memory only and lost on restart (`jobs/bulk_scrape.py`).
    - After the 60 s swap timeout `reset()` clears `cancelled`, so the old
      worker keeps going beside the new one. Use a run token.
    - Queue DB writes with retry backoff run under `self._lock`, blocking
      status polls.
    - `ss_region_repair` and `ai_fill_bulk` end the whole run on one game's
      error.
    - `player_cores_job` is not drained on shutdown and has no cancel.
    - A run stopped by a service limit ends as completed with no message.
    - Importing `app` from a second process marks the live server's jobs
      interrupted.
    - Resume has no guard against a double click.
    - Wishlist items stay on "scraping" after an error or a restart.
    - Migrations: `apply_pending` reads `user_version` before the lock.
    - PSN: sign-in runs inside `_psn_sync_lock`; keep-alive is per process
      and renews daily; one game's sync pulls the whole title list.
    - After SIGTERM the sync loops run with no delay.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-244] **Updates and game launches recover from a failure (audit-fix, S).**
  - **Resolution** (2026-11-05): Shipped in f331bf48 (2026-11-05). Tests: tests/test_pass59_244_recover.py.
    Dismissed with reasons in the commit body: the standalone version check
    (checksum plus /health after the swap, with rollback) and the scan-root
    check with rom_path unset (LAN-only threat model).
  - **Status**: done
  - **Why**: audit 2026-11-04, lane 15. Related: PASS-59-174 (rollback),
    PASS-59-168 (command port bound to 127.0.0.1).
  - **Fix**:
    - `updater_apply.apply` returns without restarting on an unknown plan
      version, a missing plan key, or a folder error before its `try`; the
      old app has already exited. Restart on every early exit.
    - The standalone build's version is never checked before the swap.
    - Two player launches at once both pass the one-session check.
    - No scan-root check on a ROM when `rom_path` is unset.
    - Cheats: `take_back` can pick up another game's `.cht` with the same
      file name; `place_for_launch` and `take_back` catch `OSError` only.
    - `standalone_settings.write_lines` leaves a temp file on failure,
      replaces a symlink, and sets 0600; `_read_lines` fails on non-UTF-8.
    - `cheats.py` writes `sources.json` in place.
    - `game-launch.js` core wait has no timeout and treats an error page as
      done; it uses `confirm()`, not `showConfirm`.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-245] **Keyboard focus is always easy to see, and every control works from the keyboard (accessibility, M).**
  - **Resolution** (2026-11-05): Done 2026-11-05. One global `:focus-visible` ring (core/reset.css,
    3px, `--primary-cyan-light`, `!important` so `outline: none` cannot hide
    it); focus glows moved to `color-mix` of the theme colour; card filter
    links and the running-games indicator are buttons; the popover closes on
    Esc (focus returns) or an outside click; the play screen keeps Tab;
    swatches carry aria-label and aria-pressed; trophy alts are full names.
    Checked in headless Chrome on a :5001 scratch copy at 1600px and 375px:
    the ring shows in the theme colour, Enter on a filter button refetches
    the filtered list, no sideways overflow, no console errors. The rest of
    the fixed cyan is PASS-59-255; themes.md §1 says so.
    Tests: tests/test_pass59_245_focus.py.
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 12 and 13. The user is partially
    sighted.
  - **Fix**:
    - No global `:focus-visible` rule; several controls show focus only as a
      1px border change, the same as hover; `launch-indicator.css` removes
      it.
    - Focus rings are a fixed cyan, so they ignore the theme.
    - Library card filter links are spans with no tabindex, role or key
      handler (`all-games-controller.js`); both Library and console pages.
    - The play screen has no focus trap; the running-games popover does not
      close on Escape or outside click.
    - Tag colour swatches lack `aria-label` and `aria-pressed`.
    - Trophy images use `alt="P"`, `"G"`, `"S"`, `"B"`.
    - `docs/specs/themes.md` says every component uses the colour tokens;
      many fixed colours remain. Move the visible ones to tokens and correct
      the claim.
    - Check each fix at desktop and 375px.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-246] **The last untranslated screen text, and right-to-left for Hebrew (i18n, M).**
  - **Resolution** (2026-11-05): Done 2026-11-05: 336a1f24 (queue panel escapes system_name),
    20340a30 (Python replies), b29b55f7 (library card and indicator JS),
    and the template commit (setup, tags, list, compare, ROM Tools settings,
    queue panel, game page). Every edited page renders under the
    pseudolocale (tests/test_pass59_246_i18n.py). Dismissed:
    services/formatters.py "Unknown" (module unused outside tests). Queued:
    PASS-59-256 (number and size formats). Right-to-left stays after
    v4.0.0 (user, 2026-11-04).
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 5, 11, 12 and 13. Related: PASS-52-1
    (JS toasts), PASS-59-179 (maintenance tools), PASS-43-4 (RTL + Arabic).
  - **Fix**:
    - `app.py`: recovery banner, job-route and setup errors, CSRF, 404/500
      envelopes; `formatters.py` "Unknown".
    - `all-games-controller.js` card labels and badge tooltips;
      `launch-indicator.js` fallback name.
    - `base.html` job-queue panel (also escape `system_name`); `setup.html`;
      `tags.html`; `list_detail.html`; `compare_games.html`;
      `rom_tools_settings.html`; two strings in `game_detail.html`.
    - Steam/Xbox "Game has no achievements" and platform-sync job errors.
    - Number and size formats ignore the language.
    - `base.html` sets no `dir="rtl"` though Hebrew ships; decide with
      PASS-43-4 whether RTL lands for v4.0.0.
    - Translate the new strings with `scripts/translate_release.py`.
  - **Source**: audit 2026-11-04.
  - **Decided** (user, 2026-11-04): right-to-left layout waits until after
    v4.0.0 (PASS-43-4). Hebrew ships marked as a preview whose layout is
    not yet right to left.
  - **Progress** (2026-11-05): the job-queue panel now escapes
    `system_name` (336a1f24). Survey of what is still unwrapped, by file:
    `app.py` (recovery banner per job type with progress and count
    placeholders, Resume/Start, job-route and setup `api_error` texts, CSRF,
    404/500 envelopes); `services/formatters.py` "Unknown"; Steam/Xbox
    "Game has no achievements"; `platform_sync.py` job errors;
    `all-games-controller.js` card labels, filter title, badge titles
    (bonus discs is a plural), "(cross-mapped)"; `launch-indicator.js`
    fallback name; `base.html` job-queue panel; `setup.html` (all but the
    MIT licence text); `tags.html`; `list_detail.html`;
    `compare_games.html`; `rom_tools_settings.html` (one line holds a
    link); `game_detail.html` hybrid-scrape title, HLTB "via {term}" note,
    `Screenshot {n}` alt.
    - **Traps**: `app.py` has no module-level `_` (functions import it);
    `platform_sync.py` errors are set in a job thread, so translate where
    the status is returned; new `t()` msgids reach the page through
    `services/js_i18n_strings.py` (`build_js.py`); plurals take `{count}`.

  ---
  Kind: implement.

- ✅ [PASS-59-247] **Scrapers follow the service rules and close what they open (audit-fix, S).**
  - **Resolution** (2026-11-05): Done 2026-11-05 in six commits: e8eeb89b (ssrf is_global and relative
    redirects, odd release years, IGDB int ids, cache key), c48f9497 (ES-DE
    ~ paths, copy size cap, unused bulk_import_esde removed), 4bb6cef3
    (listed region kept, not defaulted), ccaa7345 (decided: Settings check
    buttons do not wait for a turn, recorded in scrapers.md), 78052df8
    (gap-fill under circuit breakers), d0069c90 (ScreenScraper lookup stop
    rules, dropped replies closed), 215b542d (version suggestions keep
    rejected pairs apart). Tests: tests/test_pass59_247_scrapers.py.
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 1, 3, 4 and 9.
  - **Fix**:
    - Gap-fill calls TGDB, IGDB, RAWG and ScreenScraper outside their
      circuit breakers; only AI uses one (`hybrid_scraper.py`).
    - ScreenScraper `get_game_info` skips the quota and daily-stop rules.
    - ScreenScraper streamed replies are not closed on early exits.
    - The Settings check routes call services without `wait_for_turn`;
      decide whether checks are exempt and record it.
    - `ssrf.py` fails on a relative `Location` redirect; `_ip_is_public`
      should use `is_global`.
    - A region with no listed part becomes `default_region`.
    - `release_dates.year_gap_with_own_region` can raise and roll back the
      whole scrape.
    - ES-DE: `bulk_import_esde` has no caller and its data does not fit
      `apply_esde_metadata`; fix or remove. `~/` paths are not expanded;
      ES-DE media copies have no size cap.
    - Cache keys `"123:None"` vs `"123:"`.
    - IGDB ids go into query text without `int()`.
    - Version-group suggestions can join a rejected pair through a third.
  - **Source**: audit 2026-11-04.

  ---
  Kind: implement.

- ✅ [PASS-59-248] **Sign-in hardening and release-pipeline checks (security, S).**
  - **Resolution** (2026-11-05): Shipped 2026-11-05 in a627863e (sign-in: session stamp, avatar order,
    setup CSRF, non-text 400s, secret-key warning) and 98431808 (release
    test job, pinned tools, exact cosign identity, true Dependabot comment,
    pip cache). All nine findings and the CI tuning note fixed; none
    dismissed or queued.
  - **Status**: done
  - **Why**: audit 2026-11-04, lanes 1, 11 and 14. Threat model: LAN, one
    household (memory deployment-threat-model), so keep fixes small.
  - **Fix**:
    - A password change or admin reset leaves other sessions valid for 7
      days (`docs/specs/auth.md` §7 says otherwise). Add a session epoch.
    - The old avatar is deleted before the new upload is checked.
    - Setup API has no CSRF before setup completes.
    - Non-string inputs give unformatted 500s on auth routes.
    - `release.yml` runs no tests on a tag push; tool installs there and in
      `dependabot-lockfile.yml` are unpinned.
    - `release.yml` advises `--certificate-identity-regexp '.*'`.
    - `dependabot-lockfile.yml` claims the PR turns green on its own; a
      `GITHUB_TOKEN` push starts no run.
    - A secret key that cannot be written signs everyone out each restart,
      with nothing logged.
  - **Source**: audit 2026-11-04.
  - Found 2026-11-05 (CI tuning, ci-gate): `dependabot-lockfile.yml` has
    no dependency cache (local-gate.md § 9). Add `cache: pip` to its
    setup-python step while pinning its tool installs.

  ---
  Kind: implement.

- ✅ [PASS-59-249] **Smaller correctness and speed fixes from the audit (audit-fix, M).**
  - **Done** (2026-11-06, in the open 4.0.0): groups E (imports), G
    (images), H (database, restore), I (maintenance, scanning), J
    (collections, trophies, ROM tools) and K (`apply_esde_metadata`
    removed; obsolete `#~` catalog entries dropped, and
    `--ignore-obsolete` is now the documented update) closed, after A to
    D and F. Every finding's disposition is in
    docs/reviews/close-findings-2026-11-05-pass-59-249.md. Queued:
    PASS-59-262, PASS-59-263 (the audit's open questions), Xbox lows on
    PASS-59-261, DecompressionBomb on PASS-59-250.
  - **Status**: done
  - **Why**: audit 2026-11-04, all lanes; each low on its own. Already
    filed: PASS-59-160 ("Action" filter).
  - **Fix**:
    - Library card ETag ignores progress and launch changes.
    - BIOS rows in header counts, letter bar and `api_filter_games`; similar
      games lists own regional versions.
    - Letter bar and accented first letters disagree.
    - Select all stops at 10,000 silently; bulk edit splits a string id.
    - Bulk edit runs `_note_hand_edits` per game outside the transaction.
    - Analytics manufacturer map misses five ES-DE folders; use
      `SYSTEM_SPECS`.
    - "Recently scraped" misses re-scrapes.
    - Category logs duplicate `rom_tools` and `image_resize` lines.
    - Changelog and JSON reads in `app.py` have no `encoding=`; test on the
      Windows PC. The changelog YAML is parsed on every request.
    - Museum controller images go under `STATIC_PATH`, not `IMAGE_PATH`.
    - `HSA_OVERRIDE_GFX_VERSION=10.3.0` forced for every AMD card.
    - CLZ import: non-Latin titles all match; preview creates systems.
    - Bonus discs can loop; auto-link re-marks an unmarked disc.
    - GIFs are upscaled then discarded; the model download has no hash.
    - Restore removes `-wal`/`-shm` with connections open.
    - Other lows in the audit file, lanes 2, 5, 6, 8 to 11.
  - **Source**: audit 2026-11-04.
  - Found 2026-11-05 (PASS-59-246): `services/formatters.py` is imported
    only by `tests/test_formatters.py`; `app.py` has a comment saying the
    helpers moved there. Remove the module and its test, or wire it in.
  - Found 2026-11-05: the `.po` catalogs keep obsolete `#~` entries that
    repeat live msgids, so GNU `msgfmt --statistics` reports "duplicate
    message definition" (Babel's compile ignores them). Drop the obsolete
    entries (`pybabel update --ignore-obsolete`, or delete the `#~` blocks).
  - Found 2026-11-05 (PASS-59-247 removed the unused `bulk_import_esde`):
    `scrape_esde.apply_esde_metadata` now has no caller outside tests, yet
    CLAUDE.md and docs/specs/scrapers.md name it the canonical COALESCE
    pattern. Point both at `hybrid_scraper._save_game_row` and remove it,
    with its tests moved to `_save_game_row`.
  - **Progress** (2026-11-05): Closing by subject; the ledger is
    docs/reviews/close-findings-2026-11-05-pass-59-249.md, one row per
    finding with its disposition. Done: A (lists, Select all, bulk edit,
    HLTB, error pages), B (app core), C (logging), D (museum pictures, GPU
    override), F (bonus disc loops). Queued: PASS-59-262. Dismissed with
    reasons: formatters.py "unused", the letter bar, Select all's preferred
    versions, per-record settings load. Left: E (imports), G (images), H
    (database, restore), I (maintenance and scanning), J (collections,
    trophies), K (apply_esde_metadata, obsolete .po entries), and the
    audit's open questions listed in the ledger.

  ---
  Kind: implement.

- ✅ [PASS-59-250] **Docs and comments that say what the code does not (doc-fix, S).**
  - **Resolution** (2026-11-06): 2026-11-06: done. Specs auth, jobs, scrapers, image-pipeline,
    api-contracts, updater §6 and decision record 0003 now match the code;
    stale comments fixed; help contents link added in every locale.
    Image.open audit: only the Screenshot Review scan lacked the
    DecompressionBombError catch — fixed with a test. Code findings left
    over filed as PASS-59-264.
  - **Status**: done
  - **Why**: audit 2026-11-04, all lanes.
  - **Fix**:
    - `auth.md`: §7 session revocation (fixed by PASS-59-248 or reworded),
      §9 bucket clear and force-change, §13.1 bare POST routes, §6 token
      store also holds RetroAchievements.
    - `jobs.md`: lock directory, progress cadence, `current`/`total`.
    - `scrapers.md`: `ai_claude_api_key`; fill-only exceptions match
      CLAUDE.md; `apply_esde_metadata` named as canonical though unused.
    - `api-contracts.md` §3.2 vs museum, achievements, trophies routes that
      answer failures with HTTP 200, and exception text in messages.
    - `image-pipeline.md` §12.1, §15 rule 3.
    - Updater spec §6 lacks `/api/updates/dismiss`.
    - Code comments: CSP "report-only", migration 016 foreign keys, 012 log
      line, `game-launch.js` onclick, `game_utils` examples,
      `security.py` realpath, museum admin-only, `platform_tokens`.
    - `pyproject.toml` pip-compile; `release.yml` `/mnt/Storage`;
      `ci_local.sh` failure text suggests `--no-verify`.
    - `help.html` contents list lacks `#emulators-play`.
  - **Source**: audit 2026-11-04.
  - 2026-11-06, from PASS-59-249: done there, so skip here: scrapers.md
    no longer names `apply_esde_metadata` (removed); `image-pipeline.md`
    §12.1's worklist and disk precheck were rewritten (re-read §12.1 for
    anything else the audit meant). Added here: the audit's open question
    that `Image.DecompressionBombError` is not caught in code everywhere
    the spec says it is; check each `Image.open` site, not only the doc.

  ---
  Kind: implement.

- ✅ [PASS-59-251] **Finish the audit where it only searched, and update its partition (audit, M).**
  - **Resolution** (2026-11-10): Triage done. All 610 findings (code 32 High, 111 Medium;
    tests 16 High, 62 Medium; plus Lows and open questions) are queued:
    new passes PASS-59-274 to PASS-59-293, by subject, and notes added to
    PASS-59-221 (two slow tests), PASS-59-255 (fixed cyan), PASS-59-256
    (number formats) and PASS-59-239 (player-profile isolation, done in
    PASS-59-289). None was fixed or dismissed in the triage; each pass
    says to confirm its findings against current source first. The ledger
    (one row per finding, with the pass it went to) stays off the public
    repo, beside the reports.
  - **Status**: done
  - **Why**: audit 2026-11-04. Lanes 12, 13 and 14 searched patterns more
    than they read; lane 15 skipped `services/emulator_seeder.py`; lane 9
    skipped the `SYSTEM_DEFAULT_CONTROLLER` table; lane 4 skipped lookup
    tables.
  - **Do**:
    - Run cold lanes over the unread JavaScript files, the templates and
      CSS, `tests/`, `install*.py`, `.semgrep.yml`, `.gitleaks.toml` and
      `services/emulator_seeder.py`, split small enough to read in full.
    - Update `roadmap.md` § Periodic Independent Review: drop the four
      missing paths, add the launch/emulators/cheats/updater lane, and
      split the oversized JS and template lanes.
    - Triage the new findings into this audit's passes.
  - **Source**: audit 2026-11-04.
  - **Progress** (2026-11-09): 2026-11-09: lanes ran. review-code (20 lanes, JS, templates, CSS,
    installers, plus the Python files the 2026-11-04 sweep never opened or
    read in part) found 32 High, 111 Medium and about 258 Low/Info.
    review-tests (17 lanes over tests/) found 16 High, 62 Medium and 54
    Low. Reports are kept off the public repo, under
    /mnt/Emulators/.claude/Scratchpad/RetroDB/reviews/RetroDB/review-{code,tests}-2026-11-09/.
    The partition in § Periodic Independent Review is rewritten. Still
    owed: triage the findings into passes (close-findings).
  - **Progress** (2026-11-10): User decisions, 2026-11-10, for the triage: (1) raise --text-muted in
    the six failing themes and drop the "documented acceptable" note in
    docs/theme_contrast.md; (2) design standards §11 also promises
    keyboard use (WCAG 2.1.1) and named controls (4.1.2); (3) brand
    colours (Steam, Xbox, PSN, rating boards, system badges) become named
    tokens with a written exemption from "no hard-coded colours". Also
    decided in the session: the player-profile test gap joins the shipped
    PASS-59-239 isolation work as a tightening; the CSRF-masked auth tests
    get one pass with a shared fixture.

  ---
  Kind: implement.

- ✅ [PASS-59-253] **Each member can save their own Steam key and Steam ID in Profile (feature, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06. Profile has Steam key and Steam ID boxes; the ID must
    be the number, since the sync job does not look up profile names.
    Import errors now point to My Profile. The English help step changed;
    the translated help pages still say "in Settings".
  - **Status**: done
  - **Why**: PASS-59-241 stopped a member with no Steam key getting the
    admin's library. `user_settings` has `steam_api_key` and `steam_id`
    columns, but nothing writes them: Profile offers RA and PSN only. So a
    non-admin cannot sync Steam at all now.
  - **Fix**: add both to `routes/auth.py` `allowed_fields` and to the
    Profile page; the key masked like the others.
  - **Decided** (user, 2026-11-06): yes, add both boxes before v4.0.0.

  ---
  Kind: implement.

- ✅ [PASS-59-257] **A scrape credits only what it wrote, and the edit form credits only what was typed (review-fix, M).**
  - **Resolution** (2026-11-06): Done 2026-11-06 (7d454648). The reviewer's unconfirmed point held for
    AI Fill: it now re-reads the row before writing. The scrape's own
    read-then-write runs on one cursor milliseconds apart; left as is.
  - **Status**: done
  - **Why**: cold read of 97f77776 (PASS-59-242), 2026-11-05. The save
    check's high finding (own media clears) was fixed in ecd19a0a.
  - **Fix**:
    - A field the save check drops still gets a scrape_history entry
      (`_build_scrape_history_json` uses `filled_fields`), so the
      scraper overtakes a hand edit's `(manual)`. Credit only what was
      written.
    - The edit form sends `players` as `{{ game.players or 1 }}`
      (`_modals/edit_modal.html`), and `players` is in
      `HAND_EDITED_FIELDS`, so any save marks an empty Players as a
      typed 1. Ratings the form cross-maps get `(manual)` the same way.
      Credit only fields the person changed.
    - AI Fill's `other_platforms == 'exclusive'` branch
      (`services/ai_fill.py`) runs before the hand-edited check, so a
      hand-set Exclusive is replaced. Check hand edits first.
    - Reviewer's reading, not confirmed: `_what_to_write`'s SELECT and
      `_save_game_row`'s UPDATE are not one transaction; AI Fill builds
      from the row read before the AI call and writes plain `col = ?`.
  - **Source**: session_message 1394 from oneup.

  ---
  Kind: implement.

- ✅ [PASS-59-258] **Screen readers and keyboards: the running-games popover and the library cards (accessibility, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06 (079c6dca); walked in headless Chrome. Not checked:
    Shift+Enter on a filter button.
  - **Status**: done
  - **Why**: cold a11y read of 557461fa (PASS-59-245), 2026-11-05. Its
    high finding (hidden indicator a Tab stop) was fixed in 632da447.
  - **Fix**:
    - `aria-live="polite"` on the indicator button reads a bare "1" on
      each 5 s refresh. Drop it; write "1 game running" into a hidden
      `role="status"` span only when the count changes.
    - `aria-haspopup="true"` announces a menu; the popover is a plain
      div. Use `"dialog"` (or none) plus `aria-controls`, give the
      popover `role="dialog"` and a name, and move focus into it on open.
    - Kill closes the popover and drops focus to the page top; return
      focus to the indicator (or the next control if it hides).
    - Kill and Next disk buttons do not name the game; with two games
      a reader hears "Kill" twice.
    - A library card (`all-games-controller.js`, `.game-card-new`) opens
      only on click: no keyboard way to a game's details. Put a button
      or link in the title.
    - The filter buttons on a card are named by value only ("Capcom");
      name them "Filter by Developer: Capcom" in full.
    - Not checked: whether Shift+Enter on a filter button excludes.
  - **Source**: session_message 1403 from localwebservermanager.

  ---
  Kind: implement.

- ✅ [PASS-59-259] **Bulk scrape hand-off: no counts from the old worker, and the token read under the lock (review-fix, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06 (132dc2c6).
  - **Status**: done
  - **Why**: cold read of 63151f2c (PASS-59-243), 2026-11-05. Its
    reproduced finding (a second swap lost a job) was fixed in aa4e2c8b.
  - **Fix**:
    - After the swap's 60 s join gives up, the old worker's game in
      flight still adds to the new job's success, skipped or failed
      count and its recent list; only loop top and exit check
      `_replaced()`. Check it before those writes too. The demote
      warning still says "state mixing possible".
    - `_run_scrape` reads `self._run_token` inside the new thread, and
      `self._thread` is assigned outside the lock in `start()`,
      `resume_from_params`, `_start_next_queued` and the swap. Read the
      token and job fields under the lock and pass them to the thread.
    - `routes/collections.py` replies success to a refused second
      wishlist "scrape all" click (the job returns None).
  - **Source**: session_message 1382 from album-builder (F2, F3, and the
    eeb37be7 cosmetic note). Not done: migration 012's own commit lets a
    second process re-run it; dismissed, 012 is idempotent.

  ---
  Kind: implement.

- ✅ [PASS-59-260] **PSN sync can correct a wrong automatic game link (review-fix, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06: psn_games.link_set_by_hand (migration 041). Old links
    are checked again on the next sync (user, 2026-11-06). A read of the
    live library found 238 of 691 links the matcher no longer confirms, 94
    of them to a PS1 game named "D". Tag id reuse after 039: dismissed; a
    tag id is kept only in game_tags, which cascades.
  - **Status**: done
  - **Why**: cold read of 597a2edb (PASS-59-241), 2026-11-05. Its high
    finding (migration 039 stopping the app) was fixed in da22c8d7.
  - **Fix**:
    - `routes/trophies.py` keeps the stored `psn_games.linked_game_id`
      over a new match. Automatic and hand-set links are stored alike,
      so every wrong link the old substring match made ("Doom" to
      "Doom Eternal") is now frozen. Mark how a link was made, and let
      sync replace only an automatic one.
    - Unverified: migration 039's table rebuild resets the tags id
      counter, so a deleted tag's id can be reused. Matters only if a
      tag id is kept elsewhere (saved filters, URLs); check, then fix
      or dismiss.
  - **Source**: session_message 1388 from contact-list.

  ---
  Kind: implement.

- ✅ [PASS-59-264] **Failure replies at HTTP 200, and launch errors that show raw system text (audit-fix, S).**
  - **Resolution** (2026-11-09): 2026-11-09 part 2 done (26430cf0, 6c1148dc, 0d122bcf): every
    LaunchResolutionError message translated (resolver, player.py,
    CoreMissing), names and paths kept; spawn/kill failure logs the OS
    text and replies with a translated sentence naming the program;
    unknown launch token = translated 404; RA sign-in reason wrapped in a
    translated sentence; api-contracts.md §13 records the exception. Tests
    in tests/test_pass59_264_error_status.py.
  - **Status**: done
  - **Found by**: PASS-59-250, checking api-contracts.md §3.2 and
    decision record 0003 against the routes.
  - **HTTP 200 failures** (§3.2 now lists them): `routes/museum.py`
    `fetch_controller_image`, `upload_controller_image`,
    `remove_controller_bg`; `achievements.api_achievements_sync_cancel`
    on another user's job (should be 403); job start/pause/resume/cancel
    routes that `return jsonify(result)`. Check each browser caller
    before converting (record 0003). `/api/psn/status` stays 200.
  - **Raw text to the client**: `routes/launch.py::_launch_game` sends
    `str(LauncherError)`, which `services/launcher/local.py` builds from
    the OSError and the emulator path; `LaunchResolutionError` messages
    are English and carry config values; `api_ra_sign_in` passes
    RetroAchievements' own error text through untranslated.
  - **Dead line**: `routes/auth.py::api_login` clears
    `{ip}:login:{user_id}` on success, which no failure ever writes
    (auth.md §9). Remove it or count failures per user too.
  - **Progress** (2026-11-06): 2026-11-06 part 1 done: museum image routes answer
    400/404/409/422/500; job start/pause/cancel routes go through
    api_helpers.job_reply (refusal = 409); RA sync-cancel of another
    user's job = 403; six JS callers fixed (bulk-scrape.js start, main.js
    RA refresh, museum.js, toast-controller performCancel/cancelQueued,
    achievements.js); dead login-bucket clear removed (auth.md §9). Tests
    tests/test_pass59_264_error_status.py. LEFT: launch errors. User
    decided 2026-11-06: translate every LaunchResolutionError message and
    keep names/paths; a spawn or kill failure logs the OS text and shows a
    short translated message; RA sign-in wraps RA's reason in a translated
    sentence. WIP for services/launch_resolver.py saved at
    /mnt/Games/DevTools/cache/retrodb-p264-launch-wip.patch (git apply).
    Still to do: services/player.py raises, routes/launch.py
    spawn/kill/status, services/ra_sign_in.py,
    test_launch_resolver/test_launcher_local wording, catalog regen and
    translation of the new msgids.

  ---
  Kind: implement.

- ✅ [PASS-59-265] **Reset to defaults keeps setup done and the ROM path, so the sign-in-free setup pages stay shut (security, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06: reset_to_defaults keeps setup_completed and rom_path
    under the settings write lock; the reply no longer claims a restart.
    Locked by tests/test_settings_reset.py. No page calls this route; an
    admin's direct request could.
  - **Status**: done
  - **Why**: `settings_manager.reset_to_defaults` saves `DEFAULT_SETTINGS`
    (`setup_completed` False, `rom_path` empty). With `config.ROM_PATH`
    empty, as shipped, `/api/setup` and `/api/setup/browse-folders` answer
    without a sign-in until an admin redoes setup. Checked 2026-11-06.
  - **Fix**: keep `setup_completed` and `rom_path` through a reset; the
    reply's `restart_required` is also wrong (the redirect is at once).

  ---
  Kind: implement.

- ✅ [PASS-59-266] **One answer to which kind a system is, for the ROM naming check (fix, S).**
  - **Resolution** (2026-11-09): Shipped 2026-11-09: SYSTEM_TYPE_MAP moved to services/game_utils.py as
    the one table; get_system_type() reads systems.system_type first.
    Test: tests/test_pass59_266_system_type.py.
  - **Status**: done
  - **Why**: `game_utils.get_system_type` and `routes/systems.py`
    `SYSTEM_TYPE_MAP` disagree on many folders (3ds, vita, thomson, mac,
    zxnext, adam, virtualboy...). The naming report uses the first, so a
    computer such as `mac` is checked for a Region tag, and a type set on
    the Systems page is ignored.
  - **Fix**: one source, preferably `systems.type`.

  ---
  Kind: implement.

- ✅ [PASS-59-267] **The log viewer hides secrets in old log files too (security, S).**
  - **Resolution** (2026-11-06): Done 2026-11-06: log_manager.get_log_content and get_full_log_content
    run log_redactor.redact() on what they return; the download route
    sends that redacted text instead of the file. Locked by
    tests/test_pass59_267_log_redaction.py.
  - **Status**: done
  - **Why**: `routes/scrape_logs.py` content, view and download send the
    file as written; redaction happens only at write time, so a log from
    before a pattern was added (RA `y`/`z`, ScreenScraper `sspassword`)
    shows it in clear. Needs `system_functions`.
  - **Fix**: run `log_redactor.redact()` on what those routes send.

  ---
  Kind: implement.

- ✅ [PASS-59-268] **A RetroAchievements job asked for while another runs waits in a real server queue (ux, M).**
  - **Resolution** (2026-11-09): Shipped 2026-11-09 as a real server queue (user's choice, 2026-11-09):
    services/jobs/ra_queue.py, /api/ra-queue, ra_queue in both status
    replies; the localStorage queue is gone. Test:
    tests/test_pass59_268_ra_queue.py. Also fixed: the console page's
    Refresh RA button sent no system id.
  - **Status**: done
  - **Why**: RA sync and refresh routes reply `queued=True` and start
    nothing; the queue lives in this browser's localStorage and runs only
    while a page here polls. Other devices and users never see it.
  - **Fix**: queue on the server as bulk scrape does, or reword the
    reply and toast to say busy, retry.

  ---
  Kind: implement.

- ✅ [PASS-59-269] **Load the AI upscaler only while an upscale runs (perf, S).**
  - **Resolution** (2026-11-09): 2026-11-09 (48e75a67): services/upscale_worker.py runs Real-ESRGAN in
    `app.py --upscale-worker`, started on first upscale, exits after 120 s
    idle; crash → CPU-only helper → off until restart. Idle :5001 scratch
    server 1.39 GB RSS (onnxruntime + 9 ROCm libs mapped) before, 87–90 MB
    with none after; an upscale through the queue still worked on GPU.
    Helper log: logs/upscale_worker.log.
  - **Status**: done
  The live server held about 730 MB with onnxruntime and the ROCm
  (hip*) libraries mapped while idle (measured 2026-11-09). Import
  them only inside the upscale job, ideally in a child process that
  exits when the job ends. Check: RSS of an idle server before and
  after; an upscale still works.

  ---
  Kind: implement.

- ✅ [PASS-59-271] **4.0.0 is the last web version: say so everywhere, and its updater points to the desktop app (feature, M).**
  - **Decisions** (user, 2026-11-09): the web version stays available
    to download after 4.0.0; future versions are desktop and Android
    only (PASS-59-270). Said in the 4.0.0 changelog, the README, Help
    and Settings > Updates, and on the website. Until the desktop app
    does everything, 4.0.x gets security and data-loss fixes only.
  - **Updater**: 4.0.0 reads GitHub's release list. A 4.0.x release is a
    web update and installs as before; 4.1.0 and up is the desktop app:
    a message and a download link, never an install. The desktop app
    ships in pieces as 4.x.0, then 5.0.0 (user, 2026-11-09); web fixes
    stay 4.0.x.
  - **Shipped** (2026-11-09): updater reads the release list
    (services/updater.py `_newest_by_line`, `WEB_LAST_LINE`); Settings >
    Updates, dashboard banner, Help, README and the 4.0.0 notes say it, in
    every language. Website asked to say it at the 4.0.0 release.
  - **Status**: done.

  ---
  Kind: implement.

- ✅ [PASS-59-273] **Museum background removal runs in a helper that closes when idle, like the upscaler (perf, M).**
  - **Asked** (user, 2026-11-09): load heavy items into memory only when
    needed, and clear them out when not in use.
  - **Measured** (2026-11-09, standalone script, CPU path): rembg's
    `birefnet-general` model (973 MB file) takes a process from 237 MB to
    2.1 GB when loaded and to about 9 GB during one 512 px removal;
    dropping the session leaves 900 MB. `routes/museum.py` keeps it in the
    server for good (`_rembg_session`). The GPU path failed on this machine
    with MIOPEN error 7, so the code's CPU fallback is the one that runs.
  - **Do**: run it in its own helper process, on `services/upscale_worker.py`'s
    machinery (start on first use, exit after `IDLE_SECONDS`), never in the
    same process as the upscaler.
  - **Checked, fine**: idle server 89 MB, 172 MB after every main page;
    the upscaler already runs in a helper (PASS-59-269); the other in-memory
    caches are capped.
  - **Resolution** (2026-11-09): **Resolution** (2026-11-09): built in the open 4.0.0 (commit
    4d01977a). `services/rembg_worker.py` runs rembg in `app.py
    --rembg-worker` on the upscale helper's machinery; `routes/museum.py`
    never imports rembg. Real-model run: calling process 37 MB, helper
    peak 2.5 GB (GPU worked in the helper), helper exited after 121 s
    idle. Tests: `tests/test_rembg_worker.py`. Not walked: the Museum page
    in a browser.
  - **Status**: done.

  ---
  Kind: implement.

- ✅ [PASS-59-274] **Keyboard: confirm dialogs, focus traps, and controls only a mouse can use (accessibility, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Do first**: write the promise into `docs/RETRODB_DESIGN_STANDARDS.md` §11: every control works from the keyboard (WCAG 2.1.1) and has a name and role (4.1.2). User decision 2026-11-10.
  - **Then**: fix the findings, and walk each named page with the keyboard alone.
  - **Follows**: PASS-59-245 and PASS-59-258 (shipped).
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `static/css/components/forms.css:134-138,175-177`: Toggle switches show no visible focus: the ring lands on a hidden zero-size input and the slider only…
  - H `static/css/pages/game-list.css:1366-1369`: Game-card open button's focus ring is drawn outside and clipped by the overflow-hidden title, so library…
  - H `static/js/log-viewer.js:449`: Log session headers are unfocusable divs and bodies are hidden, so keyboard users cannot open any…
  - H `templates/achievements_system.html:218-219…`: Game cards are unfocusable divs, so keyboard users cannot open any game's achievements on three pages.
  - H `templates/base.html:488-492`: A document-wide Enter handler confirms the modal even when focus is on × or Cancel, so keyboard users…
  - H `templates/compare_games.html:607`: Compare search results are plain divs that cannot take focus, so the compare page is unusable from the…
  - H `templates/game_detail.html:3185-3187,5370`: Scrape-source checkbox is display:none, so keyboard users cannot select secondary scrape sources at all.
  - H `templates/game_imports.html:194-199`: CLZ file input is display:none behind a label, so the tab's only action cannot be reached by keyboard.
  - H `templates/login.html:212`: Login profile picker items are divs with no tabindex/role/key handler, so a keyboard-only user cannot…
  - H `templates/tags.html:149-155,413`: Tag Edit/Delete buttons are invisible (opacity 0) unless hovered, focus ring included; the tag card…
  - M `static/js/bulk-scrape.js:407-411,392,365`: Reopening the bulk-scrape modal from a toast activates no focus trap; closing it then pops whatever trap…
  - M `static/js/main.js:1450,1712-1715`: Pressing ? with the shortcuts dialog open stacks a second focus trap; after Escape, Tab is dead…
  - M `templates/base.html:512-515`: The confirm callback runs before the modal hides, so a follow-up showModal/alert is hidden at once and…
  - M `templates/psn_trophies.html:1689`: On network error the bulk modal hides without deactivating its focus trap, so every Tab press is blocked…

  ---
  Shipped 2026-11-10 (commits 2e468d39, dc840b13, cec59029, 466f7710; in
  the open 4.0.0 entry). Confirmed against source first: 12 of 14 held;
  H1 partly (a faint ring existed, but on a zero-size input); H2 already
  fixed in 079c6dca. §11 "Keyboard" written. Dialog fixes proven
  red/green in headless Chrome. Mouse-only controls converted on every
  page with the pattern, including sites the review missed. Left:
  dashboard row (title link exists), museum.html grid zoom (inside the
  card link), archive scanner path cell (View button). New aria-label
  strings are untranslated in the catalogs. Not run in a browser: M1
  (needs a live bulk scrape), M4 (needs PSN sign-in).
  Kind: implement.

- ✅ [PASS-59-276] **Escape every value put into page HTML, and close the data-on-* gadget (security, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Do**: run each named value through the shared escape helper; limit `data-on-*` in `static/js/main.js` to an allowlist of handlers.
  - **Threat model**: LAN, one household (docs/decisions). Scraped data and file names are still outside input.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `templates/game_detail.html:4112,4303,4383,4635,4719,4803,4931`: Seven edit-modal tag renderers put scraped DB values into innerHTML unescaped; injected data-on-* can…
  - H `templates/multi_disc_organizer.html:323,329,330`: File names and system go into innerHTML unescaped, so a crafted ROM name injects attributes that call…
  - M `static/js/main.js:288-303`: data-on-* calls any function reachable from window with JSON args, so any HTML injection can fire…
  - M `static/js/toast-controller.js:1546`: return_url check passes /\evil.example and /<TAB>/evil.example, so one user's toast can send others to…
  - M `templates/game_detail.html:5561`: Filter-modal boxart URL is neither encoded nor escaped; a quote breaks out of src and opens the…
  - M `templates/game_detail.html:5751,5755,5759,5672,5741`: HLTB values from howlongtobeat.com go into innerHTML unescaped.
  - M `templates/reports.html:788,961,1079`: item.system (disk folder name) goes into innerHTML unescaped in the system select and badges.
  - M `templates/rom_tools_settings.html:461,500`: Saved unwanted-pattern and excluded-path strings go into innerHTML unescaped, unlike the archive…
  - M `templates/settings.html:2554-2557,2482,2492,2530,2564,2604,2694,2620`: checkRateLimits puts ScreenScraper response fields and error text into innerHTML unescaped.
  - M `templates/settings.html:2888`: Admin-entered dropdown-option values go into innerHTML unescaped.
  - M `templates/settings.html:4343-4346,4339,3755,3582`: Logo-reference table, system select text and manufacturer options interpolate DB/disk names into HTML…
  - M `templates/systems.html:719,728,752,770`: System type, spec values and folder name go into innerHTML unescaped, unlike line 816 in the same file.
  - Low: static/js/global-search.js:96; templates/base.html:367-370; templates/game_detail.html:5140; static/js/all-games-controller.js:594,607,666,679…; static/js/museum.js:311; templates/wishlist.html:615,640-642; templates/settings.html:2056; templates/settings.html:2036,3715,3763,3822,3898,4132,4868-4…; templates/archive_scanner.html:1279-1281; templates/psn_trophies.html:1230; templates/psn_trophies.html:1378; templates/reports.html:963,1084,1156,1160
  - Open questions (answer first): static/js/game-list.js:41; templates/settings.html:2888

  ---
  Shipped 2026-11-10 (12d102cf, 186f8686, 41db8f0e, f440c94e, baa19aba,
  f166faf6). data-on-* runs only names the app writes
  (services/action_names.py via base.html); every listed sink escaped or
  encoded; return-URL guard parses every value. Open questions answered:
  dropdown editor is admin-only to write; fanart names are app-made.
  Kind: implement.

- ✅ [PASS-59-277] **Job progress: stuck pollers, repeated "completed" toasts, and failures nobody is told about (review-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Needs a decision**: the Queue Manager in `templates/base.html` has no way to open it (H, `jobs.md` §9). Wire it to the queued toast, or delete it and correct §9. Ask the user.
  - **Follows**: PASS-59-243 (shipped).
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `static/js/rom-tools.js:163-171; templates/chd_verify.html:324…`: cancel() stops the poller before onCancel runs, so CHD pages stay with Start disabled; cancel errors…
  - H `static/js/rom-tools.js:94-109`: TaskPoller stops only on completed/error/cancelled; workers set 'failed', so a crashed CHD job polls…
  - H `static/js/toast-controller.js:225-230,790-801`: Completion keys age by job start time, so an hour after a job starts every page load deletes the key and…
  - H `templates/base.html:796`: openQueueManager has no caller, so the Queue Manager (promote/demote/swap) promised in jobs.md §9 cannot…
  - M `static/js/apply-progress.js:131-138`: One failed poll closes the gauge with 'Could not apply metadata' while the apply succeeds; no deadline…
  - M `static/js/bulk-scrape.js:319-321,347-349`: Pause and Cancel failures on a running bulk scrape are only logged; the user gets no sign it was refused.
  - M `static/js/rom-tools.js:110-116`: One failed poll stops polling for good and reports an error while the server task keeps running; scanner…
  - M `static/js/rom-tools.js:79-86; templates/archive_scanner.html:1215`: 'Task not found' branch can never run (API.get throws on 404, message is translated), so the…
  - M `static/js/toast-controller.js:1266-1270`: The completion key is shared across tabs, so other tabs return early and their toast stays on 'Complete'…
  - M `static/js/toast-controller.js:1323,1361`: Bulk queued toasts lack a .queue-position span, so after a reorder they show a stale 'Queued (#N)' and…
  - M `static/js/toast-controller.js:1469-1471,1411-1413,1503-1505…`: Failed cancel/pause/cancel-queued requests are only logged; the toast stays and the user is told nothing.
  - M `templates/achievements_system.html:345-543…`: achievements.js is never loaded; it got the i18n/format/refusal fixes while the live page copy of sync…
  - M `templates/achievements_system.html:404-408,620`: After a sync starts the button stays disabled showing 'Syncing...' until reload; nothing resets it on…
  - M `templates/dashboard.html:1168-1177,1213-1222`: dismissJob is silent on failure and dismissAll removes the banner without waiting, so jobs reappear…
  - M `templates/dashboard.html:1189-1209`: Resume All reports success even when all fail, animates out failed items, and leaves the banner stuck…
  - M `templates/psn_trophies.html:1574,1587-1608`: After a server restart status returns phase 'idle', which is unhandled, so the sync modal polls forever…
  - M `templates/screenshot_dedup.html:439`: Cancel fetch is not awaited or checked; an editor gets a silent 403 while the log says 'Cancelling…
  - Low: static/js/toast-controller.js:856-858; templates/base.html:834; static/js/toast-controller.js:225; static/js/bulk-edit.js:283…; static/js/mame-names.js:42-44; static/js/museum.js:150-152; static/js/museum.js:130; templates/steam_achievements.html:188-202…; templates/achievements_system.html:624; templates/dashboard.html:1352
  - Open questions (answer first): static/js/main.js:1196; routes/trophies.py:1064; templates/psn_trophies.html

  ---
  Shipped 2026-11-10 (59c92a02). User chose to connect the Queue
  Manager: queued scrape toasts get a Reorder button (jobs.md §9
  updated). Pollers handle failed/404/idle, completion keys age by write
  time, failures shown. Q answered: the client owns the PSN idle case.
  Kind: implement.

- ✅ [PASS-59-283] **Game, Library, Collections and Museum pages: bugs found by the review (audit-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `templates/game_detail.html:5722-5727`: The game page's HLTB save omits hltb_id and players, so every save NULLs them and the HLTB link and…
  - M `static/js/ai-fill-bulk.js:56,135`: Stale-response guard checks only the system, so an old count can appear in the paid 'Fill {count} games…
  - M `static/js/all-games-controller.js:1187`: Filter tags show the system's numeric id on /games, and raw untranslated system_type/source/rating…
  - M `static/js/game-box-faces.js:21-29,47,77`: fetch has no try, so a network/server failure on upload or remove ends in an unhandled rejection with no…
  - M `static/js/game-modals.js:919,1253`: Quick-edit stores HLTB confidence on a 0-100 scale then multiplies by 100 again, so every saved match…
  - M `static/js/museum.js:231-245,309-312`: A failed Search/Upload on an imaged controller card adds a placeholder beside the existing image; Search…
  - M `static/js/museum.js:345-350`: The background-removal confirm's Cancel and Escape both upload the file, so the user cannot abort the…
  - M `templates/list_detail.html:99-100`: data-key='Enter' applies to every event on the input, so debounceGameSearch on input never runs…
  - M `templates/lists.html:310-321; templates/tags.html:386-397…`: If the lists/tags/wishlist load fails, the page is blank with no message (error only logged, no !success…
  - M `templates/lists.html:419-461; templates/tags.html:483-521…`: Only wishlist disables Save during the request; in Lists a double click creates two lists.
  - Low: static/js/game-modals.js:1166; static/js/box-viewer.js:316,323; static/js/game-emulator-settings.js:107…; templates/filter_modal.html…; templates/game_detail.html:5322; templates/game_detail.html:5787-5789,5801; templates/game_detail.html:5779,5712; templates/game_detail.html:5969; templates/game_detail.html:6034-6035; templates/game_detail.html:4052; templates/game_detail.html:5436,5440,5458,5555; static/js/all-games-controller.js:1308-1309…; static/js/all-games-controller.js:822,1053; templates/compare_games.html:581,596; templates/list_detail.html:487-491,75; static/js/museum.js:296-297,302-303; templates/list_detail.html:384
  - Open questions (answer first): static/js/manual-reader.js:45; static/js/game-modals.js:1089; routes/collections.py:169,418,631

  ---
  Shipped 2026-11-10 (c23c2ff6). HLTB save keeps hltb_id and players;
  data-key applies to key events only. Qs: sort title follows the server
  rule (pronoun I kept); collections stay login_required (owner-scoped);
  duplicate filterModal ids never share a page; manual-reader CSP not
  re-tested.
  Kind: implement.

- ✅ [PASS-59-284] **Settings, sign-in and dashboard: bugs found by the review (audit-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `static/js/emulators-settings.js:307,372; routes/launch_settings.py:135`: Emulator folders are joined/split on ':', so every Windows path is refused and the feature is unusable…
  - H `templates/_settings_tabs/account.html:257`: Change Password block is admin-only, so editors, players and viewers can never change their own password.
  - H `templates/_settings_tabs/data.html:160-161`: Toggle label's for= points at the select-all checkbox, so clicking it selects all rows and the filter…
  - H `templates/dashboard.html:1279; routes/scraper.py:297-298`: Scraper check endpoint is admin-only, so editors and viewers see a false 'N configured APIs are offline'…
  - M `static/js/emulators-settings.js:234`: Save failure uses browser alert(), which the design standards forbid; a nearby comment wrongly says no…
  - M `static/js/settings-page.js:265; templates/settings.html:2102-2162`: showConfirm is overridden by a page-local copy with English buttons, lost line breaks, dropped onCancel…
  - M `static/js/theme.js:224-227,141`: If the theme save POST fails, only the console hears; the server copy wins on next load, so the old…
  - M `templates/_settings_tabs/account.html:110,196,241…`: Stored API keys and tokens are rendered as value= attributes (mostly type=text), exposing them in page…
  - M `templates/_settings_tabs/account.html:315,423…`: UI copy and login comment say only admins need a password, contradicting auth.md (every role has one).
  - Low: static/js/global-search.js:16; static/js/global-search.js:144-147; static/js/updates.js:191; static/js/launch-indicator.js:63-66,53; templates/settings.html:2308-2315; templates/settings.html:1192,1214,1319-1342,5242,5266,5147; templates/settings.html:1044,1095,1105; templates/settings.html:2060-2063; templates/settings.html:1021,3130-3165,1018,4379-4410; templates/setup.html:570,498; templates/setup.html:520; templates/login.html:307…; static/js/emulators-settings.js:431-437; templates/_settings_tabs/data.html:54; templates/settings_emulators.html:136-138,161-164; templates/_settings_tabs/library.html:242,5-10; templates/systems.html:843
  - Open questions (answer first): templates/base.html:1421-1436; templates/_macros/sticky_subnav.html; templates/settings.html:1132-1138; templates/setup.html:359; templates/_settings_tabs/account.html:420-423; templates/dashboard.html:248

  ---
  Shipped 2026-11-10 (3c26b8ed). Qs: setup browse refuses after setup;
  subnav pages both define scrollToSection; per-user RA/Steam settings
  win over the global fallback by design; autocomplete stays off except
  on fields naming a purpose. Stored keys: password inputs only; full
  fix filed as PASS-59-295.
  Kind: implement.

- ✅ [PASS-59-285] **ROM tools and maintenance pages: bugs found by the review (audit-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `static/js/log-viewer.js:53; log_manager.py:176`: Log line regex expects 4 fields but files have 5, so Source filter and module column show request IDs…
  - H `templates/chd_verify.html:295-299,236`: Verify results are matched to rows by index, so after unticked or rejected files Valid/Invalid badges…
  - H `templates/game_imports.html:784,811-819`: Header select-all ticks rows hidden by the platform filter, and Import sends them, silently importing…
  - M `static/js/log-viewer.js:116-127`: If the log file list fails to load, the File select stays on 'Loading...' and the user is told nothing.
  - M `templates/archive_scanner.html:1395-1396`: closeArchiveModal nulls currentArchivePath before viewArchive uses it, throwing a TypeError so the modal…
  - M `templates/archive_scanner.html:814`: rom_path is put into a JS string HTML-escaped; Windows paths like D:\xbox cause a SyntaxError that kills…
  - M `templates/game_imports.html:696,877`: If the Xbox/PSN status check fails, status stays 'Checking...' with Fetch disabled and no explanation.
  - M `templates/game_imports.html:974-975,244`: Steam ID is pre-filled from install-wide settings and preferred by the server, reviving the…
  - M `templates/rom_tools_settings.html:588,300,591`: Reset writes a hardcoded Linux path /mnt/Games/ROMS and copies the pattern default by hand, wrong on…
  - Low: templates/archive_scanner.html:878-886…; templates/multi_disc_organizer.html:410; static/js/rom-tools.js:269-320…; templates/screenshot_dedup.html:447; templates/screenshot_review.html:202; static/js/log-viewer.js:502; static/js/log-viewer.js:11,373; templates/game_imports.html:776-777; templates/hltb_review.html:237; templates/duplicate_finder.html:189-196; templates/duplicate_finder.html:317-332; templates/game_imports.html:621
  - Open questions (answer first): log_manager.get_full_log_content; templates/game_imports.html (applyPlatformVisibility)

  ---
  Shipped 2026-11-10 (186f8686..f1fa214d, f166faf6). Reset uses
  rom_tools_defaults(). PSN 'Not Configured' text on Game Imports still
  names the wrong tab: PASS-59-296.
  Kind: implement.

- ✅ [PASS-59-286] **Achievements, trophies, reports and analytics: bugs found by the review (audit-fix, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `templates/local_trophies.html:397`: AlphabetNav.init runs inline before the deferred games bundle loads, so the A-Z bar renders but no…
  - H `templates/psn_trophies.html:1335-1337`: Select-mode click handler attaches only to existing cards; later-loaded cards navigate away and lose the…
  - H `templates/steam_achievement_game.html:224`: unlock_time is an integer epoch but the tz filter only handles datetime/str, so Steam unlocks show a raw…
  - M `templates/analytics.html:1553-2530`: Chart.js canvas animations ignore prefers-reduced-motion; the CSS rule does not reach them.
  - M `templates/analytics.html:2761,2771,2773`: On plain-HTTP LAN navigator.clipboard is undefined and throws before the fallback; fallback reports…
  - M `templates/local_trophy_detail.html:356-365,432`: HLTB save/clear never checks the response, so a refused (403) save or clear is shown as done.
  - M `templates/psn_trophies.html:1141-1143`: A failed games fetch is only logged: empty grid with no message, and infinite scroll stops silently.
  - M `templates/psn_trophies.html:922-951,1153-1154`: Saved letter filter is restored without marking its button, silently limiting the grid to one letter on…
  - M `templates/reports.html:1309,606-617,1186; routes/reports.py:691-745`: Batch rename uses suggestions from an unexpiring cached scan and the server never checks the current…
  - M `templates/reports.html:739,755,769-770`: A {success:false} scan reply raises no warning and old results are saved with a fresh 'just now'…
  - Low: templates/steam_achievements.html:25…; templates/psn_trophy_detail.html:299-325; templates/analytics.html:2798; templates/analytics.html:2784; templates/analytics.html:2807; templates/reports.html:1461-1466,1322-1327,1345-1346,1484-14…; templates/reports.html:1261,1276; templates/analytics.html:2734-2737,2809-2813; templates/reports.html:610
  - Open questions (answer first): templates/reports.html (rename buttons)

  ---
  Shipped 2026-11-10 (41db8f0e..f40b7ece). Q answered: rename buttons
  now editor/admin only.
  Kind: implement.

- ✅ [PASS-59-288] **Tests: sign-in refusal tests must reach the sign-in check, not stop at the CSRF check (test, S).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **User decision 2026-11-10**: one pass with a shared fixture that seeds a CSRF token and completes setup, then asserts the sign-in layer's own reply.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `tests/test_auth_hardening.py:432`: Anonymous POSTs to destructive endpoints are refused by the CSRF 403, so the test stays green if…
  - H `tests/test_pass40_1_8_security.py:532`: Accepts 302, which the first-run setup gate returns before safe_path runs; also depends on user 1's role…
  - H `tests/test_retroarch_detect.py:137`: Anonymous POST has no CSRF header, so validate_csrf's 403 answers first; removing the login/admin guard…
  - H `tests/test_routes_smoke.py:180`: 19 anonymous POST cases get the CSRF 403 before auth runs (also :208, routes_launch:35…
  - M `tests/test_pass41_security.py:1081`: Anonymous-rejection test accepts 302, which the setup gate returns with no setup_complete fixture…
  - Low: tests/test_routes_launch.py:138
  - Open questions (answer first): tests/test_auth_hardening.py:432; tests/test_auth_hardening.py:428; tests/test_emulator_autodetect.py:92; tests/test_pass41_security.py:1081; tests/test_retroarch_detect.py:137; tests/test_emulator_registry_routes.py:44; tests/test_routes_smoke.py:180

  ---
  Shipped 2026-11-10 (4d7db867): conftest anon_client +
  assert_sign_in_refused; 28 anonymous request tests moved onto them and
  proved red against a guard-stripping plugin. The m3u path test signs
  in as admin and asserts 400; the viewer launch/shutdown refusals check
  their own message. Source-text "requires_admin" tests are left to
  PASS-59-292.
  Kind: implement.

- ✅ [PASS-59-290] **Tests that cannot fail: stubs on names the code never reads, and asserts that never run (test, M).**
  - **Status**: todo
  - **Source**: PASS-59-251 review 2026-11-09.
  - **Do**: for each, prove it red against a broken copy of the code before calling it fixed.
  - **Before fixing**: confirm each claim, and its fix, against current source. Full text: off-repo `triage-2026-11-10/ledger.json` beside the review reports.
  - **Findings**:
  - H `tests/test_bulk_scrape_race.py:98`: Both swap/demote ordering tests (also :149) would pass on the old cancel-sleep-reset code they exist to…
  - H `tests/test_etag_and_gzip.py:120`: test_request_parity skips on every run (setup gate 503), so its ETag/304 assertions never run.
  - H `tests/test_input_hardening_scrapers.py:63`: example.invalid fails the SSRF DNS gate first, so the patched get and the 100 MB cap are never reached…
  - H `tests/test_pass40_1_8_security.py:392`: Fake chdman never makes the .part file, so conversion fails and nothing is ever deleted; the decoy check…
  - H `tests/test_pass46_frozen_paths.py:39`: conftest always sets RETRODB_*_PATH, so the if-guards at :39/:45/:53 never run and three tests assert…
  - H `tests/test_pass59_247_scrapers.py:43`: hybrid_scraper has no http_post, so that case patches nothing; sent == [] always holds, and a regression…
  - H `tests/test_pass59_packaging.py:441`: Stale-tag guard test never runs release-standalone.sh; it only checks git resolves an old tag elsewhere…
  - H `tests/test_pass59_scrapers.py:146`: Stub on base_scraper.validate_and_pin_url is never read (imported from services.ssrf in-function); real…
  - M `tests/test_launch_resolver.py:62`: raising=False patch on _RETROARCH_OVERRIDES (also :421, :475) is the only isolation; a rename makes…
  - Low: tests/test_auth_hardening.py:63; tests/test_etag_and_gzip.py:60; tests/test_game_logo.py:48; tests/test_log_redactor.py:228; tests/test_media_path_isolation.py:111; tests/test_pass32_hardening.py:237; tests/test_pass32_hardening.py:193; tests/test_pass38_ra_check_helper.py:96; tests/test_pass41_security.py:1275; tests/test_pass41_security.py:599; tests/test_pass45_security.py:2236; tests/test_pass59_215_service_limits.py:164; tests/test_translate_release.py:247
  - Open questions (answer first): tests/test_ai_fill_bulk.py:183; tests/test_bulk_scrape_race.py:98; tests/test_ci_gate_parity.py:14; tests/test_etag_and_gzip.py:120; tests/test_input_hardening_scrapers.py:63; tests/test_launch_resolver.py:62; tests/test_mame_names.py:229; tests/test_pass40_1_8_security.py:392; tests/test_pass46_frozen_paths.py:39; tests/test_pass59_237_disc_files.py:64; tests/test_pass59_237_disc_files.py:64; tests/test_pass59_216_extra_data.py:235; tests/test_pass59_245_focus.py:22; tests/test_pass59_auth_api.py:125; tests/test_pass59_scrapers.py:146; tests/test_pass59_scrapers.py:146; tests/test_rembg_worker.py:97

  ---
  Shipped 2026-11-10 (f16e3765). All nine tests confirmed and each
  proven red against broken code.
  Kind: implement.

- ✅ [PASS-59-294] **The Logs page lists files it then refuses to open (fix, S).**
  - Seen: on a fresh browser the Logs page loaded its first listed file
    and got 403 "Invalid log file". /api/logs/content accepts only names
    starting with VALID_PREFIXES (routes/scrape_logs.py); logs/ also holds
    upscale_worker.log, which has none of them. Which file was first in
    the list is not confirmed.
  - Fix: make /api/logs/files list only what /api/logs/content serves, or
    serve the extra files. Confirm against source first.
  Shipped 2026-11-10 (e59b72ff): /api/logs/files lists only names
  VALID_PREFIXES accepts. The first file was upscale_worker.log (reverse
  name sort). Test: tests/test_pass59_294_log_list.py.
  **Layman:** Opening the Logs page can show "Invalid log file" straight away, because it offers a file the server will not show.
  Kind: fix.
  Source: PASS-59-274 browser walk 2026-11-10.

- ✅ [PASS-59-295] **Stop sending stored API keys and tokens to the Settings page.**
  - **Status**: todo
  - **Why**: account.html and scraping.html render each stored key as an input value (now type=password, autocomplete off), so it sits in page source.
  - **Do**: render a set/not-set marker; send a key only when the field changes; the save routes keep the stored key when the field is left blank. Every save path must agree, or a save blanks keys.
  - **Threat model**: LAN, one household (docs/decisions); low priority.
  Shipped 2026-11-10 (746fe0ba). The Scraping tab was already masked
  (Pass 26.5); My Profile's RA key, NPSSO and Steam key now are too
  (USER_SECRET_FIELDS, routes/auth.py), in the page and GET
  /api/users/settings. A mask echoed on save keeps the key; PSN Save &
  Test with the mask tests the stored token. Test:
  tests/test_pass59_295_user_key_masks.py.
  **Layman:** Settings shows your saved keys as dots now, but the page still carries them; this would send only 'set' or 'not set' instead.
  Kind: security.
  Source: PASS-59-284 2026-11-10.

- ✅ [PASS-59-296] **Game Imports' PSN "Not Configured" message names the wrong place.**
  - **Status**: todo
  - **Where**: templates/game_imports.html, the PSN 'Not Configured' text, set through innerHTML in English.
  - **Do**: point it at Settings > My Profile (the NPSSO wizard) and translate it.
  - **Source**: reported by the PASS-59-285 helper.
  Shipped 2026-11-10 (8b5b139d): info box and status point at Settings >
  My Profile (#profile); status text through _()|tojson and t().
  **Layman:** The PSN import tells you to go to Settings, API Keys, but the PSN sign-in is under My Profile.
  Kind: fix.
  Source: PASS-59-284 2026-11-10.

- ✅ [PASS-59-297] **Viewer pages ask for admin-only data and log 403s.**
  - **Status**: todo
  - **Seen**: headless walk as a viewer on :5001, 2026-11-10.
  - **Every page**: toast-controller.js polls /api/ai-fill-bulk/status (editor-only) for every role.
  - **Settings**: /api/settings/paths, /api/backups, /api/settings and /api/check-scraper/* answer 403 to a viewer.
  - **Do**: poll and fetch only for roles the route allows (window.IS_ADMIN, or a role flag from base.html).
  Shipped 2026-11-10 (420a3342): window.IS_EDITOR in base.html gates the
  AI Fill poll; five admin-only Settings loaders return early for
  non-admins. Viewer walk: 12 403s before, 0 after.
  **Layman:** Nothing breaks on screen, but for a viewer every page quietly asks the server for things only an admin may see.
  Kind: fix.
  Source: browser walk 2026-11-10.

- ✅ [PASS-59-298] **One spelling per name: "Doom" and "DOOM" become one, and the AI gives official capitals (enhancement, M).**
  - **Why**: found 2026-11-10 (PASS-59-160 live check): case twins
    ("Doom" 14 games, "DOOM" 3) count as two entries in the filter
    window but filter together. Settings > Normalization cannot fix
    them: get_unique_values keys on lower case, so it hides twins, and
    apply_normalization skips a change that only alters capitals.
  - **Agreed** (user, 2026-11-10): (1) AI Fill asks for franchise,
    publisher and developer names with their official capitalisation.
    (2) A saved name equal to a library spelling apart from capitals
    takes the library's spelling. (3) Settings > Normalization lists
    each twin group, most-used spelling pre-selected; the user confirms
    or picks another, then Apply. Nothing changes without the user.
  - **Verify**: on a copy of the live DB, the twins list shows Doom /
    DOOM; applying one spelling leaves one entry with the summed count;
    a scrape bringing "doom" saves the library's spelling.
  - **Status**: todo.
  - **Shipped** 2026-11-10 (4.0.0): normalization.use_library_spellings
    in the scrape save and AI Fill; Settings > Normalization lists twin
    groups (case_twin_groups / apply_spellings); the AI prompt asks for
    official capitals. Checked on a copy of the live DB: Doom 14 / DOOM 3
    became Doom 17. Tests: tests/test_pass59_298_one_spelling.py.
  **Layman:** A franchise, publisher or developer spelled with different capitals shows as one name, spelled the official way.
  Kind: enhancement.
  Source: user-request-2026-11-10.

- ✅ [PASS-59-299] **Company names ending ", Ltd." or ", Inc." are split into two names (fix, S).**
  - **Why**: found 2026-11-10 in the PASS-59-298 walk. publisher and
    developer split on every comma, so "Foo, Ltd." becomes "Foo" and
    "Ltd."; Settings > Normalization > Publisher lists "Ltd, LTD" and
    "Ltd., LTD." as names. On 2026-11-10 the live library held 187
    games with ", Ltd" or ", Inc" in either field.
  - **Fix**: keep a company suffix (Ltd., Inc., Co., Corp., LLC) with
    the name before it wherever these fields are split, and never
    rewrite stored names (user, 2026-11-10: keep the name whole, comma
    included).
  - **Status**: todo.
  - **Shipped** 2026-11-10 (b72874a1): `normalization.split_names` keeps
    a suffix with its name everywhere the fields are split; the Library
    cards use `firstCompany`. No stored name was rewritten, and a
    2026-10-22 backup shows the old dropped-suffix bug never hit a row.
  - **Left open**: a filter on a bare name ("Sega Enterprises") also
    matches "Sega Enterprises, Ltd." in `whole_value_sql`. Extra games
    shown, none hidden; PASS-59-300's merge makes it rarer.
  **Layman:** A company such as "Foo, Ltd." shows as two names, "Foo" and "Ltd.", in filters and Settings.
  Kind: fix.
  Source: pass59-298-live-check-2026-11-10.

- ✅ [PASS-59-300] **One company under different names: suggest look-alikes, the user merges them (feature, M).**
  - **Why**: the user, 2026-11-10: "Eidos" and "Eidos Interactive" are
    one company and should show as one name.
  - **Decision** (user, 2026-11-10): Settings > Normalization suggests
    publisher and developer names that look like one company; the user
    picks the name to keep and ticks which to merge. Nothing merges by
    itself: "Atari, Inc." and "Atari Games" are two companies.
  - **Fix**: group names where one is the other plus a common company
    word (Interactive, Entertainment, Software, Games, Studios, a
    suffix such as Ltd.). The merge rewrites stored names, like the
    PASS-59-298 spellings, and later scrapes take the chosen name.
  - **Builds on**: PASS-59-299 (whole company names) and PASS-59-298.
  - **Status**: todo.
  - **Shipped** (2026-11-11, 4af900c6): Settings > Normalization >
    Publisher / Developer lists look-alikes (normalization
    .company_lookalike_groups), none ticked. Merge rewrites both company
    fields and saves `company` rules that company_aliases() lays over
    COMPANY_ALIASES. On the live library it suggests 162 publisher and
    142 developer groups. Test: tests/test_pass59_300_company_lookalikes.py.
  **Layman:** "Eidos" on one game and "Eidos Interactive" on another become one name, once you confirm it in Settings.
  Kind: feature.
  Source: user-request-2026-11-10.

- ✅ [PASS-59-301] **A comma inside brackets splits a company name in two (fix, S).**
  - **Seen**: the PASS-59-300 browser walk listed "Majesco (licensed
    from Konami" and "Disney)" as names: split_names cuts at every
    comma, even inside brackets.
  - **Fix**: split_names (and the JS firstCompany twin) skip commas
    inside brackets; check what the stored rows hold first.
  - **Status**: todo.
  - **Shipped** 2026-11-11 (8ca9476e): split_names and firstCompany split
    only at commas outside () and []; a stray closer is ignored. The live
    library held three such publishers, all balanced; no stored name was
    rewritten. ada1166d also stops the PASS-59-300 tests leaking company
    merges into other tests (it broke the PASS-59-213 Acclaim case under
    shuffled order).
  **Layman:** A publisher such as "Majesco (licensed from Konami, ...)" shows as broken pieces like "Disney)"; it should stay one name.
  Kind: fix.
  Source: pass-59-300-walk-2026-11-11.

- ✅ [PASS-59-302] **Settings > Bonus Discs gets a "Not a bonus disc" button, so a wrong Auto-Link mark can be undone (ux, S).**
  - **Why**: the Bonus Discs panel in `templates/settings.html` can only
    mark and link. `/api/bonus-discs/unlink/<id>` and `/api/bonus-discs/mark`
    with `is_bonus: false` have no button, so a disc Auto-Link marked
    wrongly stays hidden. PASS-59-262 made the server remember the answer
    (`games.not_bonus_disc`).
  - **Do**: list current bonus discs with a "Not a bonus disc" button
    (editors only) calling the unmark route; translate the new strings.
  Shipped 2026-11-11: Settings > Bonus Discs lists current bonus discs
  (from /api/bonus-discs/stats) with a "Not a bonus disc" button for
  editors, calling /api/bonus-discs/mark with is_bonus false. No server
  change. Checked on a :5001 scratch copy: desktop, 375px, viewer (no
  buttons), failed request (button re-enabled, error toast).
  **Layman:** You can tell RetroDB a disc is not a bonus disc, and Auto-Link will leave it alone.
  Kind: ux.
  Source: user, 2026-11-11 (found in PASS-59-262).

- ✅ [PASS-59-303] **Removing a picture in the Edit form keeps the file when another game still uses it (fix, S).**
  routes/games.py: the Edit form's `_remove` queues the old file for deletion
  without the sharing check `_upload` makes, so a file another games row
  names is deleted from under it. Both paths should use one check.
  Shipped 2026-11-11 in fd197bcd.
  **Layman:** If two games share one picture, removing it from one game no longer deletes it from the other.
  Kind: fix.
  Source: user-request-2026-11-11.

- ✅ [PASS-59-304] **Small back-of-box pictures from a scrape get upscaled like the front (fix, S).**
  A scrape defers every small image's upscale (upscale_later), but the
  worker's list services/upscale_queue.py `_MEDIA_FIELDS` has no
  `boxart_back`, so a deferred back cover is never upscaled.
  Shipped 2026-11-11 in fd197bcd.
  **Layman:** Back covers saved small by a scrape are now enlarged in the background, as front covers already are.
  Kind: fix.
  Source: user-request-2026-11-11.

## 4.0.x — Security and data-loss fixes for the web version

After 4.0.0 the web version gets security and data-loss fixes only, always as 4.0.x: the 4.0 updater treats 4.1.0 and up as the desktop app.

## 4.1.0 — Desktop app: browse and play

The first piece of the native app (Rust + Slint): the Library, console and game
pages, and launching games. Port plan phases 0 to 2
(docs/plans/PASS-59-270-native-app-port.md).

- 📋 [PASS-59-182] **A missing emulator falls back to a RetroArch that can play the game (ENHANCEMENT, S).**
  - **Report**: Tomb Raider (GBC) failed with "Emulator binary not
    found on PATH: 'mgba-qt'". The user expects RetroArch to play it.
  - **Found** (2026-10-29): gb, gbc and gba default to mGBA, not
    installed. `launch_resolver.pick_launch_mapping` already falls back
    to the player when the default does not resolve, but
    `_player_serves` needs the player's program, and RetroArch
    (RetroDB) is not downloaded yet (no `data/player/`). The user's own
    RetroArch row is never tried.
  - **Target**: (1) the error offers Get RetroArch where the player
    could serve the system; (2) consider the user's own RetroArch with
    a core for the system as a further fallback.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** If a game's emulator is missing, RetroArch plays it instead.
  Kind: implement.

- 📋 [PASS-59-184] **3D box art matches the ROM's region (ENHANCEMENT, M).**
  - **Target**: a game's 3D box shows its own region's case; many
    regions' cases look different.
  - **Open**: which sources give region-tagged 3D boxes, and how the
    region is read (the `region` field, the ROM name's tags). Related:
    PASS-59-162, PASS-59-143.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** A game's 3D box matches its region's case.
  Kind: implement.

- 📋 [PASS-59-191] **Sort and filter the Library by copies sold (feature, S).**
  - **Target**: a Copies sold sort option beside Critic score and User
    score (`templates/system_games.html`, `AllGamesController`, so the
    Library and system pages stay in sync), and a "has a sales figure"
    filter.
  - **Status**: todo.

  ---
  **Layman:** Sort and filter the Library by copies sold.
  Kind: implement.

- 📋 [PASS-59-193] **Best-seller badges on a game's page (feature, S).**
  - **Target**: a badge on the game page from `units_sold`: its rank
    among the system's games with a figure ("#3 best seller on SNES in
    your library"), shown only for the top 10.
  - **Status**: todo.

  ---
  **Layman:** Best-seller badges on a game's page.
  Kind: implement.

- 📋 [PASS-59-230] **Arcade flyers on the game page (enhancement, S).**
  - **Status**: todo
  - **Decided** (user, 2026-11-02): after v4.0.0.
  - **What the sources send**: ScreenScraper `flyer` (documentation only,
    in no sample seen). Check a real arcade answer before building.
  - **Pattern**: the box back (PASS-59-225) — its own column and folder,
    fill-only, and a place on the game page.

  ---
  **Layman:** Arcade flyers on the game page.
  Kind: implement.

## 4.2.0 — Desktop app: edit and scrape

Editing games and filling them from the online sources. Port plan phase 3.

- 📋 [PASS-53-5] **Role-aware rating display in the edit form (UX, S)**
  - **Status**: planned.
  - **Problem**: the Edit form's "Technical" tab stacks all 10 age-rating
    dropdowns — ESRB/PEGI/CERO/USK/ACB/FPB/GRAC/ClassInd (`base.html:1213-1305`) —
    for every user, though almost everyone cares about one region.
  - **Plan** (per user 2026-07-03): **admin** users keep all rating boards visible
    (they curate cross-region data); **every non-admin** user sees ONLY the single
    rating system selected in their Settings (`preferred_rating_system`). Gate the
    extra boards on `current_user.role == 'admin'`; non-admins get one dropdown.
    Cross-mapping / auto-fill (`map_rating`) is unchanged — this is a display
    filter, not a data change.
  - **Est.**: S — a role check + conditional render around the rating block.
  **Layman:** The edit form shows only the age-rating boxes that matter to you.
  Kind: implement.

- 📋 [PASS-53-9] **Deep-link from scrape failure to the API-key form (UX, S)**
  - **Status**: planned.
  - **Problem**: API keys live three levels deep (Settings → Scraping → sub-tab,
    `scraping.html:7,265`), yet skipping them causes silent scrape failures whose
    fix is buried. There's no link from the failure back to the fix.
  - **Plan**: when a scrape fails for a missing / invalid key, surface a direct
    link to the API-keys sub-tab (`/settings#scraping` + sub-nav anchor). Pairs
    with the setup wizard's optional-API-key step (Pass 53.8).
  - **Est.**: S — a targeted link in the failure message / toast.
  **Layman:** A scrape that fails for a missing key takes you straight to where you enter it.
  Kind: implement.

- 📋 [PASS-59-183] **MobyGames as a scrape source (FEATURE, M).**
  - **Target**: RetroDB fetches game details from MobyGames. The user
    has no API key.
  - **Research first** (unverified): whether MobyGames' API needs a
    paid or approved key, its rate limits and terms, and whether any
    keyless route is allowed. Scraping its web pages may breach its
    terms. Fits PASS-59-162's source review.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** MobyGames as another place to look up game details.
  Kind: implement.

- 📋 [PASS-59-185] **One AI Fill tool in ROM Tools, with a switch for each kind of fill (UX, M).**
  - **Target**: ROM Tools shows two AI tools today, Official Names and
    Backfill Alternate Titles. Merge them into one AI Fill with an
    on/off switch per kind, plus release dates for all regions.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** One AI Fill tool, with a switch for each kind of detail it fills.
  Kind: implement.

- 📋 [PASS-59-220] **Sales figures for 8-bit games: cited numbers and period sources (enhancement, M).**
  - **Status**: todo
  - **Request** (user, 2026-10-31): a Gemini answer listed sources for 8-bit sales figures; see if it can be used.
  - **Measured 2026-10-31**: `units_sold` is empty on every Commodore 64, ZX Spectrum and Atari 5200 game in one library, and on most Atari 2600 games. Only the AI fills it, and `_build_prompt` already names Wikipedia's lists and VGChartz, with nothing for 8-bit computers.
  - **Treat the answer as leads, not data**: checked against Wikipedia, its Pitfall! and Asteroids figures differ (about 4.5m and 4.3m against 4,000,000 and 3,832,886), and Sensible Soccer is not listed for Spectrum or C64.
  - **Plan**: 1. A small shipped table of cited figures, each with its source link, starting with Wikipedia's Atari 2600 list (24 games, each row referenced; text CC BY-SA 4.0, so credit it). It fills `units_sold` fill-only, without paying for AI. 2. For 8-bit systems, add to the AI prompt: the C64 Wiki, Spectrum Computing, World of Spectrum, AtariAge and period magazines on archive.org. Keep "a published figure, never your own estimate", and accept a stated milestone only as that game's figure. 3. Show the source beside the number, with PASS-59-211.
  - **Not planned**: scraping VGChartz, forums or magazine scans; no API, and terms not checked. A forum estimate is not a published figure.
  - **Limit**: most 8-bit games have no published figure, so most stay empty, which is the true answer.

  ---
  **Layman:** Sales figures for 8-bit games, with their sources.
  Kind: implement.

## 4.3.0 — Desktop app: tools, cheats and statistics

Everything else the web version does: long tasks, the image upscaler,
achievements and trophies, cheats, imports, ROM tools, analytics and the museum.
Port plan phase 4.

- 📋 [PASS-53-6] **ROM Tools nav link: hub vs last-visited, as a preference (UX, S)**
  - **Status**: planned (low priority — the maintainer prefers the current
    last-visited behaviour for their own use; kept as an opt-in option, not a
    forced change).
  - **Problem**: the sidebar "ROM Tools" link jumps to the last sub-tool visited
    (`base.html:840-855`) rather than the hub, so the label and destination
    disagree — disorienting for a new user.
  - **Correction** (2026-10-17): the premise is false. The link has always
    opened the hub: `navigateToRomTools` in `base.html` is defined but nothing
    calls it, in the whole git history, so the `lastRomToolsPage` script is
    dead code. A last-visited option would be new behaviour, not a
    preference over existing behaviour. The dead script is not removed yet.
  - **Plan**: make it a user preference (Settings): "ROM Tools opens → hub /
    last-visited", defaulting to hub for new users so power users keep the
    shortcut. Small, opt-in; no behaviour forced.
  - **Est.**: S — one setting + a branch in the nav redirect.
  **Layman:** A setting chooses whether the ROM Tools link opens the tool list or the last tool you used.
  Kind: implement.

- 📋 [PASS-53-12] **Persistent inline error state for walk-away operations (UX, S)**
  - **Status**: planned.
  - **Problem**: errors from user-initiated operations surface only as ephemeral
    toasts (e.g. AI-fill error `game-modals.js:2311`). If the user walks away, the
    only record vanishes when the toast times out — no lasting indication on the
    affected item.
  - **Plan**: add a durable inline error indicator on the affected item (game card
    / job row) for scrape / AI-fill / bulk operations, complementing — NOT
    replacing — the toast system. NOTE (user 2026-07-03): toast timeouts are
    already per-category user-editable (success / info / warning / error each
    independently, `notification_timeouts`, injected `base.html:330-335`) — preserve
    that. This item adds durability; it does not change toast timing.
  - **Est.**: S — an inline error state hooked into the existing error paths.
  **Layman:** An error from a long task stays on screen until you have seen it.
  Kind: implement.

- 📋 [PASS-59-171] **Cheats for PSP games in PPSSPP (MEDIUM, S).**
  - **Status**: todo
  - Deferred from PASS-59-155 (user, 2026-10-23: not in v4.0.0).
  - The user's PSP cheat database is in `/mnt/Emulators/Cheats/Sony
    PlayStation Portable/PPSSPP` (`cheat.db`, and per-game `.ini` files
    named by game id). PPSSPP's own enable mechanism: not researched.

  ---
  **Layman:** Cheats for PSP games played in PPSSPP.
  Kind: implement.

- 📋 [PASS-59-172] **Research RPCS3 game patches as cheats (LOW, S).**
  - **Status**: todo
  - Deferred from PASS-59-155 (user, 2026-10-23: research before
    deciding; not committed to v4.0.0).
  - RPCS3 cheats are game patches in `patch.yml`, a different and
    larger format than the other emulators' cheat files.

  ---
  **Layman:** Find out whether RPCS3's game patches can work as cheats.
  Kind: implement.

- 📋 [PASS-59-173] **Cheats when a game runs in the user's own RetroArch (LOW, S).**
  - **Status**: todo
  - Deferred from PASS-59-155 (2026-10-23).
  - The user's RetroArch reads its own `cheat_database_path`; RetroDB
    would write the `.cht` there through the overrides layer
    (`services/launch_resolver.py::_retroarch_overrides`).

  ---
  **Layman:** Cheats for games played in your own RetroArch.
  Kind: implement.

- 📋 [PASS-59-180] **A game series timeline: what changed from game to game, and between regions and consoles (FEATURE, L).**
  - **Target**: a timeline of a series showing what each game changed,
    and how its regional and console versions differ, graphics too.
  - **Mockups**: HTML mockups under `docs/mockups/series-timeline/`,
    for the user to choose from.
  - **Open**: where the change data comes from (AI, scraped, typed in);
    how it ties to franchise/series fields and regional versions
    (PASS-59-106).
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** A timeline of a game series showing what changed from game to game.
  Kind: implement.

- 📋 [PASS-59-181] **Console museum: three new presentations to choose from (UX, M).**
  - **Target**: three mockups of how the console museum could be
    presented, by Claude's own design; the user picks one.
  - **Mockups**: `docs/mockups/museum/`. Building waits for the pick.
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** Three new looks for the console museum to choose from.
  Kind: implement.

- 📋 [PASS-59-187] **One place to update RetroDB's RetroArch and its cores, with a dashboard reminder when they are out of date (ENHANCEMENT, M).**
  - **Ask** (user, 2026-10-29): RetroArch downloaded beside RetroDB
    needs a way to stay updated: a dedicated place to run updates, and
    a dashboard note when RetroArch has not been updated in a while.
  - **Today** (read 2026-10-29): RetroArch is pinned per RetroDB
    release (`services/player_install.py` VERSION + SHA-256); "Download
    RetroArch again" reinstalls the pin. "Update cores" in Settings >
    Emulators re-downloads cores whose buildbot CRC changed. Nothing
    says either is due. RetroArch's own Online Updater inside the
    player is untested (it would bypass `cores/installed.json`).
  - **Target**: one Updates card (beside Settings > System > Updates,
    or in Settings > Emulators) showing the installed RetroArch against
    the pin this RetroDB carries, and how many cores have newer builds;
    one button runs both. The dashboard shows a note when the pin is
    newer than the install or cores were last checked long ago.
  - **Open**: how long "a while" is; whether the core check runs
    daily like the RetroDB update check (PASS-59-169).
  - **Status**: todo.
  - **Source**: user, 2026-10-29.

  ---
  **Layman:** One place to update RetroArch and its cores, with a reminder when they are out of date.
  Kind: implement.

- 📋 [PASS-59-190] **A Sales card on the Analytics page (feature, M).**
  - **Target**: a Sales card on `templates/analytics.html` built from
    `games.units_sold`: total copies sold, a bar chart of totals per
    system, the 10 best-selling games (linked), and coverage (games
    with a figure / all games).
  - **Why**: AI Fill and Bulk AI Fill now fill sales figures; nothing
    shows them except the game page.
  - **Status**: todo.

  ---
  **Layman:** An Analytics card showing how many copies your games sold.
  Kind: implement.

- 📋 [PASS-59-192] **Sales totals by publisher, genre and decade (feature, M).**
  - **Target**: tabs on the Analytics Sales card (PASS-59-190)
    totalling `units_sold` by publisher, by genre (multi-value: a game
    counts under each of its genres, and the card says so) and by
    release decade.
  - **Blocked by**: PASS-59-190.
  - **Status**: todo.

  ---
  **Layman:** Copies sold, added up by publisher, genre and decade.
  Kind: implement.

- 📋 [PASS-59-233] **Check each ROM is a good copy against No-Intro and Redump lists (feature, M).**
  - **When**: after v4.0.0 (user, 2026-11-04).
  - **Why**: a bad dump plays wrongly or not at all, and nothing in
    RetroDB says so today. The CHD check covers CHD files only.
  - **Start from**: `services/rom_identity.py` already gives a file's
    name, size and CRC (PASS-59-217). Compare those to No-Intro and
    Redump DAT files the user supplies.
  - **Open**: where the result shows (ROM Tools, the game page, both),
    and how DAT files reach the app. Ask the user before building.
  - **Status**: todo.

  ---
  **Layman:** Check each ROM is a good copy against the No-Intro and Redump lists.
  Kind: implement.

- 📋 [PASS-59-234] **Back up and restore each game's saves (feature, M).**
  - **When**: after v4.0.0 (user, 2026-11-04).
  - **Why**: saves live only in each emulator's folders; a lost disk or
    a bad emulator update loses them. Nothing in RetroDB copies them.
  - **Start from**: `services/player.py` names RetroArch's
    `savefile_directory` and `savestate_directory` keys; DuckStation,
    PCSX2 and the other standalone emulators keep their own folders.
  - **Open**: which emulators first, where copies go, and how many
    copies to keep. Ask the user before building.
  - **Status**: todo.

  ---
  **Layman:** Back up and restore each game's saves.
  Kind: implement.

- 📋 [PASS-59-236] **ROCm's roctracer aborts every GPU process at exit: find a fix that needs no copy of ROCm (investigate, S).**
  - **When**: after v4.0.0 (user, 2026-11-04).
  - **Why**: `roctracer` 6.4.0 (openSUSE build) fails an assertion in
    `hsa_support::Finalize` at exit. pytest exits 134, and a plain kill
    of a server writes a core dump of hundreds of MB.
  - **Try, in order**: a newer ROCm; keeping `libroctracer64` from
    loading; reporting it to AMD or openSUSE.
  - **Decided** (user, 2026-11-04): no fork of ROCm. Measured that day
    for this machine's gfx1032 card (run as gfx1030): the ROCm files the
    upscaler loads are 2.48 GB on disk, 534 MB packed with `xz -1`, for
    one card family only.
  - **Status**: todo.
  - **Found** 2026-11-04: installed ROCm is mixed 6.4 (rocblas from AMD's
    SLES 15.6 build in /opt/rocm-6.4.0; roctracer 6.4.0 from OBS
    science:GPU:ROCm; hip 6.4.2), and zypper shows roctracer locked.
    Tumbleweed's main repo has ROCm 7.2.0. Its librocblas5 7.2.0-10.1
    builds for gfx1031 but not gfx1032 (rpm -qlp, 2026-11-04).
    - **Idea** (user, 2026-11-04): ask openSUSE to add gfx1032 to the
    build targets, and report the roctracer abort. Test 7.2 first: a
    report against 6.4 would likely be answered "upgrade". Moving to 7.2
    must keep onnxruntime's ROCm provider working (memories
    onnxruntime_rocm_trap, rocsolver_missing). The user posts any report.
  - **Decided** (user, 2026-11-04): after v4.0.0, draft the openSUSE
    gfx1032 build-target request and test the roctracer abort on 7.2;
    show the user the report text to post.

  ---
  **Layman:** Find a fix for the graphics-card library that crashes every program using it when it closes.
  Kind: implement.

## 4.4.0 — Desktop app: looks and languages

Themes, layouts, plugins and new languages. Port plan phase 5.

- 📋 [PASS-56-2] **Further language packs — Czech, Swedish, Thai, Vietnamese (FEATURE, L)**
  - **Target**: four more locales — **`cs` Czech, `sv` Swedish, `th` Thai,
    `vi` Vietnamese** — the next-highest-value gaps for a retro-gaming audience
    after the Pass 56.1 set.
  - **Why**: all four are widely-spoken, well-resourced for quality translation,
    all left-to-right (no RTL prerequisite, unlike Pass 43.4's Arabic), and absent
    from the current 21-language set. Suggested to and approved by the user
    2026-07-05.
  - **Plan**: identical pipeline to Pass 56.1 — `pybabel init -l <code>` →
    per-locale `{msgid: translation}` JSON → `scripts/apply_po_translations.py`
    (strict: hard-fails on any missing msgid or dropped placeholder) → `pybabel
    compile`; then the 14-entry `data/changelog.<code>.yaml` + the ~2000-line
    `templates/help.<code>.html` (copy-then-translate-prose, anchors byte-identical).
    Zero code changes — `available_locales()` auto-surfaces each new catalog in the
    Settings dropdown / validator / selector. Plural-form counts (from CLDR, set by
    `pybabel init`): `cs` 4, `sv` 2, `th` 1, `vi` 1. Would take the shipped set to
    25 languages.
  - **Verify**: `available_locales()` returns the four new codes; `pybabel compile`
    clean; `scripts/check_i18n_fresh.py` green (msgid set unchanged — locales only);
    each changelog parses at the current recent-entry count; each help file's
    `id`/`href` anchor set + Jinja-token count byte-identical to `help.html`.
  - **Status**: planned (2026-07-05). Not started; a self-contained follow-on to
    Pass 56.1 whenever the user wants the next batch.

  ---
  **Layman:** Czech, Swedish, Thai and Vietnamese translations.
  Kind: implement.

- 📋 [PASS-43-4] **RTL layout support + Arabic (MEDIUM, L)**
  - **Target**: `static/css/core/*.css`, every grid/flex layout, every
    text-align/margin-left utility.
  - **Why**: Arabic and Hebrew are RTL; the current CSS bakes
    left-to-right assumptions deep into the grid/sticky-nav system.
  - **Plan**: switch directional utilities (`margin-left/right`,
    `text-align: left`) to logical properties (`margin-inline-start/end`,
    `text-align: start`).  Add `[dir="rtl"]` overrides where logical
    properties don't reach (icons, chevrons, sortable column arrows).
    `<html dir="rtl">` driven by locale class (`app.py::select_locale` result →
    Babel `Locale.parse(code).text_direction`).  The CSS audit is the bulk:
    ~360 physical `left/right` rules, zero logical, no `[dir]` handling as of
    Pass 56.
  - **Status**: planned — **un-gated (2026-07-05).** Pass 56 shipped a **Hebrew** (`he`)
    catalog — the first RTL `.po`, so the "needs a real RTL user" gate is now met.
    Hebrew currently renders correct Hebrew *text* in the still-LTR layout; this
    pass is what makes the layout mirror properly. **Also add Arabic (`ar`) here:**
    Arabic was deliberately held out of Pass 56's translation batch precisely
    because it needs this layout work first — once RTL layout lands, adding the
    `ar` catalog (same pipeline as Pass 56: `pybabel init` → translate →
    `scripts/apply_po_translations.py` → compile) is translation-only. Scope:
    the CSS logical-property conversion (shared by `he` + `ar`) **plus** the `ar`
    catalog. Bumped priority MEDIUM (was LOW) now that a shipped RTL locale
    depends on it.
  **Layman:** Arabic, with pages laid out right to left.
  Kind: implement.

- 📋 [PASS-59-235] **TV mode: a big-text Library you steer with a game controller (feature, L).**
  - **When**: after v4.0.0 (user, 2026-11-04).
  - **Why**: RetroDB launches games, but choosing one needs a mouse and
    keyboard. No page reads a game controller today (no `getGamepads`
    in `static/js`).
  - **Open**: a separate page or a mode of the Library; which actions it
    offers (browse, details, Play). Likely needs a spec
    (`spec-format.md` §1): it spans pages, input and layout.
  - **Status**: todo.

  ---
  **Layman:** TV mode: a big-text Library you steer with a game controller.
  Kind: implement.

## 4.5.0 — The Android app

RetroDB on an Android phone: on its own, or as a companion to the PC over home
Wi-Fi, with ROMs copied to the phone. Port plan phase 6. Nothing filed here yet.

## 5.0.0 — The full desktop app

The native app does everything the web version did, on Windows, Linux, macOS and Android.

- 📋 [PASS-59-270] **Port RetroDB to a native app in Rust + Slint for Windows, Linux, macOS and Android (feature, XL).**
  - **Status**: todo
  Decisions (user, 2026-11-09): Rust + Slint; one codebase for
  desktop and Android; Android runs standalone or as a companion to
  the PC over Wi-Fi, and can copy all or chosen ROMs from the PC to
  the phone for use on the go; WebAssembly plugins; two-level themes
  (skins, layout themes); each screen keeps its state and drops its
  view. Build starts after v4.0.0 ships (PASS-59-113). Spec:
  docs/specs/PASS-59-270-native-app-port.md. Plan:
  docs/plans/PASS-59-270-native-app-port.md.

  ---
  **Layman:** RetroDB becomes a desktop and Android app instead of a web page.
  Kind: implement.

## Ideas, not planned

Considered or dropped. Kept so the reasoning is not lost.

- 💭 [PASS-12-5] **— FTS5 virtual table for `games.title` + `alternate_titles` (MEDIUM, L)**
  - **Target**: search endpoints (`routes/games_search.py::api_games_find`
    and similar), plus filter pages doing `WHERE title LIKE '%q%'`.
  - **Why**: `LIKE '%q%'` on a 10k-row games table with no index is an
    O(N) scan every time.  SQLite FTS5 with a porter tokeniser brings
    this to sub-20 ms on the same dataset.
  - **Plan**:
    1. Define a virtual table `games_fts(title, alternate_titles, content='games', content_rowid='id')`.
    2. Populate from `games` and keep in sync via INSERT/UPDATE/DELETE triggers.
    3. Replace `WHERE title LIKE` with `WHERE id IN (SELECT rowid FROM games_fts WHERE games_fts MATCH ?)`.
  - **Caveat**: FTS5 doesn't replace prefix LIKE for all cases (autocomplete,
    substring mid-word).  Keep LIKE where required.
  - **Source**: <https://www.sqlite.org/fts5.html>
  - **Status**: deferred — L-sized; gated on a benchmark run that confirms
    `WHERE title LIKE '%q%'` is actually the hot path on a realistic
    10k-row library.  `RETRODB_SLOW_QUERY_MS=100` (Pass 12.4) is the
    instrument to collect that data.
  **Layman:** Faster title search on very large libraries.
  Kind: implement.

- 💭 [PASS-14-2] **— Gradual type hints on high-risk modules (LOW, L)**
  - **Target**: `scraper/metadata_merger.py`, `services/game_query.py`,
    `routes/games.py`.
  - **Why**: largest / most-called modules in the codebase. Type hints on
    function signatures make IDE autocomplete and `mypy` checks meaningful.
    Currently the codebase has ~0% type coverage.
  - **Plan**: adopt one module at a time.  Start with signatures (`-> dict`,
    `-> list[dict]`, `int | None`) then internal variables only where
    they help.  Add `mypy` as a CI-only check (not pre-commit) with
    `--ignore-missing-imports`.
  - **Status**: deferred (LOW priority, L sized — its own pass)

  ---
  **Layman:** Add type labels to the biggest code files so mistakes show up sooner.
  Kind: implement.

- 💭 [PASS-55-4] **Overlap whole games in the bulk scrape (PERF, L) — NOT STARTED**
  - **Status**: considered, not started 2026-07-05. `BulkScrapeManager._run_scrape`
    processes games one at a time on a single daemon thread; a small worker pool
    (e.g. 3-4 games in flight) is the largest theoretical win. Risk is real:
    ScreenScraper enforces per-account daily quotas + concurrent-thread caps
    (already hard-stops on the daily limit), RAWG self-throttles, and DB writes
    serialise under WAL. Needs quota-aware bounded concurrency, not a blind pool —
    held pending user appetite for the extra complexity.

  ---
  **Layman:** Scrape several games at once to finish a bulk scrape sooner.
  Kind: implement.

- 💭 [PASS-49-9] **`clear-ra-data` library-wide vs per-user semantics (MEDIUM, S)**
  - **Status**: deferred — design decision, not a silent fix.
  - **Lane**: collections/achievements/trophies (Lane 10).
  - **Finding**: `routes/ra_sync.py` `api_clear_ra_data_all` / `_system` DELETE
    `game_achievement_progress` with no `user_id` predicate, wiping every user's
    earned-achievement progress (the table is per-user, migration 009). It is
    paired with clearing the *shared* `games.ra_game_id` links, so clearing all
    progress is internally consistent (otherwise orphaned) — which is why this is
    a semantics call, not a clear bug.
  - **Decision**: confirm intended meaning — a library-wide admin reset (current)
    or a per-user clear. If per-user, scope BOTH the link clear and the progress
    DELETE by `g.user['id']`. Single-household threat model keeps impact LOW.
  **Layman:** Decide whether clearing RetroAchievements data clears everyone's or only yours.
  Kind: implement.

- 💭 [PASS-49-2] **bulk-scrape swap/demote counter corruption after join timeout (MEDIUM, M)**
  - **Status**: deferred — needs careful concurrency design.
  - **Lane**: background jobs (Lane 7).
  - **Finding**: `services/jobs/bulk_scrape.py` `swap_with_running` /
    `demote_running` `join(timeout=60)` then proceed even if the old worker is
    still alive; a hung scraper's worker can wake after `reset()` and increment
    the *new* job's `success_count`/`failed_count`.
  - **Decision**: block or hard-fail the swap when the old thread is still alive
    rather than "proceed with state mixing possible".
  **Layman:** Swapping a running bulk scrape could mix up its counts.
  Kind: implement.

- 💭 [PASS-49-3] **SSRF redirect-chain HEAD probes are unpinned (MEDIUM, M)**
  - **Status**: deferred — hardening; the GET is now correctly pinned (Pass 49 port-0 fix).
  - **Lane**: core/SSRF (Lane 11).
  - **Finding**: `services/ssrf.py` `validate_redirect_chain` validates each hop
    then issues `session.head(...)` unpinned, re-resolving DNS — a rebinding
    server can pass validation and serve a private/metadata IP to the HEAD.
  - **Decision**: wrap each HEAD hop in `pin_host_ip` (or re-validate the IP the
    HEAD resolved). Low live risk on a LAN with no internal SSRF targets.
  **Layman:** A web-safety check on followed links could be tightened further.
  Kind: implement.

- 💭 [PASS-49-4] **`organize-multidisc` relies on incidental path-nesting (MEDIUM, S)**
  - **Status**: deferred — currently safe; explicit hardening.
  - **Lane**: maintenance/reports (Lane 9).
  - **Finding**: `routes/reports.py` move branch blocks a traversing `system`
    param only because `folder_path` nests under `system_path` and `safe_path`
    catches the escape — there is no independent DB/`safe_path` check on `system`
    like the multidisc-scan path has.
  - **Decision**: add an explicit `system` validation mirroring `reports.py:405`.
  **Layman:** Add an extra check on the multi-disc organiser, which is safe today.
  Kind: implement.

- 💭 [PASS-49-6] **i18n — inline-`<script>` toast/modal strings untranslatable (MEDIUM, L)**
  - **Status**: deferred — large mechanical sweep (~138 strings across ~20 templates).
  - **Lane**: templates/i18n (Lane 13).
  - **Finding**: `build_js.py` only scans `static/js/*.js`, so toast/modal string
    literals inside template inline `<script>` blocks ride neither the JS `t()`
    path nor `{{ _() }}`; they are permanently English for non-English locales and
    invisible to `pybabel extract` (`game_detail.html`, `settings.html`,
    `dashboard.html`, achievement/trophy/chd templates, …). Plus 4 constrained
    `settings.html` JS-string sites (tz/avatar/role) still want `|tojson` for
    consistency.
  - **Decision**: wrap each inline-`<script>` user-facing string in `{{ _('...') }}`
    (the `wishlist.html` pattern) and regenerate catalogs per `docs/specs/i18n.md`.
  **Layman:** Translate pop-up text written inside page scripts.
  Kind: implement.

- 💭 [PASS-49-7] **Assorted LOW / INFO review notes (LOW, S)**
  - **Status**: deferred bundle — verified-but-low; pick up opportunistically.
  - Items:
    - `services/migrations/__init__.py` — add a defensive `not conn.in_transaction`
      assert before `BEGIN IMMEDIATE` so a future stray open transaction fails loudly.
    - `services/database.py:_fsync_path` duplicates `services/atomic_io.py:fsync_path`
      — dedupe to prevent drift.
    - `services/jobs/museum.py` `get_status()` field names (`current_index`/
      `total_systems`/`success_count`) diverge from the §7/§9 toast contract
      (`current`/`total`/`success`, no `processing`/`percent`).
    - `services/jobs/webp_migrate.py` resume path adopts a pre-existing `.webp`
      sibling without the `verify()` the fresh path does (spec §12.1) → corrupt
      sibling can silently replace a good boxart.
    - `image_resize` and `webp_migrate` take distinct singleton locks and can race
      the same boxart tree (stranded orphan `.png`); responsive-variant regen runs
      on `'skipped'` files too (disk churn).
    - `routes/trophies.py` import-time global monkeypatch of `pyrate_limiter`
      (`_Limiter._try_acquire`) is fragile across library upgrades.
    - ~~`scraper/scrape_thegamesdb.py` assigns free-text TGDB ratings verbatim into
      `esrb_rating`; `metadata_merger.py` drops bare single-letter ESRB codes
      ("E"/"T"/"M") that lack a trailing space.~~ Closed by Pass 59.19 — both
      parses share one whole-token parser and the verbatim fallback is gone.
    - `scraper/scrape_rawg.py` defaults `players` to `1` (truthy), pre-filling a
      weak value that crowds out a better secondary source.
    - ~~Xbox scrapers (`scrape_xbox.py`) bypass `base_scraper.http_get` — no SSRF
      risk (hardcoded `*.xboxlive.com`/`login.live.com` hosts) but `docs/specs/
      scrapers.md` §10 wrongly claims Xbox was migrated; fix the doc.~~ Closed by
      Pass 59.26 — the code was migrated instead, so §10 is now true as written.
    - `hybrid_scraper.py` generic-controller `elif` branch is a no-op `pass` whose
      comment promises to clear generic controller values.
    - ~~`static/js/main.js` `performGlobalSearch` is dead (`#globalSearch` absent
      from all templates, `/api/search` route absent) — surface before removing.~~
      Closed by Pass 59.39 — deleted with its binding and helpers.
    - `build_dist.py` source-ZIP walk is denylist-only (a gitignored
      `audit_rule_quality.json` shipped); `EXCLUDE_DIRS` matches by basename at any
      depth. No secret leaked today, but make the walk respect `.gitignore` and
      anchor `EXCLUDE_DIRS` to top-level.
    - **(Loop-2)** `ra_sync`/`platform_sync` skip-path (`if result is None:
      continue`) bypasses the `shutdown_requested.wait()` rate-limit — a long run
      of skipped games becomes a tight loop that drains a SIGTERM slightly slower
      than the per-request budget implies.
    - **(Loop-2)** `services/ssrf.py` pin host match is exact-string + fail-open
      (`return _orig_getaddrinfo` on miss); a future caller passing a
      non-normalized host (trailing dot / uppercase) to `pin_host_ip` would
      silently skip the pin. Normalize/lower the host on both store and compare.
  **Layman:** A bundle of small, low-risk code notes from a review.
  Kind: implement.

- 💭 [PASS-49-8] **Job resume off-by-one silently drops the in-progress game (MEDIUM, S)**
  - **Status**: deferred — pre-existing (predates the Pass 49 per-game-commit fix);
    surfaced by the Loop-2 cold re-review.
  - **Lane**: background jobs (Lane 7).
  - **Finding**: the periodic-persist block runs at the *top* of iteration `i` and
    writes `'current': i + 1`, but only games `0..i-1` are committed at that point.
    `resume_from_params` computes `remaining_ids = game_ids[resume_index:]` =
    `game_ids[i+1:]`, so the in-progress game at index `i` is skipped on resume and
    counted in neither success nor failed (`ra_sync.py`, `platform_sync.py` ×2).
  - **Decision**: persist `current` as completed-count, or resume from
    `max(resume_index - 1, 0)` — the upserts are idempotent (`ON CONFLICT DO
    UPDATE`), so re-processing one already-done game is harmless. Re-runnable sync
    job, so impact is LOW-MEDIUM.

  ---
  **Layman:** A resumed job could skip the game it was on.
  Kind: implement.

- 💭 [PASS-47-5] **Buy Me A Coffee (LOW, S)**
  - **Target**: <https://buymeacoffee.com> profile.
  - **Why**: lowest-friction one-off-tip surface for users without a
    GitHub account or who don't want monthly commitment. Stripe-backed;
    recipient pays standard processing fees (~2.9% + $0.30) plus 5% BMAC
    fee.
  - **Plan**:
    1. Sign up at <https://buymeacoffee.com>; pick a username matching
       the GitHub handle (`milnet01`) for cross-platform consistency.
    2. Add the BMAC URL to `.github/FUNDING.yml` (Pass 47.6) under the
       `custom` field — BMAC isn't a natively-recognised FUNDING.yml
       platform.
    3. **Skip the BMAC "memberships" feature** — that overlaps
       Patreon/Sponsors and fragments the monthly-tier story across
       three platforms. Use BMAC strictly for one-off coffees.
  - **Status**: deferred
  Progress (2026-06-30): Parked by maintainer. Buy Me A Coffee does not support South Africa yet, so this surface can't go live regardless of code. Leave planned; revisit only if/when BMAC adds ZA payouts. GitHub Sponsors already covers the in-app/README/FUNDING donation surfaces, so nothing is blocked on this.
  **Layman:** A Buy Me A Coffee page for one-off tips.
  Kind: implement.

- 🚫 [PASS-59-131] **Scrape speed: skip a fallback source that cannot fill any field still empty (MEDIUM, M).**
  - **Status**: dropped
  - **Where**: `scraper/hybrid_scraper.py::_run_fallbacks` stops early only
    when every key of the ~40-field metadata dict is filled, including fields
    no source supplies (`edition`, `campaign`, `playtime_estimate`). So every
    enabled source is queried for every game.
  - **Do**: give each source a list of fields it can supply. Skip a source
    when none of the still-empty fields is on its list; stop the loop when no
    remaining source can add anything.
  - **Keeps**: sources still run in Settings priority order and the first
    non-empty value still wins; a skipped source could only have added
    nothing. Manual still never queries an unticked source.
  - **Risk**: a wrong capability list silently drops data. Pin each list
    with a test against the source's apply function.
  - **Progress** (2026-10-21): Dropped 2026-10-21 (user). Every image fallback (TGDB, IGDB, RAWG,
    ScreenScraper) appends screenshots with no cap, so none can be skipped
    without losing screenshots; only AI could be skipped, and it nearly
    always has an empty field. The speed-up moves to PASS-59-132 (parallel
    fetch).

  ---
  Kind: implement.

- 💭 [PASS-59-135] **Scrape speed: fetch by stored IGDB or ScreenScraper ID instead of searching (LOW, M).**
  - **Status**: deferred
  - **Where**: `hybrid_scraper.py` writes `igdb_id` and `screenscraper_id`
    but no scrape reads them to skip a search; only
    `services/version_groups.py` does.
  - **Held**: PASS-59-124 found 111 games whose stored IDs pointed at the
    wrong game. Using IDs would repeat those mistakes on every re-scrape.
    Consider only for normal (fill) mode, never Full Re-scrape, and only once
    PASS-59-125 makes the search use the filename.

  ---
  **Layman:** Look up games by their saved IGDB or ScreenScraper ID instead of searching again.
  Kind: implement.

- 🚫 [PASS-59-196] **Fewer Claude web searches per game, and log how many each uses (perf, S).**
  - **Target**: lower CLAUDE_MAX_SEARCHES in scraper/scrape_ai.py from 5 to 2, and
    log each game's search count from the reply. The changelog's '5 searches, 5
    US cents' wording and test_search_is_capped_per_game move with it.
  - **Why**: nothing records real use. A system with no published sales figures
    probably spends the whole cap and finds nothing (Atari 5200 found none).
  - **Status**: dropped; declined by the user 2026-10-30.
  - **Decision** (user, 2026-10-30): declined. The limit stays at 5
    searches per game and no per-game count is logged.

  ---
  Kind: implement.

- 🚫 [PASS-59-0298] **One spelling per name: "Doom" and "DOOM" become one, and the AI gives official capitals (enhancement, M).**
  - **Why**: found 2026-11-10 (PASS-59-160 live check): case twins
    ("Doom" 14 games, "DOOM" 3) count as two entries in the filter
    window but filter together. Settings > Normalization cannot fix
    them: get_unique_values keys on lower case, so it hides twins, and
    apply_normalization skips a change that only alters capitals.
  - **Agreed** (user, 2026-11-10): (1) AI Fill asks for franchise,
    publisher and developer names with their official capitalisation.
    (2) A saved name equal to a library spelling apart from capitals
    takes the library's spelling. (3) Settings > Normalization lists
    each twin group, most-used spelling pre-selected; the user confirms
    or picks another, then Apply. Nothing changes without the user.
  - **Verify**: on a copy of the live DB, the twins list shows Doom /
    DOOM; applying one spelling leaves one entry with the summed count;
    a scrape bringing "doom" saves the library's spelling.
  - **Status**: todo.
  - **Dropped** (2026-11-10): filed twice; the counter gave this copy a
    padded id. The item is PASS-59-298.
  **Layman:** A franchise, publisher or developer spelled with different capitals shows as one name, spelled the official way.
  Kind: enhancement.
  Source: user-request-2026-11-10.
  Duplicate-of: PASS-59-298.

## Done index

Compact one-liner per landed pass.  Detail lives in git history
(`git log --grep "v2.83"` or similar), in `data/changelog.yaml`, and
in the commit messages themselves.  Listed in version order so the
landing sequence stays legible — Pass numbers reflect planning order
and may jump (e.g. Pass 17 → 16 → 23 → 19) because rows are sorted
by landed version.

LOC numbers in the historical rows below reflect the file size **at
the time the pass landed**, not the current file size.  Subsequent
edits drift the numbers; do not "correct" them — the historical figure
is the audit trail.

### v2.83.x — Refactoring waves (Passes 2–10)

- [x] **Pass 2 (waves 1–2)** — `@handle_api_errors` decorator + `success()` /
  `error()` response-builder helpers across 14 fully-swept routes (118
  handlers, 186 jsonify migrations).  Carry-over for partial files in
  Active.  (v2.83.5–7)
- [x] **Pass 3** — HLTB service extraction; `routes/games_hltb.py` 366 → 165
  LOC + new `services/hltb_service.py` (3 classes, typed error surface).
  (v2.83.8)
- [x] **Pass 4** — `routes/maintenance.py` split: 693 → 254 LOC + three
  service modules (`rom_scanner.py`, `media_cleanup.py`,
  `game_cleanup.py`); per-field delete blocks collapsed via `_MEDIA_LAYOUT`.
  (v2.83.10)
- [x] **Pass 5** — `scraper/metadata_merger.py` split: 1293 → 1090 LOC +
  `image_dedup.py` (dHash + post-download dedup) + `metadata_normalizer.py`
  (title/ESRB/alt-titles helpers).  (v2.83.11)
- [x] **Pass 6** — `scraper_manager.py` split: 1022 → 684 LOC + `match_scorer.py` /
  `title_normalizer.py` / `scraper_cache.py`; SS result-parsing flattened
  to `_parse_ss_result` + `_pick_ss_region`.  (v2.83.12)
- [x] **Pass 7 stages 1–3** — `routes/games.py` decomposition: 1373 → 1128
  LOC; carved `game_metadata_service.py`, `achievement_linking.py`,
  `game_media_service.py`; consolidated three normalization regimes;
  unified `apply_metadata_to_game` / `apply_hybrid_metadata_to_game`
  service entry point used by all three call sites.  (v2.83.13/16/19)
- [x] **Pass 8** — `window.API` migration across 13 JS files (83 of 84
  raw `fetch` sites collapsed); bundle 312 KB → 271 KB minified.
  (v2.83.22)
- [x] **Pass 9** — scraper/ filename consistency: `scrape_metadata_igdb.py`
  → `scrape_igdb.py`, `scrape_metadata_thegamesdb.py` →
  `scrape_thegamesdb.py`; 6 import sites updated; standards §24.1
  enforced.  (v2.83.21)
- [x] **Pass 10** — template macros: 6 modal partials extracted from
  `game_detail.html` into `templates/_modals/`; 5904 → 5376 LOC (−8.9%).
  (v2.83.23)

### v2.84.x — Security + DB perf + frontend perf + tests

- [x] **Pass 11 (7 items)** — Security hardening: PBKDF2-SHA256 100k → 600k
  with migrate-on-login, `SESSION_COOKIE_SECURE` env-gate, image-upload
  magic-byte validation, rate-limits on heavy admin routes (+ 2 stale
  endpoint-name fixes), CSRF rationale doc, root-logger `SecretRedactor`
  install.  (v2.84.0)
- [x] **Pass 12 (4 of 5)** — DB perf: per-request + long-lived `PRAGMA
  optimize`, batched job progress connection, `ANALYZE` after
  `CREATE INDEX`, `RETRODB_SLOW_QUERY_MS` query log.  12.5 (FTS5)
  deferred — see Active.  (v2.84.1)
- [x] **Pass 13** — Frontend perf: streaming image downloads
  (`iter_content`), single `app.bundle.js` split into `core.bundle.js` +
  `games.bundle.js` (127 KB savings on non-games pages), per-file
  content-hash cache-busting via `static/asset_manifest.json`.  (v2.84.2)
- [x] **Pass 14 (2 of 3)** — `.pre-commit-config.yaml` (ruff + gitleaks);
  characterisation tests for `metadata_merger.py` (30 tests) and
  `bulk_scrape.py` state machine (24 tests); 145 → 199 tests total.
  14.2 (type hints) deferred — see Active.  (v2.84.3)

### v2.85.x–v2.95.x — A11y, observability, headers, image, ops, migrations, ETag/gzip, CI, input hardening, multi-user

- [x] **Pass 15 (5 items)** — A11y round 1: skip-link, `ModalFocusTrap` (15
  call sites), theme contrast audit (`scripts/audit_contrast.py` +
  `docs/theme_contrast.md`; bladerunner contrast bumped 2.80 → 5.10:1),
  redundant ARIA sweep, keyboard-shortcut overlay refactor.  (v2.85.0)
- [x] **Pass 17 (3 items)** — Observability: `/health` + `/ready` probes,
  request-ID correlation via `setLogRecordFactory`, slow-request logging
  (`SLOW_REQUEST_MS`).  (v2.86.0)
- [x] **Pass 16 (4 items)** — HTTP security headers: drop `X-XSS-Protection`,
  add CSP **Report-Only** (per-request nonce via `secrets.token_urlsafe`),
  add `Permissions-Policy` (11 sensors/APIs), env-gated `Strict-Transport-Security`.
  Enforcing flip tracked as FU.1.  (v2.87.0)
- [x] **Pass 18 (3 items)** — Image pipeline: WebP on ingest
  (`RETRODB_IMAGE_FORMAT` + `finalize_downloaded_image`),
  `loading="lazy" decoding="async"` on every card/grid `<img>`, responsive
  `srcset` + `_make_responsive_variants`.  Grid-card srcset → FU.2.
  (v2.88.0)
- [x] **Pass 23 (9 items)** — Correctness bugfixes from 2026-04-23 review:
  scraper-manager AttributeError fix, RAWG fill-only alignment, rating
  cross-map dedup, set-iter ordering, source=rom paren fix, manuals path
  divergence, GIF animation preservation, `config.example.py` resync,
  hybrid-scraper test pin.  (v2.88.1)
- [x] **Pass 19 (8 items)** — Operational resilience: SQLite online backup
  API + integrity check, SIGTERM/SIGINT graceful shutdown, backup rotation
  (`MAX_BACKUPS`), bulk-scrape swap/demote race fix, MuseumGenerateJob
  brought up to persistence contract + dedup, `JOB_HISTORY_RETENTION_DAYS`
  sweep, `atomic_write_json` for settings, PSN ALTER table-existence
  guard.  (v2.89.0/2.90.0)
- [x] **Pass 20 (2 items)** — Versioned schema migrations: `services/migrations/`
  framework with `PRAGMA user_version`; `database_init.py` 647 → ~115 LOC;
  3 migrations seeded (baseline, normalize_genres, normalize_pegi);
  standards doc §25 added.  (v2.91.0)
- [x] **Pass 21 (2 items)** — Request-level caching: weak ETag on
  `/api/games/card-data` keyed on `MAX(updated_at)` (migration 004 +
  triggers); `compress_response` gzip after_request hook.  (v2.92.0)
- [x] **Pass 22 (8 items)** — CI/CD hardening: dependabot config, `pip-audit`
  in CI, `pytest-cov` reporting, py 3.12+3.13 matrix, semgrep wired to
  `.semgrep.yml`, signed release artifacts (cosign + SLSA + SBOM),
  destructive-endpoint coverage (landed alongside Pass 24), lockfile-drift
  test.  (v2.93.0/2.95.0)
- [x] **Pass 25 (9 items)** — Input hardening / SSRF / size caps: ES-DE
  path-traversal guard, `/api/reports` system-folder whitelist, museum
  Bing-search SSRF (`_is_public_https_url`), museum upload size cap, CLZ
  PDF page cap + scoped dup check, `MAX_VIDEO_SIZE`, response size caps
  on scraper image downloads, `MAX_LIST_ROWS` on list endpoints,
  Flask-Limiter rules on 5 expensive endpoints.  (v2.94.0)
- [x] **Pass 24 (8 items)** — Multi-user authn/authz: passwordless-editor
  bypass closed, `session.clear()` on auth boundary, force-password-change
  middleware pinned, password min 8 → 12 + change-endpoint rate-limit,
  11 destructive endpoints raised to `@editor_required`, Xbox OAuth state
  param, token JSON `0o600`, `SecretRedactor` label-gated token pattern.
  (v2.95.0)

### v2.96.x–v2.99.x — Scraper HTTP, multi-user data ownership, a11y round 2, bugfixes

- [x] **Pass 26 (5 items)** — Scraper HTTP uniformity & API-key hygiene:
  ScreenScraper + RetroAchievements through `base_scraper`, Gemini key
  out of querystring, AI circuit-breaker at call site, unified 5xx retry
  policy, mask API keys on settings GETs.  (v2.96.0)
- [x] **Pass 28 (6 items)** — A11y round 2: `<label for=>` association
  (87 sites), `ModalFocusTrap` on template-local modals, drop positive
  `tabindex` from `_modals/edit_modal.html`, skip-link verification,
  `prefers-reduced-motion` kill-switch on theme canvas, `aria-live="polite"`
  on notifications + loading containers.  (v2.97.0)
- [x] **Pass 27 (3 items)** — Multi-user data ownership round 1: `owner_id`
  on tags / lists / wishlist (migration 005), per-user PSN/Xbox tokens
  (migration 006), platform sync jobs scoped to user.  (v2.98.0)
- [x] **Pass 30 (10 items)** — Correctness bugfixes from 2026-04-24 review:
  fresh-install owner_id ordering, `scrape_history` fallback UPDATE
  removed, IGDB `themes` orphaned key removed, IGDB+TGDB
  `apply_metadata_to_game` COALESCE wrap, dashboard Resume 400s for 3
  job types, SIGTERM `cancelled` → `interrupted` for recovery banner,
  UTC datetime in bulk_scrape, `exc_info=True` in
  `handle_internal_error`, analytics cache invalidation gaps wired,
  TGDB `download_image` rename to disambiguate.  (v2.98.1)
- [x] **Pass 31 (9 items)** — Multi-user data ownership round 2: `user_id`
  on `psn_games` / `psn_trophies` (migration 007), `user_id` on
  `game_achievement_progress` + `steam_achievements` + `xbox_achievements`
  (migration 009), `user_id` on `collector_trophies` (migration 008),
  per-user Steam/PSN sync credentials, owner-scoped + role-gated PSN
  mutation endpoints, role-gated CLZ PDF import, `@editor_required` on
  `POST /game/<id>` write actions, `oauth_state_xbox` cleared across
  login boundary.  (v2.99.0)

### v3.x — Multi-user round 3, frontend defense, auth round 2, data integrity, a11y round 3

- [x] **Pass 32 (15 items)** — Input hardening round 2: filesystem-path
  validation in `api_update_paths`, per-key validators on
  `api_update_all_settings`, `api_restore` close-pool + delete-WAL/SHM,
  `clean_missing_roms` single-txn batched writes, `api_rename_rom` ROM-
  root jail, SSRF gate on `base_scraper.download_image` + media downloads,
  museum SSRF DNS-rebinding pin, CLZ PDF per-cell size cap, atomic
  image-pipeline writes + Pillow FD-leak fixes, format-vs-extension
  validation on image upload, consistent `safe_path` across media helpers,
  `api_games_bulk_edit` field names through `safe_column()`, escape
  user-controlled values in AI prompts, response-size caps on AI + RA
  HTTP, HTTP response hardening in metadata_merger image/video downloads.
  (v3.0.0)
- [x] **Pass 29 (5 items)** — Frontend defense in depth round 1: escape
  user-derived strings in `innerHTML` sinks, CSRF token propagation in
  `API.post` / `API.postForm` (lands with Pass 24 backend CSRF
  middleware), consolidate duplicate keyboard handlers + enforce
  focus-trap stacking, `try/catch` around `JSON.parse` of `localStorage`,
  `AbortController` on search-style API calls.  (v3.1.0)
- [x] **Pass 33 (11 items)** — Auth & session hardening round 2: `ProxyFix`
  env-gated, `safe_filename` on avatar upload, length-check `new_password`
  in `api_update_user`, force password change after admin reset, session
  rotation on password change, full `session.clear()` on logout, require
  Pillow for avatar upload, surface new CSRF token in login response,
  rate-limiter cleanup efficiency, `SecretRedactor` dict/bytes args,
  redact credentials in scraper INFO logs.  (v3.2.0)
- [x] **Pass 34 (7 items)** — Response envelope + observability round 2:
  `app.py` routes via `@handle_api_errors` + `success()` / `error()`,
  `inject_config` cache scraper_settings.json by mtime, delete zombie
  log helpers, rate-limiter view-function lookup hard-fail, log-rollover
  on UTC boundary, `asset_url` double-registration fix, observability on
  mutations in game routes.  (v3.2.0)
- [x] **Pass 35 (5 items)** — Data integrity & backup hardening: backup
  destination `chmod 0o600` + fsync file + parent dir, `atomic_write_json`
  fsync parent directory, `PRAGMA foreign_keys = ON` in migration
  connection, `journal_mode=WAL` / `journal_size_limit` moved to init,
  guard legacy `ensure_user_tables` ALTER blocks via
  `_add_column_if_missing`.  (v3.3.0)
- [x] **Pass 36 (10 items)** — Frontend defense in depth round 2: `escAttr`
  rewritten for JS-string context, escape system name + slug in
  `settings-page.js`, escape controller image filename in `museum.js`,
  escape log-viewer dynamic fields, migrate remaining
  `JSON.parse(localStorage.getItem(...))` sites, AbortController on
  `performGlobalSearch`, `DOM.create()` defaults to `textContent`,
  consolidate six document-level `keydown` handlers, `Storage.clearAll`
  prefix-list sync, notification container aria-live severity split.
  (v3.3.0)
- [x] **Pass 37 (7 items)** — Accessibility round 3: `<label for=>` on
  composite fields, focus trap on PSN trophies modals, reduced-motion
  kill-switch for canvas effects, `rel="noopener noreferrer"` on
  `target="_blank"`, heading hierarchy fixes, `aria-live` status regions
  on flash messages, promote hardcoded colors into variables.  (v3.4.0)
- [x] **Pass 40 (16 items)** — Tier-1 indie-review sweep (2026-04-24
  14-agent review): chdman_path RCE validator + admin gate (40.1),
  CHD convert/verify path traversal (40.2), archive-scanner m3u admin
  gate + per-entry safe_path (40.3), Steam achievements user-scoping
  IDOR (40.4), ETag cache-bleed user-id discriminator (40.5), players
  fill-only invariant + `normalize_players_value` (40.6), TGDB image
  download SSRF gate (40.7), museum job preserves failed status (40.8),
  ImageResizeJob persistence + lock discipline (40.9), shutdown-aware
  rate-limit sleeps across 5 jobs (40.10), CHD conversion atomic + verify
  wired (40.11), toast-controller XSS on system_name (40.12), showModal
  opt-in HTML via options.allowHtml (40.13), PSN trophy-detail
  game-link search XSS (40.14), `download_image` atomic + stale-clear
  race fix (40.15), `docs/PROXY-DEPLOY.md` authored for
  RETRODB_TRUST_PROXY trust contract (40.16).  (v3.4.1 — v3.5.0)
- [x] **Pass 41.1 (3 items)** — Tier-2 auth hygiene: `login_required`
  5-name allow-list bypass dropped, `api_change_password` rate bucket
  re-keyed to `(ip, user_id)` (isolated from `/api/login` and per-user),
  `count_stale_password_hashes()` startup sweep with `logger.warning`
  for active users below the OWASP PBKDF2 floor.  (v3.5.1)
- [x] **Pass 44 (multi-emulator launch — MAJOR FEATURE, 20 sub-tasks)** —
  ▶ Play button on game detail launches games via the right emulator
  (RetroArch with the right core for libretro platforms, DuckStation /
  PCSX2 / RPCS3 / Dolphin / mGBA / melonDS / Citra / PPSSPP / Cemu /
  ScummVM / MAME for standalones).  Schema: migration 010 +
  `emulators` / `system_emulators` tables + 12 emulator + 25 system-mapping
  seed.  New `Player` role + `launch` / `track_progress` permissions.
  Service layer: `services/launcher/` Protocol + LocalLauncher (Popen,
  TERM/KILL escalation, stderr tail) + ProcessRegistry (in-memory, GC TTL).
  `services/launch_resolver.py` turns game_id into argv via
  per-game-override → system-default → fallback chain, RA-special-cased
  for binary + cores dir, token-wise template substitution (no shell
  injection), ROM-path scan-root validation.  Routes: `routes/launch.py`
  (4 endpoints), `routes/emulators.py` (registry CRUD + admin page at
  `/settings/emulators`), `routes/launch_settings.py`
  (`/api/settings/retroarch/detect` probe).  UI: Play button (Jinja
  `has_perm`-gated), Launch section in edit-game modal, Settings →
  Emulators admin page (cyberpunk-themed), floating "now playing"
  indicator with kill popover.  94 new tests across 12 files (607 total,
  was 513).  (v3.6.0)

### v3.5.x — Tier-2 hardening + indie-review-2026-04-25 + refactor wave + CI hardening

The v3.5 line landed the bulk of Pass 41 (tier-2 hardening), Pass 45
(indie-review 2026-04-25 — 20 sub-items), Pass 38/42 (refactor +
consolidation waves), Pass 39 (CI/CD hardening round 2), Pass 46.1/46.2
(vendor third-party assets + pip pin refresh), and partials of Pass
43 (i18n) and Pass 47 (open-source flip prep). Per-version detail is
in `data/changelog.yaml`; per-pass detail is in the Active section of
this file. Each landed-in-v3.5.x pass is annotated with the version
in its **Status** line; `grep "done (v3.5" roadmap.md` enumerates all.

- [x] **Pass 41.2–41.14** — Tier-2 hardening across all 14 subsystems
  (auth, database, app bootstrap, scraper orchestration, scraper
  adapters, jobs, OAuth/trophy parser, achievements/trophies, game
  routes, settings/maintenance/tools, museum, frontend JS, templates
  /a11y, image/media).  See Pass 41.1–41.14 entries above and
  `tests/test_pass41_security.py`.  (v3.5.1 – v3.5.14)
- [x] **Pass 45.1–45.20** — Indie-review 2026-04-25 sweep (post-Pass-41
  cross-cutting themes T1–T14).  See Pass 45.x entries above; tests
  at `tests/test_pass45_security.py`.  (v3.5.15 – v3.5.33)
- [x] **Pass 46.1 + 46.2 + 46.3 part 1** — Vendor Chart.js + 17 WOFF2
  + pip pin refresh (6 packages) + PyInstaller spec scaffolding.  See
  Pass 46.x entries; tests at `tests/test_pass46_*`.  (v3.5.35 –
  v3.5.39)
- [x] **Pass 38 + Pass 42 refactor waves** — `apply_hybrid_metadata`
  partial extraction, scraper-settings consolidation, `installer_core.py`
  extraction, Jinja-macro extraction, removed `app.bundle.js` from
  installers, dead-code sweep, migration-helper dedup, global window
  error/unhandledrejection handler, RA 401 observability, settings.html
  split deferred.  See Pass 38.x / 42.x entries.  (v3.5.41 – v3.5.65)
- [x] **Pass 39.1–39.12** — CI/CD hardening round 2: SHA-pin actions,
  explicit `permissions:`, hard-fail pip-audit + semgrep, hash-locked
  `requirements.lock`, Dependabot lockfile regen workflow,
  env-configurable `STAGING_DIR`, multidisc-scan rate limit, gitleaks
  allowlist for test fixtures, `usedforsecurity=False` MD5/SHA1,
  gitleaks regex allowlist for Claude model literals, re-pin notes,
  Dependabot label scaffolding.  (v3.5.40 / 2026-05-02 dated entries)
- [x] **Pass 47 partials** — Pre-publish hygiene sweep + repo
  visibility flip prep (Pass 47.1–47.2 in flight as of v3.6.x).

### v3.6.x — Multi-emulator launch + test-suite audits + dependency bumps + small fixes

- [x] **Pass 44** — Multi-emulator launch (see entry above).  (v3.6.0)
- [x] **Test-suite audits + hot-fixes + UX fixes + bonus stats opt-in
  + project-path migration follow-through + AMD ROCm helper script**
  — three test-suite audit fix-passes resolving 119 + 100 + 133 raw
  findings (v3.6.8 / v3.6.9 / v3.6.14); two hot-fixes (HLTB endpoint
  `/api/find`→`/api/bleed`, scan 4xx when `rom_path` unset) (v3.6.10–
  v3.6.11); UX fix-pass (v3.6.12); CLAUDE.md staged-tree workflow
  note (between v3.6.13 and v3.6.14); dependency bumps (requests /
  onnxruntime / numpy) (v3.6.13).  See `data/changelog.yaml` for
  per-version detail.  (v3.6.1 – v3.6.14)
- [x] **Pass 47.1** — pre-publish hygiene sweep: gitleaks-all clean
  (0 leaks / 203 commits); every excluded path `git log --all` empty;
  one stray Inkscape host-path stripped from `static/images/systems/cps.svg`;
  `SECURITY.md` authored; `.github/ISSUE_TEMPLATE/` + `PULL_REQUEST_TEMPLATE.md`
  authored; README adds a Status line and a Support-development section
  pointing at GitHub Sponsors. Items 7-screenshots and 8-repo-metadata
  deferred to a maintainer-curation step and Pass 47.2 respectively.
  (v3.6.15)
- [x] **Pass 38.4** — Jinja macros + select-filter modal partial:
  `_macros/breadcrumb.html` (`breadcrumb(items)`; 11 templates
  converted), `_macros/sticky_subnav.html` (`tab_subnav` /
  `subnav_link`; all 6 settings subnav blocks converted),
  `_modals/select_filter_modal.html` ({% include %} partial for
  `all_games.html` + `system_games.html`). Pass 10 closed
  substantively. Suite 1015 → 1039 (+24). (v3.6.16)
- [x] **Pass 38.6** — Split `settings.html` by tab: six panels
  extracted into `_settings_tabs/{account,library,scraping,data,
  customization,system}.html`; shell shrank 7,368 → 5,201 lines.
  Three pre-existing source-grep tests widened via new helper
  `tests._util.read_settings_with_partials()`. Suite 1039 → 1084
  (+45). (v3.6.17)
- [x] **FU.2** — Grid-card boxart srcset: `boxart_dir_listing()`
  request-scoped scandir cache + `boxart_srcset(filename, existing=…)`
  batch mode (no per-card PIL width read); `build_game_card()` emits
  `boxart_srcset` / `boxart_3d_srcset`; `renderGameCard()` clears
  `srcset`/`sizes` in the 3D→2D `onerror` fallback. (v3.6.18)
- [x] **FU.3** — Bulk JPEG/PNG → WebP migration endpoint:
  `services/jobs/webp_migrate.py::WebPMigrateJob` (singleton
  `webp_migrate_job`); `POST /api/maintenance/convert-to-webp/
  {start,status,cancel}` in `routes/maintenance.py`. Worklist covers
  boxart / boxart_3d / fanart / screenshots; manuals + gifs skipped;
  pre-flight disk-space precheck (refuse if `free < 2 × in_scope_bytes`);
  resumes by adopting existing `.webp` siblings; wipes legacy
  `-sm.jpg` / `-md.png` and re-runs `_make_responsive_variants`
  after each conversion. (v3.6.19)
- [x] **FU.1 phase A** — CSP enforcing prep: every inline `onclick=`
  on dialog controls migrated to event-bound listeners + `csp_nonce`
  wired through `base.html`. Phase B (flip CSP to enforcing mode) and
  Phase C (remove `unsafe-inline`/`unsafe-eval`) still active. (v3.6.20)

---

<a id="scope-notes--considered-and-dropped"></a>

## Scope notes — considered and dropped

The following were considered during this planning round and intentionally
not added to the roadmap. Document here so they don't keep re-appearing.

- **Flask-Talisman**: replaces 4-8 lines of manual header setting with a
  dependency. Not worth it.
- **Flask-Migrate / Alembic**: requires SQLAlchemy adoption, which RetroDB
  explicitly doesn't use (raw SQL is part of the design). Pass 20 uses the
  suckless PRAGMA-user_version pattern instead.
- **Progressive Web App / service worker**: no offline story for a
  localhost ROM manager. Adds maintenance burden for zero user benefit.
- **Docker image / container**: `setup.sh` + `install_gui.py` already
  target bare-metal installs. A container would add a distribution surface
  without simplifying anything for current users.
- **API versioning / OpenAPI spec**: API is internal to the app. No
  external consumers to break.
- **Feature flags**: single-user app — no gradual rollouts needed.
- **Python 3.13 free-threaded build**: research confirmed single-threaded
  Flask perf regresses 30-50% in free-threaded mode. Actively avoid — pin
  to the GIL build.
- **Sentry / error tracking SaaS**: exfiltrates stack traces and request
  context to a third party. Local log files are the right place for a
  self-hosted app. Covered by Pass 17.3 instead.
- **Prometheus `/metrics`**: no scraper. Local `/health` + `/ready`
  (Pass 17.1) covers the actual need.
- **Distribution / portfolio website** (per-user landing page hosting
  RetroDB and the user's other apps with download links + donation
  CTAs): a separate, multi-app effort outside RetroDB itself. Tracked
  at the user's portfolio level, not in this roadmap. Pass 47 covers
  donation surfacing inside the RetroDB repo + app — the landing site
  comes later, host TBD (Cloudflare Pages / Netlify / GitHub Pages /
  Vercel are all viable for a static multi-app site). Mentioned here
  so the Pass 47 scope stays sharp and the website doesn't get
  retrofitted into a RetroDB-shaped pass.

---

## Audit hygiene

The 2026-04-21 ants-audit run produced 228 raw findings with only ~3
actionable (~1.3% signal rate).  The remediation belongs on the
**audit-tool side**, not in this project — it's about teaching the
audit tool to respect calibration files that already exist here
(`.semgrep.yml`, `pyproject.toml`'s ruff S-code ignores, `.gitleaks.toml`).

Those recommendations are captured in a standalone document intended
for the Claude Code session maintaining the `/audit` skill:
**`audit_hygiene.md`** (repo root).  That file is portable — it can be
handed to the audit-tool maintainer without any RetroDB-specific
context.

---

<a id="periodic-independent-review"></a>

## Periodic Independent Review

The 2026-04-23 multi-agent sweep that surfaced Passes 23-29 is the
counterweight to the "author marks own homework" problem: an agent that
wrote the code can't write tests that meaningfully vet it, because the
tests encode the same (possibly wrong) understanding.  Dispatching
multiple independent agents — each seeing only a subsystem's code + the
project docs, *not* seeing the orchestrator's prior reasoning — produces
fresh-eyes findings at full-codebase scale.

### Cadence

Re-run the multi-agent sweep:

1. **Every 5 landed passes**, or
2. **Before any minor version bump** (`x.N+1.0`), or
3. **After an architectural change** that touches >3 subsystems
   (migration, auth model change, DB schema reshape).

Whichever comes first.

### How to run

Run the sweep with the `review-code` skill over the source and the
`review-tests` skill over `tests/`. Each skill carries its own reviewer
brief, and each lane reads its files whole. Give it this partition, the
one the 2026-11-04 and 2026-11-09 sweeps used. Put a new file in the
lane that owns its subject. Split a lane when its files will not fit one
careful read; split a big file by concern, on function or block
boundaries.

**Python**

1. **Auth & security** — `services/{auth,security,log_redactor,ssrf,path_browser,platform_tokens,ra_sign_in,ra_standalone}.py`, `routes/auth.py`
2. **Database & schema** — `services/{database,database_init,atomic_io}.py`, `settings_manager.py`, `services/migrations/**`
3. **Scraper orchestration & metadata** — `scraper/{scraper_manager,hybrid_scraper,metadata_merger,metadata_normalizer,match_scorer,title_normalizer,scraper_cache,image_dedup,service_limits}.py`, `services/{game_metadata_service,normalization,field_sources,release_dates,version_groups}.py`, including the mapping tables in `normalization.py`
4. **Per-source scrapers, A** — `scraper/{base_scraper,scrape_igdb,scrape_thegamesdb,scrape_rawg,scrape_screenscraper,ss_regions}.py`, lookup tables included
5. **Per-source scrapers, B** — `scraper/{scrape_esde,scrape_ai,retroachievements,hltb_lookup}.py`, `services/ai_fill.py`, lookup tables included
6. **Platform imports** — `routes/{platform_import,steam_achievements,xbox_achievements,game_imports}.py`, `scraper/{scrape_steam,scrape_xbox,trophy_parser}.py`, `services/playtime.py`, `services/jobs/{platform_sync,psn_keepalive,psn_refresh}.py`
7. **Image pipeline** — `services/{image_utils,game_media_service,media_cleanup,screenshot_fit,box_faces,upscale_queue}.py`, `services/jobs/{image_resize,webp_migrate}.py`
8. **Background jobs** — every other `services/jobs/*.py`, `services/apply_progress.py`
9. **Game routes** — `routes/games*.py`, `routes/{versions,ai_fill_bulk}.py`, `services/{game_query,hltb_service,rpcs3_compat}.py`
10. **Maintenance, settings, systems, reports routes** — `routes/{systems,maintenance,settings,scraper,bulk_scrape,controllers,reports,mame_names}.py`, including the `SYSTEM_DEFAULT_CONTROLLER` table
11. **ROM scanning & validators** — `services/{rom_scanner,game_cleanup,rom_identity,rom_tools_validators,settings_validators,scraper_settings_validators,mame_names,disc_serial}.py`, `scraper/{scan_roms,rom_tools}.py`
12. **Collections, museum, imports** — `routes/{collections,museum,bonus_discs,clz_import}.py`, `services/wishlist_scraper.py`
13. **Achievements, trophies, tools** — `routes/{achievements,trophies,collector_trophies,ra_sync,scrape_logs,tools}.py`, `services/achievement_linking.py`
14. **Core app** — `app.py`, `config.example.py`, `server_port.py`, `log_manager.py`, `platform_utils.py`
15. **Shared utilities & i18n** — `services/{api_helpers,template_filters,formatters,game_utils,analytics,assets,i18n,i18n_labels,service_stop_text}.py`
16. **Launch, cheats, updater** — `updater_apply.py`, `services/{updater,cheats,launch_resolver,player,player_install,retroarch_command}.py`, `routes/{launch,cheats,updates}.py`
17. **Emulator settings** — `services/launcher/*`, `services/{player_cores,standalone_settings,emulator_adapters,emulator_seeder,disc_files}.py`, `routes/{launch_settings,emulators}.py`
18. **Worker processes** — `services/{upscale_worker,rembg_worker,gpu_env}.py`

**JavaScript and templates** (templates under `templates/`, scripts under `static/js/`)

19. **Core JS** — `utils.js`, `main.js`, `global-search.js`, `theme.js`
20. **Shell & jobs** — `toast-controller.js`, `launch-indicator.js`, `game-launch.js`, `apply-progress.js`, `updates.js`, `base.html`, `_macros/*`, `_changelog_entries.html`, `changelog.html`
21. **Game JS & modals** — `game-modals.js`, `game-box-faces.js`, `game-cheats.js`, `game-emulator-settings.js`, `manual-reader.js`, `box-viewer.js`, `versions.js`, `ra-sign-in.js`, `_modals/*`
22. **Game page** — `game_detail.html` markup and inline script
23. **Library** — `all-games-controller.js`, `filters.js`, `bulk-scrape.js`, `bulk-edit.js`, `game-list.js`, `ai-fill-bulk.js`, `all_games`, `system_games`, `_bulk_edit_modal`, `_bulk_scrape_modal`, `ai_fill_bulk`, `compare_games`
24. **Collections pages** — `lists`, `list_detail`, `wishlist`, `tags`, `museum.js`, `museum`, `museum_system`, `versions_review`, `mame_names`, `mame-names.js`
25. **Settings page** — `settings.html` inline script, `settings-page.js`
26. **Settings tabs & sign-in** — `_settings_tabs/*`, `settings_emulators.html`, `emulators-settings.js`, `setup`, `login`, `force_change_password`
27. **ROM tools pages** — `rom-tools.js`, `rom_tools_hub`, `rom_tools_settings`, `archive_scanner`, `chd_verify`, `chd_converter`, `multi_disc_organizer`
28. **Maintenance pages** — `duplicate_finder`, `screenshot_dedup`, `screenshot_review`, `hltb_review`, `logs.html`, `log-viewer.js`, `game_imports`
29. **Achievements pages** — `achievements.js`, `achievements_system`, `achievement_game`, `steam_*`, `xbox_*`, `collector_trophies`, `achievements_ra_empty`
30. **Trophy pages** — `psn_trophies`, `psn_trophy_detail`, `local_trophies`, `local_trophy_detail`
31. **Analytics & reports** — `analytics.html`, `reports.html`
32. **Dashboard, systems, help** — `dashboard.html`, `systems.html`, `help.html`

**CSS** (under `static/css/`)

33. **CSS foundation** — `core/*`, `components/*`, `layout/*`, `effects/*`, `utilities.css`
34. **CSS pages** — `pages/*`, plus the inline style block in `settings.html`
35. **CSS features** — `features/*`, plus the inline style block in `game_detail.html`

**Tooling**

36. **Build, install, CI** — `build_*.py`, `install.py`, `install_gui.py`, `installer_core.py`, `scripts/`, `pyproject.toml`, `.semgrep.yml`, `.gitleaks.toml`, `.pre-commit-config.yaml`, `.github/workflows/*`

**Tests** go to `review-tests`: `tests/`, whole files, packed in name order.

**Not reviewed:** generated output (`core.bundle.js`, `games.bundle.js`, `main.min.css`, `services/js_i18n_strings.py`), vendored code (`static/js/vendor/`), and the translated help copies (`help.<locale>.html`). `static/css/main.css` is not in `build_css.py`'s `CSS_ORDER`, so nothing builds or loads it.

The harness runs at most 20 helpers at once, so the lanes go in waves.

### Triage rules

- Any **CRITICAL runtime bug** across two or more reports → land as the
  next pass.
- **Security findings** → weight against the "single-user localhost"
  threat model documented below; HIGH on SaaS ≠ HIGH here.
- **Consistent drift between CLAUDE.md and code** → either fix the code
  or fix the doc; don't let the claim stand unverified.
- **Findings already on the roadmap** → skip (acknowledge + link to the
  existing pass, don't duplicate).

The resulting triage lives as new numbered passes inserted before the
follow-ups section (see Passes 23-29 for a worked example).

---

## Notes

- Refactor passes that touch `services/*.py` or `scraper/*.py` must run
  `python3 -m pytest` (per CLAUDE.md workflow rule #4).
- Each pass should be its own patch version bump + changelog entry — they
  are behaviour-preserving by design, so `x.y.Z+1` is appropriate.
- Update this file (tick items, add notes) as work lands.
- **Severity calibration** for security items uses the single-user
  localhost threat model documented in `.semgrep.yml`.  Items that would
  be HIGH on a public-facing SaaS (e.g. CSRF, cookie flags) are LOW here;
  see §22 of the design standards doc.
- **Online sources** cited in specific passes are captured at time of
  writing (2026-04-21).  If >6 months old when you pick up the work,
  re-check OWASP / CVE databases for newer guidance.
