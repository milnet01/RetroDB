<!-- ants-spec-format: 1 -->
# PASS-59-270 — Port RetroDB to a native Rust + Slint app for desktop and Android

**Status:** accepted (2026-11-09; contract gate cancelled for this project). Building starts after v4.0.0.
**Kind:** feature.
**Source:** ROADMAP PASS-59-270 (user request, 2026-11-09).

**Blocked by:** PASS-59-113 (the v4.0.0 release; building starts after it ships).
**Pairs with:** PASS-59-269 (load the upscaler only while it runs).

Layman: RetroDB becomes a light app you install on a PC or an Android phone, instead of a web page that needs a browser, and it gains home-made themes and plugins.

## 1. Goal

One Rust codebase builds RetroDB for Windows, Linux, macOS and Android. It opens the user's existing library unchanged. It uses far less memory than today's server plus browser. Each screen remembers where the user was. Users can install home-made themes and sandboxed plugins. The Python web app's last version is 4.0.0 (user, 2026-11-09): it stays available to download, and gets only security and data-loss fixes (4.0.x) until the native app does everything it does. The native app's first version is 5.0.0, because the 4.0.0 updater treats 5.0.0 and up as the desktop app (`docs/specs/PASS-59-169-self-updater.md` §3).

## 2. Problem

1. **Memory.** The live server process held about 730 MB resident on 2026-11-09, idle (`grep VmRSS /proc/<pid>/status` → `747452 kB`; `RssAnon` → `729932 kB`). The browser tab costs more on top of that. The user wants something "very, very RAM friendly" without the browser's overhead.
2. **No phone app.** RetroDB on a phone today is a web page served by the PC. It does nothing when the phone is away from home.
3. **Themes are code.** A theme is a block of CSS inside the app (`docs/specs/themes.md` §1). Users can't make or share their own the way they can for ES-DE or LaunchBox.
4. **No plugins.** Every scraper, importer and emulator launcher is built into the app.

## 3. Scope decisions (agreed with the user)

All made by the user on 2026-11-09:

- **Language and toolkit: Rust + Slint.** C++/Qt and Rust + web view (Tauri) were offered and declined (§8).
- **One codebase** for Windows, Linux, macOS and Android. There is no second full app to maintain.
- **Android runs both modes**, picked in its settings:
  - **standalone**: its own library and ROMs on the phone;
  - **companion**: browses and edits the PC's library over home Wi-Fi.
- **Android can copy ROMs from the PC to the phone**, either all of them or ones the user picks, so the phone works away from home.
- **Plugins run in WebAssembly**, sealed off, with each permission approved by the user. Lua was declined (§8).
- **Themes have two levels:** skins (a text file plus pictures, fonts and sounds) and layout themes (Slint screen files loaded at runtime).
- **Building starts after v4.0.0 ships.** The plan is written now.

Recommended by this session and accepted with the choices above:

- **Each screen keeps its state and drops its view** (§4.4).
- **The phone's remote view replaces a separate web app.** The Python app stops at 4.0.x (§1).

## 4. Design

### 4.1 Shape of the code

