"""Display-time translation of canonical multi-value field labels (Pass 43.2).

The DB stores **canonical English** for the multi-value fields (e.g. a game's
genre column holds ``"First-Person-Shooter, 3D"``); these helpers translate only
the *rendered label*. The stored value, every filter/API parameter, and every
``data-filter-value`` stay canonical English, so filtering and round-tripping are
unaffected — the controller / query layer never sees a translated token.

See ``docs/specs/i18n.md`` §7 for the full contract. Import-light by design
(only ``flask_babel``) so it unit-tests without constructing the Flask app.
"""

from flask_babel import gettext, lazy_gettext as _

# Single source of truth for WHICH scraper.scrape_ai.FIELD_SCHEMAS keys get
# label translation. FIELD_SCHEMAS also holds non-label keys (save_type, the
# eight *_rating keys, other_platforms, campaign) which this layer must NOT
# touch. tests/test_i18n_labels.py reads this tuple to pin (a) coverage and
# (b) cross-field uniqueness against FIELD_SCHEMAS over exactly these keys.
I18N_LABEL_FIELDS = ('genre', 'perspective', 'dimension', 'modes', 'game_structure')

# Literal ``lazy_gettext`` anchors so ``pybabel extract`` pulls every canonical
# value into the catalog under the default ``_`` keyword. These MUST stay literal
# ``_('...')`` calls (not a comprehension over FIELD_SCHEMAS) — pybabel does
# static analysis and only extracts literal arguments. The drift test guards
# against this list falling out of sync with FIELD_SCHEMAS, so an added canonical
# value without an anchor here fails CI. ``lazy_gettext`` (deferred) is correct
# at import time, before any request context; the anchors are never rendered —
# display_field_value() does the eager, request-aware translation.
_CANONICAL_LABEL_ANCHORS = (
    # genre
    _('Action'), _('Action-Adventure'), _('Action-Platformer'),
    _('Action-RPG'), _('Adventure'), _('Battle-Royale'), _('Beat-em-up'),
    _('Board-Card'), _('Casual'), _('City-Builder'), _('Driving'),
    _('Educational'), _('Fighting'), _('First-Person-Shooter'), _('Flight'),
    _('Hack-n-Slash'), _('Horror'), _('Hunting'), _('JRPG'),
    _('Life-Simulation'), _('Light-Gun'), _('Management'), _('MMORPG'),
    _('Music-Rhythm'), _('Party'), _('Platformer'),
    _('Psychological-Horror'), _('Puzzle'), _('Racing'),
    _('Real-Time Strategy'), _('RPG'), _('Shoot-em-up'), _('Shooter'),
    _('Simulation'), _('Sports'), _('Stealth'), _('Strategy'), _('Survival'),
    _('Survival-Horror'), _('Tower-Defence'), _('Trivia'),
    _('Turn-Based Strategy'), _('Vehicular-Combat'), _('Visual-Novel'),
    # perspective
    _('First-Person'), _('Isometric'), _('Side-Scroller'), _('Third-Person'),
    _('Top-Down'), _('Vertical-Scroller'),
    # dimension
    _('2D'), _('2.5D'), _('3D'), _('AR (Augmented Reality)'),
    _('FMV (Full Motion Video)'), _('Pseudo-3D'), _('VR'),
    # modes
    _('Asynchronous Multiplayer'), _('Cross-Platform Play'),
    _('LAN-System Link'), _('Local Co-op'), _('Local Multiplayer'), _('MMO'),
    _('Online Co-op'), _('Online Multiplayer'), _('Single-Player'),
    _('Split-Screen'), _('Versus'),
    # game_structure
    _('Hub-Based'), _('Immersive-Sim'), _('Interactive-Drama'),
    _('Labyrinth'), _('Level-Based'), _('Linear'), _('Match-Based'),
    _('Metroidvania'), _('Open-World'), _('Procedural'), _('Roguelike'),
    _('Sandbox'), _('Turn-Based'),
)

# Plain-string view of the same canonical set, for field_labels_map() to build
# window.FIELD_LABELS. Derived from the anchors so the two never drift (str() of
# a lazy_gettext proxy is its msgid before any translation is applied — safe here
# because we only stringify the source text, not a translated result).
CANONICAL_LABELS = tuple(str(anchor) for anchor in _CANONICAL_LABEL_ANCHORS)


def display_field_value(field, value):
    """Translate a comma-separated canonical field value for display.

    Splits ``value`` on ``,``, translates each token via request-aware
    ``gettext``, rejoins with ``', '``. ``None`` / ``''`` -> ``''``. A token with
    no catalog entry (e.g. a user-added dropdown value) passes through unchanged,
    since ``gettext`` returns its argument when there is no translation.

    ``field`` is accepted for call-site clarity and a future ``pgettext`` context;
    v1 uses one flat msgid namespace (the canonical values are unique across the
    five I18N_LABEL_FIELDS — pinned by the drift test).
    """
    if not value:
        return ''
    return ', '.join(
        gettext(token.strip())
        for token in value.split(',')
        if token.strip()
    )


def field_labels_map():
    """Return ``{canonical: translated}`` for every canonical label, active locale.

    Backs ``window.FIELD_LABELS`` (emitted once per full-page render in
    base.html). Locale-aware via eager ``gettext``; a few dozen in-memory catalog
    lookups, so not worth caching (see docs/specs/i18n.md §6 Performance).
    """
    return {label: gettext(label) for label in CANONICAL_LABELS}
