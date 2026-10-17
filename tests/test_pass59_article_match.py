"""PASS-59-92: titles named "Name, The" must pass the scraper match filter.

No-Intro file names put the article last ("Legend of Zelda, The"); every
scraper result puts it first ("The Legend of Zelda"). Before the fix the
comma stayed glued to the last word ("zelda,"), so the word sets never
matched and the bulk scrape logged "No results passed match filter".
"""

import pytest

from scraper.match_scorer import calculate_title_match_score, calculate_tgdb_score
from scraper.scraper_manager import MIN_MATCH_SCORE, passes_match_filter

SCORE_MODE = {'mode': 'score', 'min_score': MIN_MATCH_SCORE,
              'title_quality': 'close', 'platform_required': True}
CRITERIA_MODE = {'mode': 'criteria', 'min_score': MIN_MATCH_SCORE,
                 'title_quality': 'close', 'platform_required': True}

ARTICLE_CASES = [
    ("Legend of Zelda, The", "The Legend of Zelda"),
    ("Legend of Zelda, The: Ocarina of Time", "The Legend of Zelda: Ocarina of Time"),
    ("Legend of Zelda, The - Ocarina of Time", "The Legend of Zelda: Ocarina of Time"),
    ("Legend of Zelda, The (USA)", "The Legend of Zelda"),
    ("Bug's Life, A", "A Bug's Life"),
    ("American Tail, An - Fievel Goes West", "An American Tail: Fievel Goes West"),
]


def _tgdb_result(name):
    # A plain right-platform hit with no date or region extras: the weakest
    # realistic result, so the threshold is tested without help from bonuses.
    return {'name': name, 'platform_match': True}


@pytest.mark.parametrize("local,result", ARTICLE_CASES)
def test_trailing_article_scores_as_exact_match(local, result):
    assert calculate_title_match_score(result, local) >= 300


@pytest.mark.parametrize("local,result", ARTICLE_CASES)
def test_trailing_article_passes_bulk_filter(local, result):
    r = _tgdb_result(result)
    r['score'] = calculate_tgdb_score(r, local)
    assert passes_match_filter(r, SCORE_MODE), r
    assert passes_match_filter(r, CRITERIA_MODE), r


@pytest.mark.parametrize("local,result", ARTICLE_CASES)
def test_trailing_article_passes_score_mode_on_title_alone(local, result):
    # The 2026-10-15 failure was score mode. Not every source sets
    # platform_match, so the title must clear the default floor by itself.
    r = {'name': result}
    r['score'] = calculate_tgdb_score(r, local)
    assert passes_match_filter(r, SCORE_MODE), r


def test_sequel_does_not_become_exact_match_for_original():
    # Negative control: the article fix must not make a different game in the
    # series score as the same title.
    score = calculate_title_match_score(
        "Zelda II: The Adventure of Link", "Legend of Zelda, The")
    assert score < 150


def test_comma_inside_title_is_not_an_article():
    # "A" after a comma mid-title is a word, not a moved article.
    assert calculate_title_match_score(
        "Rock, Paper, Scissors", "Rock, Paper, Scissors") == 350
    assert calculate_title_match_score(
        "The Rock Paper", "Rock, Paper, A Scissors") < 300


def test_unrelated_title_still_rejected():
    r = _tgdb_result("The Legend of Kage")
    r['score'] = calculate_tgdb_score(r, "Legend of Zelda, The")
    assert not passes_match_filter(r, CRITERIA_MODE)
    assert r['title_score'] < 150
