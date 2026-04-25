# =============================================================================
# BASE SCRAPER UTILITIES
# =============================================================================
# Shared HTTP request logic, retry patterns, rate limiting, and error handling
# for all RetroDB scrapers. Provides importable helper functions that any
# scraper module can use without requiring class inheritance.
# =============================================================================

import requests
import logging
import random
import time
import os
import re
import sqlite3
import sys

# Ensure project root is on path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

logger = logging.getLogger(__name__)

# Shared HTTP session for connection pooling across all scrapers
_http_session = requests.Session()
_http_session.headers.update({
    'Accept': 'application/json',
})


def get_scraper_conn():
    """Get a SQLite connection with WAL mode and busy timeout for scraper operations.

    All scrapers should use this instead of raw sqlite3.connect() to ensure
    consistent WAL journal mode and a generous busy timeout that prevents
    'database is locked' errors during concurrent bulk scrape operations.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    conn.execute("PRAGMA journal_size_limit = 67108864")
    return conn


_RETRYABLE_5XX = (500, 502, 503, 504)


def _backoff_delay(attempt):
    """Exponential backoff with jitter (Pass 26.4).

    Returns `2**attempt` seconds plus up to 1 second of uniform jitter so
    many concurrent scrapers don't all retry in lockstep after a shared
    upstream blip (thundering herd).
    """
    return (2 ** attempt) + random.random()


def _check_response_size_cap(response, max_bytes, url, method):
    """Return True if the response is within `max_bytes`, False otherwise.

    Pass 32.14 — caps apply to AI + RA API calls whose bodies are otherwise
    unbounded. Checks Content-Length first (cheap pre-read reject), falls
    through to an actual len(response.content) check because `requests`
    has already materialised the body at this point anyway.
    """
    if max_bytes is None or max_bytes <= 0:
        return True
    declared = int(response.headers.get('Content-Length', 0) or 0)
    if declared and declared > max_bytes:
        logger.warning(
            f"{method} response rejected: {url} declared {declared} bytes exceeds {max_bytes}"
        )
        return False
    try:
        actual = len(response.content)
    except Exception:
        return True
    if actual > max_bytes:
        logger.warning(
            f"{method} response rejected: {url} body {actual} bytes exceeds {max_bytes}"
        )
        return False
    return True


def http_get(url, params=None, headers=None, timeout=30, retries=2, max_bytes=None):
    """
    HTTP GET request with retry logic and exponential backoff.

    Args:
        url: The URL to request.
        params: Optional query parameters dict.
        headers: Optional request headers dict.
        timeout: Request timeout in seconds (default 30).
        retries: Number of retry attempts after the initial request (default 2).
        max_bytes: If set, reject responses whose body exceeds this cap
            (Pass 32.14 — applied to AI + RA API calls).

    Returns:
        requests.Response object on success, or None on total failure.
    """
    last_error = None

    for attempt in range(retries + 1):
        try:
            logger.debug(f"HTTP GET {url} (attempt {attempt + 1}/{retries + 1})")
            response = _http_session.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 200 and not _check_response_size_cap(response, max_bytes, url, 'HTTP GET'):
                return None

            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                # Rate limited - respect Retry-After header or use exponential backoff
                if attempt < retries:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = min(int(retry_after), 60)
                        except (ValueError, TypeError):
                            wait_time = _backoff_delay(attempt)
                    else:
                        wait_time = _backoff_delay(attempt)
                    logger.warning(f"Rate limited (429), waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"Rate limited (429), no retries left - {url}")
                    return response
            elif response.status_code in _RETRYABLE_5XX:
                # Transient server error — retry with jittered backoff (Pass 26.4)
                if attempt < retries:
                    wait_time = _backoff_delay(attempt)
                    logger.warning(
                        f"HTTP GET server error {response.status_code}, waiting {wait_time:.1f}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue
                logger.warning(
                    f"HTTP GET server error {response.status_code} after {retries + 1} attempts - {url}"
                )
                return response
            else:
                # Non-retryable HTTP error (401/403/4xx/etc.)
                logger.warning(f"HTTP GET failed: {response.status_code} - {url}")
                return response

        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning(f"HTTP GET timeout (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(_backoff_delay(attempt))
                continue
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning(f"HTTP GET connection error (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(_backoff_delay(attempt))
                continue
        except Exception as e:
            logger.error(f"HTTP GET unexpected error: {e}")
            return None

    if last_error:
        logger.error(f"HTTP GET failed after {retries + 1} attempts: {last_error}")
    return None


def http_post(url, data=None, json_data=None, headers=None, timeout=30, retries=2, max_bytes=None):
    """
    HTTP POST request with retry logic and exponential backoff.

    Args:
        url: The URL to request.
        data: Optional form data (string or dict).
        json_data: Optional JSON body (dict). Mutually exclusive with data.
        headers: Optional request headers dict.
        timeout: Request timeout in seconds (default 30).
        retries: Number of retry attempts after the initial request (default 2).
        max_bytes: If set, reject responses whose body exceeds this cap
            (Pass 32.14 — applied to AI + RA API calls).

    Returns:
        requests.Response object on success, or None on total failure.
    """
    last_error = None

    for attempt in range(retries + 1):
        try:
            logger.debug(f"HTTP POST {url} (attempt {attempt + 1}/{retries + 1})")
            response = _http_session.post(
                url, data=data, json=json_data, headers=headers, timeout=timeout
            )
            if response.status_code == 200 and not _check_response_size_cap(response, max_bytes, url, 'HTTP POST'):
                return None

            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                if attempt < retries:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = min(int(retry_after), 60)
                        except (ValueError, TypeError):
                            wait_time = _backoff_delay(attempt)
                    else:
                        wait_time = _backoff_delay(attempt)
                    logger.warning(f"Rate limited (429), waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"Rate limited (429), no retries left - {url}")
                    return response
            elif response.status_code in _RETRYABLE_5XX:
                # Transient server error — retry with jittered backoff (Pass 26.4)
                if attempt < retries:
                    wait_time = _backoff_delay(attempt)
                    logger.warning(
                        f"HTTP POST server error {response.status_code}, waiting {wait_time:.1f}s before retry..."
                    )
                    time.sleep(wait_time)
                    continue
                logger.warning(
                    f"HTTP POST server error {response.status_code} after {retries + 1} attempts - {url}"
                )
                return response
            else:
                logger.warning(f"HTTP POST failed: {response.status_code} - {url}")
                return response

        except requests.exceptions.Timeout as e:
            last_error = e
            logger.warning(f"HTTP POST timeout (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(_backoff_delay(attempt))
                continue
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning(f"HTTP POST connection error (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(_backoff_delay(attempt))
                continue
        except Exception as e:
            logger.error(f"HTTP POST unexpected error: {e}")
            return None

    if last_error:
        logger.error(f"HTTP POST failed after {retries + 1} attempts: {last_error}")
    return None


def download_image(url, dest_path, timeout=15):
    """
    Download an image from a URL to a local path. Skips download if the
    destination file already exists.

    Args:
        url: The image URL to download.
        dest_path: Local filesystem path to save the image.
        timeout: Request timeout in seconds (default 15).

    Returns:
        True if the image was downloaded (or already exists), False on failure.
    """
    if not url:
        return False

    # Skip if already downloaded
    if os.path.exists(dest_path):
        logger.debug(f"Image already exists, skipping: {dest_path}")
        return True

    # Ensure URL is absolute
    if url.startswith('//'):
        url = 'https:' + url
    elif not url.startswith('http'):
        url = 'https:' + url if url.startswith('//') else url

    # Pass 32.6: SSRF gate. Reject non-http(s) schemes and any URL whose
    # host resolves to a private/loopback/link-local/metadata IP (e.g.
    # 169.254.169.254 AWS IMDS, 127.0.0.1, 10/8, etc.). An attacker-controlled
    # upstream metadata record (TGDB, RAWG, …) can otherwise steer the
    # scraper into internal endpoints.
    # Pass 45.2: validate_and_pin_url walks the redirect chain through the
    # SSRF gate AND captures the IP we'll pin via pin_host_ip() to defeat
    # DNS rebinding between validate and GET (Pass 32.7 had only museum.py
    # using the pin; every other scraper download path now uses it too).
    from services.ssrf import validate_outbound_url, validate_and_pin_url, pin_host_ip
    from urllib.parse import urlparse as _urlparse
    ok, _, _ = validate_outbound_url(url)
    if not ok:
        logger.warning(f"SSRF block: refusing to fetch {url}")
        return False

    # Ensure destination directory exists
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    # Pass 25.7 — streaming-download size cap. A malicious or misconfigured
    # upstream could stream gigabytes into IMAGE_PATH; cap at 50 MB by
    # default and delete the partial file on overflow so disk doesn't fill.
    try:
        import config as _config
        max_bytes = getattr(_config, 'MAX_MEDIA_DOWNLOAD_BYTES', 50 * 1024 * 1024)
    except Exception:
        max_bytes = 50 * 1024 * 1024

    # Pass 40.15 — atomic write: stream into a tempfile in the same
    # directory, fsync, then os.replace into the final path.  The
    # previous version streamed `open(dest_path, 'wb')` directly; any
    # mid-stream exception (connection reset, OOM, SIGKILL) left a
    # partial file at dest_path, and the `if os.path.exists(dest_path)`
    # short-circuit at the top of this function then treated the corrupt
    # bytes as "already downloaded" forever.  Mirrors the
    # metadata_merger._download_and_finalize scaffold.
    import tempfile as _tempfile
    tmp_fd = None
    tmp_path = None
    try:
        # Walk the redirect chain manually so every hop goes through the
        # SSRF validator. If no redirect is returned, safe_url == url.
        safe_url, pinned_ip, err = validate_and_pin_url(
            _http_session, url, max_redirects=3, timeout=timeout,
        )
        if err:
            logger.warning(f"SSRF block: redirect chain rejected for {url} ({err})")
            return False
        pinned_host = _urlparse(safe_url).hostname

        # mkstemp gives us an exclusive-create file descriptor in the same
        # directory as the destination — same filesystem so os.replace is
        # an atomic rename.
        tmp_fd, tmp_path = _tempfile.mkstemp(
            prefix='.dl-', suffix='.part', dir=dest_dir or None,
        )
        # stream=True so the whole response body isn't materialised in memory
        # before write; iter_content pipes directly to disk in 8 KB chunks.
        # Pass 45.2: pin_host_ip() forces every getaddrinfo for `pinned_host`
        # within this thread to return `pinned_ip` for the duration of the GET,
        # so a hostile DNS server can't flip the record after validation.
        with pin_host_ip(pinned_host, pinned_ip), _http_session.get(safe_url, timeout=timeout, stream=True, allow_redirects=False) as response:
            if response.status_code != 200:
                logger.warning(f"Image download failed: HTTP {response.status_code} - {safe_url}")
                return False
            declared = int(response.headers.get('Content-Length', 0) or 0)
            if declared and declared > max_bytes:
                logger.warning(
                    f"Image download rejected: {safe_url} — declared {declared} bytes exceeds {max_bytes}"
                )
                return False
            written = 0
            with os.fdopen(tmp_fd, 'wb') as f:
                tmp_fd = None  # ownership transferred to the file object
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        written += len(chunk)
                        if written > max_bytes:
                            logger.warning(
                                f"Image download aborted: {safe_url} exceeded {max_bytes} bytes"
                            )
                            return False
                        f.write(chunk)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        # Atomic promote — between this point and the next line, dest_path
        # either stays absent or contains the complete tempfile bytes;
        # never a half-written body.
        os.replace(tmp_path, dest_path)
        tmp_path = None  # ownership transferred to dest_path

        # Post-download: re-encode to match extension (so dest_path=*.webp →
        # on-disk WebP bytes), standardize size, generate responsive variants.
        try:
            from services.image_utils import finalize_downloaded_image
            parent_dir = os.path.basename(os.path.dirname(dest_path))
            if parent_dir in ('boxart', 'screenshots', 'boxart_3d', 'controllers', 'fanart'):
                finalize_downloaded_image(dest_path, parent_dir)
        except Exception:
            pass  # Non-critical — don't fail the download
        logger.debug(f"Downloaded image: {dest_path}")
        return True
    except Exception as e:
        logger.warning(f"Image download error: {e}")
        return False
    finally:
        # Drop any orphaned tempfile so the directory never accumulates
        # .dl-*.part files from interrupted downloads.
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def rate_limit(delay=0.5):
    """
    Simple sleep-based rate limiter.

    Args:
        delay: Seconds to sleep (default 0.5).
    """
    time.sleep(delay)


def safe_json(response):
    """
    Safely parse JSON from a requests.Response object.

    Args:
        response: A requests.Response object (or None).

    Returns:
        Parsed JSON (dict or list) on success, or None on failure.
    """
    if response is None:
        return None
    try:
        return response.json()
    except Exception as e:
        logger.warning(f"JSON parse error: {e}")
        return None


# =============================================================================
# ROMAN NUMERAL NORMALIZATION
# =============================================================================
# Converts Roman numerals in game titles to Arabic numbers so that
# "Rick Dangerous II" matches "Rick Dangerous 2", etc.
# Excludes "I" (too common as pronoun: "I Am Bread") and "X" (brand: "Mega Man X").
# Includes "V" (safe: "GTA V", "Civilization V").

_ROMAN_TO_ARABIC = {
    "xx": "20", "xix": "19", "xviii": "18", "xvii": "17", "xvi": "16",
    "xv": "15", "xiv": "14", "xiii": "13", "xii": "12", "xi": "11",
    "ix": "9", "viii": "8", "vii": "7", "vi": "6",
    "v": "5", "iv": "4", "iii": "3", "ii": "2",
}

# Pre-compiled regex: match Roman numerals as whole words, longest first
_ROMAN_PATTERN = re.compile(
    r'\b(' + '|'.join(_ROMAN_TO_ARABIC.keys()) + r')\b'
)


def normalize_roman_numerals(text):
    """
    Replace Roman numerals (ii-xx) with Arabic equivalents in lowercased text.
    Uses word boundaries to avoid mangling words that contain Roman numeral substrings.

    Args:
        text: Lowercased string to normalize.

    Returns:
        Text with Roman numerals replaced by Arabic numbers.
    """
    if not text:
        return text
    return _ROMAN_PATTERN.sub(lambda m: _ROMAN_TO_ARABIC[m.group(0)], text)
