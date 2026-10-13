from __future__ import annotations

import datetime as dt
import random
import re
from copy import deepcopy
from urllib.parse import unquote

from flask import Blueprint, abort, current_app, jsonify, request

from core.paths import BASE, STU_PATH

try:
    from core.paths import PERSONS_PATH, PERSON_IDENTITY_JOURNAL_PATH
except ImportError:  # Compatibility for isolated route fixtures with a minimal paths stub.
    PERSONS_PATH = BASE / "persons.json"
    PERSON_IDENTITY_JOURNAL_PATH = (
        BASE / "instance" / "person_identity_transactions" / "pending.json"
    )
from core.person_identity import (
    PERSON_PROFILE_FIELDS,
    PersonIdentityConflictError,
    PersonIdentityNotFoundError,
    PersonIdentityValidationError,
    allocate_unique_sid,
    validate_identity_state,
)
from core.person_identity_store import (
    PersonIdentityRecoveryRequiredError,
    PersonIdentityUnavailableError,
    create_student_with_identity,
    identity_is_configured,
    identity_state_lock,
    load_identity_state_strict,
    mutate_identity_state,
    retire_student_identity,
    update_person_profile_field,
)
from core.storage import file_lock, load, save_atomic
from core.student_auto_assignment_rules import (
    AUTO_VIDEO_ASSIGN_FIELD,
    apply_able_auto_video_assign_default,
    coerce_auto_video_assign_count,
    is_able_curriculum_value,
    student_uses_able_curriculum,
)
from core.student_notification_hooks import enqueue_current_schedule_changes
from core.video_sources import GICHUL_OVERLAY_FIELD


bp_api_students = Blueprint("api_students", __name__)

KST = dt.timezone(dt.timedelta(hours=9))
_ASSIGNMENT_HOOKS_EXTENSION = "student_identity_assignment_hooks"
_PERSON_PROFILE_FIELD_ALIASES = {
    "highSchool": "school",
    "middleSchool": "school",
}
WHITE_REVIEW_PENDING_FIELD = "whiteReviewPending"


def configure_student_identity_assignment_hooks(
    app,
    *,
    initialize_today,
    reconcile_today,
) -> None:
    if not callable(initialize_today) or not callable(reconcile_today):
        raise TypeError("student identity assignment hooks must be callable")
    app.extensions[_ASSIGNMENT_HOOKS_EXTENSION] = {
        "initialize_today": initialize_today,
        "reconcile_today": reconcile_today,
    }


def _assignment_hooks() -> tuple:
    hooks = current_app.extensions.get(_ASSIGNMENT_HOOKS_EXTENSION)
    if not isinstance(hooks, dict):
        raise RuntimeError("student identity assignment hooks are not configured")
    initialize_today = hooks.get("initialize_today")
    reconcile_today = hooks.get("reconcile_today")
    if not callable(initialize_today) or not callable(reconcile_today):
        raise RuntimeError("student identity assignment hooks are incomplete")
    return initialize_today, reconcile_today


def _person_identity_configured() -> bool:
    return identity_is_configured(
        PERSONS_PATH,
        PERSON_IDENTITY_JOURNAL_PATH,
        STU_PATH,
    )


def _person_identity_writes_degraded() -> bool:
    return bool(current_app.config.get("PERSON_IDENTITY_WRITES_DEGRADED"))


def _person_identity_error(message: str, status: int):
    return jsonify(
        {"ok": False, "error": message, "code": "person_identity_unavailable"}
    ), status


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _updated_student_rows(
    current_students: list[dict],
    sid: str,
    field: str,
    value,
) -> list[dict] | None:
    next_students = deepcopy(current_students)
    next_value = value
    for student in next_students:
        if str(student.get("id")) != str(sid):
            continue
        was_able = student_uses_able_curriculum(student)
        if field == AUTO_VIDEO_ASSIGN_FIELD:
            next_value = coerce_auto_video_assign_count(next_value)
        student[field] = next_value
        if (
            field in {"curriculum", "subCurriculum"}
            and student_uses_able_curriculum(student)
            and (not was_able or is_able_curriculum_value(next_value))
        ):
            apply_able_auto_video_assign_default(student)
        return next_students
    return None


@bp_api_students.get("/api/students")
def api_students():
    if _person_identity_configured():
        if _person_identity_writes_degraded():
            return _person_identity_error("person identity recovery is required", 503)
        try:
            with identity_state_lock(PERSONS_PATH, STU_PATH, PERSON_IDENTITY_JOURNAL_PATH):
                if PERSON_IDENTITY_JOURNAL_PATH.exists():
                    return _person_identity_error("person identity recovery is required", 503)
                _, students = load_identity_state_strict(PERSONS_PATH, STU_PATH)
            return jsonify(students)
        except (PersonIdentityUnavailableError, OSError, TimeoutError) as error:
            return _person_identity_error(str(error), 503)
    return jsonify(load(STU_PATH))


