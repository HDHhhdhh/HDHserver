"""Focused raw-request-target probes shared by the Todo 7 surface checks."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from flask.testing import FlaskClient


Check = Callable[[bool, str], None]


def malformed_root_statuses(client: FlaskClient, headers: Mapping[str, str]) -> dict[str, int]:
    fixtures = {
        "RAW_URI double slash": {"PATH_INFO": "/", "RAW_URI": "//student-app.html"},
        "REQUEST_URI double slash": {"PATH_INFO": "/", "REQUEST_URI": "//student-app.html"},
        "matching raw double slash": {
            "PATH_INFO": "/",
            "RAW_URI": "//student-app.html",
            "REQUEST_URI": "//student-app.html",
        },
        "conflicting raw targets": {"PATH_INFO": "/", "RAW_URI": "/", "REQUEST_URI": "//student-app.html"},
        "encoded double slash": {"PATH_INFO": "/", "RAW_URI": "/%2fstudent-app.html"},
        "normalized path mismatch": {"PATH_INFO": "/", "RAW_URI": "/admin"},
    }
    return {
        label: client.get(
            "/",
            base_url="https://app.5a-math.com",
            headers=dict(headers),
            environ_overrides=environment,
        ).status_code
        for label, environment in fixtures.items()
    }


def check_public_root_boundary(client: FlaskClient, headers: Mapping[str, str], check: Check) -> None:
    request = {"base_url": "https://app.5a-math.com", "headers": dict(headers)}
    root = client.get("/", **request)
    check(root.status_code == 302, "public root redirects")
    check(root.headers.get("Location") == "/app", "redirect stays same-origin")
    exact = client.get(
        "/",
        **request,
        environ_overrides={"PATH_INFO": "/", "RAW_URI": "/", "REQUEST_URI": "/"},
    )
    check(exact.status_code == 302 and exact.headers.get("Location") == "/app", "exact raw root redirects")
    for label, status in malformed_root_statuses(client, headers).items():
        check(status == 404, f"{label} is denied before root redirect")
    canonical = client.get("/app", **request)
    check(canonical.status_code == 200 and canonical.headers.get("Cache-Control") == "no-store", "canonical app root is public")
    check(client.get("/student-app.html", **request).status_code == 404, "raw student shell alias is denied")


def get_equivalent_encoded_announcement(client: FlaskClient, headers: Mapping[str, str]):  # noqa: ANN201
    return client.get(
        "/files/announcements/notice.pdf",
        base_url="https://app.5a-math.com",
        headers=dict(headers),
        environ_overrides={
            "RAW_URI": "/files/announcements/%6eotice.pdf",
            "REQUEST_URI": "/files/announcements/notice.pdf",
        },
    )


__all__ = ("check_public_root_boundary", "get_equivalent_encoded_announcement", "malformed_root_statuses")
