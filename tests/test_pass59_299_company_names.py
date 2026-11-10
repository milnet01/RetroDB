"""PASS-59-299: a company name keeps its suffix.

Publisher and developer split on every comma, so "Foo, Ltd." showed as two
names, "Foo" and "Ltd.", in the filters and in Settings > Normalization.
"""
import pytest

from services import game_query, normalization
from services.normalization import canonical_companies, case_twin_groups, split_names
from services.template_filters import company_names_filter
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.mark.parametrize('text, names', [
    ('Nintendo Co., Ltd.', ['Nintendo Co., Ltd.']),
    ('Foo, Inc., Bar', ['Foo, Inc.', 'Bar']),
    ('Foo, Co., Ltd.', ['Foo, Co., Ltd.']),
    ('Foo,LLC', ['Foo, LLC']),
    ('Paradox Interactive, AB', ['Paradox Interactive, AB']),
    ('Konami, Capcom', ['Konami', 'Capcom']),
    ('Ltd., Foo', ['Ltd.', 'Foo']),       # nothing before it to belong to
    ('Coconut, Incredible', ['Coconut', 'Incredible']),  # whole words only
    ('', []),
    (None, []),
])
def test_split_names(text, names):
    assert split_names(text) == names


def test_two_companies_with_the_same_suffix_both_keep_it():
    assert canonical_companies('Foo, Ltd., Bar, Ltd.') == 'Foo, Ltd., Bar, Ltd.'


def test_the_page_lists_each_company_whole():
    assert company_names_filter('Taito, Corp., Sega') == ['Taito, Corp.', 'Sega']


@pytest.fixture
def games(vdb):
    vdb.game('A', publisher='Foo299, Ltd', developer='Bar299, LTD')
    vdb.game('B', publisher='Baz299, LTD', developer='Bar299, LTD')
    normalization.invalidate_normalization_cache()
    game_query.invalidate_filter_cache()
    yield vdb
    normalization.invalidate_normalization_cache()
    game_query.invalidate_filter_cache()


def test_settings_lists_no_suffix_as_a_name(games):
    keys = {g['suggested'].casefold() for g in case_twin_groups('publisher')}
    assert not keys & {'ltd', 'ltd.'}


def test_filter_lists_whole_company_names(games):
    publishers = dict(game_query._get_filter_options()['publisher'])
    assert publishers.get('Foo299, Ltd') == 1
    assert publishers.get('Baz299, LTD') == 1
    assert 'Ltd' not in publishers and 'LTD' not in publishers


def test_the_library_cards_use_the_same_suffixes():
    import re
    from pathlib import Path
    js = Path(__file__).parent.parent / 'static/js/all-games-controller.js'
    found = re.search(r'const COMPANY_SUFFIX = /\^(.*)\$/i;', js.read_text())
    assert found and found.group(1) == normalization._COMPANY_SUFFIX.pattern
