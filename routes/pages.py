from __future__ import annotations

import logging
import os

from flask import Blueprint, Response, abort, current_app, g, make_response, request
from werkzeug.utils import safe_join

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, verify_admin_authorization
from core.network_access import ip_allowed

bp_pages = Blueprint("pages", __name__)

log = logging.getLogger("app.ip")

_ADMIN_PAGE_PATHS = frozenset({
    "/admin",
    "/admin.html",
    "/all.html",
    "/dh1130",
    "/file-manage",
    "/file-manage.html",
    "/school-cal",
    "/school-cal.html",
    "/students",
    "/tests",
    "/tests.html",
    "/video-manage",
    "/video-manage.html",
})
_ADMIN_STATIC_FILES = (
    "admin.html",
    "all.html",
    "file-manage.html",
    "school-cal.html",
    "tests.html",
    "video-manage.html",
)


def _admin_route_key(path: str) -> str:
    segments = (segment.rstrip(" .").casefold() for segment in path.replace("\\", "/").split("/"))
    return "/" + "/".join(segment for segment in segments if segment)


def _is_admin_static_alias() -> bool:
    if request.endpoint != "static" or not isinstance(request.view_args, dict):
        return False
    filename = request.view_args.get("filename")
    static_root = current_app.static_folder
    if not isinstance(filename, str) or not isinstance(static_root, str):
        return False
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if ".htm" not in leaf:
        return False
    candidate = safe_join(static_root, filename)
    if candidate is None:
        return False
    for protected_name in _ADMIN_STATIC_FILES:
        protected = safe_join(static_root, protected_name)
        try:
            if protected is not None and os.path.samefile(candidate, protected):
                return True
        except OSError:
            continue
    return False

@bp_pages.before_app_request
def _log_ip():
    # ✅ print 대신 logging (WinError 233 방지)
    log.info("IP %s %s", request.remote_addr, request.path)


def _admin_auth_required() -> Response:
    response = make_response("관리자 로그인이 필요합니다.", 401)
    response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@bp_pages.before_app_request
def _gate_admin_pages() -> Response | None:
    if _admin_route_key(request.path) not in _ADMIN_PAGE_PATHS and not _is_admin_static_alias():
        return None
    verifier = current_app.config.get("ACADEMY_ADMIN_AUTHORIZER")
    if not callable(verifier):
        verifier = verify_admin_authorization
    if not verifier(request.headers.get("Authorization")):
        return _admin_auth_required()
    return None

@bp_pages.get("/")
def root():
    return current_app.send_static_file("index.html")


@bp_pages.get("/js/test_answer_link_map.json")
def student_answer_link_map():
    if getattr(g, "student_app_public_request", False) is True:
        active_sid = getattr(g, "student_app_active_sid", None)
        client_ip = getattr(g, "student_app_client_ip", None)
        if not isinstance(active_sid, str) or not active_sid:
            abort(404)
        if not isinstance(client_ip, str) or not ip_allowed(client_ip):
            abort(404)
    response = current_app.send_static_file("js/test_answer_link_map.json")
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_pages.get("/app")
@bp_pages.get("/app/")
@bp_pages.get("/app/login")
@bp_pages.get("/app/help")
@bp_pages.get("/app/home")
@bp_pages.get("/app/checks")
@bp_pages.get("/app/inbox")
@bp_pages.get("/app/materials")
@bp_pages.get("/app/tests")
@bp_pages.get("/app/videos")
def page_student_app():
    return current_app.send_static_file("student-app.html")


@bp_pages.get("/admin")
@bp_pages.get("/dh1130")
@bp_pages.get("/demo/rh3123")
def page_admin():
    return current_app.send_static_file("admin.html")

@bp_pages.get("/students")
@bp_pages.get("/demo/rh3123/students")
def page_all():
    return current_app.send_static_file("all.html")

@bp_pages.get("/student/<sid>")
def page_student(sid: str):
    return current_app.send_static_file("student.html")

@bp_pages.get("/video-manage")
@bp_pages.get("/demo/rh3123/video-manage")
def page_video_manage():
    return current_app.send_static_file("video-manage.html")

@bp_pages.get("/school-cal")
@bp_pages.get("/demo/rh3123/school-cal")
def page_school_cal():
    return current_app.send_static_file("school-cal.html")

@bp_pages.get("/tests")
@bp_pages.get("/demo/rh3123/tests")
def tests_page():
    return current_app.send_static_file("tests.html")

@bp_pages.get("/file-manage")
def page_file_manage():
    return current_app.send_static_file("file-manage.html")
