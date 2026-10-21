# =============================================================================
# PASS-59-136 — ES-DE parses each gamelist.xml once until the file changes
# =============================================================================
# A bulk scrape searches ES-DE once per game, so re-reading a large gamelist
# on every search wasted time. The parsed list is kept per file and reused
# while the file's modified time and size are unchanged.
# =============================================================================

import os

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)

_XML = '<gameList><game><path>./{0}.zip</path><name>{0}</name></game></gameList>'


@pytest.fixture
def esde(monkeypatch):
    from scraper import scrape_esde
    monkeypatch.setattr(scrape_esde, '_gamelist_cache', {}, raising=False)
    calls = []
    real = scrape_esde._sanitize_xml

    def counting(raw):
        calls.append(1)
        return real(raw)

    monkeypatch.setattr(scrape_esde, '_sanitize_xml', counting)
    return scrape_esde, calls


def test_unchanged_file_is_parsed_once(esde, tmp_path):
    scrape_esde, calls = esde
    xml = tmp_path / 'gamelist.xml'
    xml.write_text(_XML.format('Alpha'), encoding='utf-8')

    first = scrape_esde.parse_gamelist_xml(str(xml))
    second = scrape_esde.parse_gamelist_xml(str(xml))

    assert first == second == [{'path': './Alpha.zip', 'name': 'Alpha'}]
    assert len(calls) == 1


def test_changed_file_is_parsed_again(esde, tmp_path):
    scrape_esde, calls = esde
    xml = tmp_path / 'gamelist.xml'
    xml.write_text(_XML.format('Alpha'), encoding='utf-8')
    scrape_esde.parse_gamelist_xml(str(xml))

    # Same size on purpose: only the modified time tells the files apart.
    xml.write_text(_XML.format('Bravo'), encoding='utf-8')
    st = os.stat(xml)
    os.utime(xml, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    assert scrape_esde.parse_gamelist_xml(str(xml))[0]['name'] == 'Bravo'
    assert len(calls) == 2


def test_caller_changing_the_list_does_not_change_the_cache(esde, tmp_path):
    scrape_esde, _ = esde
    xml = tmp_path / 'gamelist.xml'
    xml.write_text(_XML.format('Alpha'), encoding='utf-8')

    scrape_esde.parse_gamelist_xml(str(xml)).clear()

    assert len(scrape_esde.parse_gamelist_xml(str(xml))) == 1
