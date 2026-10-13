from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from core.admin_bootstrap_service import AdminBootstrapService
from core.admin_revisions import date_revision, log_revision
from core.absent import load_absent
from core.date_rules import is_iso_date_key
from core.paths import BASE, CAL_PATH, UPD_PATH
from core.json_revision import json_revision
from core.stores import get_store
from core.school_calendar_store import load_school_calendar_snapshot
from core.update_assignment_store import load_updates_strict
from routes.api_progress import read_progress_projection
from routes.api_students import read_admin_students
from routes.api_videos import read_admin_videos
from routes.log_repository_provider import get_log_repository

bp_api_admin_state = Blueprint("api_admin_state", __name__)


@bp_api_admin_state.get("/api/admin/bootstrap")
def api_admin_bootstrap():
    date = str(request.args.get("date") or "").strip()
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    service = AdminBootstrapService({
        'students': lambda _date: read_admin_students(),
        'videos': lambda _date: read_admin_videos(),
        'updates': lambda _date: load_updates_strict(UPD_PATH),
        'logs': lambda date: get_log_repository().read_logs(date),
        'absent': lambda _date: load_absent(),
        'progress': lambda date: read_progress_projection(date=date),
        'schoolCal': lambda _date: load_school_calendar_snapshot(CAL_PATH)[0],
    }, optional_error=lambda key, error: current_app.logger.warning(
        '[admin bootstrap] optional %s load failed: %s', key, error))
    try:
        result = service.load(date)
    except Exception:
        current_app.logger.exception('[admin bootstrap] critical load failed')
        return jsonify({"ok": False, "error": "admin_bootstrap_unavailable"}), 503
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp_api_admin_state.get("/api/admin/revisions")
def api_admin_revisions():
    date = str(request.args.get("date") or "").strip()
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    try:
        repository = get_log_repository()
        result = {
            'students': json_revision(read_admin_students()),
            'logs': log_revision(repository, date),
            'logHistory': log_revision(repository),
            'progress': date_revision(get_store('progress'), date),
            'progressHistory': get_store('progress').revision(),
            'attendance': date_revision(get_store('attendance'), date),
            'contact': date_revision(get_store('contact'), date),
            'arriveTime': date_revision(get_store('arriveTime'), date),
            'arriveHistory': get_store('arriveTime').revision(),
            'makeupCarryover': get_store('legacy', BASE / 'makeup_carryover.json').revision(),
        }
        for key, store in {
            'videos': 'videos', 'updates': 'updates', 'absent': 'absent',
            'schoolCal': 'calendar', 'weekend': 'weekend', 'extra': 'extra',
            'todayOrder': 'todayOrder',
        }.items():
            result[key] = get_store(store).revision()
    except Exception:
        current_app.logger.exception('[admin revisions] load failed')
        return jsonify({"ok": False, "error": "admin_revisions_unavailable"}), 503
    response = jsonify({'date': date, 'revisions': result})
    response.headers['Cache-Control'] = 'no-store'
    return response
