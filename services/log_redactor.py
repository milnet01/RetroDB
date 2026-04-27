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
    # Pass 33.10 — Python repr() form of the same dict keys, e.g.
    # "{'access_token': 'abc'}" coming out of `logger.info('%r', dct)`.
    (re.compile(r"('(?:access_token|refresh_token|id_token|api_key|apiKey|authorization|authKey|authz_c|session_token|secret|password|devpassword|npsso)'\s*:\s*')([^']+)(')", re.IGNORECASE), r'\1<redacted>\3'),
    # JWT triples (header.payload.signature), 3 base64url segments separated by dots
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b'), '<redacted-jwt>'),
    # Authorization header values: "Authorization: Bearer ..." / "Authorization: Basic ..."
    (re.compile(r'(Authorization:\s*(?:Bearer|Basic|XBL3\.0\s+x=[^;]+;))\s*\S+', re.IGNORECASE), r'\1 <redacted>'),
    # URL query params carrying credentials: ?apikey=... &password=... &token=...
    # Pass 41.5 — added `key` (Steam Web API: ?key=API_KEY_VALUE) and
    # `sspassword` (ScreenScraper: ?sspassword=...). The leading `[?&]`
    # boundary keeps `key` from over-matching `cache_key=` / `lookup_key=`
    # variants (those start with `&cache_key=` etc., not `&key=`).
    # Pass 45.13 — added `y` (RetroAchievements API key: ?y=KEY) and `z`
    # (RA username: ?z=USER) — single-character names that the previous
    # rule didn't cover. Same `[?&]` boundary so `?z=...` matches but
    # `?fancy=...` and `?lazy=...` don't.
    (re.compile(r'([?&](?:apikey|api_key|key|token|auth|pwd|password|devpassword|sspassword|ssid|y|z)=)([^&\s"\']+)', re.IGNORECASE), r'\1<redacted>'),
    # Raw "X-Auth: ..." / "X-API-Key: ..." header styles
    (re.compile(r'(X-(?:Auth|API-Key|Session-Token)[^:]*:\s*)\S+', re.IGNORECASE), r'\1<redacted>'),
    # Pass 24.8 — bare long tokens in sensitive-field contexts.
    # PSN NPSSO cookies are 64 chars of base64ish, Gemini API keys are
    # ~39 chars of [A-Za-z0-9_\-]; neither matches the hex-only rule
    # below. Gated to a `field_name: TOKEN` / `field_name=TOKEN` syntax
    # around a known-sensitive label so unrelated 32-char identifiers
    # (commit SHAs written with prefix, etc.) don't get false-positives.
    (re.compile(
        r'\b(npsso|NPSSO|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer|session[_-]?token|client[_-]?secret)\b'
        r'(\s*[:=]\s*|\s+is\s+|\s+=>\s+)'
        r'([A-Za-z0-9_\-\.]{24,})',
        re.IGNORECASE,
    ), r'\1\2<redacted-token>'),
    # Hex secrets ≥32 chars in a named-secret context. Pass 33.10 narrows
    # this from "any 40-char hex string" to "a hex run that appears after
    # a known-secret label" so git commit SHAs in log output stop getting
    # clobbered. Labels are tokenized broadly: token/secret/auth/sha256
    # style names before `:` or `=`.
    (re.compile(
        r'\b(token|secret|auth|key|bearer|hash|digest|npsso|sig|signature|session)\b'
        r'(\s*[:=]\s*|\s+is\s+|\s+=>\s+)'
        r'([a-f0-9]{32,})',
        re.IGNORECASE,
    ), r'\1\2<redacted-hex>'),
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
        """Redact secrets from the formatted record.

        Pass 33.10 — previously this filter only walked `record.msg` /
        positional string args. A call like
        ``logger.info("tokens=%r", response.json())`` passes a dict; the
        formatter `%r`'d it AFTER this filter ran, and the resulting line
        hit the handler unredacted. Fix: render the full message via
        ``record.getMessage()``, redact the composite, then overwrite
        ``record.msg`` with the result and empty ``record.args`` so the
        formatter doesn't re-interpolate.
        """
        try:
            # Bytes args: render via decode so regexes see the token.
            if record.args:
                normalized_args = record.args if isinstance(record.args, tuple) else (record.args,)
                decoded = []
                for a in normalized_args:
                    if isinstance(a, (bytes, bytearray)):
                        try:
                            decoded.append(a.decode('utf-8', errors='replace'))
                        except Exception:
                            decoded.append(repr(a))
                    else:
                        decoded.append(a)
                record.args = tuple(decoded)

            rendered = record.getMessage()
            record.msg = redact(rendered)
            record.args = None
        except Exception:
            # Last-resort: fall back to the old behaviour so a
            # redactor bug doesn't drop the log line entirely.
            try:
                if isinstance(record.msg, str):
                    record.msg = redact(record.msg)
            except Exception:
                pass
        return True
