# log_manager.py - Handles logging configuration for RetroDB
# ================================================================================
# Provides file-based logging with configurable levels for different modules.
# Logs are written to the logs/ folder with date-based filenames.
# ================================================================================

import os
import logging
from datetime import datetime, timezone


# ------------------------------------------------------------------------------
# REQUEST-ID LOG RECORD FACTORY
# ------------------------------------------------------------------------------
# Stamp a per-request correlation ID onto every LogRecord so format strings
# can reference %(request_id)s. Set via the Flask before_request hook in
# app.py; '-' outside a request context (background jobs, startup).

_request_id_installed = False


def install_request_id_factory():
    """Install a LogRecord factory that auto-populates record.request_id.

    Called once at import of app.py. Reads flask.g.request_id when inside a
    request context; falls back to '-' otherwise. Idempotent — installing
    twice is a no-op.
    """
    global _request_id_installed
    if _request_id_installed:
        return
    _request_id_installed = True

    original = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = original(*args, **kwargs)
        try:
            from flask import g, has_request_context
            if has_request_context():
                record.request_id = getattr(g, 'request_id', '-')
            else:
                record.request_id = '-'
        except Exception:
            record.request_id = '-'
        return record

    logging.setLogRecordFactory(factory)

# Base directory.  Pulled from config so the logs dir tracks the writable
# user-data root in a PyInstaller frozen bundle (Pass 46.3 part 2) rather
# than _internal/logs/ next to the bundled assets.
import config as _config
BASE_DIR = _config.BASE_DIR
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Logger categories. Pass 41.3.C — `'system'` was historically listed but had
# no entry in CATEGORY_LOGGERS, so each daily sweep created an empty
# `system_YYYY-MM-DD.log` that misled operators searching for system events.
# Dropped; system-level logs flow through the root logger's StreamHandler
# (with redactor) rather than a dedicated category file.
LOGGER_CATEGORIES = ['scraping', 'rom_tools', 'rom_reports', 'image_resize']

# Category to logger name mapping
CATEGORY_LOGGERS = {
    'scraping': [
        'scraper',
        'scraper.scraper_manager',
        'scraper.hybrid_scraper',
        'scraper.scrape_esde',
        'scraper.scrape_thegamesdb',
        'scraper.scrape_igdb',
        'scraper.scrape_screenscraper',
        'scraper.scrape_rawg',
        'scraper.retroachievements',
        'scraper.hltb_lookup',
        'services.jobs',
    ],
    'image_resize': [
        'services.jobs.image_resize',
        'services.image_utils',
    ],
    'rom_tools': [
        'rom_tools',
        'scraper.rom_tools',
        'scraper.scan_roms',
        'chd_tools',
        'archive_scanner',
    ],
    'rom_reports': [
        'rom_reports',
        'reports',
    ]
}


def ensure_logs_dir():
    """Ensure the logs directory exists"""
    os.makedirs(LOGS_DIR, exist_ok=True)


def get_log_filename(category):
    """Get the log filename for a category (date-based, UTC).

    Pass 34.5 — previously used naive local time, which meant:
      - a server in Europe/Berlin rolled logs at Berlin midnight, not UTC;
      - DST transitions created same-named files twice with mtime drift.
    UTC gives a single monotonic day boundary across the global fleet,
    matching the pattern in ra_sync / platform_sync (Pass 30.7).
    """
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return os.path.join(LOGS_DIR, f'{category}_{today}.log')


def get_logging_settings():
    """Load logging settings from settings.json"""
    try:
        from settings_manager import load_settings
        settings = load_settings()
        return settings.get('logging', {})
    except Exception:
        return {}


class CategoryFileHandler(logging.Handler):
    """Custom handler that writes to category-specific date-based log files"""
    
    def __init__(self, category):
        super().__init__()
        self.category = category
        self.current_date = None
        self.file_handler = None
        self._setup_handler()
    
    def _setup_handler(self):
        """Setup or rotate the file handler if date changed.

        Pass 34.5 — rolls on UTC midnight. Matches get_log_filename() so
        we never open yesterday's filename because local time disagrees
        with the filename-generation clock.
        """
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        if self.current_date != today:
            # Close existing handler if any
            if self.file_handler:
                self.file_handler.close()

            ensure_logs_dir()
            log_file = get_log_filename(self.category)

            # Check if appending to existing file (same-day server restart)
            appending = os.path.exists(log_file) and os.path.getsize(log_file) > 0

            self.file_handler = logging.FileHandler(log_file, encoding='utf-8')
            self.file_handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            # Attach secret-redaction filter so JWTs / OAuth tokens / API keys
            # logged by scrapers don't accumulate on disk as plaintext.
            from services.log_redactor import SecretRedactor
            self.file_handler.addFilter(SecretRedactor())
            self.current_date = today

            # Write version banner on new file or server restart
            try:
                import config
                version = getattr(config, 'APP_VERSION', '?')
                banner = f"RetroDB v{version}"
                if appending:
                    self.file_handler.stream.write(f"\n{'=' * 60}\n")
                    self.file_handler.stream.write(f"=== {banner} — server started ===\n")
                    self.file_handler.stream.write(f"{'=' * 60}\n")
                else:
                    self.file_handler.stream.write(f"=== {banner} ===\n")
                self.file_handler.stream.flush()
            except Exception:
                pass
    
    def emit(self, record):
        """Emit a log record"""
        self._setup_handler()  # Check for date rollover

        # If data/settings.json is malformed (e.g. `logging` got overwritten
        # with a non-dict via test pollution or hand-edit), fall back to
        # "log everything" — a raising handler propagates AttributeError
        # into the caller's `logger.info(...)` site, which previously took
        # the ESRGAN init's outer `except Exception` and silently disabled
        # upscaling with no diagnostic.
        log_settings = get_logging_settings()
        if not isinstance(log_settings, dict):
            log_settings = {}
        category_settings = log_settings.get(self.category, {})
        if not isinstance(category_settings, dict):
            category_settings = {}

        level_map = {
            logging.INFO: 'info',
            logging.WARNING: 'warning',
            logging.ERROR: 'error',
            logging.CRITICAL: 'error',
        }

        level_key = level_map.get(record.levelno, 'info')

        # Only log if this level is enabled for this category
        if category_settings.get(level_key, True):
            self.file_handler.emit(record)
    
    def close(self):
        """Close the handler"""
        if self.file_handler:
            self.file_handler.close()
        super().close()


