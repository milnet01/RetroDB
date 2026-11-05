"""The words for a service that has stopped at its limit (PASS-59-215)."""

from datetime import datetime, timezone

from flask_babel import gettext as _

from scraper import service_limits
from services.template_filters import tz_filter


def stop_sentences(sources=None):
    """One sentence for each of these services now stopped, all services if None.

    The time is in the reader's time zone from their settings (PASS-59-249).
    """
    said = []
    for source in service_limits.NAMES if sources is None else sources:
        entry = service_limits.stopped(source)
        if not entry:
            continue
        words = {
            'service': service_limits.NAMES[source],
            'when': tz_filter(datetime.fromtimestamp(entry['until'], timezone.utc), 'short'),
        }
        if entry['reason'] == service_limits.KEY_REFUSED:
            said.append(_('%(service)s refused every saved key, which usually means their '
                          'limit is reached. RetroDB will not ask it again until %(when)s.',
                          **words))
        else:
            said.append(_('%(service)s says its limit is reached. RetroDB will not ask it '
                          'again until %(when)s.', **words))
    return said
