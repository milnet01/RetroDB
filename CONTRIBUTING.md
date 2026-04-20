# Contributing to RetroDB

Thank you for your interest in contributing to RetroDB! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.8+
- pip
- Git

### Getting Started

1. **Clone the repository:**
   ```bash
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

```
RetroDB/
├── app.py                  # Main Flask application, routes, initialization
├── config.py               # Configuration (paths, API keys, constants)
├── settings_manager.py     # User-editable settings (data/settings.json)
├── platform_utils.py       # Cross-platform OS detection and helpers
├── log_manager.py          # File-based logging system
├── build_css.py            # CSS build script (modular -> bundled)
├── install.py              # Cross-platform installer
│
├── routes/                 # Flask blueprints (20+ route files)
│   ├── auth.py             # Authentication and user management
│   ├── games.py            # Game list, detail, edit, bulk edit, search
│   ├── games_hltb.py       # HowLongToBeat API endpoints
│   ├── systems.py          # System browsing
│   ├── settings.py         # Settings UI
│   ├── tools.py            # ROM tools (archive, CHD, duplicates)
│   ├── scraper.py          # Scraper config
│   ├── bulk_scrape.py      # Bulk scraping queue
│   ├── reports.py          # ROM reports
│   ├── achievements.py     # RetroAchievements
│   ├── trophies.py         # PS3 & PSN trophies
│   ├── steam_achievements.py
│   ├── xbox_achievements.py
│   ├── museum.py           # System encyclopedia
│   ├── collections.py      # Tags, lists, wishlist
│   ├── collector_trophies.py
│   ├── platform_import.py  # Steam / Xbox / PSN library import
│   └── ...
│
├── scraper/                # Scraping backends
│   ├── scraper_manager.py  # Orchestrates hybrid scraping
│   ├── hybrid_scraper.py   # Multi-source scraper
│   ├── rom_tools.py        # Archive/CHD/duplicate tools backend
│   ├── scrape_steam.py     # Steam Web API
│   ├── scrape_xbox.py      # Xbox Live API (OAuth)
│   └── ...
│
├── services/               # Service layer
│   ├── database.py         # SQLite query helpers, safe_column allowlist
│   ├── database_init.py    # Schema bootstrap + migrations
│   ├── auth.py             # Auth helpers (hashing, permissions)
│   ├── security.py         # Path validation, rate limiting
│   ├── analytics.py        # Analytics data helpers (20 functions)
│   ├── formatters.py       # format_size, get_manufacturer
│   ├── template_filters.py # Jinja filters
│   ├── game_query.py       # Shared game-list query helpers
│   ├── game_utils.py       # Title parsing, ratings, system constants
│   ├── image_utils.py      # Real-ESRGAN upscaling, Lanczos downscaling
│   ├── normalization.py    # Genre/modes normalization
│   ├── log_redactor.py     # Logs secret-redaction filter
│   └── jobs/               # Background job package (bulk scrape, RA sync, PSN, etc.)
│
├── tests/                  # pytest suite
├── .github/workflows/      # CI + release pipelines
│
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS, JS, images
│   ├── css/                # Modular CSS (built by build_css.py)
│   └── js/                 # JavaScript modules
│
├── data/                   # Runtime data (settings, scraper config)
├── database/               # SQLite databases
└── logs/                   # Application logs
```

## Code Style

RetroDB follows the conventions documented in `RETRODB_DESIGN_STANDARDS.md`. Key points:

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
python3 -m pytest                # run everything (fast — all tests are unit-level)
python3 -m pytest tests/test_game_utils.py -v   # one file, verbose
```

Every push and PR runs the suite on CI (`.github/workflows/ci.yml`) along with ruff
(`ruff check .`), a semgrep security scan, and an import smoke test. New service code
in `services/*.py` or `scraper/*.py` **must** ship with tests — the CI workflow
considers a ruff/pytest failure blocking.

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
