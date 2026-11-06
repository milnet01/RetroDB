# =============================================================================
# RETRODB - Reading stored play times
# =============================================================================
# games.playtime_estimate is text: "Main: 36 mins | Main+Extras: 2 hrs | 100%: 5
# hrs" (scraper/hltb_lookup.format_playtime). Older rows say "Main Story: 25½
# Hours" or "Main: 25h". Anything that adds these up reads them here, so a time
# in minutes is never counted as hours (PASS-59-209).
# =============================================================================

import re

_MAIN_STORY = re.compile(
    r'(?:^|\|)\s*Main(?: Story)?\s*:\s*(\d+(?:\.\d*)?|\.\d+)?(½?)\s*(min)?', re.IGNORECASE)


def main_story_hours(estimate):
    """The main-story time in hours, or None when the text holds none."""
    match = _MAIN_STORY.search(estimate or '')
    if not match or not (match.group(1) or match.group(2)):
        return None
    hours = float(match.group(1) or 0) + (0.5 if match.group(2) else 0)
    return hours / 60 if match.group(3) else hours
