"""Feature-gated student focus-session and academy summary APIs."""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, g, jsonify, make_response, request

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, admin_network_allowed, verify_admin_authorization
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_focus_repository import FocusNotInitializedError, StudentFocusRepository
from core.student_focus_rules import (
    FocusConflictError,
    FocusInputError,
    FocusSessionNotFoundError,
    class_key,
    event_batch,
    kst_iso,
    public_schedule,
    select_eligibility,
    session_id,
)
from core.student_focus_schedule_source import FocusRuntimeSource
from core.student_public_proxy import public_host_matches
from core.student_public_surface_paths import strict_sid


ScheduleProvider = Callable[[str, float], list[dict[str, object]]]
RosterProvider = Callable[[], dict[str, dict[str, str]]]


@dataclass(slots=True)
class StudentFocusApiDependencies:
    config: StudentAppConfig
    repository: StudentFocusRepository
    schedule_provider: ScheduleProvider
    roster_provider: RosterProvider
    clock: Callable[[], float] = time.time


@dataclass(slots=True)
class _Provider:
    dependencies: StudentFocusApiDependencies | None = None

    def get(self) -> StudentFocusApiDependencies:
        if self.dependencies is None:
            self.dependencies = _build_dependencies()
        return self.dependencies


def _build_dependencies() -> StudentFocusApiDependencies:
    root = Path(__file__).resolve().parents[1]
    config = load_student_app_config()
    database = Path(os.environ.get("STUDENT_APP_DB_PATH", root / "app.sqlite"))
    source = FocusRuntimeSource(Path(os.environ.get("STUDENT_APP_RUNTIME_ROOT", root)))
    return StudentFocusApiDependencies(config, StudentFocusRepository(database), source.schedule, source.roster)


_DEFAULT_PROVIDER = _Provider()


def _reply(payload: Mapping[str, Any], status: int = 200):
    response = jsonify(dict(payload))
    response.headers["Cache-Control"] = "no-store"
    return response if status == 200 else (response, status)


def _empty_404() -> Response:
    response = make_response("", 404)
    response.headers["Cache-Control"] = "no-store"
    return response


def _body() -> Mapping[str, Any] | None:
    if request.content_length is not None and request.content_length > 16 * 1024:
        return None
    value = request.get_json(silent=True)
    return value if isinstance(value, Mapping) else None


def _public_sid(deps: StudentFocusApiDependencies, *, csrf: bool) -> str | Response | tuple[Response, int]:
    if not deps.config.focus_enabled or getattr(g, "student_app_public_request", False) is not True:
        return _empty_404()
    sid = strict_sid(getattr(g, "student_app_active_sid", None))
    if sid is None:
        return _reply({"ok": False, "code": "unauthenticated"}, 401)
    if csrf and getattr(g, "student_app_csrf_validated", False) is not True:
        return _reply({"ok": False, "code": "csrf_required"}, 403)
    return sid


def _error(exc: Exception):
    if isinstance(exc, FocusInputError):
        status = 409 if exc.code == "focus_event_limit" else 400
        return _reply({"ok": False, "code": exc.code}, status)
    if isinstance(exc, FocusSessionNotFoundError):
        return _reply({"ok": False, "code": exc.code}, 404)
    if isinstance(exc, FocusConflictError):
        return _reply({"ok": False, "code": exc.code}, 409)
    if isinstance(exc, FocusNotInitializedError):
        return _reply({"ok": False, "code": "focus_unavailable"}, 503)
    return _reply({"ok": False, "code": "focus_unavailable"}, 503)


def _eligibility_payload(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": value["state"], "opensAt": value["opensAt"], "closesAt": value["closesAt"],
        "schedule": public_schedule(value.get("schedule")),
    }


