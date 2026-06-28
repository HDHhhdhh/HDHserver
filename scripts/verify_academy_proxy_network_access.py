#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# --- How to run ---
# python scripts/verify_academy_proxy_network_access.py
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from core.network_access import academy_network_allowed, client_ip_from_request  # noqa: E402


@dataclass(frozen=True, slots=True)
class RequestStub:
    remote_addr: str
    headers: Mapping[str, str]


def test_direct_academy_client_is_allowed() -> None:
    # Given
    req = RequestStub(remote_addr="192.168.0.44", headers={})

    # When
    allowed = academy_network_allowed(req)

    # Then
    if not allowed:
        raise AssertionError("direct academy Wi-Fi clients must retain answer access")


def test_direct_private_academy_lan_clients_are_allowed() -> None:
    # Given
    examples = (
        RequestStub(remote_addr="10.20.30.40", headers={}),
        RequestStub(remote_addr="172.16.5.44", headers={}),
        RequestStub(remote_addr="fd00::44", headers={}),
    )

    # When / Then
    for req in examples:
        if not academy_network_allowed(req):
            raise AssertionError(f"private academy LAN client must be allowed: {req.remote_addr}")


def test_trusted_loopback_proxy_uses_cf_connecting_ip() -> None:
    # Given
    req = RequestStub(
        remote_addr="127.0.0.1",
        headers={"CF-Connecting-IP": "110.14.147.14"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "110.14.147.14":
        raise AssertionError(f"expected CF-Connecting-IP client, got {client_ip!r}")
    if not allowed:
        raise AssertionError("trusted Cloudflare/local proxy must allow academy client IP")


def test_trusted_cloudflare_header_is_authoritative_with_forwarded_for_chain() -> None:
    # Given
    req = RequestStub(
        remote_addr="127.0.0.1",
        headers={"CF-Connecting-IP": "110.14.147.14", "X-Forwarded-For": "110.14.147.14, 172.71.0.10"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "110.14.147.14":
        raise AssertionError(f"expected authoritative CF-Connecting-IP client, got {client_ip!r}")
    if not allowed:
        raise AssertionError("trusted Cloudflare request must not be blocked by appended proxy chain")


def test_cf_connecting_ip_takes_precedence_over_forwarded_for() -> None:
    # Given
    req = RequestStub(
        remote_addr="127.0.0.1",
        headers={"CF-Connecting-IP": "110.14.147.14", "X-Forwarded-For": "203.0.113.10"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "110.14.147.14":
        raise AssertionError(f"expected CF-Connecting-IP to override forwarded peer, got {client_ip!r}")
    if not allowed:
        raise AssertionError("trusted CF-Connecting-IP must allow academy access")


def test_trusted_loopback_proxy_uses_leftmost_forwarded_for_client() -> None:
    # Given
    req = RequestStub(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "192.168.0.44, 198.51.100.23"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "192.168.0.44":
        raise AssertionError(f"expected left-most forwarded client, got {client_ip!r}")
    if not allowed:
        raise AssertionError("trusted local proxy must allow academy forwarded clients")


def test_trusted_loopback_proxy_uses_real_ip_without_forwarded_for() -> None:
    # Given
    req = RequestStub(
        remote_addr="::1",
        headers={"X-Real-IP": "192.168.0.44"},
    )

    # When
    allowed = academy_network_allowed(req)

    # Then
    if not allowed:
        raise AssertionError("trusted local proxy must use X-Real-IP when X-Forwarded-For is absent")


def test_forwarded_for_takes_precedence_over_real_ip() -> None:
    # Given
    req = RequestStub(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "not-an-ip", "X-Real-IP": "192.168.0.44"},
    )

    # When
    allowed = academy_network_allowed(req)

    # Then
    if allowed:
        raise AssertionError("X-Real-IP must not be trusted when X-Forwarded-For is present")


def test_direct_public_client_cannot_spoof_forwarded_for() -> None:
    # Given
    req = RequestStub(
        remote_addr="198.51.100.23",
        headers={"X-Forwarded-For": "192.168.0.44", "X-Real-IP": "192.168.0.44"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "198.51.100.23":
        raise AssertionError(f"direct public clients must not be replaced by headers, got {client_ip!r}")
    if allowed:
        raise AssertionError("direct public clients must not spoof academy access")


def test_direct_public_client_cannot_spoof_cf_connecting_ip() -> None:
    # Given
    req = RequestStub(
        remote_addr="198.51.100.23",
        headers={"CF-Connecting-IP": "110.14.147.14"},
    )

    # When
    client_ip = client_ip_from_request(req)
    allowed = academy_network_allowed(req)

    # Then
    if client_ip != "198.51.100.23":
        raise AssertionError(f"direct public clients must not be replaced by CF headers, got {client_ip!r}")
    if allowed:
        raise AssertionError("direct public clients must not spoof academy access with CF-Connecting-IP")


def test_answer_map_allows_trusted_cf_connecting_ip() -> None:
    # Given
    client = create_app().test_client()

    # When
    response = client.get(
        "/js/test_answer_link_map.json",
        headers={"CF-Connecting-IP": "110.14.147.14"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    # Then
    if response.status_code != 200:
        raise AssertionError(f"trusted CF-Connecting-IP answer map request failed: {response.status_code}")


def test_get_url_allows_trusted_cf_connecting_ip_with_forwarded_for_chain() -> None:
    # Given
    import routes.api_kollus as api_kollus

    old_known_mid = api_kollus._known_mid
    old_known_sid = api_kollus._known_sid
    old_signed_url = api_kollus.kollus_signed_url
    api_kollus._known_mid = lambda _mid: True
    api_kollus._known_sid = lambda _sid: True
    api_kollus.kollus_signed_url = lambda _mid, client_ip, sid="": f"signed:{client_ip}:{sid}"
    client = create_app().test_client()

    try:
        # When
        response = client.get(
            "/api/get-url?mid=abcd1234&sid=student1",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "X-Forwarded-For": "110.14.147.14, 172.71.0.10",
                "User-Agent": "Mozilla/5.0 KAKAOTALK 10.0",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        body = response.get_data(as_text=True)
    finally:
        api_kollus._known_mid = old_known_mid
        api_kollus._known_sid = old_known_sid
        api_kollus.kollus_signed_url = old_signed_url

    # Then
    if response.status_code != 200:
        raise AssertionError(f"trusted Cloudflare get-url request failed: {response.status_code} {body}")
    if body != "signed:110.14.147.14:student1":
        raise AssertionError(f"get-url used the wrong client IP: {body!r}")


def test_get_url_allows_trusted_cf_connecting_ip_when_proxyfix_is_enabled() -> None:
    # Given
    import routes.api_kollus as api_kollus

    old_known_mid = api_kollus._known_mid
    old_known_sid = api_kollus._known_sid
    old_signed_url = api_kollus.kollus_signed_url
    old_trust_proxy_headers = os.environ.get("TRUST_PROXY_HEADERS")
    os.environ["TRUST_PROXY_HEADERS"] = "1"
    api_kollus._known_mid = lambda _mid: True
    api_kollus._known_sid = lambda _sid: True
    api_kollus.kollus_signed_url = lambda _mid, client_ip, sid="": f"signed:{client_ip}:{sid}"
    client = create_app().test_client()

    try:
        # When
        response = client.get(
            "/api/get-url?mid=abcd1234&sid=student1",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "X-Forwarded-For": "110.14.147.14, 172.71.0.10",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        body = response.get_data(as_text=True)
    finally:
        api_kollus._known_mid = old_known_mid
        api_kollus._known_sid = old_known_sid
        api_kollus.kollus_signed_url = old_signed_url
        if old_trust_proxy_headers is None:
            os.environ.pop("TRUST_PROXY_HEADERS", None)
        else:
            os.environ["TRUST_PROXY_HEADERS"] = old_trust_proxy_headers

    # Then
    if response.status_code != 200:
        raise AssertionError(f"ProxyFix trusted CF get-url request failed: {response.status_code} {body}")
    if body != "signed:110.14.147.14:student1":
        raise AssertionError(f"ProxyFix get-url used the wrong client IP: {body!r}")


def test_get_url_allows_academy_ip_from_forwarded_for_without_cf_header() -> None:
    # Given
    import routes.api_kollus as api_kollus

    old_known_mid = api_kollus._known_mid
    old_known_sid = api_kollus._known_sid
    old_signed_url = api_kollus.kollus_signed_url
    old_trust_proxy_headers = os.environ.get("TRUST_PROXY_HEADERS")
    os.environ["TRUST_PROXY_HEADERS"] = "1"
    api_kollus._known_mid = lambda _mid: True
    api_kollus._known_sid = lambda _sid: True
    api_kollus.kollus_signed_url = lambda _mid, client_ip, sid="": f"signed:{client_ip}:{sid}"
    client = create_app().test_client()

    try:
        # When
        response = client.get(
            "/api/get-url?mid=abcd1234&sid=student1",
            headers={
                "X-Forwarded-For": "110.14.147.14, 172.71.0.10",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        body = response.get_data(as_text=True)
    finally:
        api_kollus._known_mid = old_known_mid
        api_kollus._known_sid = old_known_sid
        api_kollus.kollus_signed_url = old_signed_url
        if old_trust_proxy_headers is None:
            os.environ.pop("TRUST_PROXY_HEADERS", None)
        else:
            os.environ["TRUST_PROXY_HEADERS"] = old_trust_proxy_headers

    # Then
    if response.status_code != 200:
        raise AssertionError(f"Forwarded-For academy get-url request failed: {response.status_code} {body}")
    if body != "signed:110.14.147.14:student1":
        raise AssertionError(f"Forwarded-For get-url used the wrong client IP: {body!r}")


def test_get_url_blocks_external_ip_from_forwarded_for_without_cf_header() -> None:
    # Given
    import routes.api_kollus as api_kollus

    old_known_mid = api_kollus._known_mid
    old_known_sid = api_kollus._known_sid
    old_signed_url = api_kollus.kollus_signed_url
    old_trust_proxy_headers = os.environ.get("TRUST_PROXY_HEADERS")
    os.environ["TRUST_PROXY_HEADERS"] = "1"
    api_kollus._known_mid = lambda _mid: True
    api_kollus._known_sid = lambda _sid: True
    api_kollus.kollus_signed_url = lambda _mid, client_ip, sid="": f"signed:{client_ip}:{sid}"
    client = create_app().test_client()

    try:
        # When
        response = client.get(
            "/api/get-url?mid=abcd1234&sid=student1",
            headers={
                "X-Forwarded-For": "198.51.100.23, 172.71.0.10",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        body = response.get_json(silent=True) or {}
    finally:
        api_kollus._known_mid = old_known_mid
        api_kollus._known_sid = old_known_sid
        api_kollus.kollus_signed_url = old_signed_url
        if old_trust_proxy_headers is None:
            os.environ.pop("TRUST_PROXY_HEADERS", None)
        else:
            os.environ["TRUST_PROXY_HEADERS"] = old_trust_proxy_headers

    # Then
    if response.status_code != 403:
        raise AssertionError(f"Forwarded-For external get-url request should be blocked, got {response.status_code}")
    if body.get("error") != "academy_network_required":
        raise AssertionError(f"external block returned wrong body: {body!r}")


def test_answer_map_allows_trusted_cf_when_forwarded_for_has_public_peer() -> None:
    # Given
    client = create_app().test_client()

    # When
    response = client.get(
        "/js/test_answer_link_map.json",
        headers={"CF-Connecting-IP": "110.14.147.14", "X-Forwarded-For": "203.0.113.10"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    # Then
    if response.status_code != 200:
        raise AssertionError(f"trusted CF answer map request should be allowed, got {response.status_code}")


def test_answer_map_blocks_direct_public_spoofed_cf_connecting_ip() -> None:
    # Given
    client = create_app().test_client()

    # When
    response = client.get(
        "/js/test_answer_link_map.json",
        headers={"CF-Connecting-IP": "110.14.147.14"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.23"},
    )

    # Then
    if response.status_code != 403:
        raise AssertionError(f"direct public spoofed CF request should be blocked, got {response.status_code}")


def test_file_download_route_is_not_academy_network_gated() -> None:
    # Given
    import routes.api_fs as api_fs

    old_files_dir = api_fs.FILES_DIR
    old_files_root = api_fs.FILES_ROOT
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "worksheet.txt").write_text("academy material", encoding="utf-8")
        api_fs.FILES_DIR = tmp_path
        api_fs.FILES_ROOT = tmp_path.resolve()
        client = create_app().test_client()

        try:
            # When
            response = client.get(
                "/files/worksheet.txt",
                headers={"CF-Connecting-IP": "110.14.147.14", "X-Forwarded-For": "203.0.113.10"},
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
                buffered=True,
            )
            body = response.get_data(as_text=True)
            response.close()
        finally:
            api_fs.FILES_DIR = old_files_dir
            api_fs.FILES_ROOT = old_files_root

    # Then
    if response.status_code != 200:
        raise AssertionError(f"file downloads must not use academy network gate, got {response.status_code}")
    if body != "academy material":
        raise AssertionError("file download response body changed")


def run_checks(checks: Sequence[Callable[[], None]]) -> None:
    failures: list[str] = []
    for check in checks:
        try:
            check()
        except AssertionError as exc:
            failures.append(f"{check.__name__}: {exc}")

    if failures:
        detail = os.linesep.join(f"- {failure}" for failure in failures)
        raise AssertionError(f"academy proxy network access checks failed:{os.linesep}{detail}")


def main() -> None:
    run_checks(
        (
            test_direct_academy_client_is_allowed,
            test_direct_private_academy_lan_clients_are_allowed,
            test_trusted_loopback_proxy_uses_cf_connecting_ip,
            test_trusted_cloudflare_header_is_authoritative_with_forwarded_for_chain,
            test_cf_connecting_ip_takes_precedence_over_forwarded_for,
            test_trusted_loopback_proxy_uses_leftmost_forwarded_for_client,
            test_trusted_loopback_proxy_uses_real_ip_without_forwarded_for,
            test_forwarded_for_takes_precedence_over_real_ip,
            test_direct_public_client_cannot_spoof_forwarded_for,
            test_direct_public_client_cannot_spoof_cf_connecting_ip,
            test_answer_map_allows_trusted_cf_connecting_ip,
            test_get_url_allows_trusted_cf_connecting_ip_with_forwarded_for_chain,
            test_get_url_allows_trusted_cf_connecting_ip_when_proxyfix_is_enabled,
            test_get_url_allows_academy_ip_from_forwarded_for_without_cf_header,
            test_get_url_blocks_external_ip_from_forwarded_for_without_cf_header,
            test_answer_map_allows_trusted_cf_when_forwarded_for_has_public_peer,
            test_answer_map_blocks_direct_public_spoofed_cf_connecting_ip,
            test_file_download_route_is_not_academy_network_gated,
        )
    )
    print("academy proxy network access checks passed")


if __name__ == "__main__":
    main()
