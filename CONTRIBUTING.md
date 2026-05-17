# Contributing to RetroDB

Thank you for your interest in contributing to RetroDB! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10+ (CI tests on 3.12 and 3.13)
- pip
- Git

### Getting Started

1. **Clone the repository:**
   ```bash
   # Replace YOUR_USERNAME with your GitHub fork-owner (or use the upstream URL
   # once published).
   git clone https://github.com/YOUR_USERNAME/RetroDB.git
   cd RetroDB
   ```

2. **Run the installer:**
   ```bash
   python install.py
   ```

3. **Configure for development:**
   Set the `RETRODB_DEBUG` environment variable to enable Flask's auto-reloader and debug output:
   ```bash
   export RETRODB_DEBUG=true
   ```
   (`DEBUG_MODE` in `config.py` reads from this env var and defaults to `false` for safety — the Werkzeug debugger exposes an RCE endpoint if the server is bound to a non-localhost address, so we don't ship with it on.)

4. **Start the development server:**
   ```bash
   python app.py
   ```

## Project Architecture

Top-level layout (run `ls` for the live tree; this list rots fast):

- `app.py`, `config.py`, `config.example.py`, `settings_manager.py`, `platform_utils.py`, `log_manager.py` — Flask entrypoint, configuration, cross-platform helpers, file-based logger.
- `build_css.py`, `build_js.py`, `build_dist.py`, `install.py`, `install_gui.py`, `retrodb.spec` — build & packaging.
- `routes/` — Flask blueprints (30 route files at time of writing; `ls routes/` for the current set).
- `scraper/` — metadata sources + the hybrid orchestrator (TGDB, IGDB, RAWG, ScreenScraper, ES-DE, Steam, Xbox, RetroAchievements, AI Fill, plus shared `base_scraper.py`, `metadata_merger.py`, `match_scorer.py`, `metadata_normalizer.py`, `title_normalizer.py`, `scraper_cache.py`).
- `services/` — business logic and shared helpers (auth, security, database, atomic IO, log redaction, image pipeline, achievements linking, game utilities, jobs package, launcher package, migrations package, validators…).
- `services/jobs/` — background-job classes (bulk_scrape, hltb_bulk, image_resize, museum, platform_sync, psn_refresh, ra_refresh, ra_sync, alt_titles_backfill) on top of `base.py`.
- `services/migrations/scripts/` — versioned schema migrations (`001_baseline.py` … `012_emulators.py` at time of writing).
- `templates/` — Jinja2 templates; `static/css/` and `static/js/` — modular CSS/JS built by `build_css.py` / `build_js.py`.
- `tests/`, `.github/workflows/` — pytest suite + CI/release pipelines.
- `data/`, `database/`, `logs/` — runtime state (not in source ZIPs; see `build_dist.py`).

## Code Style

RetroDB follows the conventions documented in [docs/RETRODB_DESIGN_STANDARDS.md](docs/RETRODB_DESIGN_STANDARDS.md). Key points:

- **Python**: Standard Python conventions, 4-space indentation
- **Templates**: Jinja2 with `{% extends "base.html" %}`
- **CSS**: Modular files in `static/css/`, built with `build_css.py`. Use CSS variables from `core/variables.css`
- **JavaScript**: Vanilla JS, no framework. Shared utilities in `static/js/utils.js`

### Inline Styles

- Avoid inline CSS and JS in templates where possible
- Extract reusable styles to component CSS files
- Page-specific styles can remain in template `{% block styles %}` blocks

## Submitting Changes

### Issues

- Search existing issues before creating a new one
- Include steps to reproduce for bugs
- Include system info (OS, Python version, browser)

### Pull Requests

1. Create a feature branch from `main`
2. Make your changes with clear commit messages
3. Test on at least one platform (Linux preferred)
4. Ensure no personal data (API keys, paths) is included
5. Submit a PR with a description of what changed and why

### What to Work On

- Check open issues labeled `good first issue` or `help wanted`
- Bug fixes are always welcome
- New scraper integrations
- UI improvements
- Documentation improvements
- Cross-platform compatibility fixes

## Testing

### Automated tests

RetroDB has a pytest suite under `tests/`:

```bash
python3 -m pytest                # run the full suite
python3 -m pytest tests/test_game_utils.py -v   # one file, verbose
```

Most tests are unit-level; a handful (DB backup, migrations, image pipeline, observability) run as integration tests. The full suite finishes in well under a minute on a developer laptop.

Every push and PR runs the suite on CI (`.github/workflows/ci.yml`) along with ruff
(`ruff check .`), `pip-audit`, a lockfile-drift check, a semgrep security scan, and an import smoke test. New service code in `services/*.py` or `scraper/*.py` **must** ship with tests — the CI workflow considers a ruff / pytest / pip-audit / lockfile-drift failure blocking.

### Manual QA workflow

For changes that touch UI or external integrations, also do:

1. Start fresh: delete `database/roms.db` and run the app
2. Complete the setup wizard
3. Scan a ROM library
4. Test scraping (single + bulk)
5. Verify ROM tools work with your OS's tool installations
6. Check the help page renders correctly

## Questions?

Open an issue on GitHub for any questions about the codebase or contribution process.
