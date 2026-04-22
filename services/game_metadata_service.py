# =============================================================================
# RETRODB - Game Metadata Service
# =============================================================================
# Shared helpers for game metadata merging: rating cross-mapping used by both
# the manual edit form (routes/games.py) and the AI-fill endpoint
# (routes/games_ai.py), plus game-card dict shaping used by /api/games and
# /api/games/card-data.
# =============================================================================

from services.game_utils import map_rating, RATING_SYSTEM_KEYS

# 'RP' is "Rating Pending" — not an actual maturity level. Treat it as empty
# so cross-mapping replaces it with a real rating from another system.
_RP_VALUES = frozenset({'RP', 'rp'})


def cross_map_ratings(ratings):
    """Fill empty rating slots from any available rating via maturity tier.

    Args:
        ratings: dict keyed by system ('esrb', 'pegi', ...) with raw rating
                 values (strings; empty strings or None mean "missing").

    Returns:
        dict: new dict with the same keys; empty slots filled from the first
              mappable source.
    """
    result = {k: (ratings.get(k) or '') for k in RATING_SYSTEM_KEYS}
    for tgt_key in RATING_SYSTEM_KEYS:
        if result[tgt_key] and result[tgt_key] not in _RP_VALUES:
            continue
        for src_key in RATING_SYSTEM_KEYS:
            if src_key == tgt_key:
                continue
            src_val = result[src_key]
            if not src_val or src_val in _RP_VALUES:
                continue
            mapped = map_rating(src_key, src_val, tgt_key)
            if mapped:
                result[tgt_key] = mapped
                break
    return result


def import_source_for_rom_path(rom_path):
    """Classify a ROM path's import provenance.

    Returns 'clz', 'steam', 'xbox', 'psn', or None.
    """
    rp = rom_path or ''
    if rp.startswith('clz_import/'):
        return 'clz'
    if rp.startswith('steam_import/'):
        return 'steam'
    if rp.startswith('xbox_import/'):
        return 'xbox'
    if rp.startswith('psn_import/'):
        return 'psn'
    return None


# Columns pulled into a game-card dict. The row must have been selected with
# these (plus the achievement/psn joins handled in the SQL).
_CARD_COLUMNS = (
    'id', 'title', 'sort_title', 'system_id', 'boxart', 'boxart_3d', 'fanart',
    'genre', 'franchise', 'developer', 'publisher', 'release_date', 'modes',
    'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating', 'acb_rating',
    'fpb_rating', 'grac_rating', 'classind_rating',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
    'completion_status', 'scraped', 'has_retroachievements', 'is_bonus_disc',
)


def build_game_card(row, rpcs3_info=None, include_source_flag=False):
    """Shape a games JOIN systems row into the card-data dict used by
    /api/games and /api/games/card-data.

    Args:
        row: sqlite3.Row with card columns + system_name, system_folder,
             system_type, bonus_count, earned_achievements, achievement_total,
             achievement_pct, achievement_source, psn_earned, psn_total.
        rpcs3_info: optional dict with 'earned' and 'total' from RPCS3 local
                    trophies (PS3 only).
        include_source_flag: if True, also emit 'is_clz_import' for legacy
                             consumers of /api/games.

    Returns:
        dict: card-compatible dict matching the keys both endpoints used.
    """
    import_source = import_source_for_rom_path(row['rom_path'] if 'rom_path' in row.keys() else None)

    card = {col: row[col] for col in _CARD_COLUMNS}
    card.update({
        'system_name': row['system_name'],
        'system_folder': row['system_folder'],
        'system_type': row['system_type'] or '',
        'bonus_count': row['bonus_count'],
        'import_source': import_source,
        'achievement_earned': row['earned_achievements'],
        'achievement_total': row['achievement_total'],
        'achievement_pct': row['achievement_pct'],
        'achievement_source': row['achievement_source'],
        'psn_earned': row['psn_earned'],
        'psn_total': row['psn_total'],
        'rpcs3_earned': rpcs3_info['earned'] if rpcs3_info else None,
        'rpcs3_total': rpcs3_info['total'] if rpcs3_info else None,
    })
    if include_source_flag:
        card['is_clz_import'] = import_source == 'clz'
    return card
