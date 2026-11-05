"""PASS-59-246: the last untranslated screen text, and the job-queue panel's escaping."""
import re

from tests._util import read_source


def test_the_job_queue_panel_escapes_system_names():
    """A system name went into innerHTML as it was."""
    html = read_source('templates/base.html')
    assert '${data.system_name ||' not in html
    assert re.search(r"escapeHtml\(data\.system_name \|\| ", html)
    assert re.search(r"const systemName = escapeHtml\(job\.system_name", html)
