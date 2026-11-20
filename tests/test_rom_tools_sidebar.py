"""Every page in the ROM Tools tab row lights up the sidebar's ROM Tools link.

The tab list is read from `templates/_macros/nav_tabs.html`, so a tab added
there is checked here too. Pages outside the `tools` blueprint once left the
link dark.
"""
import os
import re

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rom_tool_endpoints():
    path = os.path.join(_REPO_ROOT, 'templates', '_macros', 'nav_tabs.html')
    with open(path, encoding='utf-8') as f:
        body = f.read()
    start = body.index('{% macro rom_tool_tabs')
    macro = body[start:body.index('{% endmacro %}', start)]
    return re.findall(r"url_for\('([a-z_]+\.[a-z_]+)'\)", macro)


def test_tab_list_was_read():
    assert 'maintenance.ss_region_repair_page' in _rom_tool_endpoints()


@pytest.mark.parametrize('endpoint', _rom_tool_endpoints())
def test_rom_tools_sidebar_link_is_active(admin_test_client, endpoint):
    import app as app_module
    client, _csrf = admin_test_client()
    with app_module.app.test_request_context():
        page = app_module.app.url_for(endpoint)
        hub = app_module.app.url_for('tools.rom_tools_hub')
    resp = client.get(page)
    assert resp.status_code == 200, page
    html = resp.get_data(as_text=True)
    assert (f'<a href="{hub}" class="nav-item active" aria-current="page">'
            in html), page
