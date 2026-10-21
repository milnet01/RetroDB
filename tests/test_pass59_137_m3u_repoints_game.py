# =============================================================================
# PASS-59-137 — Create M3U points the game's library entry at the playlist
# =============================================================================
# Create M3U turns an archive into a playlist plus a folder, and may move the
# archive away. The game row that pointed at the archive must then point at
# the .m3u, keeping its metadata and media, whether or not the archive moved.
# =============================================================================

import zipfile

import pytest

import routes.tools as tools
from scraper.rom_tools import ArchiveScanner
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def m3u(admin_test_client, monkeypatch, tmp_path):
    roms = tmp_path / 'roms'
    roms.mkdir()
    monkeypatch.setattr(tools, '_get_rom_path', lambda: str(roms))
    monkeypatch.setattr(ArchiveScanner, '_staging_folder',
                        lambda self: str(tmp_path / 'staging'))
    client, csrf = admin_test_client()

    def post(route, body):
        resp = client.post(f'/api/rom-tools/archive-scanner/{route}', json=body,
                           headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        return resp.get_json()

    def archive(name):
        path = roms / f'{name}.zip'
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr(f'{name} (Disk 1).d64', b'one')
            zf.writestr(f'{name} (Disk 2).d64', b'two')
        return path

    return post, archive


def _row(vdb, game_id):
    return vdb.conn.execute("SELECT title, rom_path, file_size FROM games WHERE id = ?",
                            (game_id,)).fetchone()


def test_single_create_repoints_the_row_at_the_playlist(vdb, m3u):
    post, archive = m3u
    path = archive('Game')
    game_id = vdb.game('Game', rom_path=str(path), file_size=999)

    result = post('create-m3u', {'path': str(path), 'move_to_staging': True})

    assert result['success'] and result['archive_moved']
    playlist = path.with_suffix('.m3u')
    row = _row(vdb, game_id)
    assert row['rom_path'] == str(playlist)
    assert row['file_size'] == playlist.stat().st_size
    assert row['title'] == 'Game'


def test_batch_create_repoints_even_when_archives_stay(vdb, m3u):
    post, archive = m3u
    path = archive('Other')
    game_id = vdb.game('Other', rom_path=str(path), file_size=999)

    result = post('batch-create-m3u', {'paths': [str(path)]})

    assert result['succeeded'] == 1 and path.exists()
    assert _row(vdb, game_id)['rom_path'] == str(path.with_suffix('.m3u'))
