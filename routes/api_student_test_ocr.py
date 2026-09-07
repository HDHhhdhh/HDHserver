from __future__ import annotations

import datetime as dt
import io
import threading
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, verify_admin_authorization
from core.network_access import academy_network_allowed, ip_allowed
from core.paths import BASE, PRG_PATH, TESTS_CFG_PATH
from core.progress_store import load_progress_strict
from core.runtime_server_guard import is_verified_isolated_server_root
from core.storage import load, nocache_resp
from core.student_test_ocr_assets import MAX_CAPTURE_BYTES, OcrAssetError
from core.student_test_ocr_config import StudentTestOcrConfig, load_student_test_ocr_config
from core.student_test_ocr_engine import OcrEngineError, recognize_answer_value_crop, recognize_sheet
from core.student_test_ocr_job_runner import StudentTestOcrJobRunner
from core.student_test_ocr_repository import (
    StudentTestOcrNotInitializedError,
    StudentTestOcrRepository,
    StudentTestOcrRepositoryError,
)
from core.student_test_ocr_service import StudentTestOcrService, StudentTestOcrServiceError
from core.student_test_solution_crop import UnitSolutionCropProvider
from core.student_test_sheet_cropper import crop_answer_sheet
from core.test_answer_links import resolve_test_assignment_answer_url
from core.test_config_safety import tests_config_revision
from core.student_test_ocr_eligibility import find_test_definition


bp_api_student_test_ocr = Blueprint("api_student_test_ocr", __name__)
KST = dt.timezone(dt.timedelta(hours=9))
ANSWER_LINK_MAP_PATH = BASE / "static" / "js" / "test_answer_link_map.json"
_RUNTIME_LOCK = threading.Lock()
_RUNTIME: tuple[StudentTestOcrConfig, StudentTestOcrService] | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(KST)


def _academy_allowed() -> bool:
    if is_verified_isolated_server_root():
        # The managed design server is marker-verified and bound to loopback;
        # this permits UI QA without widening the production academy ranges.
        return True
    if getattr(g, "student_app_public_request", False) is True:
        client_ip = getattr(g, "student_app_client_ip", None)
        return isinstance(client_ip, str) and ip_allowed(client_ip)
    return academy_network_allowed()


def _request_sid(value: object) -> str:
    provided = str(value or "").strip()
    if getattr(g, "student_app_public_request", False) is True:
        active = getattr(g, "student_app_active_sid", None)
        if not isinstance(active, str) or not active:
            raise StudentTestOcrServiceError("unauthenticated", "student session is required", 401)
        if provided and provided != active:
            raise StudentTestOcrServiceError("sid_mismatch", "student session does not match", 403)
        return active
    if not provided:
        raise StudentTestOcrServiceError("missing_sid", "student id is required", 400)
    return provided


def _answer_url_for_submission(submission: dict) -> str:
    config = load(TESTS_CFG_PATH)
    try:
        definition = find_test_definition(config, submission["test_id"])
    except Exception:
        return ""
    test = definition["test"]
    item = {
        **test,
        "id": submission["test_id"],
        "testId": submission["test_id"],
        "round": submission["round_no"],
        "type": definition["categoryKey"],
        "category": definition["categoryKey"],
        "categoryKey": definition["categoryKey"],
        "categoryLabel": definition["categoryLabel"],
    }
    return resolve_test_assignment_answer_url(
        item,
        tests_config=config,
        answer_link_map=load(ANSWER_LINK_MAP_PATH),
    )


