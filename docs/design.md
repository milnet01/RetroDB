# RetroDB — Design

> **Purpose — so that a contributor can tell what RetroDB is for, who it
> serves, how its parts fit, and which document owns each rule.** This file
> links; it does not restate. Each rule's detail lives in the spec it names.

Recorded 2026-10-17 (roadmap PASS-59-65). Settled decisions live in
[`decisions/`](decisions/README.md).

## 1. What RetroDB is for

RetroDB is a web application for organising a retro game ROM collection. It
catalogues games per system, fills in their metadata and artwork from online
sources, tracks play progress and achievements, and launches games in an
emulator. The feature list is in [`../README.md`](../README.md) § Features.

It ships to Patreon supporters in two shapes: a source zip and a standalone
PyInstaller bundle. How each is built is in `.claude/rules/distribution.md`.

## 2. Who uses it

One household runs one install. The person who installs it is the admin.
Other household members get their own accounts, each with one role:
admin, editor, player and viewer. The roles and their permissions are
`services/auth.py::ROLE_PERMISSIONS`; their intent is
[`specs/auth.md`](specs/auth.md) § 2.

## 3. Deployment and threat model

Decided in [decision 0001](decisions/0001-threat-model.md). In short:

- RetroDB is designed for a trusted home network.
- The server binds every network interface by default, so household devices
  can reach it. The default is `SERVER_HOST` in `config.example.py`;
  `RETRODB_HOST` overrides it.
- It is not designed to face the internet directly. Anyone who exposes it
  follows [`PROXY-DEPLOY.md`](PROXY-DEPLOY.md): a TLS-terminating reverse
  proxy and `RETRODB_TRUST_PROXY=1`.
- Every role signs in with a password (Pass 24.1, `routes/auth.py::api_login`).
- The viewer role can only read the library and track its own progress.
- A finding's severity is judged against a curious guest on the home Wi-Fi,
  not a remote attacker.

## 4. Subsystems

**Web layer.** Flask blueprints in `routes/` serve the pages and the `/api/*`
JSON routes. The standard JSON reply envelope is built by `success()` and
`error()` in `services/api_helpers.py`. Status codes, ETag, gzip, rate limits,
CSRF and security headers are [`specs/api-contracts.md`](specs/api-contracts.md).

**Accounts and access.** Sign-in, sessions, roles, route gating and per-user
data are [`specs/auth.md`](specs/auth.md).

**Database.** One SQLite database, reached through
`services/database.py::get_db`. Schema changes are numbered migrations in
`services/migrations/`. The runner is [`specs/migrations.md`](specs/migrations.md);
the authoring rules are
[`RETRODB_DESIGN_STANDARDS.md`](RETRODB_DESIGN_STANDARDS.md) § 25.

**Scraping.** `scraper/hybrid_scraper.py` walks one primary metadata source,
then fills gaps from the others in the user's priority order. Sources, merge
priority and match scoring are [`specs/scrapers.md`](specs/scrapers.md).

**Images.** Every stored image is converted to WebP by default, resized, given
`srcset` variants and de-duplicated. That is
[`specs/image-pipeline.md`](specs/image-pipeline.md).

**Background jobs.** Bulk scrapes, trophy syncs and image passes run as
cancellable singleton jobs on `services/jobs/base.py`. That is
[`specs/jobs.md`](specs/jobs.md).

**Settings.** Settings live in several stores, from `config.py` to per-user
rows. Which store holds what, and which wins, is
[`specs/settings.md`](specs/settings.md).

**Launching games.** `services/launch_resolver.py` picks the emulator and
`services/launcher/` starts it. The contract is
[`specs/PASS-59-64-launcher.md`](specs/PASS-59-64-launcher.md).

**ROM Tools.** Archive cleaning, M3U building, CHD conversion and duplicate
removal under the ROM folder. What each tool may change, and who may run it,
is [`specs/rom-tools.md`](specs/rom-tools.md).

**Trophies and achievements.** Progress from RetroAchievements, PSN, Steam,
Xbox and RPCS3 trophy files, kept per user. That is
[`specs/trophies.md`](specs/trophies.md).

**Interface.** Jinja templates in `templates/`, with CSS and JS in `static/`.
UI rules are [`RETRODB_DESIGN_STANDARDS.md`](RETRODB_DESIGN_STANDARDS.md).
Themes are [`specs/themes.md`](specs/themes.md).

**Translation.** Flask-Babel catalogs, plus whole per-locale files for the
help manual and changelog. That is [`specs/i18n.md`](specs/i18n.md).

**Updates.** RetroDB checks GitHub Releases for a newer version, and an
admin installs it with one click: the download is checked against the
release's SHA-256, the database is backed up, and the new version's helper
swaps the files, restarts, and rolls back if the new version does not come
up. That is [`specs/PASS-59-169-self-updater.md`](specs/PASS-59-169-self-updater.md).

### Subsystems without a spec

Recorded under PASS-59-66 (2026-10-17) so the next audit does not decide this
again. Each fails every trigger in `spec-format.md` § 1: one subsystem,
obvious in shape, cheap to redo. If a change to one spreads to a second
subsystem, write the spec then (§ 1's escape hatch).

- **Collections** (`routes/collections.py`) — tags, lists and wishlist over
  existing game rows. Per-user ownership is `owner_id` through
  `_owner_clause()`, stated in the module header. Nothing outside binds to it.
- **Analytics** (`services/analytics.py`, `/analytics` in `app.py`) —
  read-only chart data. It writes nothing, so a wrong result is a display
  defect.
- **Museum** (`routes/museum.py`) — per-system pages with AI-generated text.
  The content can be regenerated, and no other subsystem reads it.
- **Import** (`routes/clz_import.py`, `routes/platform_import.py`,
  `routes/game_imports.py`) — inserts new game rows from a CLZ export or a
  platform library. The platform tokens and achievement syncs it starts are
  in [`specs/trophies.md`](specs/trophies.md).

## 5. Rules that cross subsystems

- **Fill-only scraping.** A scraper never overwrites a filled field, except
  in Full Re-scrape mode. Decided in
  [decision 0002](decisions/0002-fill-only-scraping.md); the contract is
  [`specs/scrapers.md`](specs/scrapers.md) § 5.
- **Per-user data.** Every table holding one user's state carries an owner
  column, and every read filters on it.
  [`specs/auth.md`](specs/auth.md) § 5.
- **Error replies.** A failed request answers with a 4xx or 5xx status and
  the `success: false` envelope.
  [`specs/api-contracts.md`](specs/api-contracts.md) § 3.
- **Translation.** Every user-facing string is wrapped for translation.
  [`specs/i18n.md`](specs/i18n.md) § 2, and `CLAUDE.md` § Mandatory Workflow.
- **Build and bundles.** CSS and JS are edited as source files and built into
  minified bundles by `build_css.py` and `build_js.py`. The bundles and the
  page opt-ins are `CLAUDE.md` § CSS / JS Build Contracts.
