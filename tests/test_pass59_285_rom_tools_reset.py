"""PASS-59-285: ROM Tools Settings' Reset restores the server's defaults.

It used to write its own copy: a Linux-only ROM path (/mnt/Games/ROMS) and a
hand-copied pattern list. The page now carries routes/tools.rom_tools_defaults.
"""

import json
import re


def test_reset_uses_the_server_defaults(admin_test_client, monkeypatch):
    import routes.tools as tools
    monkeypatch.setattr(tools, '_get_rom_path', lambda: r'D:\Games\ROMs')
    client, _ = admin_test_client()
    html = client.get('/tools/settings').get_data(as_text=True)
    m = re.search(r'const d = (\{.*?\});', html)
    assert m, 'Reset no longer reads the server defaults'
    d = json.loads(m.group(1))
    assert d == json.loads(json.dumps(tools.rom_tools_defaults()))
    assert d['roms_path'] == r'D:\Games\ROMs'
    assert '/mnt/Games/ROMS' not in html


def test_saved_pattern_and_path_tags_are_escaped():
    from tests._util import read_source
    src = read_source('templates/rom_tools_settings.html')
    # The tag's own text, not its data- attribute (which was already escaped).
    for name in ('pattern', 'path'):
        assert re.search(r'class="tag">\s*\$\{escapeHtml\(' + name + r'\)\}', src), name
