from __future__ import annotations

import copy
import ipaddress
import os
import re
from typing import Any, Final, Protocol

from flask import request


ACADEMY_ACCESS_MESSAGE = "영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다."

ACADEMY_ALLOWED_NETWORKS = (
    ipaddress.ip_network("110.14.147.14/32"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("2a09:bac2:46d9::/48"),
    ipaddress.ip_network("fc00::/7"),
)

# Only configured reverse proxies may supply client IP headers. Public clients
# can send the same headers, but their remote_addr must remain authoritative.
# Cloudflare-authored CF-Connecting-IP is the client identity when present;
# X-Forwarded-For can contain an appended proxy chain.
TRUSTED_PROXY_CIDRS_ENV: Final = "TRUSTED_PROXY_CIDRS"
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
TRUSTED_PROXY_NETWORKS: Final[tuple[IPNetwork, ...]] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)
CLOUDFLARE_PROXY_NETWORKS: Final[tuple[IPNetwork, ...]] = (
    # Cloudflare publishes these canonical proxy ranges at
    # https://www.cloudflare.com/ips-v4 and https://www.cloudflare.com/ips-v6.
    ipaddress.ip_network("173.245.48.0/20"),
    ipaddress.ip_network("103.21.244.0/22"),
    ipaddress.ip_network("103.22.200.0/22"),
    ipaddress.ip_network("103.31.4.0/22"),
    ipaddress.ip_network("141.101.64.0/18"),
    ipaddress.ip_network("108.162.192.0/18"),
    ipaddress.ip_network("190.93.240.0/20"),
    ipaddress.ip_network("188.114.96.0/20"),
    ipaddress.ip_network("197.234.240.0/22"),
    ipaddress.ip_network("198.41.128.0/17"),
    ipaddress.ip_network("162.158.0.0/15"),
    ipaddress.ip_network("104.16.0.0/13"),
    ipaddress.ip_network("104.24.0.0/14"),
    ipaddress.ip_network("172.64.0.0/13"),
    ipaddress.ip_network("131.0.72.0/22"),
    ipaddress.ip_network("2400:cb00::/32"),
    ipaddress.ip_network("2606:4700::/32"),
    ipaddress.ip_network("2803:f800::/32"),
    ipaddress.ip_network("2405:b500::/32"),
    ipaddress.ip_network("2405:8100::/32"),
    ipaddress.ip_network("2a06:98c0::/29"),
    ipaddress.ip_network("2c0f:f248::/32"),
)
CLOUDFLARE_PSEUDO_IPV4_NETWORK: Final = ipaddress.ip_network("240.0.0.0/4")

ANSWER_LINK_FIELD_NAMES = frozenset(
    {
        "answerUrl",
        "answer_url",
        "solutionUrl",
        "solution_url",
        "answerFileId",
        "answer_file_id",
        "solutionFileId",
        "solution_file_id",
        "url",
        "link",
    }
)

TEST_ANSWER_FIELD_NAMES = frozenset(
    {
        "answerKeys",
        "answer_keys",
        "answerKey",
        "answer_key",
        "answers",
    }
)

_TEST_CONFIG_SECRET_PREFIXES = (
    "answer",
    "solution",
    "correct",
    "expected",
    "accepted",
    "canonical",
)

_TEST_CONFIG_PUBLIC_ANSWER_FIELDS: Final[frozenset[str]] = frozenset(
    {"answerlinkstatus", "answermode", "answermodes"}
)


