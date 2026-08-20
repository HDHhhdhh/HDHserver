"""Pure ProxyFix provenance checks for the public student surface."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from typing import Final, Protocol

from .student_app_config_parsing import IPNetwork
from .student_public_surface_paths import (
    ClientIPResolution,
    HeaderValues,
    exact_host,
    is_local_host,
    resolve_client_ip,
    strict_ip,
)


_PROXY_FIX_ORIGINALS: Final = "werkzeug.proxy_fix.orig"
_PROXY_FIX_FORWARDED_HEADERS: Final[frozenset[str]] = frozenset(
    {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"}
)
_PROXY_HEADER_NAMES: Final[tuple[str, ...]] = (
    "CF-Connecting-IP",
    "CF-Pseudo-IPv4",
    "CF-Connecting-IPv6",
    "Forwarded",
    "X-Forwarded-For",
    "X-Forwarded-Proto",
    "X-Forwarded-Host",
    "X-Real-IP",
    "True-Client-IP",
)


class HeaderListGetter(Protocol):
    def getlist(self, name: str) -> list[str]: ...


def proxy_header_values(headers: HeaderListGetter) -> HeaderValues:
    """Capture duplicate-sensitive forwarding headers without Flask state."""
    captured: dict[str, tuple[str, ...]] = {}
    for name in _PROXY_HEADER_NAMES:
        values = tuple(headers.getlist(name))
        if values:
            captured[name.lower()] = values
    return captured


def proxy_original(environ: Mapping[str, object], name: str) -> str | None:
    """Read a pre-ProxyFix value, rejecting a malformed originals container."""
    if _PROXY_FIX_ORIGINALS not in environ:
        value = environ.get(name)
        return value if isinstance(value, str) else None
    originals = environ.get(_PROXY_FIX_ORIGINALS)
    if not isinstance(originals, Mapping):
        return None
    value = originals.get(name)
    return value if isinstance(value, str) else None


def proxy_results_trusted(environ: Mapping[str, object], trusted: tuple[IPNetwork, ...]) -> bool:
    """Trust ProxyFix-mutated values only when the original peer is trusted."""
    if not isinstance(environ.get(_PROXY_FIX_ORIGINALS), Mapping):
        return False
    peer_ip = strict_ip(proxy_original(environ, "REMOTE_ADDR"))
    if peer_ip is None:
        return False
    peer_address = ipaddress.ip_address(peer_ip)
    return any(peer_address in network for network in trusted)


def effective_proxy_value(environ: Mapping[str, object], name: str, trusted: tuple[IPNetwork, ...]) -> str | None:
    if proxy_results_trusted(environ, trusted):
        value = environ.get(name)
        return value if isinstance(value, str) else None
    return proxy_original(environ, name)


def public_host_matches(environ: Mapping[str, object], expected: str, trusted: tuple[IPNetwork, ...]) -> bool:
    return exact_host(effective_proxy_value(environ, "HTTP_HOST", trusted), expected)


def effective_scheme(environ: Mapping[str, object], trusted: tuple[IPNetwork, ...]) -> str:
    return effective_proxy_value(environ, "wsgi.url_scheme", trusted) or ""


def local_request_allowed(environ: Mapping[str, object], academy_ip_allowed: Callable[[str], bool]) -> bool:
    """Allow a local Host only for its original loopback or academy peer."""
    original_host = proxy_original(environ, "HTTP_HOST")
    peer_ip = strict_ip(proxy_original(environ, "REMOTE_ADDR"))
    if not is_local_host(original_host) or peer_ip is None:
        return False
    return ipaddress.ip_address(peer_ip).is_loopback or academy_ip_allowed(peer_ip)


def resolve_proxy_client(
    environ: Mapping[str, object],
    headers: HeaderValues,
    trusted: tuple[IPNetwork, ...],
) -> ClientIPResolution:
    """Resolve client identity from the original peer and trusted edge headers."""
    selected = headers
    if proxy_results_trusted(environ, trusted):
        selected = {name: values for name, values in headers.items() if name not in _PROXY_FIX_FORWARDED_HEADERS}
    return resolve_client_ip(proxy_original(environ, "REMOTE_ADDR"), selected, trusted)


__all__ = (
    "effective_proxy_value",
    "effective_scheme",
    "local_request_allowed",
    "proxy_header_values",
    "proxy_original",
    "proxy_results_trusted",
    "public_host_matches",
    "resolve_proxy_client",
)
