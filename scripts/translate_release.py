#!/usr/bin/env python3
"""Translate a release's new wording into every language, once per release.

Fills what is still English: catalog strings with no usable translation, and
the newest changelog entries a locale's data/changelog.<locale>.yaml lacks.
Run it after the catalogs are regenerated (docs/specs/i18n.md section 4).

Usage:
    python3 scripts/translate_release.py --dry-run     # what would be sent; no call
    python3 scripts/translate_release.py [--locale de] [--locale ja]
    python3 scripts/translate_release.py --seed-terms  # word lists, from the catalogs

Each locale's word list, scripts/translation_terms/<locale>.json, maps an
English word to the translation it must keep. --seed-terms fills it from the
catalog and never changes a word already there, so a corrected word stays.

A translation that loses a placeholder or an HTML tag is asked for once more,
then left out and counted. Exit status is 0 only when nothing was left out.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

import requests
import yaml
from babel import Locale
from babel.messages.pofile import read_po, write_po

from apply_po_translations import _placeholders, _usable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS = os.path.join(REPO, 'translations')
DATA = os.path.join(REPO, 'data')
TERMS_DIR = os.path.join(REPO, 'scripts', 'translation_terms')
SETTINGS_FILE = os.path.join(DATA, 'scraper_settings.json')

MODEL = 'claude-sonnet-5-5'
CHUNK = 40          # strings per request: a failed request costs little
ROUNDS = 2          # a string that comes back unusable is asked for once more

PRODUCT_NAMES = ('RetroDB, RetroArch, DuckStation, PCSX2, RPCS3, RetroAchievements, '
                 'Slipcase, ScreenScraper, IGDB')
# Only words that have their own catalog entry reach a word list.
TERMS = ('Library', 'Game', 'Games', 'Boxart', 'Screenshots', 'Fanart', 'Video', 'Manual',
         'Scrape', 'Full Re-scrape', 'AI Fill', 'Save', 'Cancel', 'Delete', 'Edit', 'Import',
         'Export', 'Settings', 'Emulator', 'Emulators', 'Core', 'Cores', 'Cheats',
         'Achievements', 'Wishlist', 'System', 'Systems', 'Console', 'Genre', 'Publisher',
         'Developer', 'Region', 'Rating', 'Controller', 'Play', 'Login', 'Account', 'Theme',
         'Sign in', 'Sign out', 'Player', 'Backup', 'Download')

_TAG_RE = re.compile(r'</?[a-zA-Z][^>]*>')

tokens = Counter()


def _locales():
    """Every catalog but eo, the pseudolocale gen_pseudolocale.py generates."""
    return sorted(d for d in os.listdir(TRANSLATIONS)
                  if d != 'eo' and os.path.isdir(os.path.join(TRANSLATIONS, d)))


def _po_path(locale):
    return os.path.join(TRANSLATIONS, locale, 'LC_MESSAGES', 'messages.po')


def _terms_path(locale):
    return os.path.join(TERMS_DIR, f'{locale}.json')


def _load_terms(locale):
    if not os.path.exists(_terms_path(locale)):
        return {}
    with open(_terms_path(locale), encoding='utf-8') as f:
        return json.load(f)


def _api_key():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            key = json.load(f).get('api_keys', {}).get('ai_claude_api_key')
        if key:
            return key
    sys.path.insert(0, REPO)
    import config
    return getattr(config, 'AI_CLAUDE_API_KEY', '')


def _marks(text):
    """What must survive translation. Not entities: "&amp;" may rightly become a word."""
    return sorted(_placeholders(text) + _TAG_RE.findall(text))


def _good(source, value):
    """`source` is a string, or (singular, plural, number of forms)."""
    if isinstance(source, str):
        return isinstance(value, str) and bool(value.strip()) and _marks(value) == _marks(source)
    _singular, plural, forms = source
    return (isinstance(value, list) and len(value) == forms
            and all(isinstance(f, str) and f.strip() and _marks(f) == _marks(plural) for f in value))


def _system_prompt(language, terms):
    prompt = (
        f'You translate the wording of RetroDB, an app for a retro game library, from English '
        f'into {language}, for ordinary players. Use natural, plain wording and the same length '
        f'where you can.\n'
        f'You receive a JSON object of numbered strings. Reply with one JSON object only, with '
        f'the same numbers, and no code fences.\n'
        f'An item with "singular", "plural" and "forms" gets a list of exactly that many plural '
        f'forms for {language}, each keeping every placeholder of "plural".\n'
        f'Copy these exactly: placeholders such as %(name)s, %s and {{name}}; HTML tags and '
        f'entities; and the product names {PRODUCT_NAMES}.')
    if terms:
        listed = '\n'.join(f'{en} = {word}' for en, word in sorted(terms.items()))
        prompt += f'\nUse these words wherever the English word has this meaning:\n{listed}'
    return prompt


def _ask_claude(system, payload, key):
    """The numbered reply, or {} on any failure. The key is never printed."""
    try:
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': key, 'anthropic-version': '2023-06-01',
                     'Content-Type': 'application/json'},
            # Same shape as scrape_ai._call_claude: Sonnet 5.5 takes no temperature.
            json={'model': MODEL, 'max_tokens': 16000, 'output_config': {'effort': 'low'},
                  'system': system,
                  'messages': [{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]},
            timeout=300)
    except requests.RequestException as e:
        print(f'  Claude did not answer: {type(e).__name__}')
        return {}
    if response.status_code != 200:
        print(f'  Claude answered with error {response.status_code}')
        return {}
    data = response.json()
    usage = data.get('usage', {})
    tokens['in'] += usage.get('input_tokens', 0)
    tokens['out'] += usage.get('output_tokens', 0)
    text = ''.join(b.get('text', '') for b in data.get('content', []) if b.get('type') == 'text')
    try:
        reply = json.loads(text[text.index('{'):text.rindex('}') + 1])
    except ValueError:
        return {}
    return reply if isinstance(reply, dict) else {}


def _payload_item(source):
    if isinstance(source, str):
        return source
    return {'singular': source[0], 'plural': source[1], 'forms': source[2]}


def _translate(locale, items, key):
    """{key: source} -> {key: translation}, holding only translations that pass _good."""
    language = Locale.parse(locale).english_name
    terms = _load_terms(locale)
    done = {}
    for _round in range(ROUNDS):
        pending = [k for k in items if k not in done]
        for start in range(0, len(pending), CHUNK):
            chunk = pending[start:start + CHUNK]
            payload = {str(i): _payload_item(items[k]) for i, k in enumerate(chunk)}
            blob = json.dumps(payload, ensure_ascii=False).lower()
            used = {en: word for en, word in terms.items() if en.lower() in blob}
            reply = _ask_claude(_system_prompt(language, used), payload, key)
            for i, k in enumerate(chunk):
                value = reply.get(str(i))
                if _good(items[k], value):
                    done[k] = value
    return done


def _read_catalog(locale):
    with open(_po_path(locale), 'rb') as f:
        return read_po(f)


def translate_catalog(locale, key, dry_run):
    """Returns (strings to do, strings left out)."""
    catalog = _read_catalog(locale)
    todo = [m for m in catalog if m.id and not _usable(m)]
    if dry_run or not todo:
        return len(todo), 0
    items = {}
    for i, msg in enumerate(todo):
        if isinstance(msg.id, (list, tuple)):
            items[i] = (msg.id[0], msg.id[1], catalog.num_plurals)
        else:
            items[i] = msg.id
    done = _translate(locale, items, key)
    for i, value in done.items():
        msg = todo[i]
        msg.string = tuple(value) if isinstance(value, list) else value
        msg.flags.discard('fuzzy')
        msg.previous_id = []
    if done:
        with open(_po_path(locale), 'wb') as f:
            write_po(f, catalog, width=76)
    return len(todo), len(todo) - len(done)


def _entries_to_do(english, known):
    """Newest first, down to the first entry this locale already holds whole.
    A locale holding nothing starts at the newest: deep history stays English."""
    todo = []
    for entry in english:
        if known.get(entry['version']) == len(entry['tags']):
            break
        todo.append(entry)
    return todo if known else todo[:1]


def _write_entries(path, new_entries):
    """Put entries at the top of a locale's file, replacing the same versions.
    The other entries stay as they are, byte for byte."""
    text = ''
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            text = f.read()
    parts = re.split(r'(?m)^(?=- version:)', text)
    head, blocks = parts[0], parts[1:]
    replaced = {e['version'] for e in new_entries}
    kept = [b for b in blocks if yaml.safe_load(b)[0]['version'] not in replaced]
    fresh = [yaml.safe_dump([e], allow_unicode=True, sort_keys=False, width=10**6)
             for e in new_entries]
    result = head + ''.join(fresh + kept)
    yaml.safe_load(result)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(result)


def translate_changelog(locale, key, dry_run):
    """Returns (entries to do, entries left out). An entry is written whole or not at all:
    the /changelog route swaps a whole entry in by version."""
    with open(os.path.join(DATA, 'changelog.yaml'), encoding='utf-8') as f:
        english = yaml.safe_load(f)
    path = os.path.join(DATA, f'changelog.{locale}.yaml')
    rows = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            rows = yaml.safe_load(f) or []
    todo = _entries_to_do(english, {r['version']: len(r['tags']) for r in rows})
    if dry_run or not todo:
        return len(todo), 0
    written = []
    for entry in todo:
        items = {i: tag['label'] for i, tag in enumerate(entry['tags'])}
        if entry.get('body'):
            items['body'] = entry['body']
        done = _translate(locale, items, key)
        if len(done) < len(items):
            continue
        out = {'version': entry['version'], 'date': str(entry['date']),
               'tags': [{**tag, 'label': done[i]} for i, tag in enumerate(entry['tags'])]}
        if entry.get('body'):
            out['body'] = done['body']
        written.append(out)
    if written:
        _write_entries(path, written)
    return len(todo), len(todo) - len(written)


def seed_terms(locale):
    """Add each TERMS word the catalog has a translation for. Returns the list's size."""
    terms = _load_terms(locale)
    for msg in _read_catalog(locale):
        if msg.id in TERMS and msg.id not in terms and _usable(msg):
            terms[msg.id] = msg.string
    os.makedirs(TERMS_DIR, exist_ok=True)
    with open(_terms_path(locale), 'w', encoding='utf-8') as f:
        json.dump(terms, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    return len(terms)


def main():
    parser = argparse.ArgumentParser(description='Translate a release\'s new wording.')
    parser.add_argument('--locale', action='append', help='only this locale; may be repeated')
    parser.add_argument('--dry-run', action='store_true', help='count what would be sent; no call')
    parser.add_argument('--seed-terms', action='store_true', help='fill the word lists, then stop')
    args = parser.parse_args()
    locales = args.locale or _locales()

    if args.seed_terms:
        for locale in locales:
            print(f'[{locale}] {seed_terms(locale)} words')
        return 0

    key = '' if args.dry_run else _api_key()
    if not args.dry_run and not key:
        print('No Claude key: set it in Settings > Scraping, or AI_CLAUDE_API_KEY in config.py.')
        return 2

    left_out = 0
    catalogs_changed = False
    for locale in locales:
        strings, strings_out = translate_catalog(locale, key, args.dry_run)
        entries, entries_out = translate_changelog(locale, key, args.dry_run)
        left_out += strings_out + entries_out
        catalogs_changed = catalogs_changed or strings > strings_out
        print(f'[{locale}] {strings} strings, {entries} changelog entries'
              + (f'; left out {strings_out} strings, {entries_out} entries'
                 if strings_out or entries_out else ''), flush=True)

    if catalogs_changed and not args.dry_run:
        subprocess.run(['pybabel', 'compile', '-d', TRANSLATIONS], check=True, capture_output=True)
    if not args.dry_run:
        print(f'Tokens: {tokens["in"]} in, {tokens["out"]} out. Left out: {left_out}.')
    return 1 if left_out else 0


if __name__ == '__main__':
    sys.exit(main())