class HeaderGetter(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None:
        ...


class RequestLike(Protocol):
    remote_addr: str | None
    headers: HeaderGetter


def _proxy_fix_original_remote_addr(req: RequestLike) -> str:
    environ = getattr(req, "environ", None)
    if not isinstance(environ, dict):
        return ""
    original = environ.get("werkzeug.proxy_fix.orig")
    if not isinstance(original, dict):
        return ""
    return clean_client_ip(original.get("REMOTE_ADDR") or "")


def clean_client_ip(value: str) -> str:
    text = str(value or "").strip().strip(".")
    text = re.sub(r"%[0-9A-Za-z_.-]+$", "", text)
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_ip(value: str) -> IPAddress | None:
    try:
        ip = ipaddress.ip_address(clean_client_ip(value))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_cloudflare_pseudo_ipv4(ip: IPAddress) -> bool:
    return isinstance(ip, ipaddress.IPv4Address) and ip in CLOUDFLARE_PSEUDO_IPV4_NETWORK


def _configured_trusted_proxy_networks() -> tuple[IPNetwork, ...]:
    raw_value = os.environ.get(TRUSTED_PROXY_CIDRS_ENV, "")
    networks: list[IPNetwork] = []
    for raw_item in re.split(r"[\s,;]+", raw_value):
        item = clean_client_ip(raw_item)
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def trusted_proxy_networks() -> tuple[IPNetwork, ...]:
    return TRUSTED_PROXY_NETWORKS + CLOUDFLARE_PROXY_NETWORKS + _configured_trusted_proxy_networks()


def client_ip_from_request(req: RequestLike | None = None) -> str:
    req = req or request
    remote_addr = clean_client_ip(req.remote_addr or "")
    trust_addr = _proxy_fix_original_remote_addr(req) or remote_addr
    remote_ip = _parse_ip(trust_addr)
    if remote_ip is None or not any(remote_ip in net for net in trusted_proxy_networks()):
        return str(remote_ip) if remote_ip is not None else remote_addr

    cf_connecting_ip = clean_client_ip(req.headers.get("CF-Connecting-IP") or "")
    parsed_cf_connecting_ip = _parse_ip(cf_connecting_ip)
    if parsed_cf_connecting_ip is not None:
        if _is_cloudflare_pseudo_ipv4(parsed_cf_connecting_ip):
            cf_connecting_ipv6 = _parse_ip(req.headers.get("CF-Connecting-IPv6") or "")
            if isinstance(cf_connecting_ipv6, ipaddress.IPv6Address):
                return str(cf_connecting_ipv6)
        return str(parsed_cf_connecting_ip)

    forwarded_for = req.headers.get("X-Forwarded-For") or ""
    if forwarded_for.strip():
        first_candidate = clean_client_ip(forwarded_for.split(",", 1)[0])
        parsed_forwarded_for = _parse_ip(first_candidate)
        return str(parsed_forwarded_for) if parsed_forwarded_for is not None else remote_addr

    real_ip = clean_client_ip(req.headers.get("X-Real-IP") or "")
    parsed_real_ip = _parse_ip(real_ip)
    if parsed_real_ip is not None:
        return str(parsed_real_ip)

    return remote_addr


def ip_allowed(ip_str: str) -> bool:
    ip = _parse_ip(ip_str)
    if ip is None:
        return False
    return any(ip in net for net in ACADEMY_ALLOWED_NETWORKS)


def academy_network_allowed(req: RequestLike | None = None) -> bool:
    return ip_allowed(client_ip_from_request(req))


def strip_answer_link_fields(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, dict):
        return value, False

    out = copy.deepcopy(value)
    stripped = False

    for key in ANSWER_LINK_FIELD_NAMES:
        if key in out:
            if str(out.get(key) or "").strip():
                stripped = True
            out.pop(key, None)

    for key in TEST_ANSWER_FIELD_NAMES:
        if key in out:
            if str(out.get(key) or "").strip():
                stripped = True
            out.pop(key, None)

    for source_key in ("sourceFiles", "source_files"):
        source_files = out.get(source_key)
        if not isinstance(source_files, dict):
            continue
        for key in ANSWER_LINK_FIELD_NAMES:
            if key in source_files:
                if str(source_files.get(key) or "").strip():
                    stripped = True
                source_files.pop(key, None)

    return out, stripped


def strip_tests_config_answer_links(config: Any) -> Any:
    def is_secret_field(key: Any) -> bool:
        normalized = re.sub(r"[^0-9a-z]", "", str(key or "").casefold())
        if normalized in _TEST_CONFIG_PUBLIC_ANSWER_FIELDS:
            return False
        return normalized.startswith(_TEST_CONFIG_SECRET_PREFIXES)

    def project(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: project(child)
                for key, child in value.items()
                if not is_secret_field(key)
            }
        if isinstance(value, list):
            return [project(child) for child in value]
        return copy.deepcopy(value)

    return project(config)
