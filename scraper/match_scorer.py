# =============================================================================
# RETRODB - Match Scoring
# =============================================================================
# Scores search results against the search query. No state of its own; the
# region bonus reads the region settings. Extracted from
# scraper/scraper_manager.py so the orchestrator stays focused on orchestration.
#
# Score layout:
#   calculate_title_match_score — pure title similarity (0-350)
#   calculate_<source>_score    — title score + per-source bonuses
#
# Per-source bonuses follow the same shape:
#   release_date  : +10
#   platform_match: +150    (MAJOR — ensures correct-platform results top)
#   region        : +10-20  (Default Region and World first; region_bonus;
#                            TGDB and SS only — IGDB and RAWG give none)
# Equal titles on the same platform are then decided by the user's source order
# (the priority boost), so no source may earn more for merely being richer.
# =============================================================================

import logging
import re
import unicodedata

from scraper.title_normalizer import normalize_for_matching, strip_title_noise
from services.achievement_linking import canonical_ra_word, ra_sequel_numbers
from services.game_utils import normalize_article_for_comparison

logger = logging.getLogger(__name__)

# A title equal to the search once noise is stripped scores this or more.
EXACT_TITLE_SCORE = 300

# The title score a match must reach before scraping accepts it on its own,
# whatever other points it earns (PASS-59-208).
MIN_TITLE_SCORE = 80

# The most a title can score when its sequel number differs: below
# MIN_TITLE_SCORE and below the Settings "partial" match, still listed in a
# manual search.
SEQUEL_MISMATCH_MAX_SCORE = 40

# Source region codes (ScreenScraper's lower-case codes, TGDB's names) read
# as the names the region settings use.
_SOURCE_REGIONS = {
    'us': 'USA', 'usa': 'USA', 'north america': 'USA',
    'eu': 'Europe', 'europe': 'Europe', 'uk': 'Europe',
    'jp': 'Japan', 'japan': 'Japan',
    'wor': 'World', 'world': 'World',
}


def region_bonus(region):
    """+20 for the Default Region or World, +10 for the next preferred
    region, else 0. Follows services.version_groups.preferred_regions()."""
    from services.version_groups import preferred_regions
    name = _SOURCE_REGIONS.get((region or '').strip().lower())
    if not name:
        return 0
    order = [r.lower() for r in preferred_regions()]
    if name.lower() in order[:2]:
        return 20
    return 10 if order[2:3] == [name.lower()] else 0


