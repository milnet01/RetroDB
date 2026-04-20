# =============================================================================
# RETRODB - Museum Content Generation Job
# =============================================================================
# Background job for bulk AI generation of system museum content
# (history, summary, top games). Follows BulkScrapeJob pattern.
# =============================================================================

import threading
import time
import json
import logging
from datetime import datetime, timezone

from services.jobs.base import _get_conn

logger = logging.getLogger(__name__)


class MuseumGenerateJob:
    """Manages bulk museum content generation via AI providers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.reset()

    def reset(self):
        """Reset job state."""
        self.running = False
        self.cancelled = False
        self.completed = False
        self.current_index = 0
        self.total_systems = 0
        self.current_system_name = ""
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self.overwrite = False

    def start(self, system_ids=None, overwrite=False):
        """Start bulk museum generation.

        Args:
            system_ids: Optional list of system IDs. If None, generates for all systems.
            overwrite: If True, regenerate even if content already exists.
        Returns:
            dict with status info.
        """
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Generation already in progress'}

            self.reset()
            self.running = True
            self.overwrite = overwrite
            self.start_time = datetime.now(timezone.utc).isoformat()

            self._thread = threading.Thread(
                target=self._worker,
                args=(system_ids,),
                daemon=True
            )
            self._thread.start()

        return {'success': True, 'message': 'Museum generation started'}

    def cancel(self):
        """Cancel running generation."""
        with self._lock:
            if not self.running:
                return {'success': False, 'error': 'No generation running'}
            self.cancelled = True
        return {'success': True, 'message': 'Cancellation requested'}

    def get_status(self):
        """Return current job status."""
        return {
            'running': self.running,
            'cancelled': self.cancelled,
            'completed': self.completed,
            'current_index': self.current_index,
            'total_systems': self.total_systems,
            'current_system_name': self.current_system_name,
            'success_count': self.success_count,
            'failed_count': self.failed_count,
            'skipped_count': self.skipped_count,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'error_message': self.error_message,
        }

    def _worker(self, system_ids=None):
        """Background worker — loops systems and generates AI content."""
        import config
        from scraper.scrape_ai import (
            _get_active_provider, _call_gemini, _call_openai, _call_claude,
        )

        conn = None
        try:
            conn = _get_conn()
            c = conn.cursor()

            # Get list of systems to process
            if system_ids:
                placeholders = ','.join('?' * len(system_ids))
                c.execute(
                    f"SELECT id, name, folder FROM systems WHERE id IN ({placeholders}) ORDER BY name",
                    system_ids
                )
            else:
                c.execute("SELECT id, name, folder FROM systems ORDER BY name")

            systems = c.fetchall()
            self.total_systems = len(systems)

            if self.total_systems == 0:
                self.running = False
                self.completed = True
                self.end_time = datetime.now(timezone.utc).isoformat()
                conn.close()
                return

            # Check AI provider availability
            provider_config = _get_active_provider()
            if not provider_config:
                self.running = False
                self.error_message = 'No AI provider configured. Set up an AI provider in Settings.'
                self.end_time = datetime.now(timezone.utc).isoformat()
                conn.close()
                return

            provider = provider_config['provider']
            api_key = provider_config['api_key']
            model = provider_config['model']

            call_kwargs = {}
            if provider == 'gemini' and provider_config.get('project_id'):
                call_kwargs['project_id'] = provider_config['project_id']

            call_fn = {
                'gemini': _call_gemini,
                'openai': _call_openai,
                'claude': _call_claude,
            }.get(provider)

            if not call_fn:
                self.running = False
                self.error_message = f'Unknown AI provider: {provider}'
                self.end_time = datetime.now(timezone.utc).isoformat()
                conn.close()
                return

            for i, system in enumerate(systems):
                if self.cancelled:
                    break

                system_id = system['id']
                system_name = system['name']
                folder = system['folder']
                self.current_index = i + 1
                self.current_system_name = system_name

                # Check if already generated (skip unless overwrite)
                if not self.overwrite:
                    existing = c.execute(
                        "SELECT id FROM system_museum WHERE system_id = ? AND history IS NOT NULL AND history != ''",
                        (system_id,)
                    ).fetchone()
                    if existing:
                        self.skipped_count += 1
                        continue

                # Get specs for prompt context
                specs = config.SYSTEM_SPECS.get(folder, {})

                # Build prompt for history + summary
                prompt = _build_museum_prompt(system_name, specs)

                try:
                    raw_text = call_fn(prompt, api_key, model, **call_kwargs)
                    if not raw_text:
                        logger.warning(f"Museum: Empty AI response for {system_name}")
                        self.failed_count += 1
                        time.sleep(1.5)
                        continue

                    data = _parse_museum_response(raw_text)
                    history = data.get('history', '')
                    summary = data.get('summary', '')

                    if not history and not summary:
                        logger.warning(f"Museum: No usable content for {system_name}")
                        self.failed_count += 1
                        time.sleep(1.5)
                        continue

                    # Generate top games separately
                    top_games_json = self._generate_top_games(
                        system_id, system_name, call_fn, api_key, model, conn, call_kwargs
                    )

                    # Upsert into system_museum
                    now = datetime.now(timezone.utc).isoformat()
                    c.execute("""
                        INSERT INTO system_museum (system_id, history, summary, top_games, generated_at, generated_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(system_id) DO UPDATE SET
                            history = excluded.history,
                            summary = excluded.summary,
                            top_games = excluded.top_games,
                            generated_at = excluded.generated_at,
                            generated_by = excluded.generated_by
                    """, (system_id, history, summary, top_games_json, now, provider))
                    conn.commit()

                    self.success_count += 1
                    logger.info(f"Museum: Generated content for {system_name}")

                except Exception as e:
                    logger.error(f"Museum: Error generating for {system_name}: {e}")
                    self.failed_count += 1

                # Rate limiting between systems
                time.sleep(1.5)

        except Exception as e:
            logger.error(f"Museum generation worker error: {e}")
            self.error_message = str(e)
        finally:
            self.running = False
            self.completed = True
            self.end_time = datetime.now(timezone.utc).isoformat()
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _generate_top_games(self, system_id, system_name, call_fn, api_key, model, conn, call_kwargs=None):
        """Generate AI-suggested top 10 games, supplementing DB critic_score data.

        Returns:
            JSON string of top games array.
        """
        c = conn.cursor()

        # Get top-scored games from DB
        db_games = c.execute("""
            SELECT title, critic_score FROM games
            WHERE system_id = ? AND critic_score IS NOT NULL AND critic_score > 0
            ORDER BY critic_score DESC
            LIMIT 10
        """, (system_id,)).fetchall()

        existing_titles = [g['title'] for g in db_games]

        if len(existing_titles) >= 10:
            # Already have 10 scored games — use DB data
            top_games = [
                {'title': g['title'], 'rank': i + 1, 'source': 'db', 'score': g['critic_score']}
                for i, g in enumerate(db_games)
            ]
            return json.dumps(top_games)

        # Need AI to fill remaining spots
        prompt = _build_top_games_prompt(system_name, existing_titles)

        try:
            raw_text = call_fn(prompt, api_key, model, **(call_kwargs or {}))
            if raw_text:
                ai_data = _parse_museum_response(raw_text)
                ai_games = ai_data.get('top_games', [])

                # Combine: DB games first, then AI suggestions
                top_games = [
                    {'title': g['title'], 'rank': i + 1, 'source': 'db', 'score': g['critic_score']}
                    for i, g in enumerate(db_games)
                ]

                rank = len(top_games) + 1
                for ag in ai_games:
                    if rank > 10:
                        break
                    title = ag.get('title', '') if isinstance(ag, dict) else str(ag)
                    if title and title not in existing_titles:
                        top_games.append({'title': title, 'rank': rank, 'source': 'ai'})
                        existing_titles.append(title)
                        rank += 1

                return json.dumps(top_games)
        except Exception as e:
            logger.warning(f"Museum: Top games AI error for {system_name}: {e}")

        # Fallback: just return DB games
        top_games = [
            {'title': g['title'], 'rank': i + 1, 'source': 'db', 'score': g['critic_score']}
            for i, g in enumerate(db_games)
        ]
        return json.dumps(top_games) if top_games else '[]'


def _build_museum_prompt(system_name, specs):
    """Build AI prompt for system history and summary."""
    specs_context = ""
    if specs:
        specs_lines = []
        for key, val in specs.items():
            specs_lines.append(f"  {key}: {val}")
        specs_context = f"\nKnown specifications:\n" + "\n".join(specs_lines)

    return f"""You are a gaming history expert. Write about the "{system_name}" gaming system.
{specs_context}

Return a JSON object with exactly these fields:
- "history": A detailed 3-5 paragraph history of the system. Cover its development, launch, notable features, market reception, legacy, and impact on the gaming industry. Write in an engaging, encyclopedic style. Use plain text paragraphs separated by newlines.
- "summary": A concise 1-2 sentence summary of the system suitable for a card/preview.

Rules:
- Return ONLY valid JSON. No markdown, no code fences.
- Be factually accurate. If unsure about details, focus on what is well-known.
- Do not include specs in the history — those are displayed separately.
"""


def _build_top_games_prompt(system_name, existing_titles):
    """Build AI prompt for top games suggestions."""
    exclude = ""
    if existing_titles:
        exclude = f"\nAlready have these titles (do NOT repeat them): {', '.join(existing_titles[:10])}"

    need = 10 - len(existing_titles)

    return f"""You are a gaming expert. List the top {need} most acclaimed/beloved games for the "{system_name}".
{exclude}

Return a JSON object with exactly this field:
- "top_games": An array of objects, each with "title" (string, game name only — no platform suffixes).

Rules:
- Return ONLY valid JSON. No markdown, no code fences.
- Order by how universally acclaimed/important the game is for this platform.
- Use the most common English title for each game.
"""


def _parse_museum_response(raw_text):
    """Parse AI response JSON for museum content."""
    import re

    if not raw_text:
        return {}

    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
        text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # Try more aggressive extraction for nested JSON
    brace_start = text.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[brace_start:i + 1])
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        break

    logger.warning(f"Museum: Failed to parse AI response: {text[:200]}")
    return {}


# Singleton instance
museum_generate_job = MuseumGenerateJob()
