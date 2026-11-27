"""PASS-59-339: the Logs page reads each game of a bulk scrape as one entry
with its outcome, and filters those entries by outcome and by game name.

The real log-viewer.js runs in Node over a scraping log shaped like the
lines services/jobs/bulk_scrape.py writes:
- a skipped game writes only "Skipping <title> - <reason>", no "Scraping:";
- a scraped game writes "Scraping: <search title> for <system>" and then the
  scraper's own "Searching for: ..." line, which must not start a second entry;
- a Steam game is searched by its app number, and the outcome line names it;
- "No results passed match filter" is a failure.
"""
import json
import os
import shutil
import subprocess

import pytest

from tests._util import REPO_ROOT

NODE = shutil.which('node')

_LOG = '\n'.join([
    "2026-11-26 17:25:50 | INFO     | - | services.jobs.bulk_scrape | Starting bulk scrape job bulk_1 with 4 games",
    "2026-11-26 17:25:51 | INFO     | - | services.jobs.bulk_scrape | Skipping Mario Party 8 - all metadata fields populated",
    "2026-11-26 17:25:56 | INFO     | - | services.jobs.bulk_scrape | Scraping: 21670 for Microsoft Windows",
    "2026-11-26 17:25:56 | INFO     | - | scraper.scraper_manager | Searching for: '21670' on system: Microsoft Windows (folder: windows)",
    "2026-11-26 17:25:57 | INFO     | - | scraper.scrape_igdb | IGDB found 0 results",
    "2026-11-26 17:26:04 | WARNING  | - | services.jobs.bulk_scrape | No results passed match filter (score mode) for Bionic Commando",
    "2026-11-26 17:26:05 | INFO     | - | services.jobs.bulk_scrape | Scraping: Killzone 2 for Sony PlayStation 3",
    "2026-11-26 17:26:05 | INFO     | - | scraper.scraper_manager | Searching for: 'Killzone 2' on system: Sony PlayStation 3 (folder: ps3)",
    "2026-11-26 17:26:06 | ERROR    | - | scraper.base_scraper | HTTP POST failed: 401 - https://example.invalid/",
    "2026-11-26 17:26:09 | INFO     | - | services.jobs.bulk_scrape | Updated Killzone 2 with 5 fields from IGDB",
    "2026-11-26 17:26:10 | INFO     | - | scraper.image_dedup | Skipping duplicate IGDB screenshot 1_igdb_ss2.webp (visually matches 1_igdb_ss1.webp)",
    "2026-11-26 17:30:00 | INFO     | abcd1234 | scraper.scraper_manager | Searching for: 'Alien Syndrome' on system: Sony PlayStation Portable (folder: psp)",
    "2026-11-26 17:30:02 | INFO     | abcd1234 | scraper.scrape_igdb | IGDB found 2 results",
])

_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
function el() {
  return {value: '', innerHTML: '', style: {}, textContent: '',
          appendChild() {}, addEventListener() {}, setAttribute() {},
          classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }}};
}
const els = {};
const document = {
  addEventListener() {},
  getElementById(id) { return els[id] || (els[id] = el()); },
  querySelectorAll() { return []; },
  createElement() { return el(); },
};
const t = (s, p) => s.replace(/\{(\w+)\}/g, (_, k) => (p && k in p ? p[k] : _));
const ctx = {document, window: {}, console, t, formatNumber: String,
             escapeHtml: s => String(s), actionArgs: () => ''};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const LV = ctx.window.LogViewer;
LV.loadedCategory = 'scraping';
LV.parseContent(fs.readFileSync(0, 'utf8'));
const pick = (outcome, game) => {
  LV.activeOutcome = outcome; LV.gameTerm = game;
  return {
    sessions: LV.getFilteredSessions().map(s => s.title),
    flat: LV.getFilteredLines().map(l => l.lineNumber),
  };
};
console.log(JSON.stringify({
  sessions: LV.sessions.map(s => [s.title, s.outcome, s.lines.length]),
  failed: pick('error', ''),
  skipped: pick('skipped', ''),
  updated: pick('success', ''),
  has_errors: pick('has_errors', ''),
  game: pick('', 'bionic'),
  steam_number: pick('', '21670'),
  none: pick('', 'zelda'),
}));
"""


def _run():
    out = subprocess.run(
        [NODE, '-e', _HARNESS, os.path.join(REPO_ROOT, 'static', 'js', 'log-viewer.js')],
        input=_LOG, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


pytestmark = pytest.mark.skipif(NODE is None, reason='node not installed')


def test_each_game_is_one_entry_with_its_outcome():
    assert _run()['sessions'] == [
        ['Pre-session log entries', 'unknown', 1],
        ['Mario Party 8', 'skipped', 1],
        ['Bionic Commando', 'error', 4],
        ['Killzone 2', 'success', 5],
        ['Alien Syndrome', 'unknown', 2],
    ]


def test_outcome_filter():
    r = _run()
    assert r['failed']['sessions'] == ['Bionic Commando']
    assert r['skipped']['sessions'] == ['Mario Party 8']
    assert r['updated']['sessions'] == ['Killzone 2']
    # An error line inside a game that still updated.
    assert r['has_errors']['sessions'] == ['Killzone 2']


def test_flat_view_follows_the_same_filter():
    r = _run()
    assert r['failed']['flat'] == [3, 4, 5, 6]
    assert r['skipped']['flat'] == [2]


def test_game_filter_matches_the_name_and_the_searched_number():
    r = _run()
    assert r['game']['sessions'] == ['Bionic Commando']
    assert r['steam_number']['sessions'] == ['Bionic Commando']
    assert r['none'] == {'sessions': [], 'flat': []}
