# RetroDB Standards Addendum

> **Important**: This addendum should be incorporated into RETRODB_DESIGN_STANDARDS.md

---

## Version Release Checklist

When releasing any version update, complete ALL of the following steps:

### 1. Update config.py (Required)
```python
APP_VERSION = "1.20.1"          # Version number: MAJOR.MINOR.PATCH
APP_LAST_UPDATE = "2026-02-05"  # Today's date in YYYY-MM-DD format
```

**Version Format**: `MAJOR.FEATURE.PATCH` (e.g., v1.20.1)
- **MAJOR** (v1.x.x): Major revisions/updates to the site as a whole
- **FEATURE** (v1.20.x): Major features
- **PATCH** (v1.20.1): Minor features, patches, bug fixes

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
RetroDB uses five log categories:
- **scraping** - Metadata scraping operations (IGDB, TGDB, ScreenScraper, RAWG, ES-DE, AI Fill)
- **rom_tools** - ROM scanning, CHD conversion, archive extraction, M3U creation
- **rom_reports** - ROM naming checks, mismatch detection, batch rename operations
- **image_resize** - Image standardization job progress (upscale/downscale)
- **system** - General application activity, maintenance tasks, startup

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
