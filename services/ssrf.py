# =============================================================================
# RETRODB - SSRF guards (Pass 32.6 / 32.7)
# =============================================================================
# Shared helpers for validating outbound URLs against private-IP / metadata
# endpoints. Used by base_scraper.download_image, scrape_screenscraper media
# downloads, museum proxy, and metadata_merger image/video downloads.
#
# Why a shared module: every ad-hoc check so far has shipped a slightly
# different allowlist of schemes and private ranges. This module defines the
# canonical set and a single `validate_outbound_url` helper, so adding a new
# network-sinking endpoint to the app only needs one line.
# =============================================================================

import ipaddress
import logging
import socket
import threading
from contextlib import contextmanager
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Only http and https are ever valid for our scraper / proxy paths. `file://`,
# `ftp://`, `gopher://`, etc. are how SSRF usually becomes RCE or LFI.
_ALLOWED_SCHEMES = frozenset({'http', 'https'})

# Resolve-time IP check: refuse private, loopback, link-local, reserved,
# multicast, and unspecified. `ipaddress` already covers RFC 1918 and
# 127/8 via is_private, but we enumerate them for clarity and to include
# 169.254.169.254 (AWS IMDS) via is_link_local.
def _ip_is_public(ip_obj):
    return not (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    )


def validate_outbound_url(url, *, require_https=False):
    """Validate that `url` is safe to dereference from the server.

    Checks:
        - scheme is http or https (or https only if require_https=True)
        - host is present
        - every resolved A/AAAA record points at a public IP

    Returns:
        (ok: bool, reason_or_url: str, resolved_ips: list[str])
        On success: (True, parsed_url_string, resolved_ips)
        On failure: (False, error_reason, [])

    NOTE: this does a getaddrinfo lookup. Callers concerned about DNS
    rebinding should pin the returned IP and connect to it directly rather
    than rely on another lookup at request time (see 32.7).
    """
    if not isinstance(url, str) or not url:
        return False, 'missing url', []

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f'disallowed scheme: {parsed.scheme}', []
    if require_https and parsed.scheme != 'https':
        return False, 'https is required', []
    host = parsed.hostname
    if not host:
        return False, 'missing hostname', []

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        return False, f'DNS failure: {e}', []

    resolved = []
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f'invalid resolved IP: {ip_str}', []
        if not _ip_is_public(ip):
            logger.warning(
                f'SSRF block: {host} resolved to non-public IP {ip_str}'
            )
            return False, f'disallowed IP range: {ip_str} ({host})', []
        resolved.append(ip_str)

    return True, url, resolved


# -----------------------------------------------------------------------------
# Pass 32.7 — pin resolved IP against DNS rebinding
# -----------------------------------------------------------------------------
# Without this, an adversarial DNS server can return a public IP during
# validate_outbound_url() and flip to 127.0.0.1 before the actual GET fires
# (TOCTOU). We install a process-wide socket.getaddrinfo shim that checks a
# threading.local for a pinned (host → ip) binding; inside a pin_host_ip()
# block on the calling thread, resolution always returns the pinned IP. All
# other threads fall through to real DNS, so the shim is thread-safe.
_pinned = threading.local()
_orig_getaddrinfo = None


def _pinned_getaddrinfo(host, *args, **kwargs):
    pinned = getattr(_pinned, 'value', None)
    if pinned and pinned[0] == host:
        ip = pinned[1]
        family = socket.AF_INET6 if ':' in ip else socket.AF_INET
        # Echo the port the caller asked for. getaddrinfo's signature is
        # getaddrinfo(host, port, family, type, proto, flags); urllib3 passes
        # the real port (e.g. 443) as the second positional. Earlier this
        # hard-coded port 0 into the sockaddr, so a *fresh* pinned connection
        # tried to connect to port 0 and hung — the pin only "worked" when an
        # earlier unpinned HEAD on the same session had warmed the connection
        # pool (so getaddrinfo was never called for the GET, defeating the
        # whole rebinding guard). Preserve the port so the pin is real.
        # getaddrinfo's port arg is an int (connect), a service-name str, or
        # None (resolve-only). urllib3 passes the real int port for a connect;
        # echo it so the pinned socket targets e.g. 443 instead of 0 (the old
        # bug). For the resolve-only (None) and service-name cases the sockaddr
        # port is inconsequential, so fall back to 0 — exactly the prior
        # always-pin behaviour, which the resolve-only path still relies on.
        port = args[0] if args else kwargs.get('port', 0)
        if not isinstance(port, int):
            port = 0
        # sockaddr is a 2-tuple for IPv4, 4-tuple (ip, port, flowinfo, scope)
        # for IPv6. getaddrinfo 5-tuple: (family, type, proto, canonname, sockaddr)
        sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
        return [(family, socket.SOCK_STREAM, 0, '', sockaddr)]
    return _orig_getaddrinfo(host, *args, **kwargs)


def _install_getaddrinfo_shim():
    global _orig_getaddrinfo
    if _orig_getaddrinfo is None:
        _orig_getaddrinfo = socket.getaddrinfo
        socket.getaddrinfo = _pinned_getaddrinfo


_install_getaddrinfo_shim()


@contextmanager
def pin_host_ip(host, ip):
    """Within this block, socket.getaddrinfo(host, ...) always returns `ip`.

    Only the calling thread is affected. Use this to connect to the same IP
    that validate_outbound_url() just verified, defeating DNS rebinding.
    """
    previous = getattr(_pinned, 'value', None)
    _pinned.value = (host, ip)
    try:
        yield
    finally:
        _pinned.value = previous


def validate_and_pin_url(session, url, *, max_redirects=3, timeout=5, require_https=False):
    """Walk the redirect chain through the SSRF gate, then re-resolve the
    final URL to capture the IP that the caller will pin via pin_host_ip().

    This is the canonical helper for any outbound GET that needs DNS-rebinding
    protection (Pass 32.7 / 45.2). Pattern at the call site:

        safe_url, pinned_ip, err = validate_and_pin_url(session, url)
        if err:
            return False
        host = urlparse(safe_url).hostname
        with pin_host_ip(host, pinned_ip), session.get(safe_url, ...) as r:
            ...

    Returns:
        (safe_url, pinned_ip, None) on success
        (None, None, error_reason) on failure
    """
    safe_url, err = validate_redirect_chain(
        session, url, max_redirects=max_redirects, timeout=timeout,
    )
    if err:
        return None, None, err
    ok, _, ips = validate_outbound_url(safe_url, require_https=require_https)
    if not ok or not ips:
        return None, None, 'final URL re-validation failed'
    return safe_url, ips[0], None


def validate_redirect_chain(session, start_url, *, max_redirects=3, timeout=5):
    """Follow a redirect chain manually, validating each hop.

    Uses `session.head(..., allow_redirects=False)` to peek at every
    Location header and re-run validate_outbound_url before dereferencing.
    Returns the final safe URL that the caller can then GET with
    allow_redirects=False.

    Returns:
        (final_url, None) on success
        (None, error_reason) on failure
    """
    current = start_url
    for _ in range(max_redirects + 1):
        ok, result, _ = validate_outbound_url(current)
        if not ok:
            return None, result
        try:
            head = session.head(current, allow_redirects=False, timeout=timeout)
        except Exception as e:  # requests may raise many flavors here
            return None, f'HEAD failed: {e}'
        if head.status_code in (301, 302, 303, 307, 308):
            next_url = head.headers.get('Location')
            if not next_url:
                return None, 'redirect without Location'
            current = next_url
            continue
        return current, None
    return None, f'exceeded {max_redirects} redirects'
