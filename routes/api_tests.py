from __future__ import annotations

import os
from copy import deepcopy
import datetime as dt
import re
import threading

from flask import Blueprint, current_app, g, jsonify, request

from core.network_access import (
    ACADEMY_ACCESS_MESSAGE,
    academy_network_allowed,
    ip_allowed,
    strip_tests_config_answer_links,
)

from core.paths import (
    BASE, LOGS_PATH, PRG_PATH, TESTS_PATH, STU_PATH,
    TESTS_CFG_PATH
)
from core.progress_store import load_progress_strict
from core.quick_printer_export import (
    NoQuickPrinterAssignments,
    QuickPrinterExportFailure,
    QuickPrinterResourceFailure,
    build_quick_printer_export,
    file_sha256,
    read_mapping_bundle,
    read_registered_catalog,
)
from core.quick_printer_export_history import QuickPrinterExportHistoryRepository
from core.storage import file_lock, load, save_atomic, nocache_resp, utc_now_isoz
from core.test_answer_links import resolve_test_assignment_answer_url
from core.test_config_safety import (
    TestsConfigWriteConflict,
    merge_tests_config_for_write,
    patch_test_config_record,
    tests_config_revision,
)
from core.test_record_projection import (
    build_test_catalog,
    find_test_def_by_id as _find_test_def_by_id,
    get_answer_key_for_round as _get_answer_key_for_round,
    merge_test_record_candidates,
    normalized_test_record_candidates as _normalized_test_record_candidates,
    normalize_test_record_filters,
    parse_record_date,
    project_test_records,
    sanitize_tests_payload_for_public_api,
)
from core.test_statistics_projection import project_test_statistics
from routes.log_repository_provider import get_log_repository


bp_api_tests = Blueprint("api_tests", __name__)
TEST_ANSWER_LINK_MAP_PATH = BASE / "static" / "js" / "test_answer_link_map.json"
QUICK_PRINTER_CATALOG_PATH = BASE / "core" / "resources" / "quick_printer_registered_tests.csv"
QUICK_PRINTER_MAPPING_PATH = BASE / "core" / "resources" / "quick_printer_test_mapping.json"
def _is_public_student_request() -> bool:
    return getattr(g, "student_app_public_request", False) is True


def _academy_request_allowed() -> bool:
    if _is_public_student_request():
        client_ip = getattr(g, "student_app_client_ip", None)
        return isinstance(client_ip, str) and ip_allowed(client_ip)
    return academy_network_allowed()


def _public_session_available() -> bool:
    if not _is_public_student_request():
        return True
    active_sid = getattr(g, "student_app_active_sid", None)
    return isinstance(active_sid, str) and bool(active_sid)


_LEGACY_TEST_RECORD_CACHE_LOCK = threading.Lock()
_LEGACY_TEST_RECORD_CACHE: tuple[tuple[object, ...], tuple[dict, ...]] | None = None


