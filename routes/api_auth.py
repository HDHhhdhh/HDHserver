# routes/api_auth.py — 학생 로그인/자동로그인/아이디·비번 변경 + (계정ID -> 여러 SID 지원)
from __future__ import annotations

import os
import json
import secrets
import time
import pathlib
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import get_ident
from typing import Any, List, Optional

import jwt
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from core.person_identity import is_valid_person_id, normalized_text, same_person
from core.storage import file_lock, save_atomic

bp_api_auth = Blueprint("api_auth", __name__, url_prefix="/api/auth")

BASE = pathlib.Path(__file__).resolve().parents[1]  # project root (routes/..)
STU_PATH = BASE / "students.json"

# ✅ 계정 맵 (로그인ID -> pw_hash + sids[])
ACCT_PATH = BASE / "auth_accounts.json"

AUTH_SECRET = os.environ.get("AUTH_SECRET", "").strip()
if not AUTH_SECRET or AUTH_SECRET == "CHANGE_ME_AUTH_SECRET":
    AUTH_SECRET = secrets.token_urlsafe(32)
TOKEN_EXPIRE_SEC = 60 * 60 * 24 * 30  # 30일

# 알려진 학생/계정 로그인과 계정 변경에서 허용하는 서버 환경변수.
MASTER_PW = os.environ.get("MASTER_PW", "").strip()
_ACCOUNT_LEASE = ContextVar("legacy_auth_account_lease", default=None)


@contextmanager
def _account_lock():
    # Helpers inside one request reuse its lease; other writers still lock.
    held = _ACCOUNT_LEASE.get()
    owner = (os.getpid(), get_ident())
    if held is not None and held["active"] and held["path"] == ACCT_PATH and held["owner"] == owner:
        yield
        return
    with file_lock(ACCT_PATH):
        held = {"path": ACCT_PATH, "owner": owner, "active": True}
        token = _ACCOUNT_LEASE.set(held)
        try:
            yield
        finally:
            held["active"] = False
            _ACCOUNT_LEASE.reset(token)


