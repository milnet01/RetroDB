# =============================================================================
# RETRODB - Collector Trophies Blueprint
# =============================================================================
# Gamification system that awards trophies based on collection milestones.
# Tracks progress across game count, systems, scraping, and completion stats.
# =============================================================================

from flask import Blueprint, render_template, jsonify
from services.database import query, execute
from services.auth import login_required
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

bp = Blueprint('collector_trophies', __name__)


# =============================================================================
# TROPHY DEFINITIONS
# =============================================================================

TROPHY_DEFINITIONS = [
    # --- Bronze (easy) ---
    {
        'id': 'first_game',
        'name': 'First Steps',
        'description': 'Add your first game',
        'icon': '\U0001F3AE',
        'tier': 'bronze',
        'category': 'collection',
        'threshold': 1,
        'stat': 'game_count',
    },
    {
        'id': 'ten_games',
        'name': 'Getting Started',
        'description': 'Reach 10 games',
        'icon': '\U0001F4DA',
        'tier': 'bronze',
        'category': 'collection',
        'threshold': 10,
        'stat': 'game_count',
    },
    {
        'id': 'first_scrape',
        'name': 'Data Hunter',
        'description': 'Scrape your first game',
        'icon': '\U0001F50D',
        'tier': 'bronze',
        'category': 'discovery',
        'threshold': 1,
        'stat': 'scraped_count',
    },
    {
        'id': 'five_systems',
        'name': 'Multi-Platform',
        'description': 'Have games across 5 systems',
        'icon': '\U0001F579\uFE0F',
        'tier': 'bronze',
        'category': 'collection',
        'threshold': 5,
        'stat': 'system_count',
    },
    {
        'id': 'first_complete',
        'name': 'Finisher',
        'description': 'Complete your first game',
        'icon': '\u2705',
        'tier': 'bronze',
        'category': 'completion',
        'threshold': 1,
        'stat': 'completed_count',
    },

    # --- Silver (medium) ---
    {
        'id': 'hundred_games',
        'name': 'Century Club',
        'description': 'Reach 100 games',
        'icon': '\U0001F4AF',
        'tier': 'silver',
        'category': 'collection',
        'threshold': 100,
        'stat': 'game_count',
    },
    {
        'id': 'fifty_scraped',
        'name': 'Metadata Maven',
        'description': 'Scrape 50 games',
        'icon': '\U0001F4E1',
        'tier': 'silver',
        'category': 'discovery',
        'threshold': 50,
        'stat': 'scraped_count',
    },
    {
        'id': 'ten_systems',
        'name': 'System Collector',
        'description': 'Have games across 10 systems',
        'icon': '\U0001F5A5\uFE0F',
        'tier': 'silver',
        'category': 'collection',
        'threshold': 10,
        'stat': 'system_count',
    },
    {
        'id': 'ten_complete',
        'name': 'Dedicated Player',
        'description': 'Complete 10 games',
        'icon': '\U0001F3C5',
        'tier': 'silver',
        'category': 'completion',
        'threshold': 10,
        'stat': 'completed_count',
    },
    {
        'id': 'five_hundred_games',
        'name': 'Serious Collector',
        'description': 'Reach 500 games',
        'icon': '\U0001F48E',
        'tier': 'silver',
        'category': 'collection',
        'threshold': 500,
        'stat': 'game_count',
    },

    # --- Gold (hard) ---
    {
        'id': 'thousand_games',
        'name': 'Grand Collector',
        'description': 'Reach 1,000 games',
        'icon': '\U0001F451',
        'tier': 'gold',
        'category': 'collection',
        'threshold': 1000,
        'stat': 'game_count',
    },
    {
        'id': 'all_scraped_100',
        'name': 'Completionist Curator',
        'description': '100% metadata coverage',
        'icon': '\U0001F4DC',
        'tier': 'gold',
        'category': 'discovery',
        'threshold': 100,
        'stat': 'scraped_percentage',
    },
    {
        'id': 'twenty_systems',
        'name': 'Platform Master',
        'description': 'Have games across 20 systems',
        'icon': '\U0001F30D',
        'tier': 'gold',
        'category': 'collection',
        'threshold': 20,
        'stat': 'system_count',
    },
    {
        'id': 'fifty_complete',
        'name': 'True Gamer',
        'description': 'Complete 50 games',
        'icon': '\U0001F3C6',
        'tier': 'gold',
        'category': 'completion',
        'threshold': 50,
        'stat': 'completed_count',
    },

    # --- Platinum (legendary) ---
    {
        'id': 'five_thousand',
        'name': 'Legendary Hoarder',
        'description': 'Reach 5,000 games',
        'icon': '\U0001F525',
        'tier': 'platinum',
        'category': 'collection',
        'threshold': 5000,
        'stat': 'game_count',
    },
    {
        'id': 'hundred_complete',
        'name': 'Living Legend',
        'description': 'Complete 100 games',
        'icon': '\u2B50',
        'tier': 'platinum',
        'category': 'completion',
        'threshold': 100,
        'stat': 'completed_count',
    },
    {
        'id': 'thirty_systems',
        'name': 'Universal Collector',
        'description': 'Span 30+ systems',
        'icon': '\U0001F680',
        'tier': 'platinum',
        'category': 'collection',
        'threshold': 30,
        'stat': 'system_count',
    },
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _gather_collection_stats():
    """
    Query the database for current collection statistics used to evaluate
    trophy progress. Returns a dict of stat_name -> current_value.
    """
    # Total game count
    row = query("SELECT COUNT(*) AS cnt FROM games", one=True)
    game_count = row['cnt'] if row else 0

    # Distinct systems with at least one game
    row = query("SELECT COUNT(DISTINCT system_id) AS cnt FROM games", one=True)
    system_count = row['cnt'] if row else 0

    # Games that have been scraped (have a description or overview populated)
    row = query(
        "SELECT COUNT(*) AS cnt FROM games WHERE description IS NOT NULL AND description != ''",
        one=True
    )
    scraped_count = row['cnt'] if row else 0

    # Scraped percentage (0-100)
    if game_count > 0:
        scraped_percentage = int(round((scraped_count / game_count) * 100))
    else:
        scraped_percentage = 0

    # Completed games
    row = query(
        "SELECT COUNT(*) AS cnt FROM games WHERE completion_status IN ('completed', '100_percent')",
        one=True
    )
    completed_count = row['cnt'] if row else 0

    return {
        'game_count': game_count,
        'system_count': system_count,
        'scraped_count': scraped_count,
        'scraped_percentage': scraped_percentage,
        'completed_count': completed_count,
    }


def _refresh_trophies():
    """
    Recalculate all trophy progress from current database state.

    For each trophy definition:
      - Look up the relevant stat value
      - Compute progress (capped at threshold)
      - If threshold is met and trophy not already earned, set earned_at
      - Upsert into collector_trophies table

    Returns a summary dict with counts of earned / newly earned trophies.
    """
    stats = _gather_collection_stats()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    newly_earned = 0
    total_earned = 0

    for trophy_def in TROPHY_DEFINITIONS:
        trophy_id = trophy_def['id']
        stat_key = trophy_def['stat']
        threshold = trophy_def['threshold']
        current_value = stats.get(stat_key, 0)

        # Cap progress at threshold
        progress = min(current_value, threshold)
        met = current_value >= threshold

        # Check existing row
        existing = query(
            "SELECT earned_at FROM collector_trophies WHERE id = ?",
            (trophy_id,),
            one=True
        )

        if existing is not None:
            # Row exists — update progress, conditionally set earned_at
            already_earned = existing['earned_at'] is not None

            if met and not already_earned:
                execute(
                    "UPDATE collector_trophies SET progress = ?, earned_at = ? WHERE id = ?",
                    (progress, now, trophy_id)
                )
                newly_earned += 1
                total_earned += 1
            elif met and already_earned:
                # Already earned — just refresh progress in case threshold changed
                execute(
                    "UPDATE collector_trophies SET progress = ? WHERE id = ?",
                    (progress, trophy_id)
                )
                total_earned += 1
            else:
                # Not met — update progress only
                execute(
                    "UPDATE collector_trophies SET progress = ? WHERE id = ?",
                    (progress, trophy_id)
                )
        else:
            # Insert new row
            earned_at = now if met else None
            if met:
                newly_earned += 1
                total_earned += 1
            execute(
                """INSERT INTO collector_trophies
                   (id, name, description, icon, tier, category, threshold, earned_at, progress)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trophy_id,
                    trophy_def['name'],
                    trophy_def['description'],
                    trophy_def['icon'],
                    trophy_def['tier'],
                    trophy_def['category'],
                    threshold,
                    earned_at,
                    progress,
                )
            )

    logger.info(
        "Collector trophies refreshed: %d total earned, %d newly earned",
        total_earned, newly_earned
    )

    return {
        'total_trophies': len(TROPHY_DEFINITIONS),
        'total_earned': total_earned,
        'newly_earned': newly_earned,
        'stats': stats,
    }


# =============================================================================
# PAGE ROUTES
# =============================================================================

@bp.route('/collector-trophies')
@login_required
def collector_trophies_page():
    """Render the collector trophy showcase page."""
    trophies = query(
        "SELECT * FROM collector_trophies ORDER BY "
        "CASE tier WHEN 'platinum' THEN 1 WHEN 'gold' THEN 2 "
        "WHEN 'silver' THEN 3 WHEN 'bronze' THEN 4 END, name"
    )

    # If no trophies in DB yet, run an initial refresh
    if not trophies:
        _refresh_trophies()
        trophies = query(
            "SELECT * FROM collector_trophies ORDER BY "
            "CASE tier WHEN 'platinum' THEN 1 WHEN 'gold' THEN 2 "
            "WHEN 'silver' THEN 3 WHEN 'bronze' THEN 4 END, name"
        )

    earned_count = sum(1 for t in trophies if t.get('earned_at'))
    total_count = len(trophies)

    return render_template(
        'collector_trophies.html',
        trophies=trophies,
        earned_count=earned_count,
        total_count=total_count,
    )


# =============================================================================
# API ROUTES
# =============================================================================

@bp.route('/api/collector-trophies')
@login_required
def get_all_trophies():
    """Return all collector trophies with their current status."""
    trophies = query(
        "SELECT * FROM collector_trophies ORDER BY "
        "CASE tier WHEN 'platinum' THEN 1 WHEN 'gold' THEN 2 "
        "WHEN 'silver' THEN 3 WHEN 'bronze' THEN 4 END, name"
    )

    # If table is empty, do an initial population
    if not trophies:
        _refresh_trophies()
        trophies = query(
            "SELECT * FROM collector_trophies ORDER BY "
            "CASE tier WHEN 'platinum' THEN 1 WHEN 'gold' THEN 2 "
            "WHEN 'silver' THEN 3 WHEN 'bronze' THEN 4 END, name"
        )

    earned_count = sum(1 for t in trophies if t.get('earned_at'))

    return jsonify({
        'trophies': trophies,
        'earned_count': earned_count,
        'total_count': len(trophies),
    })


@bp.route('/api/collector-trophies/refresh', methods=['POST'])
@login_required
def refresh_trophies():
    """Recalculate all trophy progress from current database state."""
    try:
        result = _refresh_trophies()
        return jsonify({
            'success': True,
            'message': f"{result['newly_earned']} new trophies earned!" if result['newly_earned']
                       else 'Trophy progress updated.',
            **result,
        })
    except Exception as e:
        logger.error("Failed to refresh collector trophies: %s", e, exc_info=True)
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
