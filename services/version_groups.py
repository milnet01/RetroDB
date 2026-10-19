# =============================================================================
# RETRODB - Regional Versions (PASS-59-106)
# =============================================================================
# Links two or more `games` rows on one system as versions of one game, picks
# the preferred version a Library card shows, and suggests groups for the user
# to confirm. The contract is docs/specs/PASS-59-106-regional-versions.md.
#
# This is the only module that writes `games.version_group_id` (INV-9). The
# migration's triggers (016_version_groups) keep the group rules when a row is
# deleted, becomes a bonus disc, or changes system; this module keeps them on
# link and unlink. Nothing is ever linked without the user.
# =============================================================================

import json
import os
import re
from datetime import datetime, timezone

import settings_manager
from services.database import query, get_db_with_context
from services.game_query import escape_like
from services.game_utils import derive_title_from_filename, parse_dump_tags

# Signal names, in the order a suggestion lists them.
SIGNALS = ('igdb_id', 'screenscraper_id', 'title', 'alternate_title')

# Region names that mean the same place for the preferred-version rank (§4.2).
_REGION_ALIASES = {'usa': ('USA', 'North America'), 'north america': ('USA', 'North America')}

_DEFAULT_REGION_OPTIONS = ['USA', 'Europe', 'Japan', 'World']

# One `(...)` or `[...]` tag in a ROM filename.
_TAG_RE = re.compile(r'[(\[]([^()\[\]]*)[)\]]')

# Columns the game page's version list and comparison read (§4.4).
_MEMBER_COLUMNS = """g.id, g.title, g.region, g.rom_path, g.release_date, g.publisher,
    g.critic_score, g.user_score, g.has_retroachievements, g.ra_achievement_count,
    g.esrb_rating, g.pegi_rating, g.cero_rating, g.version_group_id"""


