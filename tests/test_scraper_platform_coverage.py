"""A source is searched only for systems it lists, and only on that system
(user, 2026-10-27): RAWG has no Intellivision, so searching it there found
games from other platforms instead."""
import pytest


def _no_request(*_a, **_k):
    raise AssertionError('a source was searched for a system it does not list')


def test_rawg_skips_unlisted_system(monkeypatch):
    from scraper import scrape_rawg
    monkeypatch.setattr(scrape_rawg, '_make_request', _no_request)
    for folder in ('intellivision', 'colecovision', 'pcengine', 'arcade', 'virtualboy'):
        assert scrape_rawg.search_games('Astrosmash', folder) == []


def test_rawg_never_drops_platform_filter(monkeypatch):
    from scraper import scrape_rawg
    sent = []

    def fake(endpoint, params=None, max_retries=2):
        sent.append(dict(params))
        return {'results': []}

    monkeypatch.setattr(scrape_rawg, '_make_request', fake)
    scrape_rawg.search_games('Nothing Here', 'snes')
    assert sent and all(p.get('platforms') == 79 for p in sent)


@pytest.mark.parametrize('folder, platform_id', [
    ('atarist', 34), ('3do', 111), ('psx', 27), ('genesis', 167),
])
def test_rawg_platform_ids(folder, platform_id):
    from scraper.scrape_rawg import PLATFORM_MAP
    assert PLATFORM_MAP[folder] == platform_id


def test_igdb_skips_unlisted_system(monkeypatch):
    from scraper import scrape_igdb
    calls = []
    monkeypatch.setattr(scrape_igdb, 'igdb_auth', lambda: 'token')
    monkeypatch.setattr(scrape_igdb, 'get_platform_id', lambda name: None)
    monkeypatch.setattr(scrape_igdb, 'igdb_request', lambda *a: calls.append(a) or [])
    assert scrape_igdb.search_games('Astrosmash', 'Nowhere System') == []
    assert calls == []


def test_igdb_every_query_keeps_platform(monkeypatch):
    """Including the fallbacks that once searched every platform."""
    from scraper import scrape_igdb
    bodies = []
    monkeypatch.setattr(scrape_igdb, 'igdb_auth', lambda: 'token')
    monkeypatch.setattr(scrape_igdb, 'get_platform_id', lambda name: 67)
    monkeypatch.setattr(scrape_igdb, 'igdb_request',
                        lambda endpoint, body, token: bodies.append(body) or [])
    scrape_igdb.search_games('Two Words', 'Intellivision')
    assert len(bodies) >= 3
    assert all('platforms = (67)' in b for b in bodies)


def test_tgdb_skips_unlisted_system(monkeypatch):
    from scraper import scrape_thegamesdb
    monkeypatch.setattr(scrape_thegamesdb, 'get_system_id', lambda name: None)
    calls = []
    monkeypatch.setattr(scrape_thegamesdb, '_tgdb_request', lambda *a, **k: calls.append(a))
    assert scrape_thegamesdb.search_games('Astrosmash', 'Nowhere System') == []
    assert calls == []