@bp_api_students.post("/api/add-student")
def api_add_student():
    data = dict(request.get_json(force=True) or {})
    if GICHUL_OVERLAY_FIELD in data and type(data[GICHUL_OVERLAY_FIELD]) is not bool:
        return jsonify({"ok": False, "error": f"field must be a JSON boolean: {GICHUL_OVERLAY_FIELD}"}), 400
    data.pop("id", None)
    data.pop("personId", None)
    data.pop("cloneFromSid", None)
    raw_name = str(data.get("name", "user"))
    name_slug = re.sub(r"[^0-9A-Za-z가-힣]", "", raw_name)
    apply_able_auto_video_assign_default(data)

    if _person_identity_configured():
        if _person_identity_writes_degraded():
            return _person_identity_error("person identity recovery is required", 503)
        query_clone_sid = str(request.args.get("cloneFromSid") or "").strip()
        header_clone_sid = unquote(
            str(request.headers.get("X-Clone-From-Sid") or "").strip()
        )
        if query_clone_sid and header_clone_sid and query_clone_sid != header_clone_sid:
            return jsonify({"ok": False, "error": "conflicting clone source SID"}), 400
        clone_from_sid = query_clone_sid or header_clone_sid
        if len(clone_from_sid) > 256:
            return jsonify({"ok": False, "error": "clone source SID is too long"}), 400
        try:
            created = create_student_with_identity(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                data,
                sid_prefix=name_slug,
                clone_from_sid=clone_from_sid,
                suffix_factory=lambda: random.randint(0, 999),
            )
        except PersonIdentityNotFoundError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 404
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        enqueue_current_schedule_changes([created["id"]])
        return jsonify({"id": created["id"], "personId": created["personId"]})

    with file_lock(STU_PATH):
        students: list[dict] = load(STU_PATH)
        try:
            data["id"] = allocate_unique_sid(
                name_slug,
                [
                    str(row.get("id") or "")
                    for row in students
                    if isinstance(row, dict)
                ],
                suffix_factory=lambda: random.randint(0, 999),
            )
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        students.append(data)
        save_atomic(STU_PATH, students)
    enqueue_current_schedule_changes([data["id"]])
    return jsonify({"id": data["id"]})


@bp_api_students.delete("/api/students/<string:sid>")
def api_delete_student(sid: str):
    if _person_identity_configured():
        if _person_identity_writes_degraded():
            return _person_identity_error("person identity recovery is required", 503)
        try:
            retire_student_identity(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                sid,
            )
        except PersonIdentityNotFoundError:
            abort(404, description="학생을 찾을 수 없습니다.")
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return "", 204

    with file_lock(STU_PATH):
        students: list[dict] = load(STU_PATH)
        for index, student in enumerate(students):
            if str(student.get("id")) == str(sid):
                del students[index]
                save_atomic(STU_PATH, students)
                return "", 204
    abort(404, description="학생을 찾을 수 없습니다.")


@bp_api_students.post("/api/update")
def api_update_student_field():
    body = request.get_json(force=True) or {}
    sid = body.get("id")
    field = body.get("field")
    value = body.get("value")

    if not sid or not field:
        abort(400)

    field = str(field)
    if field in {"id", "personId"}:
        return jsonify({"ok": False, "error": f"field is immutable: {field}"}), 400
    if field in {WHITE_REVIEW_PENDING_FIELD, GICHUL_OVERLAY_FIELD} and type(value) is not bool:
        return jsonify(
            {
                "ok": False,
                "error": f"field must be a JSON boolean: {field}",
            }
        ), 400

    assignment_hooks = None
    if field in {"curriculum", "subCurriculum", "selfStudyDays"} or re.fullmatch(
        r"day\d+", field
    ):
        # Resolve composition before the store mutation so a misconfigured app
        # cannot persist a student edit and then fail only in post-save effects.
        assignment_hooks = _assignment_hooks()

    identity_configured = _person_identity_configured()
    if identity_configured and _person_identity_writes_degraded():
        return _person_identity_error("person identity recovery is required", 503)

    canonical_profile_field = _PERSON_PROFILE_FIELD_ALIASES.get(field, field)
    if identity_configured and canonical_profile_field in PERSON_PROFILE_FIELDS:
        try:
            update_person_profile_field(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                str(sid),
                canonical_profile_field,
                value,
            )
        except PersonIdentityNotFoundError:
            abort(404)
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return "OK"

    students: list[dict] | None = None
    if identity_configured:

        def mutation(directory: dict, current_students: list):
            next_students = _updated_student_rows(
                current_students,
                str(sid),
                field,
                value,
            )
            if next_students is None:
                raise PersonIdentityNotFoundError("student SID was not found")
            validate_identity_state(directory, next_students)
            return directory, next_students, next_students

        try:
            students = mutate_identity_state(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                mutation,
            )
        except PersonIdentityNotFoundError:
            abort(404)
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
    else:
        with file_lock(STU_PATH):
            current_students: list[dict] = load(STU_PATH)
            students = _updated_student_rows(
                current_students,
                str(sid),
                field,
                value,
            )
            if students is not None:
                save_atomic(STU_PATH, students)

    if students is None:
        abort(404)

    if field in {"curriculum", "subCurriculum", "selfStudyDays"}:
        initialize_today, _reconcile_today = assignment_hooks
        initialize_today(students=students)
    elif re.fullmatch(r"day\d+", field):
        initialize_today, reconcile_today = assignment_hooks
        reconcile_today(
            _today_kst_iso(),
            str(sid),
            students=students,
        )
        initialize_today(students=students)
    if re.fullmatch(r"(?:day|visitTime)\d+", field):
        enqueue_current_schedule_changes([str(sid)])
    return "OK"


__all__ = (
    "bp_api_students",
    "configure_student_identity_assignment_hooks",
)
