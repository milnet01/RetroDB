# PASS-59-270 — native app port — build plan

**Spec:** [docs/specs/PASS-59-270-native-app-port.md](../specs/PASS-59-270-native-app-port.md)
**Status:** not started (2026-11-09). Starts after v4.0.0 ships (PASS-59-113).

## Steps

### Phase 0 — prove the risky parts first

1. Write `docs/standards/rust.md` from spec §4.3 → **verify:** each spec §4.3 rule appears in it with how it is checked.
2. Test build: a Slint window that lists games from a copy of the real database, built for Linux, Windows (`ssh wintest`) and an Android phone → **verify:** the same game count shows on all three; resident memory recorded in spec §13.
3. On the Android test build, try Wasmtime and wasmi with one sample plugin, and try a screen reader → **verify:** spec §15's first two questions are answered and recorded there.
4. Load one sample layout theme through `slint-interpreter` → **verify:** the theme shows; a broken copy falls back with a message.

### Phase 1 — core with no screens

5. Create the Cargo workspace (spec §4.1) and CI: build, Clippy, tests, `cargo deny` → **verify:** CI passes on an empty workspace.
6. `core`: open the database, read settings, check the migration version → **verify:** INV-1's test fails against a runner without the version check, then passes.
7. `core`: game queries, matching `_build_games_query`'s results (regional-version grouping included) → **verify:** a comparison script lists the same games in the same order as the Python app for ten saved filters.

### Phase 2 — browse and play (desktop)

8. Library, system and game screens, with the screen-state store (spec §4.4) → **verify:** INV-3's test passes; you use it day to day.
9. Launch through emulator mappings, as today's launcher does (`docs/specs/PASS-59-64-launcher.md`) → **verify:** a RetroArch game and a standalone-emulator game each start from the native app.
10. Soak test and memory-budget checks in CI → **verify:** INV-4's test fails against a build with a deliberate cache leak, then passes.

### Phase 3 — edit and scrape

11. Edit modals and hand-edit crediting → **verify:** an edit made natively shows as `(manual)` in the Python app.
12. Fill-only merge, then each scraper in turn → **verify:** the INV-2 port passes; the same game scraped by both apps gives the same stored row.

### Phase 4 — everything else

13. Jobs, upscaler helper, achievements, trophies, cheats, Steam/PSN/Xbox imports, ROM tools, museum, i18n catalogs → **verify:** a feature checklist built from `routes/` is ticked, item by item, against the Python app.

### Phase 5 — themes and plugins

14. Skins (today's seven themes as built-ins), then layout themes → **verify:** INV-5's theme test passes; a sample skin and a sample layout theme load.
15. Plugin host and WIT interface `1.0`, then one scraper moved into a plugin → **verify:** INV-5's plugin test passes; the plugin scraper fills the same fields as the built-in one.

### Phase 6 — Android

16. Android standalone mode: folder picker, launching through Android emulator apps → **verify:** a game starts in RetroArch for Android from the phone.
17. Pairing and companion mode (spec §4.7) → **verify:** INV-7's test passes; the phone edits a game and the PC shows the change.
18. ROM copy to the phone → **verify:** INV-6's test passes; a multi-disc game copied with its `.m3u` plays on the phone with Wi-Fi off.

### Phase 7 — ship and cut over

19. Installers (Linux AppImage or Flatpak, Windows installer, Android APK), self-updater, About Slint panel → **verify:** a clean install on `wintest` and on a phone; an update from the previous version installs.
20. Cut-over: the first native release is 5.0.0; the Rust runner takes over migrations; 4.0.x fixes stop → **verify:** a 4.0.0 web install's Settings > Updates offers the 5.0.0 download page and no install; the native app migrates a copy of the live database; the Python app then opens it read-only.

## Definition of done

Every item on the phase 4 feature checklist is ticked. All seven invariant tests pass in CI. The native app runs the live library on Linux, Windows and Android within the spec §13 budgets.
