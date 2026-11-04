"""The words for a service that has stopped at its limit (PASS-59-215)."""

from datetime import datetime

from flask_babel import gettext as _

from scraper import service_limits


def stop_sentences(sources=None):
    """One sentence for each of these services now stopped, all services if None."""
    said = []
    for source in sources or service_limits.NAMES:
        entry = service_limits.stopped(source)
        if not entry:
            continue
        words = {
            'service': service_limits.NAMES[source],
            'when': datetime.fromtimestamp(entry['until']).strftime('%Y-%m-%d %H:%M'),
        }
        if entry['reason'] == service_limits.KEY_REFUSED:
            said.append(_('%(service)s refused every saved key, which usually means their '
                          'limit is reached. RetroDB will not ask it again until %(when)s.',
                          **words))
        else:
            said.append(_('%(service)s says its limit is reached. RetroDB will not ask it '
                          'again until %(when)s.', **words))
    return said
