"""PASS-59-267: the log viewer hides secrets in log files written before a
redaction pattern existed. Redaction at write time cannot reach those files,
so every route that sends a log's text runs it through log_redactor.redact().
"""
import pytest

import log_manager

LOG = 'scraping_2020-01-01.log'
SECRET = 'Hunter2Secret'
LINE = (f'GET https://api.screenscraper.fr/api2/jeuInfos.php?devid=x'
        f'&sspassword={SECRET}&ssid=me\n')


@pytest.fixture
def old_log(tmp_path, monkeypatch):
    monkeypatch.setattr(log_manager, 'LOGS_DIR', str(tmp_path))
    (tmp_path / LOG).write_text('first line\n' + LINE, encoding='utf-8')


def _get(admin_test_client, url):
    client, _csrf = admin_test_client()
    resp = client.get(url)
    assert resp.status_code == 200
    return resp


def test_content_route_hides_the_secret(old_log, admin_test_client):
    data = _get(admin_test_client, f'/api/logs/content/{LOG}').get_json()
    assert isinstance(data['content'], str) and 'first line' in data['content']
    assert SECRET not in data['content']


def test_view_route_hides_the_secret(old_log, admin_test_client):
    data = _get(admin_test_client, f'/api/logs/view/{LOG}').get_json()
    assert isinstance(data['content'], list) and data['content']
    assert not any(SECRET in line for line in data['content'])


def test_download_route_hides_the_secret(old_log, admin_test_client):
    resp = _get(admin_test_client, f'/api/logs/download/{LOG}')
    body = resp.get_data(as_text=True)
    assert 'first line' in body
    assert SECRET not in body
    assert 'attachment' in resp.headers.get('Content-Disposition', '')
