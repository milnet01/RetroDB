# log_manager.py - Handles logging configuration for RetroDB
# ================================================================================
# Provides file-based logging with configurable levels for different modules.
# Logs are written to the logs/ folder with date-based filenames.
# ================================================================================

import os
import logging
from datetime import datetime

# Base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Logger categories
LOGGER_CATEGORIES = ['scraping', 'rom_tools', 'rom_reports', 'image_resize', 'system']

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
    """Get the log filename for a category (date-based)"""
    today = datetime.now().strftime('%Y-%m-%d')
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
        """Setup or rotate the file handler if date changed"""
        today = datetime.now().strftime('%Y-%m-%d')

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
                '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
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
        
        # Check if this level should be logged based on settings
        log_settings = get_logging_settings()
        category_settings = log_settings.get(self.category, {})
        
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


def get_scraping_log_files():
    """Get log files filtered to scraping category only"""
    return [f for f in get_log_files() if f['category'] == 'scraping']


def log_scraping(level, message, logger_name='scraper'):
    """Convenience function for scraping logs"""
    logger = logging.getLogger(logger_name)
    getattr(logger, level.lower(), logger.info)(message)


def log_rom_tools(level, message, logger_name='rom_tools'):
    """Convenience function for ROM tools logs"""
    logger = logging.getLogger(logger_name)
    getattr(logger, level.lower(), logger.info)(message)


def log_rom_reports(level, message, logger_name='rom_reports'):
    """Convenience function for ROM reports logs"""
    logger = logging.getLogger(logger_name)
    getattr(logger, level.lower(), logger.info)(message)
