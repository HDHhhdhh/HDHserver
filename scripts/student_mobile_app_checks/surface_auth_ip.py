"""Real auth-route seam check for resolved client-IP throttle input."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from flask import Flask

from core.student_app_auth_service import StudentAuthDependencies
from core.student_app_config import load_student_app_config
from core.student_public_surface import install_student_public_surface
from routes.api_student_app_auth import create_blueprint


def _check(state: list[int | str], condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    state[0] = int(state[0]) + 1
    state.append(label)


class _Accounts:
    def get(self, account_id: str):  # noqa: ARG002
        return None

    def load(self):
        return {}


class _Throttle:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def status(self, identifier: str, client_ip: str):  # noqa: ARG002
        self.seen.append(client_ip)
        return {"blocked": False, "retry_after": 0}

    def record_failure(self, identifier: str, client_ip: str):  # noqa: ARG002
        self.seen.append(client_ip)
        return {"blocked": False, "retry_after": 0}


def run_auth_throttle_ip_check(state: list[int | str]) -> None:
    with tempfile.TemporaryDirectory(prefix="student-auth-ip-") as raw:
        root = Path(raw)
        students_path = root / "students.json"
        students_path.write_text(json.dumps([{"id": "sid-a", "name": "Alice", "school": "A", "grade": "1"}], ensure_ascii=False), encoding="utf-8")
        config = load_student_app_config(
            {
                "STUDENT_APP_PUBLIC_ENABLED": "1",
                "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
                "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            }
        )
        throttle = _Throttle()
        dependencies = StudentAuthDependencies(config, _Accounts(), None, None, throttle, students_path)
        app = Flask("surface-auth-ip")
        install_student_public_surface(app, config=config, auth_blueprint=create_blueprint(dependencies))
        client = app.test_client()
        trusted = client.post(
            "/api/mobile/auth/login",
            json={"id": "Alice", "password": "bad"},
            base_url="https://app.5a-math.com",
            headers={"CF-Connecting-IP": "110.14.147.14"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        untrusted = client.post(
            "/api/mobile/auth/login",
            json={"id": "Alice", "password": "bad"},
            base_url="https://app.5a-math.com",
            headers={"CF-Connecting-IP": "198.51.100.8"},
            environ_base={"REMOTE_ADDR": "198.51.100.9"},
        )
        expected = ["110.14.147.14", "110.14.147.14", "198.51.100.9", "198.51.100.9"]
        _check(state, trusted.status_code == 401 and untrusted.status_code == 401 and throttle.seen == expected, "auth throttle observes trusted CF and untrusted peer IP")


__all__ = ("run_auth_throttle_ip_check",)
