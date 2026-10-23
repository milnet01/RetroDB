# =============================================================================
# RETRODB - Official names: review, accept, reject (PASS-59-159)
# =============================================================================
# The proposals services/jobs/official_names.py stores wait here for the
# user. Accepting one is the only path that writes a proposed name into
# `games` (docs/specs/PASS-59-159-official-names.md §4.5).
# =============================================================================

import json
import logging
import os
from datetime import datetime

from services.database import get_db

logger = logging.getLogger(__name__)

SOURCE = 'official_names'


def pending(system_id=None):
    """Pending proposals, ordered by system then old title."""
    where = "AND g.system_id = ?" if system_id else ""
    params = (system_id,) if system_id else ()
    conn = get_db()
    try:
        rows = conn.execute(f"""
            SELECT p.game_id, g.system_id, s.name AS system_name, g.rom_path,
                   p.old_title, p.proposed_title, p.old_title_region
            FROM title_proposals p
            JOIN games g ON g.id = p.game_id
            JOIN systems s ON s.id = g.system_id
            WHERE p.status = 'pending' {where}
            ORDER BY s.name COLLATE NOCASE, p.old_title COLLATE NOCASE
        """, params).fetchall()
    finally:
        conn.close()
    return [{
        'game_id': r['game_id'], 'system_id': r['system_id'],
        'system_name': r['system_name'],
        'rom_file': os.path.basename(r['rom_path'] or ''),
        'old_title': r['old_title'], 'proposed_title': r['proposed_title'],
        'old_title_region': r['old_title_region'],
    } for r in rows]


def _history_with(history_json, old_title, new_title):
    try:
        history = json.loads(history_json) if history_json else []
    except (ValueError, TypeError):
        history = []
    if not isinstance(history, list):
        history = []
    history.append({
        'timestamp': datetime.now().isoformat(),
        'primary_source': SOURCE,
        'sources_used': ['Official names'],
        'fields_filled': [f'title (Official names: {old_title} → {new_title})'],
        'fields_missing': [],
    })
    return json.dumps(history)


def accept(game_ids):
    """Apply each game's pending proposal. Returns (accepted, skipped).

    A game whose title changed since the proposal was made is skipped and
    its proposal deleted (INV-5)."""
    from scraper.metadata_normalizer import alt_title_entry, merge_alt_titles
    from services.game_utils import generate_sort_title

    accepted = skipped = 0
    conn = get_db()
    try:
        with conn:
            for game_id in game_ids:
                row = conn.execute("""
                    SELECT p.old_title, p.proposed_title, p.old_title_region,
                           g.title, g.alternate_titles, g.scrape_history
                    FROM title_proposals p JOIN games g ON g.id = p.game_id
                    WHERE p.game_id = ? AND p.status = 'pending'
                """, (game_id,)).fetchone()
                if row is None:
                    continue
                if row['title'] != row['old_title']:
                    conn.execute("DELETE FROM title_proposals WHERE game_id = ?", (game_id,))
                    skipped += 1
                    continue
                new_title = row['proposed_title']
                alts = merge_alt_titles(
                    row['alternate_titles'],
                    [alt_title_entry(row['old_title'], region=row['old_title_region'],
                                     source=SOURCE)],
                    primary_title=new_title)
                # merge_alt_titles drops new entries equal to the primary,
                # but keeps stored ones.
                alts = [a for a in alts if a['title'].lower() != new_title.lower()]
                conn.execute("""
                    UPDATE games SET title = ?, sort_title = ?, title_locked = 1,
                                     alternate_titles = ?, scrape_history = ?
                    WHERE id = ?
                """, (new_title, generate_sort_title(new_title),
                      json.dumps(alts) if alts else None,
                      _history_with(row['scrape_history'], row['old_title'], new_title),
                      game_id))
                conn.execute("DELETE FROM title_proposals WHERE game_id = ?", (game_id,))
                accepted += 1
    finally:
        conn.close()
    logger.info(f"Official names: {accepted} accepted, {skipped} skipped (title changed)")
    return accepted, skipped


def reject(game_ids):
    """Mark each game's pending proposal rejected. Returns how many."""
    if not game_ids:
        return 0
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                f"UPDATE title_proposals SET status = 'rejected' "
                f"WHERE status = 'pending' AND game_id IN ({','.join('?' * len(game_ids))})",
                tuple(game_ids))
            return cur.rowcount
    finally:
        conn.close()
