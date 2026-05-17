# RetroDB Standards Addendum

> Standalone addendum. Section §21 of `RETRODB_DESIGN_STANDARDS.md` covers the same version-bump steps in summary form; this file is the extended checklist + logging-system reference.

---

## Version Release Checklist

When releasing any version update, complete ALL of the following steps:

### 1. Update config.py + config.example.py (Required)
```python
APP_VERSION = "3.6.14"          # Version number: MAJOR.MINOR.PATCH
APP_LAST_UPDATE = "2026-05-17"  # Today's date in YYYY-MM-DD format
```

**Version Format**: `MAJOR.MINOR.PATCH` (e.g., v3.6.14)
- **MAJOR** (vN.x.x): Major releases / breaking changes
- **MINOR** (v3.N.x): New features, enhancements, new options
- **PATCH** (v3.6.N): Bug fixes, cleanup, refactoring, accessibility

Both `config.py` AND `config.example.py` must be bumped in lockstep — `build_dist.py` reads from whichever exists.

### 2. Update data/changelog.yaml (Required)
Add a new changelog entry at the TOP of `data/changelog.yaml`:

```yaml
- version: X.X.X
  date: YYYY-MM-DD
  tags:
  - type: feature
    label: New Feature
  body: |
    <ul>
        <li><strong>Feature Name</strong> &mdash; Description of the feature.</li>
    </ul>
```

**Changelog Tag Types** — see `RETRODB_DESIGN_STANDARDS.md` §16 for full color reference:
- `feature` - New features (cyan)
- `enhancement` - Enhancements to existing features (green)
- `minor` - Minor improvements (purple)
- `patch` - Code quality, cleanup (orange)
- `fix` - Bug fixes (red)
- `major` - Major releases (magenta)
- `ui` - UI-only changes (purple)
- `improvement` - General improvements (cyan)
- `initial` - Initial release (magenta)

### 3. About Modal (Automatic)
The About modal automatically displays `APP_VERSION` and `APP_LAST_UPDATE` from config.py, so updating config.py also updates the About section.

### Summary
For every release, always update:
1. ✅ `config.py` - APP_VERSION and APP_LAST_UPDATE
2. ✅ `data/changelog.yaml` - Add new entry at top
3. ✅ (Automatic) About modal shows config.py values

---

## Logging System

### Log Categories
RetroDB uses four log categories (defined in `log_manager.py::LOGGER_CATEGORIES`; Pass 41.3.C dropped the historical `system` category that no longer had a writer):
- **scraping** - Metadata scraping operations (IGDB, TGDB, ScreenScraper, RAWG, ES-DE, AI Fill)
- **rom_tools** - ROM scanning, CHD conversion, archive extraction, M3U creation
- **rom_reports** - ROM naming checks, mismatch detection, batch rename operations
- **image_resize** - Image standardization job progress (upscale/downscale)

### Log File Location
- Directory: `logs/`
- Filename format: `{category}_{date}.log` (e.g., `scraping_2026-01-21.log`)

### Log Levels
Each category can independently enable/disable:
- **Info** - General operational messages
- **Warning** - Potential issues that don't stop operations
- **Error** - Failures and exceptions

### Using Logging in Code
```python
import logging
logger = logging.getLogger('scraper')  # or 'rom_tools', 'rom_reports'

logger.info("Operation started")
logger.warning("Potential issue detected")
logger.error(f"Operation failed: {e}")
```

### Settings
Logging settings are stored in `data/settings.json` under the `logging` key and can be configured via Settings → System → Logging.
