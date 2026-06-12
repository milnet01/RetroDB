"""Regression pins for the canonical-label translation layer (Pass 43.2).

See docs/specs/i18n.md §7. The drift guards (FIELD_SCHEMAS coverage + cross-field
uniqueness) are pure-Python and always run; the pseudolocale translation
assertions need the compiled catalog (built by the §4 extract -> compile
workflow), so they read services.i18n.PSEUDO_LOCALE rather than hard-coding 'eo'.
"""

import app as app_module
from scraper.scrape_ai import FIELD_SCHEMAS
from services.i18n import PSEUDO_LOCALE
from services.i18n_labels import (
    display_field_value, field_labels_map, CANONICAL_LABELS, I18N_LABEL_FIELDS,
)

app = app_module.app
BRACKET = '⟦'


# ---------------------------------------------------------------------------
# Drift guards (§7) — pure Python, no catalog needed.
# ---------------------------------------------------------------------------

def test_every_field_schema_value_has_a_label_anchor():
    schema_values = set()
    for field in I18N_LABEL_FIELDS:
        schema_values.update(FIELD_SCHEMAS[field])
    missing = schema_values - set(CANONICAL_LABELS)
    assert not missing, f'canonical values without an i18n_labels anchor: {missing}'


def test_no_cross_field_value_collision():
    # Flat msgid namespace assumption: each value lives in exactly one field.
    seen = {}
    for field in I18N_LABEL_FIELDS:
        for value in FIELD_SCHEMAS[field]:
            assert value not in seen, (
                f'{value!r} appears in both {seen[value]!r} and {field!r} — '
                'flat-namespace assumption broken')
            seen[value] = field


def test_label_fields_excludes_non_label_schema_keys():
    # save_type / the *_rating keys etc. must NOT be in the label set.
    for non_label in ('save_type', 'esrb_rating', 'other_platforms', 'campaign'):
        assert non_label not in I18N_LABEL_FIELDS


# ---------------------------------------------------------------------------
# display_field_value (§7)
# ---------------------------------------------------------------------------

def test_display_field_value_roundtrips_english():
    with app.test_request_context('/', headers={'Accept-Language': 'en'}):
        assert display_field_value('genre', 'Action, RPG') == 'Action, RPG'
        assert display_field_value('genre', '') == ''
        assert display_field_value('genre', None) == ''


def test_display_field_value_translates_and_preserves_comma_structure():
    with app.test_request_context('/', headers={'Accept-Language': PSEUDO_LOCALE}):
        out = display_field_value('genre', 'Action, RPG')
        assert out.count(',') == 1                       # structure preserved
        assert all(BRACKET in tok for tok in out.split(','))


def test_unknown_token_passes_through_under_pseudolocale():
    with app.test_request_context('/', headers={'Accept-Language': PSEUDO_LOCALE}):
        out = display_field_value('genre', 'Action, ZzzUserValue')
        assert 'ZzzUserValue' in out                      # user value untouched
        assert BRACKET in out                             # canonical translated


def test_field_labels_map_covers_all_canonical_under_pseudolocale():
    with app.test_request_context('/', headers={'Accept-Language': PSEUDO_LOCALE}):
        fl = field_labels_map()
        assert len(fl) == len(CANONICAL_LABELS)
        assert all(BRACKET in v for v in fl.values())
