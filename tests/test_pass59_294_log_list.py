"""PASS-59-294: the Logs page lists only files it will open.

logs/ also holds worker and dev-server logs. The list sorts newest
name first, so upscale_worker.log came first, and the page opened it
and showed "Invalid log file".
"""
import log_manager


def test_list_holds_only_files_the_content_route_opens(
        tmp_path, monkeypatch, admin_test_client):
    monkeypatch.setattr(log_manager, 'LOGS_DIR', str(tmp_path))
    (tmp_path / 'upscale_worker.log').write_text('worker\n')
    (tmp_path / 'scraping_2026-11-10.log').write_text('scrape\n')

    client, _csrf = admin_test_client()
    data = client.get('/api/logs/files').get_json()

    names = [f['filename'] for f in data['files']]
    assert names == ['scraping_2026-11-10.log']
    assert data['total'] == 1
    for name in names:
        assert client.get(f'/api/logs/content/{name}').status_code == 200
