from __future__ import annotations

import copy
import ipaddress
import re
from typing import Any, Protocol

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

# Only loopback reverse proxies may supply client IP headers. Public clients
# can send the same headers, but their remote_addr must remain authoritative.
# Cloudflare-authored CF-Connecting-IP is the client identity when present;
# X-Forwarded-For can contain an appended proxy chain.
TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

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


class HeaderGetter(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None:
        ...


class RequestLike(Protocol):
    remote_addr: str | None
    headers: HeaderGetter


def clean_client_ip(value: str) -> str:
    text = str(value or "").strip().strip(".")
    text = re.sub(r"%[0-9A-Za-z_.-]+$", "", text)
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_ip(value: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(clean_client_ip(value))
    except ValueError:
        return None


def client_ip_from_request(req: RequestLike | None = None) -> str:
    req = req or request
    remote_addr = clean_client_ip(req.remote_addr or "")
    remote_ip = _parse_ip(remote_addr)
    if remote_ip is None or not any(remote_ip in net for net in TRUSTED_PROXY_NETWORKS):
        return remote_addr

    cf_connecting_ip = clean_client_ip(req.headers.get("CF-Connecting-IP") or "")
    if _parse_ip(cf_connecting_ip) is not None:
        return cf_connecting_ip

    forwarded_for = req.headers.get("X-Forwarded-For") or ""
    if forwarded_for.strip():
        for candidate in reversed(forwarded_for.split(",")):
            client_ip = clean_client_ip(candidate)
            if _parse_ip(client_ip) is not None:
                return client_ip
        return remote_addr

    real_ip = clean_client_ip(req.headers.get("X-Real-IP") or "")
    if _parse_ip(real_ip) is not None:
        return real_ip

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
    if not isinstance(config, dict):
        return config

    out = copy.deepcopy(config)
    categories = out.get("categories")
    if not isinstance(categories, dict):
        return out

    for category in categories.values():
        if not isinstance(category, dict) or not isinstance(category.get("tests"), list):
            continue
        next_tests = []
        for test in category.get("tests") or []:
            stripped_test, _ = strip_answer_link_fields(test)
            next_tests.append(stripped_test)
        category["tests"] = next_tests

    return out
