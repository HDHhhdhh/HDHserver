from __future__ import annotations

import datetime as dt
import mimetypes
import os
import pathlib
import re
import shutil
import time
import uuid
from typing import Any

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from core.paths import ANN_STATUS_PATH, ANNS_PATH, FILES_DIR, STU_PATH, VID_PATH
from core.student_board_projection import student_board_announcement_visible
from core.student_notification_events import deterministic_event_id
from core.storage import file_lock, load, save_atomic, utc_now_isoz

bp_api_announcements = Blueprint("api_announcements", __name__)

ANN_TTL_SECONDS = 4 * 60 * 60
TARGET_MODES = {"slot1", "slot2", "today", "all", "curriculum", "grade", "direct"}
ANN_KINDS = {"announcement", "survey", "video"}
VIDEO_MID_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
SURVEY_STATUSES = {"draft", "public", "closed"}
SURVEY_QUESTION_TYPES = {"single", "multiple", "short", "long"}
ANN_IMAGE_DIR = FILES_DIR / "announcements"
ANN_IMAGE_MAX_BYTES = 8 * 1024 * 1024
ANN_REPLY_LIMIT = 3
ANN_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ANN_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_time(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _expires_at_for(ann: dict[str, Any]) -> dt.datetime:
    explicit = _parse_time(ann.get("expiresAt"))
    if explicit is not None:
        return explicit
    created = _parse_time(ann.get("createdAt")) or _now()
    return created + dt.timedelta(seconds=ANN_TTL_SECONDS)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _image_source_dir() -> pathlib.Path:
    env = str(os.environ.get("ANNOUNCEMENT_IMAGE_SOURCE_DIR") or "").strip()
    candidates = []
    if env:
        candidates.append(pathlib.Path(env))
    candidates.extend([
        pathlib.Path("C:/Downloads"),
        pathlib.Path("C:/downloads"),
        pathlib.Path.home() / "Downloads",
    ])
    for path in candidates:
        try:
            if path.exists() and path.is_dir():
                return path
        except OSError:
            continue
    return pathlib.Path("C:/Downloads")


def _image_source_label(path: pathlib.Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _safe_source_image(rel: str) -> pathlib.Path:
    root = _image_source_dir().resolve()
    candidate = (root / str(rel or "")).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("invalid path")
    if not candidate.is_file():
        raise ValueError("file not found")
    if candidate.suffix.lower() not in ANN_IMAGE_EXTS:
        raise ValueError("unsupported image")
    return candidate


def _ann_image_public_path(filename: str) -> str:
    return f"announcements/{filename}"


def _ann_image_payload(path: pathlib.Path, original_name: str = "") -> dict[str, Any]:
    public_path = _ann_image_public_path(path.name)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "name": path.name,
        "originalName": original_name or path.name,
        "path": public_path,
        "url": f"/files/{public_path}",
        "mime": mime,
        "size": size,
    }


def _unique_image_name(original_name: str) -> str:
    raw_name = secure_filename(original_name or "announcement-image")
    suffix = pathlib.Path(raw_name).suffix.lower()
    if suffix not in ANN_IMAGE_EXTS:
        suffix = ".png"
    stem = pathlib.Path(raw_name).stem or "announcement-image"
    stamp = int(time.time() * 1000)
    return f"{stamp}_{uuid.uuid4().hex[:8]}_{stem[:44]}{suffix}"


def _save_announcement_image(file_storage) -> dict[str, Any]:
    filename = str(file_storage.filename or "").strip()
    if not filename:
        raise ValueError("파일 이름이 없습니다.")
    suffix = pathlib.Path(filename).suffix.lower()
    if suffix not in ANN_IMAGE_EXTS:
        raise ValueError("이미지 파일만 첨부할 수 있습니다.")
    mime = str(file_storage.mimetype or mimetypes.guess_type(filename)[0] or "")
    if mime and mime not in ANN_IMAGE_MIMES:
        raise ValueError("지원하지 않는 이미지 형식입니다.")
    content_length = int(getattr(file_storage, "content_length", 0) or 0)
    if content_length > ANN_IMAGE_MAX_BYTES:
        raise ValueError("이미지는 8MB 이하만 첨부할 수 있습니다.")

    ANN_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ANN_IMAGE_DIR / _unique_image_name(filename)
    file_storage.save(dst)
    try:
        size = dst.stat().st_size
    except OSError:
        size = 0
    if size <= 0:
        try:
            dst.unlink()
        except OSError:
            pass
        raise ValueError("빈 파일은 첨부할 수 없습니다.")
    if size > ANN_IMAGE_MAX_BYTES:
        try:
            dst.unlink()
        except OSError:
            pass
        raise ValueError("이미지는 8MB 이하만 첨부할 수 있습니다.")
    return _ann_image_payload(dst, original_name=filename)


def _copy_source_image(rel: str) -> dict[str, Any]:
    src = _safe_source_image(rel)
    if src.stat().st_size > ANN_IMAGE_MAX_BYTES:
        raise ValueError("이미지는 8MB 이하만 첨부할 수 있습니다.")
    ANN_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ANN_IMAGE_DIR / _unique_image_name(src.name)
    shutil.copy2(src, dst)
    return _ann_image_payload(dst, original_name=src.name)


def _normalize_image(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip().replace("\\", "/")
    path = str(raw.get("path") or "").strip().replace("\\", "/").lstrip("/")
    if url.startswith("/files/"):
        path = url.split("/files/", 1)[1].lstrip("/")
    if not path.startswith("announcements/"):
        return None
    if ".." in pathlib.PurePosixPath(path).parts:
        return None
    name = pathlib.PurePosixPath(path).name
    if pathlib.PurePosixPath(name).suffix.lower() not in ANN_IMAGE_EXTS:
        return None
    return {
        "name": str(raw.get("name") or name).strip() or name,
        "originalName": str(raw.get("originalName") or raw.get("name") or name).strip() or name,
        "path": path,
        "url": f"/files/{path}",
        "mime": str(raw.get("mime") or mimetypes.guess_type(name)[0] or "").strip(),
        "size": int(raw.get("size") or 0),
    }


def _normalize_images(raw: Any, fallback: Any = None) -> list[dict[str, Any]]:
    values = raw if isinstance(raw, list) else []
    images: list[dict[str, Any]] = []
    for item in values:
        image = _normalize_image(item)
        if image:
            images.append(image)
    if not images:
        image = _normalize_image(fallback)
        if image:
            images.append(image)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for image in images[:10]:
        key = str(image.get("path") or image.get("url") or image.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(image)
    return unique


def _safe_id(value: Any, prefix: str) -> str:
    raw = str(value or "").strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-"})
    return cleaned[:80] or f"{prefix}_{uuid.uuid4().hex[:10]}"


def _normalize_survey(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    if raw in (None, ""):
        return None, None
    if not isinstance(raw, dict):
        return None, "survey must be an object"

    status = str(raw.get("status") or "public").strip().lower()
    if status not in SURVEY_STATUSES:
        return None, "invalid survey status"

    questions_raw = raw.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        return None, "survey questions required"

    questions: list[dict[str, Any]] = []
    for q_idx, item in enumerate(questions_raw, start=1):
        if not isinstance(item, dict):
            return None, "invalid survey question"
        q_type = str(item.get("type") or "single").strip().lower()
        if q_type not in SURVEY_QUESTION_TYPES:
            return None, "invalid survey question type"
        text = str(item.get("text") or item.get("label") or "").strip()
        if not text:
            return None, "survey question text required"

        question = {
            "id": _safe_id(item.get("id") or f"q{q_idx}", f"q{q_idx}"),
            "text": text[:400],
            "type": q_type,
            "required": bool(item.get("required", True)),
            "options": [],
        }

        if q_type in {"single", "multiple"}:
            options_raw = item.get("options")
            if not isinstance(options_raw, list):
                options_raw = []
            options: list[dict[str, str]] = []
            seen_option_ids: set[str] = set()
            for opt_idx, option in enumerate(options_raw, start=1):
                if isinstance(option, dict):
                    opt_text = str(option.get("text") or option.get("label") or "").strip()
                    opt_id = _safe_id(option.get("id") or f"o{opt_idx}", f"o{opt_idx}")
                else:
                    opt_text = str(option or "").strip()
                    opt_id = f"o{opt_idx}"
                if not opt_text:
                    continue
                if opt_id in seen_option_ids:
                    opt_id = f"{opt_id}_{uuid.uuid4().hex[:4]}"
                seen_option_ids.add(opt_id)
                options.append({"id": opt_id, "text": opt_text[:240]})
            if len(options) < 2:
                return None, "choice questions need at least 2 options"
            question["options"] = options

        questions.append(question)

    return {
        "status": status,
        "anonymous": bool(raw.get("anonymous")),
        "allowMultiple": bool(raw.get("allowMultiple")),
        "questions": questions,
    }, None


def _survey_is_public(ann: dict[str, Any]) -> bool:
    survey, _ = _normalize_survey(ann.get("survey"))
    return bool(survey and survey.get("status") == "public")


def _survey_requires_completion(ann: dict[str, Any]) -> bool:
    survey, _ = _normalize_survey(ann.get("survey"))
    return bool(survey and survey.get("status") == "public" and ann.get("requireCompletion", True))


def _entry_has_survey_submission(entry: dict[str, Any]) -> bool:
    if entry.get("surveySubmittedAt") and isinstance(entry.get("surveyAnswers"), dict):
        return True
    rows = entry.get("surveyResponses")
    return isinstance(rows, list) and any(isinstance(row, dict) and isinstance(row.get("answers"), dict) for row in rows)


def _validate_survey_answers(survey: dict[str, Any], raw_answers: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw_answers, dict):
        return None, "survey answers required"

    answers: dict[str, Any] = {}
    for question in survey.get("questions") or []:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id") or "").strip()
        q_type = str(question.get("type") or "").strip()
        required = bool(question.get("required"))
        raw_value = raw_answers.get(qid)
        option_ids = {
            str(option.get("id") or "")
            for option in (question.get("options") or [])
            if isinstance(option, dict)
        }

        if q_type == "single":
            value = str(raw_value or "").strip()
            if not value:
                if required:
                    return None, "required survey answer missing"
                continue
            if value not in option_ids:
                return None, "invalid survey option"
            answers[qid] = value
            continue

        if q_type == "multiple":
            values_raw = raw_value if isinstance(raw_value, list) else []
            values: list[str] = []
            seen: set[str] = set()
            for value_raw in values_raw:
                value = str(value_raw or "").strip()
                if not value or value in seen:
                    continue
                if value not in option_ids:
                    return None, "invalid survey option"
                seen.add(value)
                values.append(value)
            if required and not values:
                return None, "required survey answer missing"
            if values:
                answers[qid] = values
            continue

        if q_type in {"short", "long"}:
            value = str(raw_value or "").strip()
            if required and not value:
                return None, "required survey answer missing"
            if value:
                answers[qid] = value[:2000]

    return answers, None


def _as_ann_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def _as_status_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for sid, by_ann in value.items():
        if isinstance(by_ann, dict):
            out[str(sid)] = {str(aid): entry for aid, entry in by_ann.items() if isinstance(entry, dict)}
    return out


def _load_students() -> list[dict[str, Any]]:
    data = load(STU_PATH)
    return data if isinstance(data, list) else []


def _student_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for stu in _load_students():
        if not isinstance(stu, dict):
            continue
        sid = str(stu.get("id") or "").strip()
        if sid:
            out[sid] = stu
    return out


def _student_name(students: dict[str, dict[str, Any]], sid: str) -> str:
    stu = students.get(str(sid)) or {}
    return str(stu.get("name") or sid).strip() or str(sid)


def _admin_reply_display_name(student_name: str, anonymous: bool) -> str:
    name = str(student_name or "").strip()
    return f"익명({name})" if anonymous else name


def _normalize_sids(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else []
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        sid = str(value or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _normalize_snapshot(raw: Any, target_sids: set[str]) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("sid") or item.get("id") or "").strip()
        if not sid or sid not in target_sids or sid in seen:
            continue
        seen.add(sid)
        rows.append({
            "sid": sid,
            "name": str(item.get("name") or "").strip(),
            "slot": str(item.get("slot") or "").strip(),
            "school": str(item.get("school") or "").strip(),
            "grade": str(item.get("grade") or "").strip(),
            "curriculum": str(item.get("curriculum") or "").strip(),
            "subCurriculum": str(item.get("subCurriculum") or "").strip(),
            "level": str(item.get("level") or "").strip(),
        })
    return rows


def _targeted(ann: dict[str, Any], sid: str) -> bool:
    sid_s = str(sid)
    target_sids = ann.get("targetSids")
    if isinstance(target_sids, list):
        return sid_s in {str(x) for x in target_sids}
    return False


def _safe_student_announcement(ann: dict[str, Any]) -> dict[str, Any]:
    survey, _ = _normalize_survey(ann.get("survey"))
    images = _normalize_images(ann.get("images"), ann.get("image"))
    row = {
        "id": ann.get("id"),
        "kind": ann.get("kind") or ("survey" if survey else "announcement"),
        "title": ann.get("title") or "공지",
        "content": ann.get("content") or "",
        "image": images[0] if images else None,
        "images": images,
        "createdAt": ann.get("createdAt"),
        "expiresAt": ann.get("expiresAt"),
        "targetLabel": ann.get("targetLabel") or "",
        "requireCompletion": bool(ann.get("requireCompletion", True)),
        "notificationEventId": None,
    }
    announcement_id = str(ann.get("id") or "").strip()
    if announcement_id:
        try:
            row["notificationEventId"] = deterministic_event_id("announcement_published", announcement_id)
        except ValueError:
            pass
    if survey and survey.get("status") == "public":
        row["survey"] = survey
    return row


def _student_visible(ann: dict[str, Any], sid: str, *, now: dt.datetime | None = None) -> bool:
    return student_board_announcement_visible(ann, str(sid), now or _now())


def _known_video_mid(value: Any) -> str:
    mid = str(value or "").strip()
    if not VIDEO_MID_RE.fullmatch(mid):
        return ""
    videos = load(VID_PATH)
    if not isinstance(videos, list):
        return ""
    return mid if any(isinstance(row, dict) and str(row.get("mid") or "").strip() == mid for row in videos) else ""


def _student_can_access_announcement_image(sid: str, image_path: str) -> bool:
    requested = _normalize_image({"path": image_path})
    if requested is None:
        return False
    expected_path = requested["path"]
    now = _now()
    for ann in _load_active_announcements():
        if not _student_visible(ann, sid, now=now):
            continue
        images = _normalize_images(ann.get("images"), ann.get("image"))
        if any(image.get("path") == expected_path for image in images):
            return True
    return False


def _push_target_sids(ann: dict[str, Any]) -> list[str]:
    """Select only targets for a currently visible saved announcement."""
    now = _now()
    target_sids = ann.get("targetSids")
    if not isinstance(target_sids, list):
        return []
    return [
        sid for sid in dict.fromkeys(target_sids)
        if isinstance(sid, str) and _student_visible(ann, sid, now=now)
    ]


def _enqueue_saved_announcement(ann: dict[str, Any]) -> None:
    """Best-effort post-commit seam; Push failures never undo announcement data."""
    targets = _push_target_sids(ann)
    if not targets:
        return
    try:
        from routes.api_student_push import enqueue_announcement

        enqueue_announcement(str(ann.get("id") or ""), targets)
    except Exception:  # noqa: BROAD_EXCEPT_OK - durable announcement remains authoritative
        return


def _prune_status(active_ids: set[str]) -> None:
    with file_lock(ANN_STATUS_PATH):
        status = _as_status_map(load(ANN_STATUS_PATH))
        changed = False
        for sid in list(status.keys()):
            for aid in list(status[sid].keys()):
                if aid not in active_ids:
                    del status[sid][aid]
                    changed = True
            if not status[sid]:
                del status[sid]
                changed = True
        if changed:
            save_atomic(ANN_STATUS_PATH, status)


def _load_active_announcements(prune: bool = False) -> list[dict[str, Any]]:
    now = _now()
    with file_lock(ANNS_PATH):
        raw = load(ANNS_PATH)
        anns = _as_ann_list(raw)
        active: list[dict[str, Any]] = []
        changed = not isinstance(raw, list)

        for ann in anns:
            if not isinstance(ann.get("targetSids"), list):
                changed = True
                continue
            expires_at = _expires_at_for(ann)
            if expires_at <= now:
                changed = True
                continue
            if not ann.get("expiresAt"):
                ann = {**ann, "expiresAt": _iso(expires_at)}
                changed = True
            active.append(ann)

        if prune and changed:
            save_atomic(ANNS_PATH, active)

    if prune:
        _prune_status({str(a.get("id")) for a in active if a.get("id")})
    active.sort(key=lambda x: str(x.get("createdAt") or ""), reverse=True)
    return active


def _announcement_from_body(body: dict[str, Any], existing: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    existing = existing or {}
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    if not title or not content:
        return None, (jsonify({"ok": False, "error": "title/content required"}), 400)

    target_sids = _normalize_sids(body.get("targetSids") or body.get("targets"))
    if not target_sids:
        return None, (jsonify({"ok": False, "error": "targetSids required"}), 400)

    students = _student_map()
    known = set(students.keys())
    if known:
        target_sids = [sid for sid in target_sids if sid in known]
    if not target_sids:
        return None, (jsonify({"ok": False, "error": "no valid targets"}), 400)

    created_at = str(existing.get("createdAt") or body.get("createdAt") or utc_now_isoz())
    expires_at = _parse_time(body.get("expiresAt")) or ((_parse_time(created_at) or _now()) + dt.timedelta(seconds=ANN_TTL_SECONDS))
    target_mode = str(body.get("targetMode") or existing.get("targetMode") or "direct")
    if target_mode not in TARGET_MODES:
        target_mode = "direct"

    survey_raw = body.get("survey") if "survey" in body else existing.get("survey")
    survey, survey_error = _normalize_survey(survey_raw)
    if survey_error:
        return None, (jsonify({"ok": False, "error": survey_error}), 400)

    kind = str(body.get("kind") or existing.get("kind") or ("survey" if survey else "announcement")).strip().lower()
    if kind not in ANN_KINDS:
        kind = "survey" if survey else "announcement"
    if kind == "survey" and not survey:
        return None, (jsonify({"ok": False, "error": "survey required"}), 400)
    video_mid = ""
    if kind == "video":
        video_mid = _known_video_mid(body.get("videoMid") if "videoMid" in body else existing.get("videoMid"))
        if not video_mid:
            return None, (jsonify({"ok": False, "code": "invalid_video_mid"}), 400)
        survey = None

    target_set = set(target_sids)
    snapshot = _normalize_snapshot(body.get("targetSnapshot"), target_set)
    if not snapshot:
        snapshot = [{
            "sid": sid,
            "name": _student_name(students, sid),
            "slot": "",
            "school": str((students.get(sid) or {}).get("school") or "").strip(),
            "grade": str((students.get(sid) or {}).get("grade") or (students.get(sid) or {}).get("gradeLevel") or (students.get(sid) or {}).get("studentGrade") or (students.get(sid) or {}).get("학년") or "").strip(),
            "curriculum": str((students.get(sid) or {}).get("curriculum") or "").strip(),
            "subCurriculum": str((students.get(sid) or {}).get("subCurriculum") or "").strip(),
            "level": str((students.get(sid) or {}).get("level") or "").strip(),
        } for sid in target_sids]

    images = _normalize_images(
        body.get("images") if "images" in body else existing.get("images"),
        body.get("image") if "image" in body else existing.get("image"),
    )

    announcement = {
        "id": existing.get("id") or body.get("id") or f"ann_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
        "kind": kind,
        "title": title,
        "content": content,
        "image": images[0] if images else None,
        "images": images,
        "createdAt": created_at,
        "expiresAt": _iso(expires_at),
        "targetMode": target_mode,
        "targetLabel": str(body.get("targetLabel") or existing.get("targetLabel") or f"{len(target_sids)}명").strip(),
        "targetSids": target_sids,
        "targetSnapshot": snapshot,
        "survey": survey,
        "requireCompletion": bool(body.get("requireCompletion", existing.get("requireCompletion", True))),
    }
    if kind == "video":
        announcement["videoMid"] = video_mid
        announcement["requireCompletion"] = False
    return announcement, None


def _reply_rows_from_status_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_replies = entry.get("replies")

    if isinstance(raw_replies, list):
        for item in raw_replies:
            if not isinstance(item, dict):
                continue
            reply = str(item.get("reply") or "").strip()
            if not reply:
                continue
            rows.append({
                "id": str(item.get("id") or ""),
                "reply": reply,
                "anonymous": bool(item.get("anonymous", entry.get("anonymous"))),
                "repliedAt": str(item.get("repliedAt") or item.get("createdAt") or ""),
            })

    legacy_reply = str(entry.get("reply") or "").strip()
    legacy_replied_at = str(entry.get("repliedAt") or "")
    if legacy_reply:
        duplicate = any(
            row.get("reply") == legacy_reply and row.get("repliedAt") == legacy_replied_at
            for row in rows
        )
        if not duplicate:
            rows.append({
                "id": "",
                "reply": legacy_reply,
                "anonymous": bool(entry.get("anonymous")),
                "repliedAt": legacy_replied_at,
            })

    return rows


def _survey_response_rows_from_status_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = entry.get("surveyResponses")
    if isinstance(raw_rows, list):
        for item in raw_rows:
            if not isinstance(item, dict) or not isinstance(item.get("answers"), dict):
                continue
            rows.append({
                "id": str(item.get("id") or ""),
                "answers": item.get("answers") or {},
                "anonymous": bool(item.get("anonymous")),
                "submittedAt": str(item.get("submittedAt") or ""),
            })

    legacy_answers = entry.get("surveyAnswers")
    if isinstance(legacy_answers, dict):
        legacy_submitted_at = str(entry.get("surveySubmittedAt") or "")
        duplicate = any(
            row.get("answers") == legacy_answers and row.get("submittedAt") == legacy_submitted_at
            for row in rows
        )
        if not duplicate:
            rows.append({
                "id": "",
                "answers": legacy_answers,
                "anonymous": bool(entry.get("surveyAnonymous")),
                "submittedAt": legacy_submitted_at,
            })
    return rows


def _survey_results_for_admin(
    survey: dict[str, Any],
    status: dict[str, dict[str, Any]],
    students: dict[str, dict[str, Any]],
    aid: str,
    target_sids: list[str],
) -> dict[str, Any]:
    submissions: list[dict[str, Any]] = []
    target_set = set(target_sids)

    for sid, by_ann in status.items():
        if target_set and sid not in target_set:
            continue
        entry = by_ann.get(aid) or {}
        for row in _survey_response_rows_from_status_entry(entry):
            anonymous = bool(survey.get("anonymous") or row.get("anonymous"))
            submissions.append({
                "id": row.get("id") or "",
                "sid": sid,
                "studentName": _student_name(students, sid),
                "displayName": _admin_reply_display_name(_student_name(students, sid), anonymous),
                "anonymous": anonymous,
                "submittedAt": row.get("submittedAt") or "",
                "answers": row.get("answers") or {},
            })

    submissions.sort(key=lambda x: str(x.get("submittedAt") or ""), reverse=True)
    submission_count = len(submissions)
    question_results: list[dict[str, Any]] = []

    for question in survey.get("questions") or []:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id") or "")
        q_type = str(question.get("type") or "")
        result: dict[str, Any] = {
            "id": qid,
            "text": question.get("text") or "",
            "type": q_type,
            "required": bool(question.get("required")),
            "responseCount": 0,
            "options": [],
            "answers": [],
        }

        if q_type in {"single", "multiple"}:
            counts: dict[str, int] = {}
            option_text: dict[str, str] = {}
            for option in question.get("options") or []:
                if not isinstance(option, dict):
                    continue
                oid = str(option.get("id") or "")
                counts[oid] = 0
                option_text[oid] = str(option.get("text") or "")

            answered = 0
            for submission in submissions:
                answer = (submission.get("answers") or {}).get(qid)
                if q_type == "single":
                    selected = [str(answer or "").strip()] if answer else []
                else:
                    selected = [str(value or "").strip() for value in answer] if isinstance(answer, list) else []
                selected = [value for value in selected if value in counts]
                if not selected:
                    continue
                answered += 1
                for value in selected:
                    counts[value] += 1

            result["responseCount"] = answered
            result["options"] = [
                {
                    "id": oid,
                    "text": option_text.get(oid) or oid,
                    "count": count,
                    "percent": round((count / submission_count) * 100, 1) if submission_count else 0,
                }
                for oid, count in counts.items()
            ]
        else:
            answers: list[dict[str, Any]] = []
            for submission in submissions:
                answer = str((submission.get("answers") or {}).get(qid) or "").strip()
                if not answer:
                    continue
                answers.append({
                    "sid": submission.get("sid") or "",
                    "displayName": submission.get("displayName") or "익명",
                    "answer": answer,
                    "submittedAt": submission.get("submittedAt") or "",
                })
            result["responseCount"] = len(answers)
            result["answers"] = answers

        question_results.append(result)

    return {
        "responseCount": submission_count,
        "submissions": submissions,
        "questions": question_results,
    }


def _summary_for_admin(anns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status = _as_status_map(load(ANN_STATUS_PATH))
    students = _student_map()
    video_catalog = load(VID_PATH)
    known_video_mids = {
        str(row.get("mid") or "").strip()
        for row in video_catalog if isinstance(video_catalog, list) and isinstance(row, dict)
        if VIDEO_MID_RE.fullmatch(str(row.get("mid") or "").strip())
    }
    rows: list[dict[str, Any]] = []

    for ann in anns:
        aid = str(ann.get("id") or "")
        target_sids = _normalize_sids(ann.get("targetSids"))
        target_set = set(target_sids)
        survey, _ = _normalize_survey(ann.get("survey"))
        kind = ann.get("kind") or ("survey" if survey else "announcement")
        read_count = 0
        replies: list[dict[str, Any]] = []

        for sid, by_ann in status.items():
            if target_set and sid not in target_set:
                continue
            entry = by_ann.get(aid) or {}
            if entry.get("acked"):
                read_count += 1
            for reply_row in _reply_rows_from_status_entry(entry):
                anonymous = bool(reply_row.get("anonymous"))
                student_name = _student_name(students, sid)
                replies.append({
                    "id": reply_row.get("id") or "",
                    "sid": sid,
                    "studentName": student_name,
                    "displayName": _admin_reply_display_name(student_name, anonymous),
                    "anonymous": anonymous,
                    "reply": reply_row.get("reply") or "",
                    "repliedAt": reply_row.get("repliedAt") or "",
                })

        replies.sort(key=lambda x: str(x.get("repliedAt") or ""), reverse=True)
        survey_results = _survey_results_for_admin(survey, status, students, aid, target_sids) if survey else None
        images = _normalize_images(ann.get("images"), ann.get("image"))
        row = {
            "id": aid,
            "kind": kind,
            "title": ann.get("title") or "공지",
            "content": ann.get("content") or "",
            "image": images[0] if images else None,
            "images": images,
            "survey": survey,
            "surveyResults": survey_results,
            "surveyResponseCount": survey_results.get("responseCount", 0) if survey_results else 0,
            "createdAt": ann.get("createdAt"),
            "expiresAt": ann.get("expiresAt"),
            "targetMode": ann.get("targetMode") or "direct",
            "targetLabel": ann.get("targetLabel") or f"{len(target_sids)}명",
            "targetCount": len(target_sids),
            "targetSids": target_sids,
            "targetSnapshot": ann.get("targetSnapshot") if isinstance(ann.get("targetSnapshot"), list) else [],
            "readCount": read_count,
            "replyCount": len(replies),
            "replies": replies,
        }
        video_mid = str(ann.get("videoMid") or "").strip()
        if kind == "video" and video_mid in known_video_mids:
            row["videoMid"] = video_mid
        rows.append(row)
    return rows


def _is_public_student_request() -> bool:
    return getattr(g, "student_app_public_request", False) is True


def _student_request_sid(caller_sid: Any) -> str:
    """Use only server-resolved session identity on the public host."""
    if _is_public_student_request():
        active_sid = getattr(g, "student_app_active_sid", None)
        return active_sid if isinstance(active_sid, str) else ""
    return str(caller_sid or "").strip()


@bp_api_announcements.route("/api/announcements", methods=["GET", "POST"])
def api_announcements():
    if request.method == "GET":
        anns = _load_active_announcements()
        sid = _student_request_sid(request.args.get("sid"))
        if _is_public_student_request() and not sid:
            return jsonify({"ok": False, "code": "unauthenticated"}), 401
        if sid:
            return jsonify([
                _safe_student_announcement(a)
                for a in anns
                if a.get("kind") != "video" and _student_visible(a, sid)
            ])
        return jsonify(anns)

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    ann, error = _announcement_from_body(body)
    if error:
        return error

    with file_lock(ANNS_PATH):
        anns = _as_ann_list(load(ANNS_PATH))
        now = _now()
        active = [
            a for a in anns
            if isinstance(a.get("targetSids"), list) and _expires_at_for(a) > now
        ]
        active.append(ann)
        save_atomic(ANNS_PATH, active)

    _prune_status({str(a.get("id")) for a in active if a.get("id")})
    _enqueue_saved_announcement(ann)
    return jsonify(ann), 201


@bp_api_announcements.post("/api/announcements/image")
def api_announcement_image_upload():
    image_file = request.files.get("file") or request.files.get("image")
    if image_file is None:
        return jsonify({"ok": False, "error": "no file"}), 400
    try:
        image = _save_announcement_image(image_file)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "image": image})


@bp_api_announcements.get("/api/announcements/image-sources")
def api_announcement_image_sources():
    root = _image_source_dir()
    files: list[dict[str, Any]] = []
    if root.exists() and root.is_dir():
        try:
            candidates = [
                path for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in ANN_IMAGE_EXTS
            ]
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            for path in candidates[:60]:
                stat = path.stat()
                files.append({
                    "name": path.name,
                    "rel": path.name,
                    "size": stat.st_size,
                    "modifiedAt": _iso(dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)),
                })
        except OSError:
            files = []
    return jsonify({
        "ok": True,
        "root": _image_source_label(root),
        "files": files,
        "maxBytes": ANN_IMAGE_MAX_BYTES,
    })


@bp_api_announcements.post("/api/announcements/image-from-downloads")
def api_announcement_image_from_downloads():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    rel = str(body.get("rel") or "").strip()
    if not rel:
        return jsonify({"ok": False, "error": "missing rel"}), 400
    try:
        image = _copy_source_image(rel)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "image": image})


@bp_api_announcements.put("/api/announcements/<aid>")
def api_announcement_update(aid: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}

    saved: dict[str, Any] | None = None
    with file_lock(ANNS_PATH):
        anns = _as_ann_list(load(ANNS_PATH))
        for idx, current in enumerate(anns):
            if str(current.get("id")) != str(aid):
                continue
            ann, error = _announcement_from_body(body, existing=current)
            if error:
                return error
            anns[idx] = ann
            save_atomic(ANNS_PATH, anns)
            saved = ann
            break
    if saved is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    _enqueue_saved_announcement(saved)
    return jsonify(saved)


@bp_api_announcements.delete("/api/announcements/<aid>")
def api_announcement_delete(aid: str):
    aid_s = str(aid)
    with file_lock(ANNS_PATH):
        anns = _as_ann_list(load(ANNS_PATH))
        next_anns = [a for a in anns if str(a.get("id")) != aid_s]
        if len(next_anns) == len(anns):
            return jsonify({"ok": False, "error": "not found"}), 404
        save_atomic(ANNS_PATH, next_anns)

    _prune_status({str(a.get("id")) for a in next_anns if a.get("id")})
    return jsonify({"ok": True})


@bp_api_announcements.get("/api/announce-status")
def api_announce_status():
    anns = _load_active_announcements()
    sid = _student_request_sid(request.args.get("sid"))
    if _is_public_student_request() and not sid:
        return jsonify({"ok": False, "code": "unauthenticated"}), 401
    status = _as_status_map(load(ANN_STATUS_PATH))
    if sid:
        visible_ids = {str(a.get("id")) for a in anns if _student_visible(a, sid)}
        own = {
            aid: entry
            for aid, entry in (status.get(sid) or {}).items()
            if aid in visible_ids
        }
        return jsonify(own)
    return jsonify(_summary_for_admin(anns))


@bp_api_announcements.post("/api/announce-ack")
def api_announce_ack():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    sid = _student_request_sid(body.get("sid"))
    aid = str(body.get("id") or "").strip()
    if not sid or not aid:
        return jsonify({"ok": False, "error": "missing sid/id"}), 400

    ann = next(
        (a for a in _load_active_announcements() if str(a.get("id")) == aid and _student_visible(a, sid)),
        None,
    )
    if not ann:
        return jsonify({"ok": False, "error": "not found"}), 404

    with file_lock(ANN_STATUS_PATH):
        status = _as_status_map(load(ANN_STATUS_PATH))
        entry = status.setdefault(sid, {}).setdefault(aid, {})
        if _survey_requires_completion(ann) and not _entry_has_survey_submission(entry):
            return jsonify({"ok": False, "error": "survey required"}), 400
        entry["acked"] = True
        entry["readAt"] = entry.get("readAt") or utc_now_isoz()
        save_atomic(ANN_STATUS_PATH, status)
    return jsonify({"ok": True})


@bp_api_announcements.post("/api/announce-submit")
def api_announce_submit():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    sid = _student_request_sid(body.get("sid"))
    aid = str(body.get("id") or "").strip()
    reply = str(body.get("reply") or "").strip()
    anonymous = bool(body.get("anonymous"))
    if not sid or not aid:
        return jsonify({"ok": False, "error": "missing sid/id"}), 400

    ann = next(
        (a for a in _load_active_announcements() if str(a.get("id")) == aid and _student_visible(a, sid)),
        None,
    )
    if not ann:
        return jsonify({"ok": False, "error": "not found"}), 404

    survey_response: dict[str, Any] | None = None
    normalized_survey_answers: dict[str, Any] | None = None
    survey, _ = _normalize_survey(ann.get("survey"))
    if "surveyAnswers" in body:
        if not survey or survey.get("status") != "public":
            return jsonify({"ok": False, "error": "survey not available"}), 400
        normalized_survey_answers, survey_error = _validate_survey_answers(survey, body.get("surveyAnswers"))
        if survey_error:
            return jsonify({"ok": False, "error": survey_error}), 400

    if not reply and normalized_survey_answers is None:
        return jsonify({"ok": False, "error": "reply or survey required"}), 400

    with file_lock(ANN_STATUS_PATH):
        status = _as_status_map(load(ANN_STATUS_PATH))
        entry = status.setdefault(sid, {}).setdefault(aid, {})
        reply_entry: dict[str, Any] | None = None
        if normalized_survey_answers is not None:
            if survey and not bool(survey.get("allowMultiple")) and _entry_has_survey_submission(entry):
                return jsonify({"ok": False, "error": "survey already submitted"}), 409
            submitted_at = utc_now_isoz()
            responses = entry.get("surveyResponses")
            if not isinstance(responses, list):
                responses = []
            survey_response = {
                "id": f"survey_{int(time.time() * 1000)}_{len(responses) + 1}",
                "answers": normalized_survey_answers,
                "anonymous": bool(survey.get("anonymous")) if survey else False,
                "submittedAt": submitted_at,
            }
            responses.append(survey_response)
            entry["surveyResponses"] = responses
            entry["surveyAnswers"] = normalized_survey_answers
            entry["surveyAnonymous"] = bool(survey.get("anonymous")) if survey else False
            entry["surveySubmittedAt"] = submitted_at
            entry["acked"] = True
            entry["readAt"] = entry.get("readAt") or submitted_at

        if reply:
            reply_rows = _reply_rows_from_status_entry(entry)
            if len(reply_rows) >= ANN_REPLY_LIMIT:
                return jsonify({
                    "ok": False,
                    "error": "reply limit reached",
                    "maxReplies": ANN_REPLY_LIMIT,
                    "remainingReplies": 0,
                }), 429
            replied_at = utc_now_isoz()
            replies = entry.get("replies")
            if not isinstance(replies, list):
                replies = []
            legacy_reply = str(entry.get("reply") or "").strip()
            legacy_replied_at = str(entry.get("repliedAt") or "")
            if legacy_reply:
                legacy_exists = any(
                    isinstance(item, dict)
                    and str(item.get("reply") or "").strip() == legacy_reply
                    and str(item.get("repliedAt") or "") == legacy_replied_at
                    for item in replies
                )
                if not legacy_exists:
                    replies.append({
                        "id": f"reply_legacy_{len(replies) + 1}",
                        "reply": legacy_reply,
                        "anonymous": bool(entry.get("anonymous")),
                        "repliedAt": legacy_replied_at,
                    })
            reply_entry = {
                "id": f"reply_{int(time.time() * 1000)}_{len(replies) + 1}",
                "reply": reply,
                "anonymous": anonymous,
                "repliedAt": replied_at,
            }
            replies.append(reply_entry)
            entry["replies"] = replies
            # Keep legacy latest-reply fields so older student UI/status consumers remain stable.
            entry["reply"] = reply
            entry["anonymous"] = anonymous
            entry["repliedAt"] = replied_at
            entry["readAt"] = entry.get("readAt") or replied_at

        save_atomic(ANN_STATUS_PATH, status)
    remaining_replies = None
    if reply_entry is not None:
        remaining_replies = max(0, ANN_REPLY_LIMIT - len(_reply_rows_from_status_entry(entry)))
    return jsonify({
        "ok": True,
        "reply": reply_entry,
        "survey": survey_response,
        "maxReplies": ANN_REPLY_LIMIT,
        "remainingReplies": remaining_replies,
    })
