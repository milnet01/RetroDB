# =============================================================================
# RETRODB - Which source filled a field, and what the game page marks as AI
# =============================================================================
# `games.scrape_history` credits every write as "field (source)". PASS-59-211:
# what the AI wrote stays, but the game page says so, because an age rating or a
# score from the AI looks just like an official one.
# =============================================================================

import json
import re
from datetime import datetime

from scraper.scrape_ai import VALIDATE_FIELDS
from services.game_utils import RATING_SYSTEM_KEYS, RATING_SYSTEMS

_RATING_COLUMNS = tuple(RATING_SYSTEMS[k]['db_column'] for k in RATING_SYSTEM_KEYS)
_CREDIT = re.compile(r'^(\w+) \((.*)\)$', re.DOTALL)
_INFERRED = 'ratings (inferred from content)'

# Credits that mean a guess. A scraper's value, a person's or a conversion from
# another board's rating is not one.
_GUESS_CREDITS = ('AI', 'inferred')

# What a person can type in the edit forms and the history credits to them:
# the fields the game page marks, the fields AI Fill would otherwise correct
# and the controller a scrape would otherwise set to the system default
# (PASS-59-242).
HAND_EDITED_FIELDS = tuple(dict.fromkeys(
    _RATING_COLUMNS + ('units_sold', 'controller_support') + tuple(sorted(VALIDATE_FIELDS))))


def _entries(history):
    """The history's entries, from the column's JSON or the list the game page
    has already parsed it into."""
    if isinstance(history, list):
        return history
    try:
        entries = json.loads(history or '[]')
    except (ValueError, TypeError):
        return []
    return entries if isinstance(entries, list) else []


def credits(history):
    """{field: source} from the newest scrape to credit each field."""
    found = {}
    for entry in reversed(_entries(history)):
        filled = entry.get('fields_filled', []) if isinstance(entry, dict) else []
        for item in filled:
            if not isinstance(item, str):
                continue
            if item == _INFERRED:
                for column in _RATING_COLUMNS:
                    found.setdefault(column, 'inferred')
            match = _CREDIT.match(item)
            if match:
                found.setdefault(match.group(1), match.group(2))
    return found


def _is_guess(source):
    return source in _GUESS_CREDITS


def ai_marks(game):
    """What the game page marks as coming from the AI.

    `critic_score_count` and `user_score_count` are the counts to show: an AI
    count beside another source's score describes a different score, so it is
    left out rather than shown as that score's count.
    """
    found = credits(game.get('scrape_history'))
    # A rating converted from another board is a guess when every rating it
    # could come from is one (PASS-59-242).
    bases = [found.get(c) for c in _RATING_COLUMNS
             if game.get(c) and not str(found.get(c) or '').startswith('cross-map')]
    from_guesses = bool(bases) and all(_is_guess(b) for b in bases)
    marks = {
        'ratings': {c for c in _RATING_COLUMNS if game.get(c) and (
            _is_guess(found.get(c))
            or (from_guesses and str(found.get(c) or '').startswith('cross-map')))},
        'units_sold': _is_guess(found.get('units_sold')),
    }
    for score in ('critic_score', 'user_score'):
        count = f'{score}_count'
        marks[score] = _is_guess(found.get(score))
        marks[count] = game.get(count)
        if _is_guess(found.get(count)) and not marks[score]:
            marks[count] = None
    return marks


def rating_board_starts(columns):
    """["ESRB 1994", ...] for these rating columns, in the boards' usual order."""
    return [f"{RATING_SYSTEMS[k]['name']} {RATING_SYSTEMS[k]['started']}"
            for k in RATING_SYSTEM_KEYS if RATING_SYSTEMS[k]['db_column'] in columns]


def hand_edit_history(history, old_values, new_values):
    """`history` with an entry crediting a person for each marked field they
    changed, or None if they changed none. A hand-corrected rating is no guess."""
    def _text(value):
        return '' if value is None else str(value).strip()

    changed = [f for f in HAND_EDITED_FIELDS
               if f in new_values and _text(new_values[f]) != _text(old_values.get(f))]
    if not changed:
        return None
    return json.dumps(_entries(history) + [{
        'timestamp': datetime.now().isoformat(),
        'primary_source': 'manual',
        'sources_used': ['Manual edit'],
        'fields_filled': [f'{f} (manual)' for f in changed],
        'fields_missing': [],
    }])
