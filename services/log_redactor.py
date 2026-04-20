"""
Log redaction filter — masks secrets in outbound log lines.

The scraper modules log HTTP request URLs, response bodies, and OAuth token
refreshes. Before this filter was added, `logs/scraping_*.log` accumulated
real JWTs, API keys, OAuth refresh tokens, and session cookies over time —
~200 gitleaks hits on a 45-day-old logs directory. See the 2026-04 audit
triage report for the original finding.

Usage:
    from services.log_redactor import SecretRedactor
    handler.addFilter(SecretRedactor())
"""

import logging
import re


# Ordered: most specific first so they win over the generic fallbacks.
_PATTERNS = [
    # JSON token fields: "access_token": "..." / "refresh_token": "..." / "api_key": "..." / etc.
    (re.compile(r'("(?:access_token|refresh_token|id_token|api_key|apiKey|authorization|authKey|authz_c|session_token|secret|password|devpassword|npsso)"\s*:\s*")([^"]+)(")', re.IGNORECASE), r'\1<redacted>\3'),
    # JWT triples (header.payload.signature), 3 base64url segments separated by dots
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b'), '<redacted-jwt>'),
    # Authorization header values: "Authorization: Bearer ..." / "Authorization: Basic ..."
    (re.compile(r'(Authorization:\s*(?:Bearer|Basic|XBL3\.0\s+x=[^;]+;))\s*\S+', re.IGNORECASE), r'\1 <redacted>'),
    # URL query params carrying credentials: ?apikey=... &password=... &token=...
    (re.compile(r'([?&](?:apikey|api_key|token|auth|pwd|password|devpassword|ssid)=)([^&\s"\']+)', re.IGNORECASE), r'\1<redacted>'),
    # Raw "X-Auth: ..." / "X-API-Key: ..." header styles
    (re.compile(r'(X-(?:Auth|API-Key|Session-Token)[^:]*:\s*)\S+', re.IGNORECASE), r'\1<redacted>'),
    # Hex secrets ≥32 chars — catches most hashed tokens; false-positive rate is acceptable for log output
    (re.compile(r'\b[a-f0-9]{40,}\b', re.IGNORECASE), '<redacted-hex>'),
]


def redact(text: str) -> str:
    """Apply all redaction patterns to a string. Public for use in non-logging contexts (e.g. error responses)."""
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class SecretRedactor(logging.Filter):
    """Logging filter that redacts secrets from the formatted message.

    Applied at the handler level so both the main message and any positional
    args get cleaned before they're written to disk.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a for a in (record.args if isinstance(record.args, tuple) else (record.args,))
                )
        except Exception:
            pass
        return True
