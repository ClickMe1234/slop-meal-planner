from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from .errors import InvalidUrlError, UnsafeUrlError

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}


def _normalise_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidUrlError("The URL contains an invalid hostname") from exc


def canonicalize_url(url: str, *, base_url: str | None = None) -> str:
    """Return a stable HTTP(S) URL suitable for deduplication.

    Fragments and common tracking parameters are removed, query parameters are
    sorted, default ports are omitted, and the host is IDNA-normalised.  This
    function does not perform DNS or network access.
    """

    candidate = urljoin(base_url, url.strip()) if base_url else url.strip()
    if not candidate or len(candidate) > 4096:
        raise InvalidUrlError("The URL is empty or too long")
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidUrlError("Only HTTP and HTTPS recipe URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("URLs containing credentials are not supported")
    if not parts.hostname:
        raise InvalidUrlError("The URL must include a hostname")

    host = _normalise_host(parts.hostname)
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidUrlError("The URL contains an invalid port") from exc
    if port is not None and not (1 <= port <= 65535):
        raise InvalidUrlError("The URL contains an invalid port")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not default_port:
        netloc = f"{netloc}:{port}"

    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    parameters = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower().startswith("utm_") or key.lower() in TRACKING_PARAMETERS:
            continue
        parameters.append((key, value))
    query = urlencode(sorted(parameters), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # is_global excludes private, loopback, link-local, multicast, reserved and
    # unspecified ranges for both IPv4 and IPv6.
    return ip.is_global


def validate_fetch_url(
    url: str,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
    allowed_hosts: set[str] | None = None,
) -> str:
    """Canonicalise a URL and reject local/private destinations (SSRF guard).

    The caller must repeat this validation for every redirect. Tests can inject
    a deterministic resolver; production defaults to ``socket.getaddrinfo``.
    """

    canonical = canonicalize_url(url)
    host = urlsplit(canonical).hostname or ""
    if allowed_hosts is not None and host not in {_normalise_host(x) for x in allowed_hosts}:
        raise UnsafeUrlError("The URL host is not allowed for this source")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    elif resolver is not None:
        addresses = list(resolver(host))
    else:
        try:
            addresses = list({row[4][0] for row in socket.getaddrinfo(host, None)})
        except OSError as exc:
            raise UnsafeUrlError("The URL hostname could not be resolved") from exc
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("The URL resolves to a local or non-public network address")
    return canonical


def resolve_fetch_url(
    url: str,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
    allowed_hosts: set[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Validate a fetch URL and return the exact public addresses to pin.

    Callers must connect to one of the returned addresses without resolving the
    hostname again. This closes the DNS validation/connection race that a
    rebinding name could otherwise exploit.
    """

    canonical = canonicalize_url(url)
    host = urlsplit(canonical).hostname or ""
    if allowed_hosts is not None and host not in {_normalise_host(x) for x in allowed_hosts}:
        raise UnsafeUrlError("The URL host is not allowed for this source")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = (str(literal),)
    elif resolver is not None:
        addresses = tuple(dict.fromkeys(resolver(host)))
    else:
        try:
            addresses = tuple(
                dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, None))
            )
        except OSError as exc:
            raise UnsafeUrlError("The URL hostname could not be resolved") from exc
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("The URL resolves to a local or non-public network address")
    return canonical, addresses