def word_order_bonus(result_words_list, search_words_list):
    """Bonus for words appearing in correct sequential order (0-40 points).

    Uses longest common subsequence (LCS) on word lists.
    """
    if not result_words_list or not search_words_list:
        return 0
    m, n = len(result_words_list), len(search_words_list)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if result_words_list[i - 1] == search_words_list[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    lcs_len = dp[m][n]
    max_len = max(m, n)
    if max_len == 0:
        return 0
    return int((lcs_len / max_len) * 40)


def _sequel_numbers_differ(words_a, words_b):
    """True when two titles' word lists carry different sequel numbers: "Doom"
    and "Doom II", "FIFA 98" and "FIFA 99".

    A "1" is left out: "Doom 1" is the game a source lists as "Doom". A number
    only one title has is forgiven when the subtitle after it is in the other,
    because sources drop it from a game's subtitle: "Golden Sun 2 - The Lost Age"
    is "Golden Sun: The Lost Age".
    """
    words_a = [canonical_ra_word(w) for w in words_a]
    words_b = [canonical_ra_word(w) for w in words_b]
    numbers_a = ra_sequel_numbers(words_a) - {'1'}
    numbers_b = ra_sequel_numbers(words_b) - {'1'}
    if numbers_a == numbers_b:
        return False
    if not (numbers_a < numbers_b or numbers_b < numbers_a):
        return True
    numbered, other = (words_a, words_b) if numbers_b < numbers_a else (words_b, words_a)
    for number in (numbers_a ^ numbers_b):
        after = [w for w in numbered[numbered.index(number) + 1:] if not w.isdigit()]
        if not after or not set(after) <= set(other):
            return True
    return False


def _comparable(title):
    """A title's words as the scorer compares them: no region or edition tags,
    article up front; accents, apostrophes and stray marks gone ("Pokémon" is
    "Pokemon", "Conker's" is "Conkers", "R.B.I." is "RBI"). A dot between digits
    stays: "3.5" is not "35"."""
    title = normalize_article_for_comparison(strip_title_noise(title or ''))
    title = unicodedata.normalize('NFKD', title)
    title = ''.join(c for c in title if not unicodedata.combining(c))
    return normalize_for_matching(re.sub(r"['’`´!?]|(?<!\d)\.|\.(?!\d)", '', title))


def sequel_numbers_agree(result_title, search_title):
    """False when two titles are different games of a series, however alike."""
    return not _sequel_numbers_differ(_comparable(result_title).split(),
                                      _comparable(search_title).split())


def calculate_title_match_score(result_title, search_title):
    """Title-similarity score between a result and the search query.

    Scoring ladder:
      1. Raw exact match (before noise strip)   -> 350
      2. Exact normalized match                 -> 300
      3. Search words ⊆ result words            -> up to 280 (fewer extras score higher)
      4. Result words ⊆ search words            -> up to 100 (penalised — missing terms)
      5. Partial overlap                        -> up to 120 (Jaccard-weighted)
      + word-order bonus (LCS)                  -> 0-40
    A different sequel number caps a non-exact match (SEQUEL_MISMATCH_MAX_SCORE).
    """
    if not result_title or not search_title:
        return 0

    # Raw exact match before noise stripping is a stronger signal than one
    # that only matches after brackets/editions are stripped.
    raw_exact = result_title.strip().lower() == search_title.strip().lower()

    result_normalized = _comparable(result_title)
    search_normalized = _comparable(search_title)

    result_words_list = result_normalized.split()
    search_words_list = search_normalized.split()
    result_words = set(result_words_list)
    search_words = set(search_words_list)

    logger.info(
        f"Title match: result='{result_normalized}' search='{search_normalized}' "
        f"| result_words={result_words} search_words={search_words}"
    )
    if result_words == search_words and result_normalized != search_normalized:
        logger.info(
            f"  Same words, different order: "
            f"result_repr={result_normalized!r} search_repr={search_normalized!r}"
        )

    # A title that was only tags ("(USA)") has nothing left to compare.
    if not result_normalized or not search_normalized:
        return 0

    # Exact normalized match — already in correct word order, no bonus needed.
    if result_normalized == search_normalized:
        bonus = 50 if raw_exact else 0
        logger.info(f"  -> EXACT MATCH: {300 + bonus} (raw_exact={raw_exact})")
        return 300 + bonus

    score = 0

    if search_words <= result_words:
        # Search is subset of result — "Rogue" finds "Assassin's Creed Rogue".
        extra_words = len(result_words) - len(search_words)
        if extra_words == 0:
            score = 280
            logger.info(f"  -> EXACT WORDS: {score}")
        elif extra_words <= 2:
            completeness = len(search_words) / len(result_words) if result_words else 0
            score = int(200 * completeness)
            logger.info(f"  -> search subset of result ({extra_words} extra): {score}")
        else:
            completeness = len(search_words) / len(result_words) if result_words else 0
            score = int(150 * completeness)
            logger.info(f"  -> search subset of result ({extra_words} extra, many): {score}")
    elif result_words <= search_words:
        # Result missing words from search — penalise. "Assassin's Creed" should
        # NOT beat "Assassin's Creed Rogue" when searching for the latter.
        missing_words = len(search_words) - len(result_words)
        completeness = len(result_words) / len(search_words) if search_words else 0
        if missing_words == 1:
            score = int(100 * completeness)
            logger.info(f"  -> result subset of search ({missing_words} missing): {score}")
        elif missing_words == 2:
            score = int(60 * completeness)
            logger.info(f"  -> result subset of search ({missing_words} missing): {score}")
        else:
            score = int(30 * completeness)
            logger.info(f"  -> result subset of search ({missing_words} missing, many): {score}")
    else:
        # Partial overlap — Jaccard weighted by search coverage.
        if result_words and search_words:
            common_words = result_words & search_words
            union_words = result_words | search_words
            jaccard = len(common_words) / len(union_words) if union_words else 0
            search_coverage = len(common_words) / len(search_words) if search_words else 0
            if search_coverage >= 0.8:
                score += int(120 * jaccard)
            elif search_coverage >= 0.6:
                score += int(80 * jaccard)
            elif search_coverage >= 0.4:
                score += int(50 * jaccard)
            else:
                score += int(20 * jaccard)

    order_bonus = word_order_bonus(result_words_list, search_words_list)
    if order_bonus > 0:
        score += order_bonus
        logger.info(f"  -> Word order bonus: +{order_bonus}")

    if _sequel_numbers_differ(result_words_list, search_words_list):
        logger.info(f"  -> Different sequel number: capped at {SEQUEL_MISMATCH_MAX_SCORE}")
        return min(score, SEQUEL_MISMATCH_MAX_SCORE)
    return score


def calculate_ss_score(result, search_title):
    """ScreenScraper relevance score. Mutates result['title_score']."""
    # Every regional name counts: a ROM may carry its Japanese title while the
    # result's main name follows the user's preferred region.
    names = [result.get('name', '')]
    names += [a.get('title', '') for a in result.get('alternate_titles') or []]
    score = max(calculate_title_match_score(n, search_title) for n in names)
    result['title_score'] = score
    if result.get('release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    return score + region_bonus(result.get('region'))


def calculate_tgdb_score(result, search_title):
    """TheGamesDB relevance score. Mutates result['title_score']."""
    score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = score
    if result.get('release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    return score + region_bonus(result.get('region'))


def calculate_igdb_score(result, search_title):
    """IGDB relevance score. Mutates result['title_score']."""
    score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = score
    if result.get('first_release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    return score


def calculate_rawg_score(result, search_title):
    """RAWG relevance score. Mutates result['title_score']."""
    title_score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = title_score
    score = title_score
    if result.get('release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    logger.info(
        f"RAWG Score for '{result.get('name', '')}': title={title_score}, "
        f"platform_match={result.get('platform_match')}, total={score}"
    )
    return score
