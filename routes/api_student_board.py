"""Session-bound, student-safe board API for the public mobile app."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, Response, g, jsonify, make_response, request

from core.network_access import ip_allowed
from core.student_board_projection import BOARD_TYPES, BoardInputError, project_student_board
from core.student_public_surface_paths import strict_sid


Loader = Callable[[], Any]


@dataclass(slots=True)
class StudentBoardApiDependencies:
    announcements: Loader
    statuses: Loader
    videos: Loader
    clock: Callable[[], dt.datetime]


@dataclass(slots=True)
class _Provider:
    dependencies: StudentBoardApiDependencies | None = None

    def get(self) -> StudentBoardApiDependencies:
        if self.dependencies is None:
            self.dependencies = _build_dependencies()
        return self.dependencies


def _build_dependencies() -> StudentBoardApiDependencies:
    # Runtime paths stay lazy so importing the route is filesystem-pure.
    from core.paths import ANN_STATUS_PATH, ANNS_PATH, VID_PATH
    from core.storage import load

    return StudentBoardApiDependencies(
        lambda: load(ANNS_PATH),
        lambda: load(ANN_STATUS_PATH),
        lambda: load(VID_PATH),
        lambda: dt.datetime.now(dt.timezone.utc),
    )


def _reply(payload: dict[str, Any], status: int = 200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response if status == 200 else (response, status)


def _empty_404() -> Response:
    response = make_response("", 404)
    response.headers["Cache-Control"] = "no-store"
    return response


def _strict_query() -> tuple[str, str | None]:
    keys = set(request.args.keys())
    if not keys.issubset({"type", "cursor"}):
        raise BoardInputError()
    if any(len(request.args.getlist(key)) != 1 for key in keys):
        raise BoardInputError()
    board_type = request.args.get("type", "all")
    cursor = request.args.get("cursor")
    if board_type not in BOARD_TYPES or cursor == "":
        raise BoardInputError()
    return board_type, cursor


def create_blueprint(dependencies: StudentBoardApiDependencies | None = None) -> Blueprint:
    provider = _Provider(dependencies)
    blueprint = Blueprint("api_student_board" if dependencies is None else f"api_student_board_{id(provider)}", __name__)

    @blueprint.get("/api/mobile/student/board")
    def board():
        if getattr(g, "student_app_public_request", False) is not True:
            return _empty_404()
        sid = strict_sid(getattr(g, "student_app_active_sid", ""))
        if sid is None:
            return _reply({"ok": False, "code": "unauthenticated"}, 401)
        try:
            board_type, cursor = _strict_query()
            deps = provider.get()
            page = project_student_board(
                deps.announcements(),
                deps.statuses(),
                deps.videos(),
                sid=sid,
                now=deps.clock(),
                board_type=board_type,
                cursor=cursor,
                page_size=50,
                academy_allowed=ip_allowed(getattr(g, "student_app_client_ip", "")),
            )
        except BoardInputError as exc:
            return _reply({"ok": False, "code": exc.code}, 400)
        except Exception:
            return _reply({"ok": False, "code": "board_unavailable"}, 503)
        return _reply(page)

    return blueprint


bp_api_student_board = create_blueprint()


__all__ = ("StudentBoardApiDependencies", "bp_api_student_board", "create_blueprint")
