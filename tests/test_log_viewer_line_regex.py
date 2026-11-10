"""PASS-59-285: the log viewer's line pattern reads the lines log_manager writes.

log_manager's file format carries a request-ID field between the level and
the logger name. The viewer's LINE_REGEX must take the logger name as the
module, not the request ID, and still read the older four-field lines.
"""
import logging
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _viewer_regex():
    src = (ROOT / 'static' / 'js' / 'log-viewer.js').read_text(encoding='utf-8')
    m = re.search(r'LINE_REGEX:\s*/(.+)/,\s*$', src, re.M)
    assert m, 'LINE_REGEX not found in log-viewer.js'
    return re.compile(m.group(1))


def _file_format():
    src = (ROOT / 'log_manager.py').read_text(encoding='utf-8')
    m = re.search(r"logging\.Formatter\(\s*'([^']+)'", src)
    assert m, 'file formatter not found in log_manager.py'
    return m.group(1)


def _format(request_id, name, msg, level=logging.INFO):
    record = logging.LogRecord(name, level, __file__, 1, msg, None, None)
    record.request_id = request_id
    fmt = logging.Formatter(_file_format(), datefmt='%Y-%m-%d %H:%M:%S')
    return fmt.format(record)


def test_module_is_logger_name_with_request_id():
    line = _format('a5afd445', 'scraper.scrape_igdb', 'Found 3 | results')
    m = _viewer_regex().match(line)
    assert m, line
    assert m.group(3) == 'INFO'
    assert m.group(4) == 'scraper.scrape_igdb'
    assert m.group(5) == 'Found 3 | results'


def test_module_is_logger_name_without_request():
    line = _format('-', 'services.jobs.psn_keepalive', 'started')
    m = _viewer_regex().match(line)
    assert m, line
    assert m.group(4) == 'services.jobs.psn_keepalive'
    assert m.group(5) == 'started'


def test_older_four_field_lines_still_read():
    line = '2026-01-02 03:04:05 | WARNING  | scraper.scrape_ai | a | b'
    m = _viewer_regex().match(line)
    assert m, line
    assert m.group(4) == 'scraper.scrape_ai'
    assert m.group(5) == 'a | b'