def _build_runtime(config: StudentTestOcrConfig) -> StudentTestOcrService:
    repository = StudentTestOcrRepository(config.db_path)
    if not repository.schema_ready():
        raise StudentTestOcrNotInitializedError()
    recognition_lock = threading.Lock()

    def cropper(*, asset_root, image_path, output_dir):
        return crop_answer_sheet(
            worker=config.crop_worker,
            asset_root=asset_root,
            image_path=image_path,
            output_dir=output_dir,
        )

    def recognizer(*, crops, asset_root, formula_profile):
        unimernet_worker = (
            config.unimernet_worker_for_profile(formula_profile)
            if formula_profile is not None
            else config.unimernet_worker
        )
        with recognition_lock:
            return recognize_sheet(
                crops=crops,
                asset_root=asset_root,
                choice_worker=config.choice_worker,
                paddle_worker=config.paddle_worker,
                formula_worker=config.formula_worker,
                unimernet_worker=unimernet_worker,
                policy=config.confidence_policy,
            )

    def answer_value_recognizer(*, question_no, image_path, asset_root, formula_profile):
        unimernet_worker = config.unimernet_worker_for_profile(formula_profile)
        with recognition_lock:
            return recognize_answer_value_crop(
                question_no=question_no,
                image_path=image_path,
                asset_root=asset_root,
                paddle_worker=config.paddle_worker,
                formula_worker=config.formula_worker,
                unimernet_worker=unimernet_worker,
                policy=config.confidence_policy,
            )

    runner = StudentTestOcrJobRunner(
        repository=repository,
        asset_root=config.asset_root,
        cropper=cropper,
        recognizer=recognizer,
        clock=_now,
    )

    def log_entry_loader(date_key: str, sid: str):
        from routes.api_basic import get_log_repository

        result = get_log_repository().read_entry(date_key, sid)
        return result.entry if isinstance(result.entry, dict) else {}

    service = StudentTestOcrService(
        repository=repository,
        job_runner=runner,
        asset_root=config.asset_root,
        tests_config_loader=lambda: load(TESTS_CFG_PATH),
        progress_loader=lambda: load_progress_strict(PRG_PATH),
        log_entry_loader=log_entry_loader,
        catalog_revision=tests_config_revision,
        answer_url_resolver=_answer_url_for_submission,
        clock=_now,
        answer_value_recognizer=answer_value_recognizer,
        solution_crop_provider=UnitSolutionCropProvider(config.solution_pdf_root),
        token_ttl_seconds=config.token_ttl_seconds,
    )
    runner.on_recognition_committed = service.complete_recognition
    return service


def _service() -> StudentTestOcrService:
    injected = current_app.config.get("STUDENT_TEST_OCR_SERVICE")
    if isinstance(injected, StudentTestOcrService) or (
        injected is not None and all(hasattr(injected, name) for name in ("start_capture_session", "submit_full_capture", "status"))
    ):
        return injected
    config = load_student_test_ocr_config()
    if not config.enabled:
        raise StudentTestOcrServiceError("feature_disabled", "student test OCR is disabled", 404)
    if not config.runtime_available():
        raise StudentTestOcrServiceError("ocr_runtime_unavailable", "local OCR runtime is unavailable", 503)
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None or _RUNTIME[0] != config:
            _RUNTIME = (config, _build_runtime(config))
        return _RUNTIME[1]


def _error(error: Exception):
    if isinstance(error, StudentTestOcrServiceError):
        status, code, message = error.status_code, error.code, error.message
    elif isinstance(error, StudentTestOcrNotInitializedError):
        status, code, message = 503, error.code, str(error)
    elif isinstance(error, StudentTestOcrRepositoryError):
        status, code, message = 409, error.code, str(error)
    elif isinstance(error, OcrAssetError):
        status, code, message = 400, error.code, error.message
    elif isinstance(error, OcrEngineError):
        status, code, message = 503, error.code, error.message
    else:
        status, code, message = 500, "ocr_unavailable", "OCR request could not be completed"
    response = _response({"ok": False, "code": code, "message": message}, status)
    if code == "admin_auth_required":
        response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
    return response


def _response(payload: dict, status: int = 200):
    response = nocache_resp(payload)
    response.status_code = status
    return response


def _require_academy() -> None:
    if not _academy_allowed():
        raise StudentTestOcrServiceError(
            "academy_network_required",
            "OCR 촬영과 제출은 학원 네트워크에서만 이용할 수 있습니다.",
            403,
        )


