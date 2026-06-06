from __future__ import annotations

import copy
import ipaddress
import re
from typing import Any

from flask import request


ACADEMY_ACCESS_MESSAGE = "영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다."

ACADEMY_ALLOWED_NETWORKS = (
    ipaddress.ip_network("110.14.147.14/32"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("2a09:bac2:46d9::/48"),
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


def clean_client_ip(value: str) -> str:
    text = str(value or "").strip().strip(".")
    text = re.sub(r"%[0-9A-Za-z_.-]+$", "", text)
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def client_ip_from_request(req=None) -> str:
    req = req or request
    return clean_client_ip(req.remote_addr or "")


def ip_allowed(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(clean_client_ip(ip_str))
    except ValueError:
        return False
    return any(ip in net for net in ACADEMY_ALLOWED_NETWORKS)


def academy_network_allowed(req=None) -> bool:
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
