"""Pure boundary parsers for the public student application surface."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Final, Mapping, TypeAlias
from urllib.parse import unquote

from .student_app_config_parsing import IPNetwork


HeaderValues: TypeAlias = Mapping[str, tuple[str, ...]]
_SAFE_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STUDENT_PAGE_RE: Final[re.Pattern[str]] = re.compile(r"^/student/([^/]+)$")
_FORWARDED_HEADERS: Final[tuple[str, ...]] = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-real-ip",
    "true-client-ip",
)


@dataclass(frozen=True, slots=True)
class ClientIPResolution:
    """Resolved client address and the trust state of the proxy hop."""

    client_ip: str
    peer_ip: str
    peer_trusted: bool
    valid: bool


def exact_host(host: str | None, expected: str) -> bool:
    """Accept one canonical DNS host, never a suffix or a host:port value."""
    if not isinstance(host, str) or host != host.strip() or not host:
        return False
    if any(char.isspace() or ord(char) < 0x21 or ord(char) == 0x7F for char in host):
        return False
    if any(marker in host for marker in ("/", "\\", ",", ":")):
        return False
    return host.lower() == expected.lower()


def is_local_host(raw_host: str | None) -> bool:
    """Keep loopback/private legacy routes available without trusting public DNS aliases."""
    if not isinstance(raw_host, str) or not raw_host:
        return False
    if raw_host.startswith("[") and "]" in raw_host:
        host = raw_host[1:].split("]", 1)[0]
    elif raw_host.count(":") == 1:
        host = raw_host.rsplit(":", 1)[0]
    else:
        host = raw_host
    if host.lower() == "localhost":
        return True
    address = strict_ip(host)
    return address is not None and ipaddress.ip_address(address).is_private


def strict_ip(raw: str | None) -> str | None:
    """Parse one canonical IP literal without ports, brackets, or zones."""
    if not isinstance(raw, str) or raw != raw.strip() or not raw:
        return None
    if any(char.isspace() or char in ",[]%" for char in raw):
        return None
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return None
    canonical = str(parsed)
    return canonical if canonical == raw else None


def _values(headers: HeaderValues, name: str) -> tuple[str, ...]:
    """Read normalized header values while retaining duplicate-field evidence."""
    return tuple(headers.get(name.lower(), ()))


def resolve_client_ip(peer: str | None, headers: HeaderValues, trusted: tuple[IPNetwork, ...]) -> ClientIPResolution:
    """Resolve one Cloudflare address only across an explicitly trusted peer."""
    peer_text = peer if isinstance(peer, str) else ""
    peer_ip = strict_ip(peer_text)
    if peer_ip is None:
        return ClientIPResolution(peer_text, peer_text, False, False)
    peer_address = ipaddress.ip_address(peer_ip)
    peer_trusted = any(peer_address in network for network in trusted)
    if not peer_trusted:
        return ClientIPResolution(peer_ip, peer_ip, False, True)
    if any(_values(headers, name) for name in _FORWARDED_HEADERS):
        return ClientIPResolution(peer_ip, peer_ip, True, False)
    if _values(headers, "cf-pseudo-ipv4") or _values(headers, "cf-connecting-ipv6"):
        return ClientIPResolution(peer_ip, peer_ip, True, False)
    connecting = _values(headers, "cf-connecting-ip")
    if len(connecting) != 1:
        return ClientIPResolution(peer_ip, peer_ip, True, False)
    client_ip = strict_ip(connecting[0])
    if client_ip is None:
        return ClientIPResolution(peer_ip, peer_ip, True, False)
    return ClientIPResolution(client_ip, peer_ip, True, True)


def parse_student_page_sid(path: str) -> str | None:
    """Return the exact SID in a one-segment legacy student page path."""
    match = _STUDENT_PAGE_RE.fullmatch(path)
    if match is None:
        return None
    return strict_sid(match.group(1))


def strict_sid(value: str | None) -> str | None:
    """Accept an opaque SID without path, control, or encoded separator bytes."""
    if not isinstance(value, str) or value != value.strip() or not value:
        return None
    if any(char.isspace() or char in "/\\\x00%," for char in value):
        return None
    return value


def _decode_uri_fixed_point(raw_uri: str) -> str | None:
    """Decode a request target until stable while rejecting encoded controls."""
    decoded = raw_uri
    for _ in range(5):
        if "\\" in decoded or any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded):
            return None
        segments = decoded.replace("\\", "/").split("/")
        if any(segment in {".", ".."} for segment in segments):
            return None
        try:
            next_decoded = unquote(decoded)
        except ValueError:
            return None
        if next_decoded == decoded:
            return None if "%" in decoded else decoded
        if "\\" in next_decoded or next_decoded.count("/") > decoded.count("/"):
            return None
        decoded = next_decoded
    return None


def safe_announcement_file(path: str, raw_uri: str | None = None) -> bool:
    """Allow only one safe announcement filename and reject encoded traversal."""
    if raw_uri:
        if _decode_uri_fixed_point(raw_uri) is None:
            return False
    prefix = "/files/announcements/"
    if not path.startswith(prefix):
        return False
    name = path[len(prefix) :]
    return bool(name) and "/" not in name and "\\" not in name and _SAFE_FILE_RE.fullmatch(name) is not None


__all__ = (
    "ClientIPResolution",
    "HeaderValues",
    "exact_host",
    "is_local_host",
    "parse_student_page_sid",
    "resolve_client_ip",
    "safe_announcement_file",
    "strict_ip",
    "strict_sid",
)