def _require_admin() -> None:
    verifier = current_app.config.get("ACADEMY_ADMIN_AUTHORIZER")
    if not callable(verifier):
        verifier = verify_admin_authorization
    if not verifier(request.headers.get("Authorization")):
        raise StudentTestOcrServiceError("admin_auth_required", "관리자 로그인이 필요합니다.", 401)


@bp_api_student_test_ocr.get("/api/student-test-ocr/capabilities")
def student_test_ocr_capabilities():
    if not _academy_allowed():
        return _response({"ok": True, "enabled": False, "academyOnly": True})
    injected = current_app.config.get("STUDENT_TEST_OCR_SERVICE")
    if injected is not None:
        return _response({"ok": True, "enabled": True, "cameraOnly": True, "problemCount": 20})
    config = load_student_test_ocr_config()
    enabled = bool(config.enabled and config.runtime_available() and StudentTestOcrRepository(config.db_path).schema_ready())
    return _response({"ok": True, "enabled": enabled, "cameraOnly": True, "problemCount": 20})


@bp_api_student_test_ocr.post("/api/student-test-ocr/session")
def start_student_test_ocr_session():
    try:
        _require_academy()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise StudentTestOcrServiceError("invalid_request", "JSON body is required")
        sid = _request_sid(body.get("sid"))
        result = _service().start_capture_session(
            sid=sid,
            assignment_date=str(body.get("date") or "").strip(),
            test_id=str(body.get("testId") or "").strip(),
            assignment_label=str(body.get("assignmentLabel") or "").strip(),
        )
        return _response({"ok": True, **result})
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/capture")
def submit_student_test_ocr_capture():
    try:
        _require_academy()
        upload = request.files.get("capture")
        if upload is None:
            raise StudentTestOcrServiceError("missing_capture", "camera capture is required")
        content = upload.stream.read(MAX_CAPTURE_BYTES + 1)
        result = _service().submit_full_capture(
            token=str(request.form.get("token") or ""),
            request_id=str(request.form.get("requestId") or ""),
            content=content,
        )
        return _response({"ok": True, **result}, 202)
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get("/api/student-test-ocr/submissions/<submission_id>")
def student_test_ocr_status(submission_id: str):
    try:
        _require_academy()
        sid = _request_sid(request.args.get("sid"))
        result = _service().status(submission_id=submission_id, sid=sid)
        return _response({"ok": True, **result})
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/submissions/<submission_id>/choice")
def student_test_ocr_choice(submission_id: str):
    try:
        _require_academy()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise StudentTestOcrServiceError("invalid_request", "JSON body is required")
        sid = _request_sid(body.get("sid"))
        result = _service().submit_choice(
            submission_id=submission_id,
            sid=sid,
            question_no=int(body.get("questionNo")),
            choice=body.get("choice"),
            revision=int(body.get("revision")),
        )
        return _response({"ok": True, **result})
    except (TypeError, ValueError):
        return _error(StudentTestOcrServiceError("invalid_request", "choice payload is invalid"))
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/submissions/<submission_id>/recapture")
def student_test_ocr_question_recapture(submission_id: str):
    try:
        _require_academy()
        upload = request.files.get("capture")
        if upload is None:
            raise StudentTestOcrServiceError("missing_capture", "camera capture is required")
        sid = _request_sid(request.form.get("sid"))
        content = upload.stream.read(MAX_CAPTURE_BYTES + 1)
        result = _service().submit_answer_value_recapture(
            submission_id=submission_id,
            sid=sid,
            question_no=int(request.form.get("questionNo")),
            revision=int(request.form.get("revision")),
            content=content,
        )
        return _response({"ok": True, **result})
    except (TypeError, ValueError):
        return _error(StudentTestOcrServiceError("invalid_request", "recapture payload is invalid"))
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/submissions/<submission_id>/retake")
def student_test_ocr_full_retake(submission_id: str):
    try:
        _require_academy()
        upload = request.files.get("capture")
        if upload is None:
            raise StudentTestOcrServiceError("missing_capture", "camera capture is required")
        sid = _request_sid(request.form.get("sid"))
        content = upload.stream.read(MAX_CAPTURE_BYTES + 1)
        result = _service().submit_full_retake(
            submission_id=submission_id,
            sid=sid,
            revision=int(request.form.get("revision")),
            content=content,
        )
        return _response({"ok": True, **result}, 202)
    except (TypeError, ValueError):
        return _error(StudentTestOcrServiceError("invalid_request", "retake payload is invalid"))
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get("/api/student-test-ocr/admin/capabilities")
def student_test_ocr_admin_capabilities():
    try:
        _require_admin()
        injected = current_app.config.get("STUDENT_TEST_OCR_SERVICE")
        if injected is not None:
            return _response({"ok": True, "enabled": True, "review": True})
        config = load_student_test_ocr_config()
        enabled = bool(
            config.enabled
            and config.runtime_available()
            and StudentTestOcrRepository(config.db_path).schema_ready()
        )
        return _response({"ok": True, "enabled": enabled, "review": True})
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get("/api/student-test-ocr/admin/pending")
def student_test_ocr_admin_pending():
    try:
        _require_admin()
        result = _service().admin_pending(assignment_date=str(request.args.get("date") or "").strip())
        return _response({"ok": True, **result})
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get("/api/student-test-ocr/admin/submissions/<submission_id>")
def student_test_ocr_admin_detail(submission_id: str):
    try:
        _require_admin()
        result = _service().admin_detail(submission_id=submission_id)
        return _response({"ok": True, **result})
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/admin/submissions/<submission_id>/resolve")
def student_test_ocr_admin_resolve(submission_id: str):
    try:
        _require_admin()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("correct"), bool):
            raise StudentTestOcrServiceError("invalid_request", "pending decision payload is invalid")
        result = _service().admin_resolve_pending(
            submission_id=submission_id,
            question_no=int(body.get("questionNo")),
            correct=body["correct"],
            revision=int(body.get("revision")),
        )
        return _response({"ok": True, **result})
    except (TypeError, ValueError):
        return _error(StudentTestOcrServiceError("invalid_request", "pending decision payload is invalid"))
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.post("/api/student-test-ocr/admin/submissions/<submission_id>/correct")
def student_test_ocr_admin_correct(submission_id: str):
    try:
        _require_admin()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise StudentTestOcrServiceError("invalid_request", "grade correction payload is invalid")
        result = _service().admin_correct_wrong(
            submission_id=submission_id,
            question_no=int(body.get("questionNo")),
            revision=int(body.get("revision")),
        )
        return _response({"ok": True, **result})
    except (TypeError, ValueError):
        return _error(StudentTestOcrServiceError("invalid_request", "grade correction payload is invalid"))
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get("/api/student-test-ocr/admin/assets/<asset_id>")
def student_test_ocr_admin_asset(asset_id: str):
    try:
        _require_admin()
        path = _service().admin_asset_path(asset_id=asset_id)
        response = send_file(path, conditional=False, max_age=0)
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Expires": "0"})
        return response
    except Exception as error:
        return _error(error)


@bp_api_student_test_ocr.get(
    "/api/student-test-ocr/admin/submissions/<submission_id>/solution-crop/<int:question_no>"
)
def student_test_ocr_admin_solution_crop(submission_id: str, question_no: int):
    try:
        _require_admin()
        content = _service().admin_solution_crop(submission_id=submission_id, question_no=question_no)
        response = send_file(
            io.BytesIO(content),
            mimetype="image/png",
            download_name=f"{submission_id}-q{question_no:02d}-solution.png",
            conditional=False,
            max_age=0,
        )
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Expires": "0"})
        return response
    except Exception as error:
        return _error(error)
