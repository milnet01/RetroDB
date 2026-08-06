"""Pins the two long-form-content invariants in docs/specs/i18n.md §9.

The help manual and the changelog are deliberately NOT in the gettext catalog
— each is translated as a whole file per locale with English fallback (Pass
43.6). That delivery path has no extractor and no `check_i18n_fresh.py` gate,
so both invariants were enforced only by the maintainer remembering them, and
one of them was already broken when Pass 57.7 filed these tests:

  * Changelog — a locale entry must repeat `version`, `date` and **every** tag
    verbatim, because the /changelog route swaps the whole entry in by version
    rather than merging field-by-field. Anything the locale entry omits is
    dropped from the rendered page, not inherited from English.
  * Help — every `id="..."` and `href="#..."` anchor must match `help.html`
    exactly, or the in-page nav links break for that locale.

Absence is never a failure in either case: §9 states partial coverage is fine
and a missing file falls back to English. What these tests catch is a file
that IS present and disagrees.
"""
import collections
import glob
import os
import re

import yaml

from tests._util import REPO_ROOT

# Versions whose locale entries are known to drop a tag, pending the
# retranslation in roadmap.md Pass 57.6. Both directions are asserted below: a
# NEW gap fails, and a gap that has since been fixed but is still listed here
# also fails — so this set cannot quietly rot into a blanket exemption.
KNOWN_TAG_GAPS = {'3.20.0'}


def _load_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _locale_changelogs():
    paths = sorted(glob.glob(os.path.join(REPO_ROOT, 'data', 'changelog.*.yaml')))
    # A glob that matched nothing would make every loop below vacuous.
    assert len(paths) >= 9, f'expected the shipped locale changelogs, found {paths}'
    return [(os.path.basename(p).split('.')[1], p) for p in paths]


def _english_by_version():
    return {e['version']: e
            for e in _load_yaml(os.path.join(REPO_ROOT, 'data', 'changelog.yaml'))}


def _tag_types(entry):
    """Multiset of tag `type` values. Labels are translated; types are not."""
    return collections.Counter(t.get('type') for t in (entry.get('tags') or []))


def test_locale_changelog_entries_name_a_real_english_version():
    """An entry whose version has no English counterpart can never render —
    the route merges by version over the English timeline."""
    english = _english_by_version()
    orphans = [(loc, e.get('version'))
               for loc, path in _locale_changelogs()
               for e in _load_yaml(path)
               if e.get('version') not in english]
    assert not orphans, f'locale entries for versions absent from English: {orphans}'


def test_locale_changelog_entries_repeat_the_date_verbatim():
    """`date` is dropped, not inherited, if the locale entry omits or changes it.

    Compared as text: YAML parses an unquoted `2026-06-26` into a datetime.date
    and a quoted one into a str, and §9 asks for the same date, not the same
    scalar type.
    """
    english = _english_by_version()
    drift = []
    for loc, path in _locale_changelogs():
        for entry in _load_yaml(path):
            version = entry.get('version')
            if version not in english:
                continue  # covered by the test above
            want = str(english[version].get('date'))
            got = str(entry.get('date'))
            if got != want:
                drift.append(f'{loc} {version}: {got!r} != English {want!r}')
    assert not drift, 'locale changelog date drift:\n  ' + '\n  '.join(drift)


def test_locale_changelog_entries_repeat_every_tag():
    """A tag the locale entry omits vanishes from the rendered page.

    This is the invariant Pass 57.6 found violated: every locale dropped the
    `fix` tag from 3.20.0, so twenty languages rendered that release as
    feature-only.
    """
    english = _english_by_version()
    gaps = collections.defaultdict(list)
    for loc, path in _locale_changelogs():
        for entry in _load_yaml(path):
            version = entry.get('version')
            if version not in english:
                continue
            want, got = _tag_types(english[version]), _tag_types(entry)
            if want != got:
                gaps[version].append(f'{loc}: missing {sorted((want - got).elements())}'
                                     f' extra {sorted((got - want).elements())}')

    new_gaps = {v: sorted(d) for v, d in gaps.items() if v not in KNOWN_TAG_GAPS}
    assert not new_gaps, (
        'locale changelog entries dropped tags English has:\n  '
        + '\n  '.join(f'{v}: {d}' for v, d in sorted(new_gaps.items()))
    )

    stale = KNOWN_TAG_GAPS - set(gaps)
    assert not stale, (
        f'{sorted(stale)} no longer drops tags — remove it from KNOWN_TAG_GAPS '
        'so the exemption does not outlive the gap it was granted for'
    )


# ---------------------------------------------------------------------------
# Help manual — anchor byte-identity (docs/specs/i18n.md §9).
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r'''\bid=["']([^"']+)["']''')
_HREF_RE = re.compile(r'''\bhref=["']#([^"']+)["']''')


def _anchors(path):
    with open(path, encoding='utf-8') as f:
        src = f.read()
    return set(_ID_RE.findall(src)), set(_HREF_RE.findall(src))


def test_help_locale_anchors_match_english_exactly():
    """Translated help files must keep `id=` / `href="#..."` byte-identical.

    Translating an anchor along with its heading text is the easy mistake, and
    it silently breaks that locale's in-page navigation — nothing else in the
    build would notice.
    """
    en_ids, en_hrefs = _anchors(os.path.join(REPO_ROOT, 'templates', 'help.html'))
    assert en_ids, 'no anchors found in help.html — the regexes are wrong'

    paths = sorted(glob.glob(os.path.join(REPO_ROOT, 'templates', 'help.*.html')))
    assert len(paths) >= 9, f'expected the shipped locale help files, found {paths}'

    drift = []
    for path in paths:
        loc = os.path.basename(path).split('.')[1]
        ids, hrefs = _anchors(path)
        if ids != en_ids:
            drift.append(f'{loc} ids: missing {sorted(en_ids - ids)} '
                         f'extra {sorted(ids - en_ids)}')
        if hrefs != en_hrefs:
            drift.append(f'{loc} hrefs: missing {sorted(en_hrefs - hrefs)} '
                         f'extra {sorted(hrefs - en_hrefs)}')
    assert not drift, 'help anchor drift:\n  ' + '\n  '.join(drift)


def test_every_help_href_resolves_to_an_id_in_english():
    """The source of truth must itself be internally consistent — otherwise
    the set-equality test above would happily pin a broken nav link into all
    twenty translations."""
    ids, hrefs = _anchors(os.path.join(REPO_ROOT, 'templates', 'help.html'))
    assert not (hrefs - ids), \
        f'help.html links to anchors it does not define: {sorted(hrefs - ids)}'
