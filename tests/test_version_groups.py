"""PASS-59-106 INV-1, INV-2, INV-3 — the rules every version group keeps.

docs/specs/PASS-59-106-regional-versions.md §4.1 and §5.
"""
import pytest

from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture


def test_control_two_games_on_one_system_link(vdb):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Japan).zip')
    gid = vg.link([a, b])
    assert gid and vdb.group_of(a) == gid == vdb.group_of(b)


# INV-1 — a link across two systems, or including a bonus disc, is refused
# and writes nothing.
def test_inv1_link_across_systems_refused(vdb):
    a = vdb.game('Alpha')
    b = vdb.game('Alpha', rom='Alpha (Japan).zip', sid=vdb.sid2)
    with pytest.raises(vg.VersionLinkError):
        vg.link([a, b])
    assert vdb.group_of(a) is None and vdb.group_of(b) is None
    assert vdb.conn.execute("SELECT COUNT(*) FROM version_groups").fetchone()[0] == 0


def test_inv1_link_across_systems_refused_when_not_first_pair(vdb):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Europe).zip')
    c = vdb.game('Alpha', rom='Alpha (Japan).zip', sid=vdb.sid2)
    with pytest.raises(vg.VersionLinkError):
        vg.link([a, b, c])
    assert [vdb.group_of(x) for x in (a, b, c)] == [None, None, None]


def test_inv1_link_with_bonus_disc_refused(vdb):
    a = vdb.game('Alpha')
    bonus = vdb.game('Alpha Bonus', rom='Alpha (Japan) (Bonus Disc).zip', is_bonus_disc=1)
    with pytest.raises(vg.VersionLinkError):
        vg.link([a, bonus])
    assert vdb.group_of(a) is None and vdb.group_of(bonus) is None
    assert vdb.conn.execute("SELECT COUNT(*) FROM version_groups").fetchone()[0] == 0


# INV-2 — no group ever has fewer than two members.
def test_inv2_unlink_down_to_one_dissolves_group(vdb):
    a, b, c = (vdb.game('Alpha', rom=f'Alpha ({r}).zip') for r in ('USA', 'Europe', 'Japan'))
    gid = vg.link([a, b, c])
    vg.unlink(a)
    assert vdb.group_of(a) is None and vdb.group_of(b) == gid == vdb.group_of(c)
    vg.unlink(b)
    assert [vdb.group_of(x) for x in (a, b, c)] == [None, None, None]
    assert vdb.conn.execute("SELECT COUNT(*) FROM version_groups WHERE id = ?",
                            (gid,)).fetchone()[0] == 0


def test_inv2_deleting_a_member_row_dissolves_group(vdb):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Japan).zip')
    gid = vg.link([a, b])
    assert vdb.group_of(b) == gid
    vdb.conn.execute("DELETE FROM games WHERE id = ?", (a,))
    vdb.conn.commit()
    assert vdb.group_of(b) is None
    assert vdb.conn.execute("SELECT COUNT(*) FROM version_groups WHERE id = ?",
                            (gid,)).fetchone()[0] == 0


def test_inv2_member_becoming_bonus_disc_leaves_group(vdb):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Japan).zip')
    gid = vg.link([a, b])
    assert vdb.group_of(b) == gid
    vdb.conn.execute("UPDATE games SET is_bonus_disc = 1 WHERE id = ?", (a,))
    vdb.conn.commit()
    assert vdb.group_of(a) is None and vdb.group_of(b) is None
    assert vdb.orphan_groups() == 0


# INV-3 — linking members of two groups merges them into one.
def test_inv3_link_across_groups_merges(vdb):
    a, b, c, d = (vdb.game('Alpha', rom=f'Alpha ({r}).zip')
                  for r in ('USA', 'Europe', 'Japan', 'World'))
    vg.link([a, b])
    vg.link([c, d])
    gid = vg.link([b, c])
    assert [vdb.group_of(x) for x in (a, b, c, d)] == [gid] * 4
    assert vdb.orphan_groups() == 0
