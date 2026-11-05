"""PASS-59-249: a log line goes to its own category's file only.

scraper.rom_tools and services.jobs.image_resize sit under scraping's
loggers, so their lines were written to the scraping log as well."""
import logging

import pytest

import log_manager


def _written(category, logger_name, monkeypatch):
    handler = log_manager.CategoryFileHandler(category)
    out = []

    class _Sink:
        def emit(self, record):
            out.append(record.name)
    monkeypatch.setattr(handler, '_setup_handler', lambda: None)
    handler.file_handler = _Sink()
    monkeypatch.setattr(log_manager, 'get_logging_settings', lambda: {})
    handler.emit(logging.LogRecord(logger_name, logging.INFO, __file__, 1, 'm', None, None))
    return out == [logger_name]


@pytest.mark.parametrize('category,name,expected', [
    ('scraping', 'scraper.rom_tools', False),
    ('scraping', 'scraper.scan_roms', False),
    ('scraping', 'services.jobs.image_resize', False),
    ('rom_tools', 'scraper.rom_tools', True),
    ('image_resize', 'services.jobs.image_resize', True),
    ('scraping', 'scraper.hybrid_scraper', True),
    ('scraping', 'services.jobs.bulk_scrape', True),
])
def test_a_line_goes_to_its_own_category(category, name, expected, monkeypatch):
    assert _written(category, name, monkeypatch) is expected
