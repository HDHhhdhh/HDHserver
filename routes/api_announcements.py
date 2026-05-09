from __future__ import annotations

import json
import time
import datetime as dt
import urllib.parse
from typing import Any

from flask import Blueprint, jsonify, request

from core.paths import ANNS_PATH, ANN_STATUS_PATH
from core.storage import load, save_atomic

bp_api_announcements = Blueprint("api_announcements", __name__)


def _get_payload_json_or_form():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    if not data and request.form:
        data = {k: v for k, v in request.form.items()}
    return data

def _try_json(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val

@bp_api_announcements.route("/api/announcements", methods=["GET", "POST"])
def api_announcements():
    if request.method == "GET":
        anns = load(ANNS_PATH)
        sid = request.args.get("sid")
        if sid:
            _sid = str(sid)
            def targeted(a: dict) -> bool:
                t = a.get("targets", "all")
                return t == "all" or (isinstance(t, list) and _sid in map(str, t))
            anns = [a for a in anns if targeted(a)]
        anns.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return jsonify(anns)

    body = _get_payload_json_or_form()
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    if not title or not content:
        return jsonify({"ok": False, "error": "title/content required"}), 400

    poll    = _try_json(body.get("poll") or None)
    survey  = _try_json(body.get("survey") or None)
    targets = _try_json(body.get("targets") or "all")

    ann = {
        "id": body.get("id") or f"a_{int(time.time()*1000)}",
        "title": title,
        "content": content,
        "createdAt": body.get("createdAt") or dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "targets": targets,
        "poll": poll,
        "survey": survey,
        "requireCompletion": bool(body.get("requireCompletion", False)),
    }
    anns = load(ANNS_PATH)
    anns.append(ann)
    save_atomic(ANNS_PATH, anns)
    return jsonify(ann), 201

@bp_api_announcements.delete("/api/announcements/<aid>")
def api_announcement_delete(aid: str):
    anns = load(ANNS_PATH)
    new_anns = [a for a in anns if str(a.get("id")) != str(aid)]
    if len(new_anns) == len(anns):
        return jsonify({"ok": False, "error": "not found"}), 404
    save_atomic(ANNS_PATH, new_anns)

    stat = load(ANN_STATUS_PATH)
    changed = False
    for sid in list(stat.keys()):
        if aid in stat[sid]:
            del stat[sid][aid]
            changed = True
        if not stat[sid]:
            del stat[sid]
            changed = True
    if changed:
        save_atomic(ANN_STATUS_PATH, stat)
    return jsonify({"ok": True})

@bp_api_announcements.get("/api/announce-status")
def api_announce_status():
    sid = str(request.args.get("sid", ""))
    stat = load(ANN_STATUS_PATH)
    return jsonify(stat.get(sid, {}))

@bp_api_announcements.post("/api/announce-ack")
def api_announce_ack():
    body = request.get_json(force=True) or {}
    sid = str(body.get("sid") or "")
    aid = str(body.get("id") or "")
    if not sid or not aid:
        return jsonify({"ok": False, "error": "missing sid/id"}), 400
    stat = load(ANN_STATUS_PATH)
    stat.setdefault(sid, {}).setdefault(aid, {})
    stat[sid][aid]["acked"] = True
    save_atomic(ANN_STATUS_PATH, stat)
    return jsonify({"ok": True})

@bp_api_announcements.post("/api/announce-submit")
def api_announce_submit():
    body = _get_payload_json_or_form()
    sid = urllib.parse.unquote(str(body.get("sid") or ""))
    aid = str(body.get("id") or "")
    if not sid or not aid:
        return jsonify({"ok": False, "error": "missing sid/id"}), 400

    stat = load(ANN_STATUS_PATH)
    entry = stat.setdefault(sid, {}).setdefault(aid, {})

    if "pollAnswer" in body and body["pollAnswer"] is not None:
        entry["poll"] = body["pollAnswer"]
    if "surveyAnswers" in body and body["surveyAnswers"] is not None:
        entry["survey"] = body["surveyAnswers"]

    save_atomic(ANN_STATUS_PATH, stat)

    anns = load(ANNS_PATH)
    ann = next((a for a in anns if str(a.get("id")) == aid), None)
    if ann and ann.get("requireCompletion"):
        has_poll = bool(ann.get("poll") and isinstance(ann["poll"].get("options"), list))
        has_survey = bool(ann.get("survey") and isinstance(ann["survey"], list) and len(ann["survey"]) > 0)

        done = True
        if has_poll:
            ans = entry.get("poll")
            if ans is None or (isinstance(ans, list) and len(ans) == 0):
                done = False
        if has_survey:
            sv = entry.get("survey", {})
            for q in ann["survey"]:
                v = sv.get(q.get("id"))
                if v is None or (isinstance(v, list) and len(v) == 0) or (isinstance(v, str) and not v.strip()):
                    done = False
                    break
        if done:
            stat.setdefault(sid, {}).setdefault(aid, {})["acked"] = True
            save_atomic(ANN_STATUS_PATH, stat)

    return jsonify({"ok": True})
    