def create_public_blueprint(dependencies: StudentFocusApiDependencies | None = None) -> Blueprint:
    provider = _DEFAULT_PROVIDER if dependencies is None else _Provider(dependencies)
    blueprint = Blueprint("student_focus", __name__, url_prefix="/api/mobile/focus")

    @blueprint.get("/current")
    def current():
        deps = provider.get()
        authorized = _public_sid(deps, csrf=False)
        if not isinstance(authorized, str):
            return authorized
        if request.args:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            if not deps.repository.schema_ready():
                raise FocusNotInitializedError("focus schema is unavailable")
            now = float(deps.clock())
            eligibility = select_eligibility(deps.schedule_provider(authorized, now), sid=authorized, now=now)
            row = deps.repository.current_for_sid(authorized)
            selected = eligibility.get("schedule")
            if row is not None and row["state"] != "active" and (
                not isinstance(selected, Mapping) or row["schedule_key"] != selected.get("scheduleKey")
            ):
                row = None
            summary = deps.repository.summary(row, now=now) if row is not None else None
            return _reply({
                "ok": True, "serverNow": kst_iso(now),
                "eligibility": _eligibility_payload(eligibility), "session": summary,
            })
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - storage/runtime detail stays private
            return _error(exc)

    @blueprint.post("/start")
    def start():
        deps = provider.get()
        authorized = _public_sid(deps, csrf=True)
        if not isinstance(authorized, str):
            return authorized
        data = _body()
        if data is None or set(data):
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            now = float(deps.clock())
            eligibility = select_eligibility(deps.schedule_provider(authorized, now), sid=authorized, now=now)
            schedule = eligibility.get("schedule")
            if eligibility.get("state") != "eligible" or not isinstance(schedule, Mapping):
                raise FocusConflictError("focus_not_eligible")
            row, resumed = deps.repository.start(authorized, schedule, now=now)
            payload = {"ok": True, "resumed": resumed, "serverNow": kst_iso(now), "session": deps.repository.summary(row, now=now)}
            return _reply(payload) if resumed else _reply(payload, 201)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            return _error(exc)

    @blueprint.post("/events")
    def events():
        deps = provider.get()
        authorized = _public_sid(deps, csrf=True)
        if not isinstance(authorized, str):
            return authorized
        data = _body()
        if data is None or set(data) != {"sessionId", "events"}:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            focus_id = session_id(data.get("sessionId"))
            normalized = event_batch(data.get("events"))
            now = float(deps.clock())
            row = deps.repository.append_events(authorized, focus_id, normalized, now=now)
            return _reply({"ok": True, "serverNow": kst_iso(now), "session": deps.repository.summary(row, now=now)})
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            return _error(exc)

    @blueprint.post("/end")
    def end():
        deps = provider.get()
        authorized = _public_sid(deps, csrf=True)
        if not isinstance(authorized, str):
            return authorized
        data = _body()
        if data is None or set(data) != {"sessionId", "seq"} or type(data.get("seq")) is not int:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        try:
            focus_id = session_id(data.get("sessionId"))
            now = float(deps.clock())
            row = deps.repository.end(authorized, focus_id, int(data["seq"]), now=now)
            return _reply({"ok": True, "serverNow": kst_iso(now), "session": deps.repository.summary(row, now=now)})
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            return _error(exc)

    return blueprint


def create_admin_blueprint(
    dependencies: StudentFocusApiDependencies | None = None,
    *,
    admin_authorizer: Callable[[str | None], bool] | None = None,
) -> Blueprint:
    provider = _DEFAULT_PROVIDER if dependencies is None else _Provider(dependencies)
    authorize = admin_authorizer or verify_admin_authorization
    blueprint = Blueprint("student_focus_admin", __name__, url_prefix="/api/admin/student-focus")

    @blueprint.before_request
    def gate_admin():
        deps = provider.get()
        if not deps.config.focus_enabled:
            return _empty_404()
        if public_host_matches(request.environ, deps.config.public_host, deps.config.trusted_proxy_networks):
            return _empty_404()
        if not admin_network_allowed(request):
            return _reply({"ok": False, "code": "academy_network_required"}, 403)
        if not authorize(request.headers.get("Authorization")):
            response, status = _reply({"ok": False, "code": "admin_auth_required"}, 401)
            response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
            return response, status
        return None

    @blueprint.get("/summary")
    def summary():
        if set(request.args) != {"date"} or len(request.args.getlist("date")) != 1:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        date_key = str(request.args.get("date") or "").strip()
        try:
            if dt.date.fromisoformat(date_key).isoformat() != date_key:
                raise ValueError
        except ValueError:
            return _reply({"ok": False, "code": "invalid_request"}, 400)
        deps = provider.get()
        try:
            if not deps.repository.schema_ready():
                raise FocusNotInitializedError("focus schema is unavailable")
            now, roster = float(deps.clock()), deps.roster_provider()
            classes: dict[str, dict[str, object]] = {}
            for row in deps.repository.list_for_date(date_key):
                item = deps.repository.summary(row, now=now)
                class_id = class_key(item["schedule"])
                group = classes.setdefault(class_id, {
                    "classId": class_id, "kind": row["schedule_kind"],
                    "startAt": kst_iso(row["schedule_start_at"]), "endAt": kst_iso(row["schedule_end_at"]),
                    "sessions": [],
                })
                label = roster.get(str(row["sid"]), {})
                group["sessions"].append({
                    "sid": row["sid"], "name": label.get("name", ""), "school": label.get("school", ""),
                    "grade": label.get("grade", ""), "state": item["state"], "startedAt": item["startedAt"],
                    "endedAt": item["endedAt"], "focusMs": item["focusMs"], "hiddenCount": item["hiddenCount"],
                    "hiddenMs": item["hiddenMs"], "longestHiddenMs": item["longestHiddenMs"], "unknownMs": item["unknownMs"],
                })
            return _reply({"ok": True, "date": date_key, "serverNow": kst_iso(now), "classes": list(classes.values())})
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            return _error(exc)

    return blueprint


bp_api_student_focus = create_public_blueprint()
bp_api_student_focus_admin = create_admin_blueprint()


__all__ = (
    "StudentFocusApiDependencies", "bp_api_student_focus", "bp_api_student_focus_admin",
    "create_admin_blueprint", "create_public_blueprint",
)
