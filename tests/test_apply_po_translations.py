"""scripts/apply_po_translations.py fills a catalog so the entries compile
(PASS-59-109): a filled fuzzy entry loses the flag, and a top-up JSON need
not repeat entries that already have a translation."""
import importlib.util
import json
import pathlib
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

from tests._util import REPO_ROOT


def _load_script():
    path = pathlib.Path(REPO_ROOT) / 'scripts' / 'apply_po_translations.py'
    spec = importlib.util.spec_from_file_location('apply_po_translations', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, monkeypatch, translations):
    po_dir = tmp_path / 'translations' / 'de' / 'LC_MESSAGES'
    po_dir.mkdir(parents=True)
    cat = Catalog(locale='de')
    cat.add('Done', 'Fertig')
    cat.add('Guess', 'Raten', flags=['fuzzy'], previous_id='Gues')
    cat.add('Empty', '')
    with open(po_dir / 'messages.po', 'wb') as f:
        write_po(f, cat)
    (tmp_path / 't.json').write_text(json.dumps(translations), encoding='utf-8')
    script = _load_script()
    monkeypatch.setattr(script, '_REPO_ROOT', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['x', 'de', str(tmp_path / 't.json')])
    with pytest.raises(SystemExit) as exit_info:
        script.main()
    with open(po_dir / 'messages.po', 'rb') as f:
        return exit_info.value.code, read_po(f)


def test_top_up_fills_and_clears_fuzzy(tmp_path, monkeypatch):
    code, cat = _run(tmp_path, monkeypatch, {'Guess': 'Vermuten', 'Empty': 'Leer'})
    assert code == 0
    assert cat.get('Guess').string == 'Vermuten'
    assert not cat.get('Guess').fuzzy
    assert not cat.get('Guess').previous_id
    assert cat.get('Done').string == 'Fertig'


def test_an_unfilled_fuzzy_entry_still_counts_as_missing(tmp_path, monkeypatch):
    code, cat = _run(tmp_path, monkeypatch, {'Empty': 'Leer'})
    assert code == 1
    assert cat.get('Guess').fuzzy
