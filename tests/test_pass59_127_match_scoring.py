"""PASS-59-127: scraper match scoring and the preferred-version rank.

- The region bonus follows the Default Region setting, not a fixed USA.
- Two titles that are only tags ("(USA)" vs "(Europe)") are not a match.
- "X-Men" carries no sequel number; "Mega Man X" does.
- The preferred-version rank reads the ROM's file name, never its folders,
  and knows the GoodTools codes (U), (E), (J), (W) the version label reads.
"""
import pytest

import settings_manager
from scraper.match_scorer import (
    calculate_ss_score, calculate_tgdb_score, calculate_title_match_score)
from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture

REGIONS = ['USA', 'Europe', 'Japan', 'World']


@pytest.fixture
def default_region(monkeypatch):
    def use(region):
        settings = {'default_region': region, 'region_options': REGIONS}
        monkeypatch.setattr(settings_manager, 'load_settings', lambda: dict(settings))
    return use


def _region_bonus(score_fn, region):
    # The bonus alone: same title both times, only the region differs.
    return (score_fn({'name': 'Sonic', 'region': region}, 'Sonic')
            - score_fn({'name': 'Sonic'}, 'Sonic'))


@pytest.mark.parametrize('setting,codes', [
    ('USA', {'us': 20, 'wor': 20, 'eu': 10, 'jp': 0}),
    ('Europe', {'eu': 20, 'uk': 20, 'wor': 20, 'us': 10, 'jp': 0}),
    ('Japan', {'jp': 20, 'wor': 20, 'us': 10, 'eu': 0}),
])
def test_ss_region_bonus_follows_default_region(default_region, setting, codes):
    default_region(setting)
    assert {c: _region_bonus(calculate_ss_score, c) for c in codes} == codes


@pytest.mark.parametrize('setting,codes', [
    ('USA', {'USA': 20, 'World': 20, 'Europe': 10, 'Japan': 0}),
    ('Europe', {'Europe': 20, 'World': 20, 'USA': 10, 'Japan': 0}),
])
def test_tgdb_region_bonus_follows_default_region(default_region, setting, codes):
    default_region(setting)
    assert {c: _region_bonus(calculate_tgdb_score, c) for c in codes} == codes


def test_tag_only_titles_are_not_a_match():
    assert calculate_title_match_score('(Europe)', '(USA)') == 0


def test_real_title_still_matches_exactly():
    assert calculate_title_match_score('Sonic (Europe)', 'Sonic (USA)') == 300


@pytest.mark.parametrize('rom,expected', [
    ('X-Men (USA).zip', False),
    ('X-Men 2 - Clone Wars (USA).zip', True),
    ('Mega Man X (USA).zip', True),
    ('Final Fantasy VII (USA).zip', True),
    ('Sonic the Hedgehog (USA).zip', False),
])
def test_sequel_number(rom, expected):
    assert vg._has_sequel_number(rom) is expected


def test_rank_ignores_region_in_folder_name(vdb, default_region):
    default_region('USA')
    jp = vdb.game('Game', rom='Collection (USA)/Game (Japan).zip', region='')
    eu = vdb.game('Game', rom='Game (Europe).zip', region='')
    vg.link([jp, eu])
    assert [m['id'] for m in vg.members(jp)] == [eu, jp]


def test_rank_reads_goodtools_codes_like_the_label(vdb, default_region):
    default_region('USA')
    jp = vdb.game('Game', rom='Game (J).zip', region='')
    us = vdb.game('Game', rom='Game (U) [!].zip', region='')
    vg.link([jp, us])
    rows = vg.members(jp)
    assert [(m['id'], m['region_label']) for m in rows] == [(us, 'USA'), (jp, 'Japan')]


def test_rank_reads_windows_paths(vdb, default_region):
    default_region('USA')
    jp = vdb.game('Game', region='',
                  rom_path='C:\\ROMs\\Collection (USA)\\Game (Japan).zip')
    eu = vdb.game('Game', rom='Game (Europe).zip', region='')
    vg.link([jp, eu])
    assert [m['id'] for m in vg.members(jp)] == [eu, jp]
