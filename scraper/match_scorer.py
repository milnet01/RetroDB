# =============================================================================
# RETRODB - Match Scoring
# =============================================================================
# Scores search results against the search query. Pure functions, no state —
# extracted from scraper/scraper_manager.py so the orchestrator stays focused
# on orchestration.
#
# Score layout:
#   calculate_title_match_score — pure title similarity (0-340)
#   calculate_<source>_score    — title score + per-source bonuses
#
# Per-source bonuses follow the same shape:
#   release_date  : +10-20  (TGDB/IGDB/RAWG/SS vary)
#   platform_match: +150    (MAJOR — ensures correct-platform results top)
#   region        : +10-20  (US/WORLD preferred; source-specific codes)
#   plus source-specific extras (RAWG +metacritic, +image)
# =============================================================================

import logging

from scraper.title_normalizer import normalize_for_matching, strip_title_noise

logger = logging.getLogger(__name__)


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


def calculate_title_match_score(result_title, search_title):
    """Title-similarity score between a result and the search query.

    Scoring ladder:
      1. Raw exact match (before noise strip)   -> 350
      2. Exact normalized match                 -> 300
      3. Search words ⊆ result words            -> 150-280 (depends on extras)
      4. Result words ⊆ search words            -> 30-100 (penalised — missing terms)
      5. Partial overlap                        -> 20-120 (Jaccard-weighted)
      + word-order bonus (LCS)                  -> 0-40
    """
    if not result_title or not search_title:
        return 0

    # Raw exact match before noise stripping is a stronger signal than one
    # that only matches after brackets/editions are stripped.
    raw_exact = result_title.strip().lower() == search_title.strip().lower()

    result_title = strip_title_noise(result_title)
    search_title = strip_title_noise(search_title)

    result_normalized = normalize_for_matching(result_title)
    search_normalized = normalize_for_matching(search_title)

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
            f"  WARN: Words match but strings differ! "
            f"result_repr={result_normalized!r} search_repr={search_normalized!r}"
        )

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

    return score


def calculate_ss_score(result, search_title):
    """ScreenScraper relevance score. Mutates result['title_score']."""
    score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = score
    if result.get('release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    region = (result.get('region') or '').upper()
    if region in ('US', 'USA', 'WOR'):
        score += 20
    elif region in ('EU', 'UK'):
        score += 10
    return score


def calculate_tgdb_score(result, search_title):
    """TheGamesDB relevance score. Mutates result['title_score']."""
    score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = score
    if result.get('release_date'):
        score += 10
    if result.get('platform_match'):
        score += 150
    region = result.get('region', '').upper() if result.get('region') else ''
    if region in ('USA', 'WORLD'):
        score += 20
    elif region in ('EUROPE', 'EU', 'UK'):
        score += 10
    return score


def calculate_igdb_score(result, search_title):
    """IGDB relevance score. Mutates result['title_score']."""
    score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = score
    if result.get('first_release_date'):
        score += 20
    if result.get('platform_match'):
        score += 150
    return score


def calculate_rawg_score(result, search_title):
    """RAWG relevance score. Mutates result['title_score']."""
    title_score = calculate_title_match_score(result.get('name', ''), search_title)
    result['title_score'] = title_score
    score = title_score
    if result.get('release_date'):
        score += 20
    if result.get('image'):
        score += 10
    if result.get('platform_match'):
        score += 150
    if result.get('metacritic'):
        score += 15
    logger.info(
        f"RAWG Score for '{result.get('name', '')}': title={title_score}, "
        f"platform_match={result.get('platform_match')}, total={score}"
    )
    return score