# Global handlers storage
_category_handlers = {}


def setup_category_logging(category):
    """Setup logging for a specific category"""
    if category not in LOGGER_CATEGORIES:
        return
    
    ensure_logs_dir()
    
    # Create the handler if not exists
    if category not in _category_handlers:
        handler = CategoryFileHandler(category)
        handler.setLevel(logging.DEBUG)  # Let the handler filter by settings
        _category_handlers[category] = handler
    
    handler = _category_handlers[category]
    
    # Attach handler to all loggers in this category
    logger_names = CATEGORY_LOGGERS.get(category, [])
    
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        
        # Remove any existing CategoryFileHandler for this category
        for h in logger.handlers[:]:
            if isinstance(h, CategoryFileHandler) and h.category == category:
                logger.removeHandler(h)
        
        logger.addHandler(handler)
        
        # Prevent propagation to parent loggers to avoid duplicate entries
        # Only set propagate=False for child loggers (those with '.' in name)
        # if parent is also in our logger list
        if '.' in logger_name:
            parent_name = logger_name.rsplit('.', 1)[0]
            if parent_name in logger_names:
                logger.propagate = False


def setup_all_logging():
    """Setup logging for all categories"""
    for category in LOGGER_CATEGORIES:
        setup_category_logging(category)


def install_global_redactor():
    """Install SecretRedactor universally on the root logger and every
    handler it currently holds.

    Catches the StreamHandler registered by ``logging.basicConfig()`` plus
    any third-party handlers attached before this call. Records originating
    in child loggers (scrapers / services / routes) that propagate to root
    pass through the root-logger filter, so their message/args get redacted
    before any root handler emits them. The per-category
    ``CategoryFileHandler`` already installs its own SecretRedactor
    instance — this adds a second, universal layer that covers anything
    routing through the stdout console or a basicConfig StreamHandler.

    Idempotent — calling twice won't attach two copies.
    """
    from services.log_redactor import SecretRedactor

    root = logging.getLogger()

    def _already_redacting(filters):
        return any(isinstance(f, SecretRedactor) for f in filters)

    if not _already_redacting(root.filters):
        root.addFilter(SecretRedactor())
    for handler in root.handlers:
        if not _already_redacting(handler.filters):
            handler.addFilter(SecretRedactor())


def get_log_files():
    """Get list of all log files with metadata"""
    ensure_logs_dir()
    
    log_files = []
    
    for filename in sorted(os.listdir(LOGS_DIR), reverse=True):
        if filename.endswith('.log'):
            filepath = os.path.join(LOGS_DIR, filename)
            stat = os.stat(filepath)
            
            # Parse category and date from filename
            parts = filename.rsplit('_', 1)
            category = parts[0] if len(parts) > 1 else 'unknown'
            date_str = parts[1].replace('.log', '') if len(parts) > 1 else ''
            
            log_files.append({
                'filename': filename,
                'filepath': filepath,
                'category': category,
                'date': date_str,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    
    return log_files


def get_log_content(filename, lines=100):
    """Get the last N lines of a log file"""
    filepath = os.path.join(LOGS_DIR, filename)
    
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        return [f"Error reading log file: {e}"]


def clear_old_logs(days=30):
    """Remove log files older than specified days"""
    ensure_logs_dir()
    
    cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
    removed = 0
    
    for filename in os.listdir(LOGS_DIR):
        if filename.endswith('.log'):
            filepath = os.path.join(LOGS_DIR, filename)
            if os.path.getmtime(filepath) < cutoff:
                try:
                    os.remove(filepath)
                    removed += 1
                except Exception:
                    pass
    
    return removed


def get_full_log_content(filename):
    """Get the full content of a log file as a string with path traversal protection"""
    # Security: only allow simple filenames, no path separators
    if os.path.sep in filename or '/' in filename or '\\' in filename or '..' in filename:
        return None

    filepath = os.path.join(LOGS_DIR, filename)

    # Verify the resolved path is inside LOGS_DIR
    if not os.path.realpath(filepath).startswith(os.path.realpath(LOGS_DIR)):
        return None

    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


# Pass 34.3 — removed get_scraping_log_files / log_scraping / log_rom_tools /
# log_rom_reports. The convenience helpers had zero callers across the repo;
# routes query logs via get_log_files() + read_log_file() directly, and
# scraper modules call getLogger() themselves. Grepping for the names at
# removal time yielded only this module's own definitions.
