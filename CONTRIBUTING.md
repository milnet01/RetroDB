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
   Edit `config.py` and set:
   ```python
   DEBUG_MODE = True
   ```
   This enables Flask's auto-reloader and debug output.

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
├── routes/                 # Flask blueprints
│   ├── auth.py             # Authentication and user management
│   ├── games.py            # Game detail, edit, scraping
│   ├── systems.py          # System browsing
│   ├── settings.py         # Settings UI
│   ├── tools.py            # ROM tools (archive, CHD, duplicates)
│   ├── scraper.py          # Single game scraping
│   ├── bulk_scrape.py      # Bulk scraping queue
│   ├── reports.py          # ROM reports
│   ├── achievements.py     # RetroAchievements
│   ├── trophies.py         # PS3 trophies
│   └── ...
│
├── scraper/                # Scraping backends
│   ├── scraper_manager.py  # Orchestrates hybrid scraping
│   ├── hybrid_scraper.py   # Multi-source scraper
│   ├── rom_tools.py        # Archive/CHD/duplicate tools backend
│   └── ...
│
├── services/               # Service layer
│   ├── database.py         # SQLite query helpers
│   ├── auth.py             # Auth helpers (hashing, permissions)
│   └── jobs.py             # Background job management
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

Currently RetroDB does not have an automated test suite. Manual testing workflow:

1. Start fresh: delete `database/roms.db` and run the app
2. Complete the setup wizard
3. Scan a ROM library
4. Test scraping (single + bulk)
5. Verify ROM tools work with your OS's tool installations
6. Check the help page renders correctly

## Questions?

Open an issue on GitHub for any questions about the codebase or contribution process.