def _tests_config_lock():
    return file_lock(TESTS_CFG_PATH, timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _admin_test_answer_url(target_meta: dict | None, test_id: str, tests_config: dict | None = None) -> str:
    if not academy_network_allowed() or not isinstance(target_meta, dict):
        return ""
    item = {
        "type": target_meta.get("type") or "UNIT",
        "category": target_meta.get("type") or "UNIT",
        "id": test_id,
        "testId": test_id,
        "sourceId": target_meta.get("source_id") or "",
        "name": target_meta.get("test_name") or target_meta.get("unit_name") or "",
        "round": target_meta.get("round") or "",
        "curriculum": target_meta.get("curriculum") or "",
        "difficulty": target_meta.get("difficulty") or "",
        "term": target_meta.get("term") or "",
    }
    config = tests_config if isinstance(tests_config, dict) else _load_tests_cfg()
    return resolve_test_assignment_answer_url(
        item,
        tests_config=config,
        answer_link_map=load(TEST_ANSWER_LINK_MAP_PATH),
    )


def _load_tests_cfg() -> dict:
    cfg = load(TESTS_CFG_PATH)
    return cfg if isinstance(cfg, dict) else {"categories": {}}


@bp_api_tests.get("/api/tests")
def api_tests():
    return nocache_resp(sanitize_tests_payload_for_public_api(load(TESTS_PATH)))
@bp_api_tests.get("/api/tests-config")
def get_tests_config():
    if not _public_session_available():
        return jsonify({"ok": False, "code": "unauthenticated"}), 401
    config = load(TESTS_CFG_PATH)
    revision = tests_config_revision(config) if isinstance(config, dict) else ""
    if not _academy_request_allowed():
        config = strip_tests_config_answer_links(config)
    response = nocache_resp(config)
    if revision:
        response.headers["X-Tests-Config-Revision"] = revision
    return response


def _quick_printer_json(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _handle_quick_printer_export(*, preview: bool):
    if _is_public_student_request():
        return _quick_printer_json(
            {"ok": False, "code": "administrator_only", "message": "관리자 전용 기능입니다."},
            403,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _quick_printer_json(
            {"ok": False, "code": "invalid_payload", "message": "JSON 요청 본문이 필요합니다."},
            400,
        )
    date_str = str(payload.get("date") or "").strip()
    student_ids = payload.get("studentIds")
    if not isinstance(student_ids, list) or len(student_ids) > 500:
        return _quick_printer_json(
            {
                "ok": False,
                "code": "invalid_student_ids",
                "message": "운영판 학생 ID 목록이 필요합니다.",
            },
            400,
        )
    include_reprints = payload.get("includePreviouslyExportedCarryovers", False)
    if type(include_reprints) is not bool:
        return _quick_printer_json(
            {
                "ok": False,
                "code": "invalid_reprint_option",
                "message": "재인쇄 포함 옵션은 JSON boolean이어야 합니다.",
            },
            400,
        )

    try:
        catalog_rows = read_registered_catalog(QUICK_PRINTER_CATALOG_PATH)
        mapping_bundle = read_mapping_bundle(QUICK_PRINTER_MAPPING_PATH)
        log_history = get_log_repository().read_export_history(
            {str(sid or "").strip(): date_str for sid in student_ids}
        )
        history_repository = QuickPrinterExportHistoryRepository()
        result = build_quick_printer_export(
            date_str=date_str,
            ordered_student_ids=student_ids,
            students=load(STU_PATH),
            progress=load_progress_strict(PRG_PATH),
            tests_config=_load_tests_cfg(),
            mapping_bundle=mapping_bundle,
            catalog_rows=catalog_rows,
            catalog_sha256=file_sha256(QUICK_PRINTER_CATALOG_PATH),
            log_history=log_history,
            exported_assignment_keys=history_repository.keys_for_students(student_ids),
            include_previously_exported_carryovers=include_reprints,
            allow_empty=preview,
        )
        history_items = result.pop("historyItems", [])
        if preview:
            result.pop("csv", None)
            result.pop("filename", None)
        else:
            history_repository.record_generated(history_items)
    except NoQuickPrinterAssignments as exc:
        return _quick_printer_json(
            {"ok": False, "code": exc.code, "message": exc.message, "issues": exc.issues},
            422,
        )
    except QuickPrinterResourceFailure as exc:
        current_app.logger.error("quick-printer resource validation failed: %s", exc)
        return _quick_printer_json(
            {"ok": False, "code": exc.code, "message": exc.message, "issues": exc.issues},
            503,
        )
    except QuickPrinterExportFailure as exc:
        status = 400 if exc.code == "invalid_date" else 409
        return _quick_printer_json(
            {"ok": False, "code": exc.code, "message": exc.message, "issues": exc.issues},
            status,
        )
    except Exception as exc:
        current_app.logger.error("quick-printer export read failed: %s", exc)
        return _quick_printer_json(
            {
                "ok": False,
                "code": "quick_printer_data_unavailable",
                "message": "테스트 인쇄 데이터를 읽을 수 없습니다.",
            },
            503,
        )

    return _quick_printer_json({"ok": True, **result})


@bp_api_tests.post("/api/tests/quick-printer-export")
def export_quick_printer_tests():
    return _handle_quick_printer_export(preview=False)


@bp_api_tests.post("/api/tests/quick-printer-export/preview")
def preview_quick_printer_tests():
    return _handle_quick_printer_export(preview=True)

@bp_api_tests.post("/api/tests-config")
def post_tests_config():
    expected_revision = str(
        request.headers.get("X-Tests-Config-Revision", "")
    ).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
        return jsonify({"ok": False, "error": "catalog_revision_required"}), 428
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    raw_removed_ids = payload.pop("__removedTestIds", [])
    if not isinstance(raw_removed_ids, list) or not all(
        isinstance(value, str) for value in raw_removed_ids
    ):
        return jsonify({"ok": False, "error": "invalid removed test IDs"}), 400
    with _tests_config_lock():
        current = load(TESTS_CFG_PATH)
        if not isinstance(current, dict):
            return jsonify({"ok": False, "error": "invalid current config"}), 500
        if tests_config_revision(current) != expected_revision:
            return jsonify({"ok": False, "error": "catalog_changed"}), 409
        try:
            merged = merge_tests_config_for_write(
                current,
                payload,
                raw_removed_ids,
            )
        except TestsConfigWriteConflict as exc:
            current_app.logger.warning(
                "tests-config write rejected: existing test IDs omitted",
                extra={
                    "missing_test_count": len(exc.missing_test_ids),
                    "missing_test_ids": list(exc.missing_test_ids[:20]),
                },
            )
            return jsonify(
                {
                    "ok": False,
                    "error": "catalog_changed",
                    "missingTestIds": list(exc.missing_test_ids[:50]),
                    "missingTestCount": len(exc.missing_test_ids),
                }
            ), 409
        except ValueError:
            return jsonify({"ok": False, "error": "invalid config"}), 400
        save_atomic(TESTS_CFG_PATH, merged)
        saved_revision = tests_config_revision(merged)
    response = jsonify({"ok": True})
    response.headers["X-Tests-Config-Revision"] = saved_revision
    return response


@bp_api_tests.patch("/api/tests-config/test")
def patch_tests_config_test():
    expected_revision = str(
        request.headers.get("X-Tests-Config-Revision", "")
    ).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
        return jsonify({"ok": False, "error": "catalog_revision_required"}), 428

    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    category_key = str(payload.get("categoryKey") or "").strip()
    category_label = str(payload.get("categoryLabel") or "").strip()
    incoming_test = payload.get("test")
    clear_fields = payload.get("clearFields", [])
    if (
        not category_key
        or not isinstance(incoming_test, dict)
        or not isinstance(clear_fields, list)
    ):
        return jsonify({"ok": False, "error": "invalid test patch"}), 400

    with _tests_config_lock():
        current = load(TESTS_CFG_PATH)
        if not isinstance(current, dict):
            return jsonify({"ok": False, "error": "invalid current config"}), 500
        if tests_config_revision(current) != expected_revision:
            return jsonify({"ok": False, "error": "catalog_changed"}), 409
        try:
            merged, saved_test = patch_test_config_record(
                current,
                category_key,
                incoming_test,
                category_label=category_label,
                clear_fields=clear_fields,
            )
        except ValueError:
            return jsonify({"ok": False, "error": "invalid test patch"}), 400
        save_atomic(TESTS_CFG_PATH, merged)
        saved_revision = tests_config_revision(merged)

    response = jsonify({"ok": True, "test": saved_test})
    response.headers["X-Tests-Config-Revision"] = saved_revision
    return response


def _test_record_file_signature(path) -> tuple[object, ...] | None:
    try:
        absolute_path = os.path.normcase(os.path.abspath(os.fspath(path)))
        stat = os.stat(path)
    except OSError:
        return None
    return (
        absolute_path,
        getattr(stat, "st_dev", 0),
        getattr(stat, "st_ino", 0),
        stat.st_mtime_ns,
        getattr(stat, "st_ctime_ns", 0),
        stat.st_size,
    )


def _legacy_test_record_candidates() -> list[dict]:
    global _LEGACY_TEST_RECORD_CACHE

    with _LEGACY_TEST_RECORD_CACHE_LOCK:
        before_signature = _test_record_file_signature(LOGS_PATH)
        cached = _LEGACY_TEST_RECORD_CACHE
        if before_signature is not None and cached is not None and cached[0] == before_signature:
            candidates = cached[1]
        else:
            try:
                from routes.api_basic import get_log_repository

                legacy_logs = get_log_repository().read_json_map()
            except Exception:
                legacy_logs = load(LOGS_PATH)

            candidates = tuple(_normalized_test_record_candidates(legacy_logs))
            after_signature = _test_record_file_signature(LOGS_PATH)
            if candidates and before_signature is not None and before_signature == after_signature:
                cached_candidates = tuple(deepcopy(candidates))
                _LEGACY_TEST_RECORD_CACHE = (after_signature, cached_candidates)

    return deepcopy(list(candidates))


def _iter_test_records(start: dt.date | None, end: dt.date | None):
    # Keep durable records first and load legacy logs only after that source.
    def sources():
        yield _normalized_test_record_candidates(load(TESTS_PATH))
        yield _legacy_test_record_candidates()

    yield from merge_test_record_candidates(sources(), start, end)

@bp_api_tests.get("/api/tests-records")
def api_tests_records():
    filters = normalize_test_record_filters(request.args)
    if not any(filters[key] for key in ("test_id", "test", "type", "curriculum", "unit_name", "test_level", "term")):
        return jsonify({"ok": False, "error": "missing filter"}), 400
    recent = request.args.get("recent_days")
    end = dt.date.today()
    try:
        days = int(recent) if recent else 30
    except Exception:
        days = 30
    days = max(1, min(3650, days))
    start = end - dt.timedelta(days=days - 1)
    cfg = _load_tests_cfg()
    catalog = build_test_catalog(cfg)
    payload = project_test_records(
        _iter_test_records(start, end), cfg, catalog, load(STU_PATH),
        start=start, end=end, filters=filters,
    )
    by_id = catalog.get("by_id") if isinstance(catalog, dict) else {}
    target_meta = by_id.get(filters["test_id"]) if isinstance(by_id, dict) and filters["test_id"] else None
    payload["answerUrl"] = _admin_test_answer_url(target_meta, filters["test_id"], cfg)
    return nocache_resp(payload)

@bp_api_tests.get("/api/tests-stats")
def api_tests_stats():
    start_q = request.args.get("start")
    end_q   = request.args.get("end")
    recent  = request.args.get("recent_days")
    include_wrong = request.args.get("include_wrong", "0") in ("1", "true", "True")

    end = parse_record_date(end_q) or dt.date.today()
    if recent:
        try:
            days = int(recent)
            start = end - dt.timedelta(days=days - 1)
        except Exception:
            start = parse_record_date(start_q)
    else:
        start = parse_record_date(start_q)

    if not start:
        start = end - dt.timedelta(days=29)
    catalog = build_test_catalog(_load_tests_cfg())
    payload = project_test_statistics(
        _iter_test_records(start, end), catalog, load(STU_PATH),
        start=start, end=end, include_wrong=include_wrong,
    )
    payload = {"range": payload.pop("range"), "updatedAt": utc_now_isoz(), **payload}
    return nocache_resp(payload)
