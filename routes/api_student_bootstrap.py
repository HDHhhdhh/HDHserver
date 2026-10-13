from __future__ import annotations

import re
from copy import deepcopy

from flask import Blueprint, current_app, g, jsonify, request
from core.date_rules import is_iso_date_key
from core.isolated_kollus_qa import isolated_kollus_qa_allowed

from core.network_access import (
    academy_network_allowed,
    ip_allowed,
    strip_answer_link_fields,
)
from core.paths import WATCH_PATH
from core.progress_rules import normalize_watch_entry, watch_rank
from core.storage import load, nocache_resp
from core.video_watch_cycles import latest_watch_projection
from core.update_assignment_rules import sid_keys
from routes.student_bootstrap_projection import (
    StudentBootstrapProjectionDependencies,
    build_student_bootstrap_payload,
)


bp_api_student_bootstrap = Blueprint("api_student_bootstrap", __name__)

_PROJECTION_EXTENSION = "student_bootstrap_projection_dependencies"


def configure_student_bootstrap_projection(
    app,
    dependencies: StudentBootstrapProjectionDependencies,
) -> None:
    if not isinstance(dependencies, StudentBootstrapProjectionDependencies):
        raise TypeError("student bootstrap projection dependencies are required")
    app.extensions[_PROJECTION_EXTENSION] = dependencies


def _projection_dependencies() -> StudentBootstrapProjectionDependencies:
    dependencies = current_app.extensions.get(_PROJECTION_EXTENSION)
    if not isinstance(dependencies, StudentBootstrapProjectionDependencies):
        raise RuntimeError("student bootstrap projection is not configured")
    return dependencies


def _is_public_student_request() -> bool:
    return getattr(g, "student_app_public_request", False) is True


def _public_session_sid() -> str | None:
    if not _is_public_student_request():
        return None
    sid = getattr(g, "student_app_active_sid", None)
    return sid if isinstance(sid, str) and sid else None


def _student_request_academy_allowed() -> bool:
    if not _is_public_student_request():
        return academy_network_allowed()
    client_ip = getattr(g, "student_app_client_ip", None)
    return ip_allowed(client_ip) if isinstance(client_ip, str) else False


def _latest_student_watch_payload(watch_all, sid: str, progress=None, date="9999-12-31") -> dict:
    out = latest_watch_projection(watch_all, progress or {}, sid, date)
    return {"ok": True, "sid": sid, "date": "", "watch": out}


def _strip_public_bootstrap_links(value, restricted_scope: bool = False):
    if isinstance(value, list):
        return [
            _strip_public_bootstrap_links(item, restricted_scope)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    stripped, _ = strip_answer_link_fields(value)
    out = {}
    for raw_key, raw_value in stripped.items():
        key = str(raw_key)
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if "answer" in normalized or "solution" in normalized:
            continue
        child_scope = restricted_scope or any(
            marker in normalized
            for marker in (
                "material",
                "homework",
                "attachment",
                "sourcefile",
                "video",
            )
        )
        if child_scope and (
            normalized in {"url", "link", "path", "src", "source", "fileid"}
            or normalized.endswith(("url", "link", "path", "fileid"))
        ):
            continue
        out[raw_key] = _strip_public_bootstrap_links(raw_value, child_scope)
    return out


def _finalize_public_bootstrap(
    payload: dict,
    sid: str,
    academy_allowed: bool,
    date: str,
) -> dict:
    if not _is_public_student_request():
        return payload
    result = deepcopy(payload)
    result["academyAccessAllowed"] = academy_allowed
    result["outsideAcademyBlocked"] = not academy_allowed
    result["networkBlocked"] = not academy_allowed
    result["watch"] = _latest_student_watch_payload(
        load(WATCH_PATH) or {},
        sid,
        _projection_dependencies().load_progress(),
        date,
    )
    return result if academy_allowed else _strip_public_bootstrap_links(result)


@bp_api_student_bootstrap.get("/api/student/bootstrap")
def api_student_bootstrap():
    dependencies = _projection_dependencies()
    caller_sid = str(request.args.get("sid") or "").strip()
    session_sid = _public_session_sid()
    public_request = _is_public_student_request()
    if public_request and session_sid is None:
        return jsonify({"ok": False, "code": "unauthenticated"}), 401
    sid = session_sid if session_sid is not None else caller_sid
    date = str(request.args.get("date") or dependencies.today_iso()).strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    payload, status = build_student_bootstrap_payload(
        dependencies,
        sid=sid,
        date=date,
        public_request=public_request,
        academy_allowed_resolver=_student_request_academy_allowed,
    )
    if status != 200:
        return jsonify(payload), status
    payload = dict(payload)
    for field in ("videos", "reviewVideos"):
        if field not in payload:
            continue
        payload[field] = [dict(video) if isinstance(video, dict) else video for video in payload[field]]
        for video in payload[field]:
            if not isinstance(video, dict):
                continue
            video.pop("localPlaybackQaAllowed", None)
            if field == "videos" and isolated_kollus_qa_allowed(sid, str(video.get("mid") or "").strip()):
                video["localPlaybackQaAllowed"] = True
                video["playbackRestricted"] = False
    academy_allowed = payload.get("academyAccessAllowed") is True
    return nocache_resp(
        _finalize_public_bootstrap(payload, sid, academy_allowed, date)
    )


__all__ = (
    "bp_api_student_bootstrap",
    "configure_student_bootstrap_projection",
)
