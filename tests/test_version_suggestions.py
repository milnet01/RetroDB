"""PASS-59-106 INV-7, INV-8 — what the suggestion list may and may not offer.

docs/specs/PASS-59-106-regional-versions.md §4.5 and §5.
"""
from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture


def _touching(suggestions, ids):
    return [s for s in suggestions if {g['id'] for g in s['games']} & set(ids)]


# INV-8 — each of the four signals suggests a pair on its own.
def test_inv8_each_signal_suggests_alone(vdb):
    pairs = {
        'igdb_id': (vdb.game('Alpha One', igdb_id=111),
                    vdb.game('Beta Two', rom='Beta Two (Japan).zip', igdb_id=111)),
        'screenscraper_id': (vdb.game('Gamma', screenscraper_id=222),
                             vdb.game('Delta', rom='Delta (Japan).zip', screenscraper_id=222)),
        'title': (vdb.game('Epsilon US', rom='Epsilon (USA).zip'),
                  vdb.game('Epsilon EU', rom='Epsilon (Europe).zip')),
        'alternate_title': (vdb.game('Zeta'),
                            vdb.game('Eta', rom='Eta (Japan).zip',
                                     alt=[{'title': 'Zeta', 'region': 'USA'}])),
    }
    found = vg.suggest_groups(vdb.sid)
    assert len(found) == 4
    for signal, pair in pairs.items():
        match = [s for s in found if {g['id'] for g in s['games']} == set(pair)]
        assert len(match) == 1, signal
        assert match[0]['signals'] == [signal]


# INV-7 — never a rejected pair, games already grouped, two discs of one game,
# or games on two systems. Every pair below shares an igdb_id, so only its own
# exclusion can keep it out.
def test_inv7_rejected_pair_not_suggested(vdb):
    pair = [vdb.game('Alpha', igdb_id=5), vdb.game('Alpha', rom='Alpha (Japan).zip', igdb_id=5)]
    assert _touching(vg.suggest_groups(vdb.sid), pair)  # control: the signal fires
    vg.reject(pair)
    assert not _touching(vg.suggest_groups(vdb.sid), pair)


def test_inv7_already_grouped_not_suggested(vdb):
    pair = [vdb.game('Alpha', igdb_id=6), vdb.game('Alpha', rom='Alpha (Japan).zip', igdb_id=6)]
    vg.link(pair)
    assert not _touching(vg.suggest_groups(vdb.sid), pair)


def test_inv7_discs_of_one_game_not_suggested(vdb):
    pair = [vdb.game('Omega', rom='Omega (USA) (Disc 1 of 2).zip', igdb_id=7),
            vdb.game('Omega', rom='Omega (USA) (Disc 2 of 2).zip', igdb_id=7)]
    assert not _touching(vg.suggest_groups(vdb.sid), pair)


def test_inv7_two_systems_not_suggested(vdb):
    pair = [vdb.game('Alpha', igdb_id=8),
            vdb.game('Alpha', rom='Alpha (Japan).zip', sid=vdb.sid2, igdb_id=8)]
    assert not _touching(vg.suggest_groups(), pair)


# §4.5 signal 3 — "different region tags": an untagged name (a platform
# import, say) carries no region tag, so it pairs with nothing on title.
def test_title_signal_needs_tags_on_both(vdb):
    pair = [vdb.game('Kappa', rom='Kappa (USA).zip'), vdb.game('Kappa', rom='Kappa')]
    assert not _touching(vg.suggest_groups(vdb.sid), pair)


# §4.5 signal 4 — PASS-59-105's regional names: an alternate title with no
# region, or a non-region tag such as ScreenScraper's "ss", is not a signal.
def test_alternate_title_signal_needs_a_region(vdb):
    for region in (None, 'ss'):
        alt = [{'title': f'Lambda {region}'} if region is None
               else {'title': f'Lambda {region}', 'region': region}]
        pair = [vdb.game(f'Lambda {region}'),
                vdb.game('Mu', rom=f'Mu {region} (Japan).zip', alt=alt)]
        assert not _touching(vg.suggest_groups(vdb.sid), pair), region


# §4.5 — a numbered sequel is not a version of the un-numbered first game,
# even when a wrong scrape gave both rows one id (live library, 2026-10-19:
# "Doom 2 (USA)" carried Doom's IGDB id). Two numbered names still pair:
# Final Fantasy III (USA) is Final Fantasy VI (Japan).
def test_sequel_number_on_one_name_only_not_suggested(vdb):
    for igdb_id, first, sequel in (
            (9, 'Doom (USA).zip', 'Doom 2 (USA).zip'),
            (19, 'Descent (USA).chd', 'Descent II (Europe).chd'),
            (29, 'Strider (1989) (Capcom).zip', 'Strider 2 (1990) (US Gold).zip')):
        pair = [vdb.game('Doom', rom=first, igdb_id=igdb_id),
                vdb.game('Doom', rom=sequel, igdb_id=igdb_id)]
        assert not _touching(vg.suggest_groups(vdb.sid), pair), sequel
    renumbered = [vdb.game('Final Fantasy III', rom='Final Fantasy III (USA).zip', igdb_id=10),
                  vdb.game('Final Fantasy VI', rom='Final Fantasy VI (Japan).zip', igdb_id=10)]
    assert _touching(vg.suggest_groups(vdb.sid), renumbered)
