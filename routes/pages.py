from __future__ import annotations

import logging
from flask import Blueprint, current_app, request

bp_pages = Blueprint("pages", __name__)

log = logging.getLogger("app.ip")

@bp_pages.before_app_request
def _log_ip():
    # ✅ print 대신 logging (WinError 233 방지)
    log.info("IP %s %s", request.remote_addr, request.path)

@bp_pages.get("/")
def root():
    return current_app.send_static_file("index.html")


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


@bp_pages.get("/app/offline-help")
def page_student_app_offline_help():
    return current_app.send_static_file("offline.html")

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

@bp_pages.get("/student-test/<sid>")
def page_student_test(sid: str):
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