One Cargo workspace (Rust's way of grouping several packages into one project):

```
retrodb/
  crates/
    core/        database, settings, migrations, jobs, launch rules; no UI
    scrapers/    one module per source; fill-only merge rules
    media/       image decode/resize, upscaler helper launcher
    sync/        PC <-> phone companion protocol and ROM copy
    plugins/     WebAssembly host and the plugin interface
    themes/      skin + layout-theme loader and fallback
    ui/          Slint screens, screen-state store, navigation
    app-desktop/ entry point for Windows / Linux / macOS
    app-android/ entry point for Android (android-activity backend)
    upscaler/    separate helper program; onnxruntime via the `ort` crate
```

`core` never depends on `ui`, so the companion server and tests can use it without a window.

### 4.2 Data compatibility

- The native app opens the same SQLite file (`config.DB_PATH`, default `database/roms.db`) and the same media folders.
- The schema version stays the `PRAGMA user_version` cursor (`docs/specs/migrations.md` §3). The Rust runner continues the same numbering, append-only (§4 of that spec).
- **Only one app migrates.** Until cut-over, the Python app owns migrations. The native app refuses to write to a database whose `user_version` is newer than it knows, and opens it read-only instead.
- The fill-only scrape rule, its five exceptions, and the title lock (project `CLAUDE.md` § Scraper fill-only invariant) carry over unchanged. `tests/test_scrape_fill_only.py` is the answer key for the Rust port.

### 4.3 Memory and speed rules (the coding standard's core)

The full standard ships as `docs/standards/rust.md`. Its binding rules:

- `#![forbid(unsafe_code)]` in every crate except a named, reviewed FFI shim. FFI (code that calls a library written in another language) covers onnxruntime and Android glue.
- No `Rc`/`Arc` cycles. A back-pointer is a `Weak`. `Box::leak` and `mem::forget` are banned outside program-lifetime statics.
- Every cache has a byte cap and evicts least-recently-used entries first. No collection grows without a named cap.
- Every channel is bounded. Every spawned task is owned by a screen or a job and is cancelled when its owner ends.
- Images are decoded at display size. Lists build only visible rows. Database reads are paged.
- Nothing slow runs on the UI thread.
- Heavy features load on first use. The upscaler runs as a separate program that exits when its job ends.
- Each screen has a memory budget and the app has a startup-time budget, both checked in CI (§7).

### 4.4 Screen state: keep the state, drop the view

```rust
/// Saved when a screen is left; restored when it is shown again.
#[derive(Serialize, Deserialize)]
struct ScreenState {
    screen: ScreenId,            // e.g. Library, System(id), Game(id)
    scroll: f32,                 // scroll position
    selection: Option<GameId>,
    filters: FilterSet,          // filters and sort
    open_panels: Vec<PanelId>,
    draft: Option<DraftEdits>,   // unsaved edits, kept until saved or discarded
}
```

- When a screen is left, its `ScreenState` is saved and the view is freed.
- The states live in a new `screen_state` table, per user, so they survive a restart.
- An unsaved edit is never lost by navigating away.

### 4.5 Themes

```
themes/<name>/
  theme.toml        name, author, version, level = "skin" | "layout", min_app_version
  colours, fonts, images, sounds    (skin)
  screens/*.slint   (layout only; loaded with slint-interpreter)
```

- A theme sees only the data the app hands it (game fields, media paths). It has no file, network or settings access.
- A theme that fails to load or compile falls back to the built-in theme and says why.
- Today's seven themes (`docs/specs/themes.md` §2) become built-in skins.
- Runtime-loaded `.slint` files cost more memory than compiled ones. Source: https://docs.rs/slint-interpreter/latest/slint_interpreter/ . So only the active layout theme is loaded.

### 4.6 Plugins

- Plugins are WebAssembly components. Their interface is written in WIT, the WebAssembly interface language, versioned from `1.0`.
- **Plugin kinds:** scraper, importer, emulator launcher, exporter, job tool.
- A plugin declares its permissions in its manifest: network hosts, read-only folders, database fields it may fill. The user approves them at install time.
- Scraper plugins return data. They never write to the database themselves; the host applies the fill-only merge (§4.2).
- A plugin is loaded on use, and dropped after a set idle time.
- **Engine:** desktop uses Wasmtime. On Android, Wasmtime has been reported as Tier 3 (Source: https://bytecodealliance.github.io/zulip-archive/stream/217126-wasmtime/topic/Wasmtime.20Android.20arm64.html), so the Android engine is decided by a test build (§15).

### 4.7 Android

- Built with Slint's Android backend. It is Rust-only and stable since Slint 1.5. Sources: https://docs.slint.dev/latest/docs/slint/guide/platforms/android and https://slint.dev/blog/slint-1.5-released .
- **Playing a game** hands it to the installed Android emulator app (RetroArch, DuckStation and others) instead of starting a program.
- **ROM folders** are chosen through Android's own folder picker.
- **Companion mode:** the PC app runs an optional, off-by-default sync service on the home network. Pairing uses a one-time code shown on the PC. All traffic is encrypted and limited to paired devices.
- **ROM copy:** the user picks all ROMs, a system, or single games.
  - Each file is checked by hash after copying.
  - An interrupted copy resumes where it stopped.
  - The phone shows the free space it needs before starting.
  - Multi-disc sets copy with their `.m3u` playlist.
  - MAME sets copy whole.
  - Copied games are marked as local to the phone.

### 4.8 Translations and accessibility

- UI strings use Slint's `@tr()` and gettext. The existing `.po` catalogs are migrated rather than re-translated. Source: https://docs.slint.dev/latest/docs/slint/guide/development/translations/ .
- Screen readers work on desktop through AccessKit. Source: https://slint.dev/blog/slint-1.1-released . Android screen-reader support is checked in the test build (§15).
- Text size, high contrast and full keyboard and gamepad control are required on every screen.

### 4.9 Licence

Slint is used under its Royalty-free licence. That requires showing that the app uses Slint, for example with an About Slint panel. Source: https://slint.dev/terms-and-conditions . RetroDB stays MIT.

## 5. Invariants

- **INV-1** — The native app never changes the database layout of a database whose `user_version` is newer than its own. It opens that database read-only.
  *Test:* `crates/core/tests/migrations.rs` opens a fixture database one version ahead and asserts that every write fails and the file's bytes are unchanged.
  *Breaks when:* the runner migrates or writes without comparing `user_version` first.

- **INV-2** — A scrape never blanks or replaces a stored value except through the five exceptions in the project `CLAUDE.md` § Scraper fill-only invariant.
  *Test:* a Rust port of `tests/test_scrape_fill_only.py`, run against the same fixtures.
  *Breaks when:* a merge writes a source's empty value over a stored one.

- **INV-3** — Leaving and returning to any screen restores its `ScreenState`, including unsaved edits.
  *Test:* `crates/ui/tests/screen_state.rs` drives each screen: set filters, scroll and a draft edit, navigate away, return, compare.
  *Breaks when:* a screen keeps state only in its view, which is freed on leave.

- **INV-4** — Opening and closing every screen 1,000 times returns resident memory to within 5% of its starting value.
  *Test:* the soak test `crates/ui/tests/soak.rs`, run in CI on Linux.
  *Breaks when:* a reference cycle, an unbounded cache or an orphaned task keeps a freed view alive.

- **INV-5** — A theme or plugin reaches no file, host or setting it did not declare and the user did not approve.
  *Test:* `crates/plugins/tests/sandbox.rs` and `crates/themes/tests/sandbox.rs` load fixtures that try each forbidden access and assert refusal.
  *Breaks when:* the host links a capability into every instance instead of per manifest.

- **INV-6** — A ROM copied to the phone matches the PC file's hash, or is deleted and reported.
  *Test:* `crates/sync/tests/copy.rs` corrupts a chunk in transit and asserts that the file is rejected and the copy resumes.
  *Breaks when:* the copy trusts the transfer without checking the hash.

- **INV-7** — Companion mode accepts connections only from paired devices, over an encrypted channel.
  *Test:* `crates/sync/tests/pairing.rs` connects without pairing and asserts refusal.
  *Breaks when:* the sync service starts without the pairing check, or listens when the user has not switched it on.

## 6. Failure modes

- **A theme fails to compile** → the built-in theme loads and the user is told which file failed.
- **A plugin crashes, overruns its time, or overruns its memory limit** → its call fails, the host carries on, and the plugin is marked faulty.
- **The PC is unreachable in companion mode** → the phone shows its last synced copy, read-only, and says so.
- **The phone runs out of space mid-copy** → the copy pauses and keeps finished files. Partial files are removed.
- **The upscaler helper crashes** → the job fails with its reason, and the app's memory is unaffected.
- **Both apps run against one database before cut-over** → SQLite's locking (`docs/specs/migrations.md` §6) serialises writes, and INV-1 stops layout changes.

## 7. Tests

- Today's Python tests are the reference for porting each service. Their fixtures are reused wherever the behaviour is the same.
- Each invariant's test is named in §5 and listed in §10. Each must be seen failing against a deliberately broken build before it counts.

| Invariant | Test |
|-----------|------|
| INV-1 | `crates/core/tests/migrations.rs` |
| INV-2 | Rust port of `tests/test_scrape_fill_only.py` |
| INV-3 | `crates/ui/tests/screen_state.rs` |
| INV-4 | `crates/ui/tests/soak.rs` |
| INV-5 | `crates/plugins/tests/sandbox.rs`, `crates/themes/tests/sandbox.rs` |
| INV-6 | `crates/sync/tests/copy.rs` |
| INV-7 | `crates/sync/tests/pairing.rs` |

- CI runs the soak test (INV-4), a per-screen memory budget check and a startup-time check on Linux. Windows and Android are checked by hand before each release.

## 8. Alternatives considered (and rejected)

- **C++ with Qt/QML.** It's mature, and Pegasus shows QML themes work. Rejected because C++ cannot guarantee freedom from memory leaks, which the user asked for.
- **Rust + web view (Tauri).** It reuses today's pages and ships soonest. Rejected because it still runs a browser engine, which costs the memory the user wants to save.
- **Keep Python and wrap it in a window.** Least work. Rejected because it keeps the Python server's memory use and adds no Android app.
- **Lua plugins.** Lightest. Rejected by the user: plugins would be Lua-only and less sealed off.
- **A second full web app beside the native one.** Rejected because it doubles every change. The phone and the companion mode cover remote use.

## 9. Out of scope

- Loading the upscaler only while it runs, in today's app — tracked by PASS-59-269.
- iOS — deferred; not yet queued.
- Importing ES-DE or LaunchBox theme files directly — deferred; not yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `crates/core/tests/migrations.rs` (to be written) |
| INV-2 | Rust port of `tests/test_scrape_fill_only.py` (to be written) |
| INV-3 | `crates/ui/tests/screen_state.rs` (to be written) |
| INV-4 | `crates/ui/tests/soak.rs` in CI (to be written) |
| INV-5 | `crates/plugins/tests/sandbox.rs`, `crates/themes/tests/sandbox.rs` (to be written) |
| INV-6 | `crates/sync/tests/copy.rs` (to be written) |
| INV-7 | `crates/sync/tests/pairing.rs` (to be written) |
| §4.3 no `unsafe` | `#![forbid(unsafe_code)]`, enforced by the compiler |
| §4.3 bounded caches and channels | **nothing** — a review judgement; a Clippy lint may cover part of it later |
| §4.9 Slint disclosure | **nothing** — checked by hand before each release |

## 11. Cross-doc impact

- `docs/design.md` gains the native app as its target architecture once phase 1 lands.
- `docs/standards/rust.md` is new: the coding standard from §4.3.
- Project `CLAUDE.md` gains the Rust build and check steps when the workspace exists.
- `docs/specs/themes.md` and `docs/specs/migrations.md` each name this spec for the native app.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-270-native-app-port-loop-log.md`.

## 13. Resource cost

Starting targets. The test build may revise them, and any revision is recorded here:

- Idle desktop app, library shown: under 150 MB resident.
- Each screen: under 80 MB above idle.
- Cold start to library shown: under 1.5 seconds on the user's PC.
- Upscaler helper: its memory is freed when it exits.

New dependencies: `slint`, `slint-interpreter`, `rusqlite` (with bundled SQLite), `ort`, `wasmtime`, `serde`, an HTTP client, and an image decoder. Each is added under `docs/DEPENDENCY_POLICY.md`.

## 14. Migration / compatibility

- **No data conversion.** The database and media folders are shared (§4.2).
- **Migrations:** Python keeps owning them until cut-over, then Rust takes over the numbering.
- **Before cut-over, both apps can run.** Only one should run scrape jobs at a time; the job locks (`docs/specs/jobs.md` §5) live in the same database.
- **Accounts:**
  - Desktop keeps users and roles (`docs/specs/auth.md` §2).
  - Sign-in is optional on a single-user PC.
  - Per-user service tokens (`docs/specs/auth.md` §6) move to the operating system's password store.

## 15. Open questions

Each is settled by the phase-0 test build in the plan:

- Which WebAssembly engine runs plugins on Android: Wasmtime, or a pure interpreter such as wasmi.
- Whether AccessKit screen-reader support works on Android with Slint.
- How the 20 translated Help pages and translated changelogs are shown: a built-in reader, or the system browser.
- Whether a closed window keeps background jobs running from a tray icon. Recommended: yes.
