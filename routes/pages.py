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

@bp_pages.get("/admin")
def page_admin():
    return current_app.send_static_file("admin.html")

@bp_pages.get("/students")
def page_all():
    return current_app.send_static_file("all.html")

@bp_pages.get("/student/<sid>")
def page_student(sid: str):
    return current_app.send_static_file("student.html")

@bp_pages.get("/student-test/<sid>")
def page_student_test(sid: str):
    return current_app.send_static_file("student copy.html")

@bp_pages.get("/video-manage")
def page_video_manage():
    return current_app.send_static_file("video-manage.html")

@bp_pages.get("/school-cal")
def page_school_cal():
    return current_app.send_static_file("school-cal.html")

@bp_pages.get("/tests")
def tests_page():
    return current_app.send_static_file("tests.html")

@bp_pages.get("/file-manage")
def page_file_manage():
    return current_app.send_static_file("file-manage.html")