def _account_transaction(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with _account_lock():
            return f(*args, **kwargs)
    return wrapper


def _load_json(path: pathlib.Path, default: Any):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


class AuthAccountStoreError(RuntimeError):
    pass


@bp_api_auth.errorhandler(AuthAccountStoreError)
def _account_store_unavailable(_error):
    return jsonify({"ok": False, "error": "account_store_unavailable"}), 503


@bp_api_auth.errorhandler(TimeoutError)
def _account_lock_timeout(_error):
    return jsonify({"ok": False, "error": "account_lock_timeout", "retryable": True}), 409


def _json_or_form() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    if request.form:
        for k in request.form:
            data[k] = request.form.get(k)
    return data


def _students_list() -> List[dict]:
    arr = _load_json(STU_PATH, [])
    return arr if isinstance(arr, list) else []


def _find_student_by_sid(sid: str) -> Optional[dict]:
    sid = str(sid or "").strip()
    if not sid:
        return None
    for s in _students_list():
        if str(s.get("id", "")).strip() == sid:
            return s
    return None


def _student_exists(sid: str) -> bool:
    return _find_student_by_sid(sid) is not None


def _find_students_by_name(name: str) -> List[dict]:
    name = str(name or "").strip()
    if not name:
        return []
    out = []
    for s in _students_list():
        if str(s.get("name") or "").strip() == name:
            out.append(s)
    return out


def _load_acct_map() -> dict:
    """
    auth_accounts.json:
    {
      "전강우": {"pw_hash":"...", "sids":["전강우334","전강우282"]},
      ...
    }
    """
    try:
        m = json.loads(ACCT_PATH.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthAccountStoreError("unreadable_accounts") from exc
    if not isinstance(m, dict) or any(not isinstance(row, dict) for row in m.values()):
        raise AuthAccountStoreError("malformed_accounts")
    if any("legacy_session_id" in row and
           (not isinstance(row["legacy_session_id"], str) or not row["legacy_session_id"])
           for row in m.values()):
        raise AuthAccountStoreError("malformed_account_session")
    return m


def _save_acct_map(m: dict) -> None:
    try:
        save_atomic(ACCT_PATH, m, mirror=False)
    except OSError as exc:
        raise AuthAccountStoreError("accounts_save_failed") from exc


def _normalize_id(x: str) -> str:
    return str(x or "").strip()


def _school_key_for_student(s: dict) -> str:
    return str(
        s.get("school")
        or s.get("highSchool")
        or s.get("middleSchool")
        or ""
    ).strip()


def _dedup_key_for_student(s: dict) -> str:
    person_id = normalized_text(s.get("personId"))
    if is_valid_person_id(person_id):
        return f"personId||{person_id}"
    # ✅ 같은 사람 묶기 기준: name + school + grade(있으면)
    name = str(s.get("name") or "").strip()
    school = _school_key_for_student(s)
    grade = str(s.get("grade") or "").strip()
    return f"{name}||{school}||{grade}"


def _group_students_for_same_person(base: dict) -> tuple[List[dict], str]:
    if not isinstance(base, dict):
        return [], "none"

    students = _students_list()
    identity_mode = same_person(base, base)
    if identity_mode is not None:
        linked = [student for student in students if same_person(base, student) is True]
        return linked, "person_id" if linked else "none"

    strict_key = _dedup_key_for_student(base)
    strict = [s for s in students if _dedup_key_for_student(s) == strict_key]
    if len(strict) > 1:
        return strict, "strict"

    # 학년만 달라진 복제본은 name+school까지 완화해서 같은 학생으로 묶는다.
    name = str(base.get("name") or "").strip()
    school = _school_key_for_student(base)
    if len(strict) == 1 and name and school:
        loose = []
        for s in students:
            if str(s.get("name") or "").strip() != name:
                continue
            if _school_key_for_student(s) != school:
                continue
            loose.append(s)
        if len(loose) > 1:
            return loose, "school_fallback"

    return strict, "strict" if strict else "none"


def _group_sids_for_same_person(base_sid: str) -> List[str]:
    """
    base_sid(예: 전강우334) 를 기준으로 같은 사람의 모든 SID를 찾는다.
    """
    base = _find_student_by_sid(base_sid)
    if not base:
        return []

    group, _ = _group_students_for_same_person(base)
    out: List[str] = []
    seen = set()
    for s in group:
        sid = str(s.get("id") or "").strip()
        if sid and sid not in seen:
            out.append(sid)
            seen.add(sid)
    return out


def _preferred_sid_for_same_person(base_sid: str) -> str:
    base_sid = _normalize_id(base_sid)
    base = _find_student_by_sid(base_sid)
    if not base:
        return base_sid

    group, mode = _group_students_for_same_person(base)
    if mode == "school_fallback":
        # 느슨한 fallback으로 묶였으면 가장 최근에 생긴 SID를 우선으로 본다.
        for s in reversed(group):
            sid = str(s.get("id") or "").strip()
            if sid:
                return sid

    if base_sid and any(str(s.get("id") or "").strip() == base_sid for s in group):
        return base_sid

    for s in group:
        sid = str(s.get("id") or "").strip()
        if sid:
            return sid

    return base_sid


def _curris_payload_from_sids(sids: List[str]) -> List[dict]:
    """
    [{cur:"미적분1", sid:"용해은550"}, ...]
    """
    out = []
    for sid in sids:
        st = _find_student_by_sid(sid)
        if not st:
            continue
        cur = str(st.get("curriculum") or "").strip()
        if not cur:
            continue
        out.append({"cur": cur, "sid": sid})
    out.sort(key=lambda x: (x.get("cur") or "", x.get("sid") or ""))
    return out


def _issue_token(sid: str, aid: str, sids: List[str], *, session_id: str | None = None) -> str:
    now = int(time.time())
    payload = {
        "sid": sid,      # ✅ 현재 선택된 학생 SID
        "aid": aid,      # ✅ 계정 ID(로그인 아이디)
        "sids": sids,    # ✅ 접근 가능한 SID 목록
        "iat": now,
        "exp": now + TOKEN_EXPIRE_SEC,
    }
    if session_id is not None:
        payload["account_session"] = session_id
    return jwt.encode(payload, AUTH_SECRET, algorithm="HS256")


def _issue_account_token(sid: str, aid: str, sids: List[str]) -> str:
    record = _load_acct_map()[aid]
    return _issue_token(sid, aid, sids, session_id=record.get("legacy_session_id"))


def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1].strip()
        if not token:
            return jsonify({"ok": False, "error": "missing token"}), 401

        payload = _decode_token(token)
        if not payload or not payload.get("sid"):
            return jsonify({"ok": False, "error": "bad token"}), 401

        with _account_lock():
            aid = str(payload.get("aid") or payload.get("sid") or "")
            record = _load_acct_map().get(aid)
            if record is None or payload.get("account_session") != record.get("legacy_session_id"):
                return jsonify({"ok": False, "error": "bad token"}), 401
            request._sid = str(payload.get("sid") or "")
            request._aid = aid
            request._sids = payload.get("sids") if isinstance(payload.get("sids"), list) else []
            return f(*args, **kwargs)
    return wrapper


def _ensure_account_in_map(m: dict, aid: str, *, base_sid_for_link: Optional[str] = None) -> bool:
    if aid in m:
        if not isinstance(m[aid].get("sids"), list):
            m[aid]["sids"] = []
            return True
        return False

    sids: List[str] = []
    if base_sid_for_link:
        sids = _group_sids_for_same_person(base_sid_for_link)

    m[aid] = {
        "pw_hash": generate_password_hash("1234"),
        "sids": sids,
        "legacy_session_id": secrets.token_urlsafe(32),
    }
    return True


def _ensure_account(aid: str, *, base_sid_for_link: Optional[str] = None) -> None:
    aid = _normalize_id(aid)
    if not aid:
        return
    with _account_lock():
        m = _load_acct_map()
        if _ensure_account_in_map(m, aid, base_sid_for_link=base_sid_for_link):
            _save_acct_map(m)


def _find_account_by_sid(m: dict, sid: str) -> Optional[str]:
    sid = str(sid or "").strip()
    if not sid:
        return None
    for aid, ent in (m or {}).items():
        sids = ent.get("sids")
        if isinstance(sids, list) and sid in sids:
            return aid
    return None


def _prune_duplicate_accounts(m: dict, keep_aid: str, sids: List[str]) -> None:
    """
    같은 sids를 가진 중복 계정(레거시 잔재 포함)을 삭제한다.
    keep_aid만 남김.
    """
    keep_aid = str(keep_aid or "").strip()
    keep_set = set(str(x).strip() for x in (sids or []) if str(x).strip())

    dead = []
    for aid, ent in (m or {}).items():
        if aid == keep_aid:
            continue
        their = ent.get("sids")
        if not isinstance(their, list):
            continue
        their_set = set(str(x).strip() for x in their if str(x).strip())
        if their_set and their_set == keep_set:
            dead.append(aid)

    for aid in dead:
        m.pop(aid, None)


def _master_pw_ok(pw: str) -> bool:
    pw = _normalize_id(pw)
    return bool(MASTER_PW) and pw == MASTER_PW


def _refresh_and_persist_account_sids(aid: str, base_sid: str) -> List[str]:
    """
    ✅ 핵심 FIX:
    - 현재 base_sid 기준으로 같은 사람의 모든 SID를 다시 묶어온다(새 커리/새 SID 자동 반영)
    - auth_accounts.json에 저장해서 다음 로그인/자동로그인에서도 유지
    """
    aid = _normalize_id(aid)
    base_sid = _normalize_id(base_sid)
    if not aid or not base_sid or not _student_exists(base_sid):
        return []

    fresh = [x for x in _group_sids_for_same_person(base_sid) if _student_exists(x)]
    if base_sid not in fresh:
        fresh.insert(0, base_sid)

    with _account_lock():
        m = _load_acct_map()
        _ensure_account_in_map(m, aid, base_sid_for_link=base_sid)
        ent = m[aid]
        ent["sids"] = fresh
        _prune_duplicate_accounts(m, keep_aid=aid, sids=fresh)
        _save_acct_map(m)

    return fresh


def _recover_sids_from_account_id(aid: str) -> List[str]:
    """
    계정에 연결된 sids가 전부 사라진 경우(퇴원/재등록 등),
    account id == 학생 이름인 케이스만 안전하게 자동 복구한다.
    - 이름이 여러 사람으로 나뉘면(학교/학년 그룹 2개 이상) 자동 복구하지 않음.
    """
    aid = _normalize_id(aid)
    if not aid:
        return []

    same = _find_students_by_name(aid)
    if not same:
        return []

    groups = {}
    for s in same:
        key = _dedup_key_for_student(s)
        groups.setdefault(key, []).append(s)

    if len(groups) != 1:
        school_groups = {}
        for s in same:
            school = _school_key_for_student(s)
            if not school:
                continue
            school_groups.setdefault(f"{aid}||{school}", []).append(s)
        if len(school_groups) != 1:
            return []
        only_group = next(iter(school_groups.values()), [])
    else:
        only_group = next(iter(groups.values()), [])

    base_sid = str((only_group[-1] or {}).get("id") or "").strip()
    if not base_sid:
        return []

    return _refresh_and_persist_account_sids(aid, base_sid)


@bp_api_auth.post("/login")
@_account_transaction
def login():
    """이름은 기존의 첫 그룹 선택을 유지하고, 변경 ID는 현재 계정으로 로그인한다."""
    data = _json_or_form()
    login_id = _normalize_id(data.get("id") or data.get("sid") or "")
    pw = _normalize_id(data.get("password") or data.get("pw") or "")

    if not login_id or not pw:
        return jsonify({"ok": False, "error": "missing id/password"}), 400

    m = _load_acct_map()

    # 1) ✅ 계정ID로 로그인
    if login_id in m:
        if not _master_pw_ok(pw):
            pw_hash = (m.get(login_id) or {}).get("pw_hash", "")
            if not pw_hash or not check_password_hash(pw_hash, pw):
                return jsonify({"ok": False, "error": "bad password"}), 401

        sids = (m.get(login_id) or {}).get("sids") or []
        if not isinstance(sids, list):
            sids = []

        sids = [sid for sid in sids if _student_exists(sid)]
        if not sids:
            # 퇴원/재등록으로 sid가 바뀐 케이스 자동 복구 시도
            sids = _recover_sids_from_account_id(login_id)
        if not sids:
            return jsonify({"ok": False, "error": "no linked sids"}), 409

        # ✅ FIX: 로그인할 때마다 최신 SID 목록으로 갱신(새 커리 자동 반영)
        base_sid = sids[0]
        sids = _refresh_and_persist_account_sids(login_id, base_sid)
        if not sids:
            return jsonify({"ok": False, "error": "no linked sids"}), 409

        sid = _preferred_sid_for_same_person(base_sid)
        if sid not in sids:
            sid = sids[0]
        token = _issue_account_token(sid=sid, aid=login_id, sids=sids)
        return jsonify({
            "ok": True,
            "sid": sid,
            "aid": login_id,
            "token": token,
            "curris": _curris_payload_from_sids(sids),
        })

    # 이름 로그인도 아래 계정·비밀번호 검증을 거친다.
    same = _find_students_by_name(login_id)
    if not same:
        return jsonify({"ok": False, "error": "unknown id"}), 401

    groups = {}
    for s in same:
        k = _dedup_key_for_student(s)
        groups.setdefault(k, []).append(s)

    # 결정: key 정렬 후 첫 그룹 (재현 가능)
    keys = sorted(list(groups.keys()))
    only_group = groups[keys[0]] if keys else same

    base_sid = str((only_group[0] or {}).get("id") or "").strip()
    if not base_sid or not _student_exists(base_sid):
        return jsonify({"ok": False, "error": "unknown id"}), 401

    # ✅ base_sid가 이미 다른 계정에 묶여있으면: 그 계정으로 로그인 시도
    already = _find_account_by_sid(m, base_sid)
    if already and already in m:
        if not _master_pw_ok(pw):
            pw_hash = (m.get(already) or {}).get("pw_hash", "")
            if not pw_hash or not check_password_hash(pw_hash, pw):
                return jsonify({"ok": False, "error": "bad password"}), 401

        # ✅ FIX: 이 계정도 항상 최신으로 갱신
        sids = _refresh_and_persist_account_sids(already, base_sid)
        if not sids:
            return jsonify({"ok": False, "error": "no linked sids"}), 409

        sid = _preferred_sid_for_same_person(base_sid)
        if sid not in sids:
            sid = base_sid if base_sid in sids else sids[0]
        token = _issue_account_token(sid=sid, aid=already, sids=sids)
        return jsonify({
            "ok": True,
            "sid": sid,
            "aid": already,
            "token": token,
            "curris": _curris_payload_from_sids(sids),
        })

    # ✅ 계정ID는 "입력한 이름" 그대로 생성
    _ensure_account(login_id, base_sid_for_link=base_sid)
    m = _load_acct_map()

    if not _master_pw_ok(pw):
        pw_hash = (m.get(login_id) or {}).get("pw_hash", "")
        if not pw_hash or not check_password_hash(pw_hash, pw):
            return jsonify({"ok": False, "error": "bad password"}), 401

    # ✅ FIX: 생성 직후에도 최신으로 갱신/저장
    sids = _refresh_and_persist_account_sids(login_id, base_sid)
    if not sids:
        return jsonify({"ok": False, "error": "no linked sids"}), 409

    sid = _preferred_sid_for_same_person(base_sid)
    if sid not in sids:
        sid = base_sid if base_sid in sids else sids[0]

    token = _issue_account_token(sid=sid, aid=login_id, sids=sids)
    return jsonify({
        "ok": True,
        "sid": sid,
        "aid": login_id,
        "token": token,
        "curris": _curris_payload_from_sids(sids),
    })


@bp_api_auth.get("/me")
@require_auth
def me():
    sid = getattr(request, "_sid", "")
    aid = getattr(request, "_aid", "")
    sids = getattr(request, "_sids", [])

    if not _student_exists(sid):
        recovered = _recover_sids_from_account_id(aid or sid)
        if not recovered:
            return jsonify({"ok": False, "error": "unknown sid"}), 401
        sid = _preferred_sid_for_same_person(recovered[0])
        if sid not in recovered:
            sid = recovered[0]
        sids = recovered

    aid = aid or sid

    # ✅ FIX: 자동로그인(me)에서도 항상 최신으로 갱신 (새 커리/새 SID 즉시 반영)
    fresh = _refresh_and_persist_account_sids(aid, sid)
    if fresh:
        sids = fresh
        preferred_sid = _preferred_sid_for_same_person(sid)
        if preferred_sid in sids:
            sid = preferred_sid
    else:
        if not isinstance(sids, list) or not sids:
            sids = [sid]
        sids = [x for x in sids if _student_exists(x)]
        if sid not in sids:
            sids = [sid] + sids

    return jsonify({
        "ok": True,
        "sid": sid,
        "aid": aid,
        "curris": _curris_payload_from_sids(sids),
    })


@bp_api_auth.post("/switch")
@require_auth
def switch():
    """
    ✅ 계정 토큰으로, 다른 SID(다른 커리)로 토큰을 바꿔준다.
    body: { "sid": "전강우282" }
    """
    data = _json_or_form()
    target = _normalize_id(data.get("sid") or data.get("targetSid") or "")
    if not target:
        return jsonify({"ok": False, "error": "missing sid"}), 400

    cur_sid = getattr(request, "_sid", "")
    aid = getattr(request, "_aid", "") or cur_sid

    # ✅ FIX: switch 직전에도 최신 sids로 갱신
    sids = _refresh_and_persist_account_sids(aid, cur_sid)
    if not sids:
        sids = getattr(request, "_sids", []) or [cur_sid]

    if target not in sids:
        return jsonify({"ok": False, "error": "forbidden sid"}), 403
    if not _student_exists(target):
        return jsonify({"ok": False, "error": "unknown sid"}), 404

    token = _issue_account_token(sid=target, aid=aid, sids=sids)
    return jsonify({"ok": True, "sid": target, "aid": aid, "token": token})


@bp_api_auth.post("/change")
@require_auth
def change():
    sid = getattr(request, "_sid", "")
    aid = getattr(request, "_aid", "") or sid

    data = _json_or_form()

    cur_pw = _normalize_id(data.get("curPw") or data.get("cur_pw") or "")
    new_id = _normalize_id(data.get("newId") or data.get("new_id") or "")
    new_pw = _normalize_id(data.get("newPw") or data.get("new_pw") or "")

    if not cur_pw:
        return jsonify({"ok": False, "error": "missing curPw"}), 400

    with _account_lock():
        m = _load_acct_map()
        _ensure_account_in_map(m, aid, base_sid_for_link=sid)

        if not _master_pw_ok(cur_pw):
            cur_hash = m[aid].get("pw_hash", "")
            if not cur_hash or not check_password_hash(cur_hash, cur_pw):
                return jsonify({"ok": False, "error": "bad password"}), 401

        if new_id and new_id != aid:
            if new_id in m:
                return jsonify({"ok": False, "error": "id taken"}), 409
            m[new_id] = m.pop(aid)
            aid = new_id
            m[aid]["legacy_session_id"] = secrets.token_urlsafe(32)

        if new_pw:
            m[aid]["pw_hash"] = generate_password_hash(new_pw)

        refreshed = [x for x in _group_sids_for_same_person(sid) if _student_exists(x)]
        if sid not in refreshed:
            refreshed.insert(0, sid)
        m[aid]["sids"] = refreshed
        _prune_duplicate_accounts(m, keep_aid=aid, sids=refreshed)
        _save_acct_map(m)

    token = _issue_account_token(sid=sid, aid=aid, sids=m[aid]["sids"])
    return jsonify({"ok": True, "sid": sid, "aid": aid, "token": token})