class VersionLinkError(ValueError):
    """A link or rejection the group rules refuse; nothing was written.

    `reason` is one of 'too_few', 'not_found', 'systems', 'bonus' so the
    route can word it for the user.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _now():
    return datetime.now(timezone.utc).isoformat()


def _placeholders(values):
    return ','.join('?' * len(values))


def _clean_ids(game_ids):
    try:
        ids = sorted({int(i) for i in game_ids})
    except (TypeError, ValueError):
        raise VersionLinkError('not_found') from None
    if len(ids) < 2:
        raise VersionLinkError('too_few')
    return ids


def _dissolve_if_small(conn, group_id):
    """A group left with fewer than two members goes (INV-2)."""
    (left,) = conn.execute("SELECT COUNT(*) FROM games WHERE version_group_id = ?",
                           (group_id,)).fetchone()
    if left < 2:
        conn.execute("UPDATE games SET version_group_id = NULL WHERE version_group_id = ?",
                     (group_id,))
        conn.execute("DELETE FROM version_groups WHERE id = ?", (group_id,))


def link(game_ids):
    """Link the games as versions of one game; return the group id.

    Games already in groups bring their whole group along, so linking members
    of two groups merges them (INV-3). Refuses — writing nothing — when the
    games are on two systems or include a bonus disc (INV-1).
    """
    ids = _clean_ids(game_ids)
    rows = query(f"SELECT id, system_id, is_bonus_disc, version_group_id FROM games "
                 f"WHERE id IN ({_placeholders(ids)})", tuple(ids))
    if len(rows) != len(ids):
        raise VersionLinkError('not_found')
    if len({r['system_id'] for r in rows}) > 1:
        raise VersionLinkError('systems')
    if any(r['is_bonus_disc'] for r in rows):
        raise VersionLinkError('bonus')

    existing = sorted({r['version_group_id'] for r in rows if r['version_group_id']})
    with get_db_with_context() as conn:
        if existing:
            group_id, merged = existing[0], existing[1:]
        else:
            group_id = conn.execute("INSERT INTO version_groups (created_at) VALUES (?)",
                                    (_now(),)).lastrowid
            merged = []
        if merged:
            conn.execute(f"UPDATE games SET version_group_id = ? "
                         f"WHERE version_group_id IN ({_placeholders(merged)})",
                         (group_id, *merged))
            conn.execute(f"DELETE FROM version_groups WHERE id IN ({_placeholders(merged)})",
                         tuple(merged))
        conn.execute(f"UPDATE games SET version_group_id = ? WHERE id IN ({_placeholders(ids)})",
                     (group_id, *ids))
        conn.commit()
    return group_id


def unlink(game_id):
    """Take one game out of its group. Returns False if it was in none."""
    row = query("SELECT version_group_id FROM games WHERE id = ?", (game_id,), one=True)
    if not row or not row['version_group_id']:
        return False
    with get_db_with_context() as conn:
        conn.execute("UPDATE games SET version_group_id = NULL WHERE id = ?", (game_id,))
        _dissolve_if_small(conn, row['version_group_id'])
        conn.commit()
    return True


def reject(game_ids):
    """Record that no two of these games are versions of each other."""
    ids = _clean_ids(game_ids)
    found = query(f"SELECT COUNT(*) AS n FROM games WHERE id IN ({_placeholders(ids)})",
                  tuple(ids), one=True)['n']
    if found != len(ids):
        raise VersionLinkError('not_found')
    pairs = [(a, b, _now()) for i, a in enumerate(ids) for b in ids[i + 1:]]
    with get_db_with_context() as conn:
        conn.executemany("INSERT OR IGNORE INTO version_link_rejections "
                         "(game_a, game_b, created_at) VALUES (?, ?, ?)", pairs)
        conn.commit()


# =============================================================================
# PREFERRED VERSION (§4.2)
# =============================================================================

def preferred_rank_sql(alias='g'):
    """SQL ranking a games row for the preferred version, lowest first.

    Tiers: the `default_region` setting, then World, then each
    `region_options` entry in order, then anything else. A row matches a tier
    when its stored region names it, or its region is empty and its ROM path
    carries "(<region>" — so "(USA, Europe)" counts as USA. Computed at query
    time, so a settings change shows on the next page load.

    Returns (sql, params).
    """
    settings = settings_manager.load_settings()
    default = (settings.get('default_region') or 'USA').strip()
    options = settings.get('region_options') or _DEFAULT_REGION_OPTIONS
    tiers = list(dict.fromkeys(r.strip() for r in [default, 'World', *options] if r and r.strip()))

    region = f"COALESCE({alias}.region, '')"
    whens, params = [], []
    for rank, tier in enumerate(tiers):
        for name in _REGION_ALIASES.get(tier.lower(), (tier,)):
            whens.append(f"WHEN LOWER({region}) = LOWER(?) OR ({region} = '' AND "
                         f"{alias}.rom_path LIKE ? ESCAPE '\\') THEN {rank}")
            params.extend([name, f"%({escape_like(name)}%"])
    return f"CASE {' '.join(whens)} ELSE {len(tiers)} END", params


def members(game_id):
    """Every version in this game's group, preferred first; [] if ungrouped.

    Each row gains `region_label` (stored region, else the filename's tag) and
    `dump_tags` (revision, languages, disc from the filename).
    """
    rank_sql, rank_params = preferred_rank_sql('g')
    rows = query(f"""
        SELECT {_MEMBER_COLUMNS}
        FROM games g
        WHERE g.version_group_id IS NOT NULL
          AND g.version_group_id = (SELECT version_group_id FROM games WHERE id = ?)
        ORDER BY {rank_sql}, g.id
    """, (game_id, *rank_params))
    from scraper.scrape_esde import extract_region_from_filename
    result = []
    for row in rows:
        version = dict(row)
        version['region_label'] = (row['region']
                                   or extract_region_from_filename(os.path.basename(row['rom_path'] or ''))
                                   or '')
        version['dump_tags'] = parse_dump_tags(row['rom_path'])
        version['file_size'] = _file_size(row['rom_path'])
        result.append(version)
    return result


def _file_size(rom_path):
    try:
        return os.path.getsize(rom_path) if rom_path and os.path.isfile(rom_path) else None
    except OSError:
        return None


# =============================================================================
# SUGGESTIONS (§4.5)
# =============================================================================

def _variant_tags(rom_path):
    """The filename's tags other than disc numbers, for the title signal."""
    name = os.path.splitext(os.path.basename(rom_path or ''))[0]
    disc = (parse_dump_tags(rom_path)['disc'] or '').lower()
    tags = {t.strip().lower() for t in _TAG_RE.findall(name)}
    tags.discard(disc)
    return frozenset(tags)


def _regional_alt_names(raw):
    """Alternate titles tagged with a real region (PASS-59-105's regional
    names). An untagged name, or a non-region tag such as ScreenScraper's
    "ss", is too often another game's name to be a signal."""
    from scraper.metadata_normalizer import alt_title_region
    try:
        parsed = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return set()
    return {a['title'].strip().lower() for a in parsed
            if isinstance(a, dict) and isinstance(a.get('title'), str) and a['title'].strip()
            and alt_title_region(a.get('region'))[0]}


def suggest_groups(system_id=None):
    """Suggest groups of games that look like versions of one game.

    Pairs non-bonus games on one system, not already in one group and not
    rejected, on any one signal in SIGNALS. Two discs of one game are never
    paired. Pairs sharing a game join into one suggestion.

    Returns [{'games': [...], 'signals': [...]}].
    """
    sql = """
        SELECT id, system_id, title, rom_path, region, igdb_id, screenscraper_id,
               alternate_titles, version_group_id
        FROM games
        WHERE (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
    """
    params = ()
    if system_id:
        sql += " AND system_id = ?"
        params = (system_id,)
    games = {r['id']: dict(r) for r in query(sql, params)}
    rejected = {(r['game_a'], r['game_b'])
                for r in query("SELECT game_a, game_b FROM version_link_rejections")}

    for g in games.values():
        g['key'] = derive_title_from_filename(g['rom_path'] or '').strip().lower()
        g['variant'] = _variant_tags(g['rom_path'])
        g['disc'] = parse_dump_tags(g['rom_path'])['disc']

    pair_signals = {}

    def add(bucket, signal, test=None):
        ids = sorted(bucket)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if test is None or test(games[a], games[b]):
                    pair_signals.setdefault((a, b), set()).add(signal)

    by_system = {}
    for g in games.values():
        by_system.setdefault(g['system_id'], []).append(g)

    for rows in by_system.values():
        for signal in ('igdb_id', 'screenscraper_id'):
            index = {}
            for g in rows:
                if g[signal]:
                    index.setdefault(g[signal], set()).add(g['id'])
            for bucket in index.values():
                add(bucket, signal)

        titles = {}
        for g in rows:
            if g['key']:
                titles.setdefault(g['key'], set()).add(g['id'])
        # "Different region tags": both names carry tags, and they differ.
        for bucket in titles.values():
            add(bucket, 'title',
                lambda a, b: a['variant'] and b['variant'] and a['variant'] != b['variant'])

        alt_index = {}
        for g in rows:
            for name in _regional_alt_names(g['alternate_titles']):
                alt_index.setdefault(name, set()).add(g['id'])
        for g in rows:
            names = {(g['title'] or '').strip().lower(), g['key']} - {''}
            for name in names:
                for other in alt_index.get(name, ()):
                    if other != g['id']:
                        add({g['id'], other}, 'alternate_title')

    def allowed(a, b):
        ga, gb = games[a], games[b]
        if (a, b) in rejected:
            return False
        if ga['version_group_id'] and ga['version_group_id'] == gb['version_group_id']:
            return False
        if ga['disc'] and gb['disc'] and ga['disc'].lower() != gb['disc'].lower():
            return False
        return True

    # Join pairs that share a game into one suggestion (union-find).
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    kept = {pair: sigs for pair, sigs in pair_signals.items() if allowed(*pair)}
    for a, b in kept:
        parent[find(a)] = find(b)
    clusters = {}
    for (a, b), sigs in kept.items():
        cluster = clusters.setdefault(find(a), {'ids': set(), 'signals': set()})
        cluster['ids'].update((a, b))
        cluster['signals'].update(sigs)

    suggestions = []
    for cluster in clusters.values():
        suggestions.append({
            'games': [{'id': i, 'title': games[i]['title'],
                       'rom_file': os.path.basename(games[i]['rom_path'] or ''),
                       'region': games[i]['region'] or '',
                       'system_id': games[i]['system_id'],
                       'version_group_id': games[i]['version_group_id']}
                      for i in sorted(cluster['ids'])],
            'signals': [s for s in SIGNALS if s in cluster['signals']],
        })
    suggestions.sort(key=lambda s: (s['games'][0]['title'] or '').lower())
    return suggestions
