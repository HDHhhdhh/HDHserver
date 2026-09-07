from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from core.date_rules import is_iso_date_key
from core.quick_printer_export_history import (
    QuickPrinterHistoryKey,
    quick_printer_history_key,
)


CSV_COLUMNS = ("주문번호", "자료ID", "학생이름", "부수", "메모")
MAPPING_VERSION = 1
MAPPABLE_CATEGORIES = ("REVIEW", "UNIT", "SCHOOL_PAST", "ILSAN_PAST")
CATEGORY_DISPLAY_ORDER = ("REVIEW", "UNIT", "SCHOOL_PAST", "ILSAN_PAST")
SUBJECT_DISPLAY_ORDER = ("공수1", "공수2", "대수", "미적분1", "미적분2", "기하", "확통")
TERM_CATEGORIES = frozenset(("SCHOOL_PAST", "ILSAN_PAST"))
CATEGORY_LABELS = {
    "REVIEW": "복습 테스트",
    "UNIT": "단원평가",
    "SCHOOL_PAST": "학군지 기출",
    "ILSAN_PAST": "일산 기출",
}
CATEGORY_DIFFICULTIES = {
    "REVIEW": ("상", "중상"),
    "UNIT": ("Lv.3", "Lv.4", "Lv.5", "Lv.6"),
    "SCHOOL_PAST": ("상", "중상"),
    "ILSAN_PAST": ("중", "중상", "그래프 포함"),
}
SUBJECT_ALIASES = {
    "공통수학1": "공수1",
    "공통수학2": "공수2",
    "미적1": "미적분1",
    "미적분Ⅰ": "미적분1",
    "미적분I": "미적분1",
    "미적2": "미적분2",
    "미적분Ⅱ": "미적분2",
    "미적분II": "미적분2",
    "확률과통계": "확통",
}
REGISTERED_CATALOG_COLUMNS = (
    "자료ID",
    "자료유형",
    "과목",
    "레벨",
    "시험구분",
    "회차",
    "개별번호",
    "표시이름",
    "파일명",
    "상대경로",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEST_ASSIGN_DAILY_ITEMS_KEY = "testAssignmentDailyTests"
TEST_ASSIGN_ABSENCE_CARRYOVER_KEY = "testAssignmentAbsenceCarryover"
TEST_ASSIGN_ABSENCE_SOURCE_KEY = "testAssignmentAbsenceSourceDate"


class QuickPrinterExportFailure(RuntimeError):
    def __init__(self, code: str, message: str, issues: Iterable[dict] = ()) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.issues = [dict(issue) for issue in issues if isinstance(issue, dict)]


class QuickPrinterResourceFailure(QuickPrinterExportFailure):
    pass


class NoQuickPrinterAssignments(QuickPrinterExportFailure):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canon_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value))


def canonical_sid(value: Any) -> str:
    sid = _text(value)
    if sid.isdigit():
        return str(int(sid))
    return sid


def normalize_subject(value: Any) -> str:
    compact = re.sub(r"\s+", "", _text(value))
    return SUBJECT_ALIASES.get(compact, compact or "공수1")


def _student_current_subject(student: Any) -> str:
    if not isinstance(student, dict):
        return ""
    raw = _text(
        student.get("curriculum")
        or student.get("subject")
        or student.get("course")
    )
    if not raw:
        return ""
    subject = (raw.split()[0] if raw.split() else raw).split(":", 1)[0]
    compact = re.sub(r"\s+", "", subject)
    return SUBJECT_ALIASES.get(compact, compact)


def _test_matches_student_current_subject(definition: dict, student: dict) -> bool:
    current_subject = _student_current_subject(student)
    if not current_subject:
        return True
    return normalize_subject(definition.get("curriculum")) == current_subject


def canonical_category_key(key: Any, label: Any = "") -> str:
    raw = f"{_text(key)} {_text(label)}".upper()
    compact = re.sub(r"\s+", "", f"{_text(key)} {_text(label)}")
    if "REVIEW" in raw or "복습" in compact:
        return "REVIEW"
    if "SCHOOL" in raw or "학군지" in compact:
        return "SCHOOL_PAST"
    if "ILSAN" in raw or "일산" in compact:
        return "ILSAN_PAST"
    if "UNIT" in raw or "단원" in compact:
        return "UNIT"
    return _text(key)


def normalize_difficulty(category_key: str, value: Any, name: Any = "") -> str:
    raw = _text(value)
    source = f"{raw} {_text(name)}"
    if category_key == "ILSAN_PAST" and (
        "그래프 포함" in source or "삼각함수 그래프 포함" in source or "그래프" in source
    ):
        return "그래프 포함"
    if raw in CATEGORY_DIFFICULTIES.get(category_key, ()):
        return raw
    level = re.search(r"(?:Lv\.?|LV\.?|레벨)\s*\.?\s*([3-6])", source)
    if level:
        return f"Lv.{level.group(1)}"
    if "중상" in source:
        return "중상"
    if "상" in source:
        return "중상" if category_key == "ILSAN_PAST" else "상"
    if category_key == "ILSAN_PAST" and "중" in source:
        return "중"
    difficulties = CATEGORY_DIFFICULTIES.get(category_key, ())
    return difficulties[0] if difficulties else raw


def normalize_round(value: Any, name: Any = "") -> str:
    raw = _text(value)
    match = re.search(r"(\d{1,2})\s*(?:회차|회)", f"{raw} {_text(name)}")
    if match:
        return match.group(1)
    if re.fullmatch(r"\d{1,2}", raw):
        return raw
    return raw or "1"


def round_label(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    return raw if "회" in raw else f"{raw}회차"


def normalize_term(value: Any, name: Any = "") -> str:
    source = f"{_text(value)} {_text(name)}".strip()
    if not source:
        return "기말고사"
    upper = source.upper()
    if "기말" in source or "FINAL" in upper or "END" in upper:
        return "기말고사"
    if "중간" in source or "MID" in upper or "MIDDLE" in upper:
        return "중간고사"
    return _text(value) or "기말고사"


def normalize_assignment_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    status = _text(value)
    if not status or status == "none":
        return ""
    if status in ("assigned", "done", "interrupted", "skip"):
        return status
    return "assigned"


def build_test_definitions(tests_config: dict) -> list[dict]:
    categories = tests_config.get("categories") if isinstance(tests_config, dict) else None
    if not isinstance(categories, dict):
        return []

    definitions: list[dict] = []
    for raw_category_key, category in categories.items():
        if not isinstance(category, dict):
            continue
        category_key = canonical_category_key(raw_category_key, category.get("label"))
        if category_key not in MAPPABLE_CATEGORIES:
            continue
        tests = category.get("tests")
        if not isinstance(tests, list):
            continue
        for index, raw_test in enumerate(tests):
            if not isinstance(raw_test, dict):
                continue
            name = _canon_text(raw_test.get("name") or raw_test.get("title") or f"테스트 {index + 1}")
            curriculum = normalize_subject(
                raw_test.get("curriculum") or raw_test.get("subject") or raw_test.get("course")
            )
            difficulty = normalize_difficulty(
                category_key,
                raw_test.get("difficulty") or raw_test.get("level"),
                name,
            )
            round_value = normalize_round(
                raw_test.get("round") or raw_test.get("session") or raw_test.get("no"),
                name,
            )
            term = (
                normalize_term(
                    raw_test.get("term")
                    or raw_test.get("examTerm")
                    or raw_test.get("semesterTerm"),
                    name,
                )
                if category_key in TERM_CATEGORIES
                else ""
            )
            test_id = _canon_text(raw_test.get("id"))
            label_parts = [
                CATEGORY_LABELS[category_key],
                curriculum,
                difficulty,
                term,
                round_label(round_value),
                name,
            ]
            label = " / ".join(part for part in label_parts if part)
            definitions.append(
                {
                    "id": test_id,
                    "categoryKey": category_key,
                    "curriculum": curriculum,
                    "difficulty": difficulty,
                    "term": term,
                    "round": round_value,
                    "name": name,
                    "label": label,
                    "sourceOrder": raw_test.get("sourceOrder")
                    if raw_test.get("sourceOrder") is not None
                    else raw_test.get("sortOrder"),
                    "problemFile": _text(
                        (raw_test.get("sourceFiles") or {}).get("problemFile")
                        if isinstance(raw_test.get("sourceFiles"), dict)
                        else ""
                    ),
                }
            )
    def rank(values: tuple[str, ...], value: Any) -> int:
        try:
            return values.index(_text(value))
        except ValueError:
            return len(values)

    def numeric(value: Any, fallback: int = 10**9) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return fallback

    def display_key(definition: dict):
        category_key = definition["categoryKey"]
        base = (
            rank(CATEGORY_DISPLAY_ORDER, category_key),
            rank(SUBJECT_DISPLAY_ORDER, definition["curriculum"]),
            rank(CATEGORY_DIFFICULTIES.get(category_key, ()), definition["difficulty"]),
            definition["difficulty"],
        )
        if category_key == "UNIT":
            return base + (
                numeric(definition["round"]),
                numeric(definition["sourceOrder"]),
                definition["name"],
            )
        return base + (
            numeric(definition["sourceOrder"]),
            numeric(definition["round"]),
            definition["name"],
        )

    definitions.sort(key=display_key)
    return definitions


def test_definition_signature(definition: dict) -> dict:
    return {
        key: definition.get(key, "")
        for key in (
            "id",
            "categoryKey",
            "curriculum",
            "difficulty",
            "term",
            "round",
            "name",
            "label",
            "sourceOrder",
            "problemFile",
        )
    }


def test_definitions_sha256(definitions: list[dict]) -> str:
    payload = [test_definition_signature(definition) for definition in definitions]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def catalog_row_signature(row: dict) -> dict:
    return {column: _text(row.get(column)) for column in REGISTERED_CATALOG_COLUMNS}


def read_registered_catalog(path: str | Path) -> list[dict]:
    catalog_path = Path(path)
    try:
        with catalog_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != REGISTERED_CATALOG_COLUMNS:
                raise ValueError(
                    "registered catalog columns must be: " + ",".join(REGISTERED_CATALOG_COLUMNS)
                )
            rows = [catalog_row_signature(row) for row in reader]
    except QuickPrinterExportFailure:
        raise
    except Exception as exc:
        raise QuickPrinterResourceFailure(
            "quick_printer_catalog_unreadable",
            f"빠른 인쇄기 등록 목록을 읽을 수 없습니다: {exc}",
        ) from exc
    return rows


def read_mapping_bundle(path: str | Path) -> dict:
    mapping_path = Path(path)
    try:
        value = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise QuickPrinterResourceFailure(
            "quick_printer_mapping_unreadable",
            f"빠른 인쇄기 자료ID 매핑을 읽을 수 없습니다: {exc}",
        ) from exc
    if not isinstance(value, dict):
        raise QuickPrinterResourceFailure(
            "quick_printer_mapping_invalid",
            "빠른 인쇄기 자료ID 매핑은 JSON 객체여야 합니다.",
        )
    return value


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resource_issue(code: str, reason: str, **extra: Any) -> dict:
    issue = {"code": code, "reason": reason}
    issue.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return issue


def validate_mapping_bundle(
    tests_config: dict,
    mapping_bundle: dict,
    catalog_rows: list[dict],
    *,
    catalog_sha256: str = "",
) -> dict:
    problems: list[dict] = []
    if mapping_bundle.get("version") != MAPPING_VERSION:
        problems.append(
            _resource_issue(
                "mapping_version_mismatch",
                f"지원하지 않는 매핑 버전입니다: {mapping_bundle.get('version')!r}",
            )
        )

    catalog_meta = mapping_bundle.get("catalog")
    if not isinstance(catalog_meta, dict):
        catalog_meta = {}
        problems.append(_resource_issue("catalog_metadata_missing", "매핑의 등록 목록 메타데이터가 없습니다."))
    expected_hash = _text(catalog_meta.get("sha256"))
    if catalog_sha256 and expected_hash != catalog_sha256:
        problems.append(
            _resource_issue(
                "catalog_hash_mismatch",
                "등록 테스트 목록이 매핑 생성 시점과 달라졌습니다. 매핑을 다시 생성해야 합니다.",
                expectedSha256=expected_hash,
                actualSha256=catalog_sha256,
            )
        )
    if catalog_meta.get("rowCount") != len(catalog_rows):
        problems.append(
            _resource_issue(
                "catalog_row_count_mismatch",
                "등록 테스트 목록 행 수가 매핑 메타데이터와 다릅니다.",
                expected=catalog_meta.get("rowCount"),
                actual=len(catalog_rows),
            )
        )

    catalog_by_id: dict[str, list[dict]] = {}
    for row in catalog_rows:
        material_id = _text(row.get("자료ID"))
        catalog_by_id.setdefault(material_id, []).append(row)
    duplicate_catalog_ids = sorted(
        material_id for material_id, rows in catalog_by_id.items() if not material_id or len(rows) != 1
    )
    if duplicate_catalog_ids:
        problems.append(
            _resource_issue(
                "catalog_material_id_duplicate",
                "등록 목록에 비어 있거나 중복된 자료ID가 있습니다.",
                materialIds=duplicate_catalog_ids[:25],
            )
        )

    definitions = build_test_definitions(tests_config)
    server_meta = mapping_bundle.get("server")
    if not isinstance(server_meta, dict):
        server_meta = {}
        problems.append(_resource_issue("server_metadata_missing", "매핑의 서버 시험 메타데이터가 없습니다."))
    expected_server_hash = _text(server_meta.get("signatureSha256"))
    actual_server_hash = test_definitions_sha256(definitions)
    if expected_server_hash != actual_server_hash:
        problems.append(
            _resource_issue(
                "server_catalog_signature_changed",
                "서버 시험 정의가 매핑 생성 후 변경되었습니다. 매핑을 다시 생성해야 합니다.",
                expectedSha256=expected_server_hash,
                actualSha256=actual_server_hash,
            )
        )
    if server_meta.get("definitionCount") != len(definitions):
        problems.append(
            _resource_issue(
                "server_definition_count_changed",
                "서버 시험 수가 매핑 메타데이터와 다릅니다.",
                expected=server_meta.get("definitionCount"),
                actual=len(definitions),
            )
        )
    definitions_by_id: dict[str, dict] = {}
    definitions_by_label: dict[str, list[dict]] = {}
    for definition in definitions:
        test_id = _text(definition.get("id"))
        if not test_id or test_id in definitions_by_id:
            problems.append(
                _resource_issue(
                    "server_test_id_duplicate",
                    "서버 시험 ID가 비어 있거나 중복되었습니다.",
                    testId=test_id,
                    testName=definition.get("name"),
                )
            )
            continue
        definitions_by_id[test_id] = definition
        definitions_by_label.setdefault(_text(definition.get("label")), []).append(definition)

    mappings = mapping_bundle.get("mappings")
    issues = mapping_bundle.get("issues")
    if not isinstance(mappings, dict):
        mappings = {}
        problems.append(_resource_issue("mapping_records_missing", "자료ID 매핑 레코드가 없습니다."))
    if not isinstance(issues, dict):
        issues = {}
        problems.append(_resource_issue("mapping_issues_missing", "매핑 실패 레코드가 없습니다."))

    mapped_ids = set(mappings)
    issue_ids = set(issues)
    definition_ids = set(definitions_by_id)
    overlap = sorted(mapped_ids & issue_ids)
    missing_coverage = sorted(definition_ids - mapped_ids - issue_ids)
    stale_coverage = sorted((mapped_ids | issue_ids) - definition_ids)
    if overlap:
        problems.append(
            _resource_issue(
                "mapping_coverage_overlap",
                "같은 서버 시험이 성공 매핑과 실패 목록에 동시에 존재합니다.",
                testIds=overlap[:25],
            )
        )
    if missing_coverage:
        problems.append(
            _resource_issue(
                "mapping_coverage_missing",
                "새 서버 시험이 영구 매핑에 반영되지 않았습니다.",
                testIds=missing_coverage[:25],
            )
        )
    if stale_coverage:
        problems.append(
            _resource_issue(
                "mapping_coverage_stale",
                "삭제되거나 변경된 서버 시험이 영구 매핑에 남아 있습니다.",
                testIds=stale_coverage[:25],
            )
        )

    material_to_tests: dict[str, list[str]] = {}
    for test_id, mapping in mappings.items():
        definition = definitions_by_id.get(test_id)
        if not isinstance(mapping, dict) or definition is None:
            continue
        material_id = _text(mapping.get("materialId"))
        material_to_tests.setdefault(material_id, []).append(test_id)
        rows = catalog_by_id.get(material_id) or []
        if len(rows) != 1:
            problems.append(
                _resource_issue(
                    "mapped_material_id_invalid",
                    "매핑된 자료ID가 등록 목록에 정확히 한 번 존재하지 않습니다.",
                    testId=test_id,
                    testName=definition.get("name"),
                    materialId=material_id,
                )
            )
            continue

    duplicate_mapped_materials = {
        material_id: test_ids
        for material_id, test_ids in material_to_tests.items()
        if not material_id or len(test_ids) != 1
    }
    if duplicate_mapped_materials:
        problems.append(
            _resource_issue(
                "mapping_material_id_duplicate",
                "하나의 자료ID가 여러 서버 시험에 매핑되었습니다.",
                duplicates={
                    material_id: test_ids[:10]
                    for material_id, test_ids in list(duplicate_mapped_materials.items())[:25]
                },
            )
        )

    for test_id, issue in issues.items():
        definition = definitions_by_id.get(test_id)
        if not isinstance(issue, dict) or definition is None:
            continue
        for candidate in issue.get("candidates") or []:
            material_id = _text(candidate.get("materialId") if isinstance(candidate, dict) else "")
            if material_id and material_id not in catalog_by_id:
                problems.append(
                    _resource_issue(
                        "mapping_issue_candidate_stale",
                        "미매칭 후보 자료ID가 현재 등록 목록에 없습니다.",
                        testId=test_id,
                        materialId=material_id,
                    )
                )

    if problems:
        raise QuickPrinterResourceFailure(
            "quick_printer_mapping_stale",
            "빠른 인쇄기 등록 목록 또는 영구 매핑이 현재 서버 시험 목록과 맞지 않습니다.",
            problems,
        )

    return {
        "definitionsById": definitions_by_id,
        "definitionsByLabel": definitions_by_label,
        "catalogById": {material_id: rows[0] for material_id, rows in catalog_by_id.items()},
        "mappings": mappings,
        "issues": issues,
    }


def _sid_entry(day: Any, sid: str) -> dict:
    if not isinstance(day, dict):
        return {}
    direct = day.get(sid)
    if isinstance(direct, dict):
        return direct
    canonical = canonical_sid(sid)
    for key, value in day.items():
        if canonical_sid(key) == canonical and isinstance(value, dict):
            return value
    return {}


def _log_entry(log_history: Any, date_key: str, sid: str) -> dict:
    if not isinstance(log_history, dict):
        return {}
    return _sid_entry(log_history.get(date_key), sid)


def _assignment_item_matches_definition(item: Any, definition: dict) -> bool:
    if not isinstance(item, dict):
        return False
    item_id = _text(item.get("id") or item.get("testId"))
    definition_id = _text(definition.get("id"))
    if item_id:
        return bool(definition_id) and item_id == definition_id
    return _text(item.get("label")) == _text(definition.get("label"))


def _entry_contains_assignment(entry: dict, definition: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    for field in ("assignedTests", TEST_ASSIGN_DAILY_ITEMS_KEY):
        items = entry.get(field)
        if isinstance(items, list) and any(
            _assignment_item_matches_definition(item, definition) for item in items
        ):
            return True
    return False


def _source_carryover_contains_assignment(
    source_entry: dict,
    source_date: str,
    definition: dict,
) -> bool:
    carryover = source_entry.get(TEST_ASSIGN_ABSENCE_CARRYOVER_KEY)
    if not isinstance(carryover, dict):
        return False
    if _text(carryover.get("sourceDate")) != source_date:
        return False
    items = carryover.get("assignedTests")
    return isinstance(items, list) and any(
        _assignment_item_matches_definition(item, definition)
        and normalize_assignment_status(item.get("status")) == "assigned"
        for item in items
        if isinstance(item, dict)
    )


def resolve_absence_carryover_origin_date(
    *,
    log_history: Any,
    date_str: str,
    sid: str,
    definition: dict,
) -> str:
    """Return the earliest exact absence-carryover source for one assignment."""
    current_date = _text(date_str)
    current_entry = _log_entry(log_history, current_date, sid)
    if not _entry_contains_assignment(current_entry, definition):
        return ""

    source_date = _text(current_entry.get(TEST_ASSIGN_ABSENCE_SOURCE_KEY))
    if not is_iso_date_key(source_date) or source_date >= current_date:
        return ""

    visited = {current_date}
    origin = ""
    cursor_date = current_date
    while source_date and source_date not in visited:
        if source_date >= cursor_date:
            return ""
        source_entry = _log_entry(log_history, source_date, sid)
        if not _source_carryover_contains_assignment(source_entry, source_date, definition):
            return ""
        visited.add(source_date)
        origin = source_date
        previous_source = _text(source_entry.get(TEST_ASSIGN_ABSENCE_SOURCE_KEY))
        if not is_iso_date_key(previous_source) or previous_source >= source_date:
            break
        cursor_date = source_date
        source_date = previous_source
    return origin


def _normalized_history_keys(values: Iterable[Any]) -> set[QuickPrinterHistoryKey]:
    out: set[QuickPrinterHistoryKey] = set()
    for raw in values or ():
        if isinstance(raw, dict):
            key = quick_printer_history_key(
                raw.get("studentId"),
                raw.get("testId"),
                raw.get("materialId"),
                raw.get("assignmentDate"),
            )
        elif isinstance(raw, (list, tuple)) and len(raw) == 4:
            key = quick_printer_history_key(*raw)
        else:
            continue
        if all(key[:3]) and is_iso_date_key(key[3]):
            out.add(key)
    return out


def _student_index(students: Any) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for student in students if isinstance(students, list) else []:
        if not isinstance(student, dict):
            continue
        sid = canonical_sid(student.get("id"))
        if sid and sid not in index:
            index[sid] = student
    return index


def _ordered_unique_sids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        sid = canonical_sid(value)
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _mapping_issue_for_assignment(
    stored_issue: dict,
    *,
    sid: str,
    student_name: str,
    definition: dict,
) -> dict:
    candidates = []
    for candidate in stored_issue.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        candidates.append(
            {
                "materialId": _text(candidate.get("materialId")),
                "displayName": _text(candidate.get("displayName")),
                "relativePath": _text(candidate.get("relativePath")),
            }
        )
    return {
        "code": _text(stored_issue.get("code")) or "quick_printer_material_unmapped",
        "reason": _text(stored_issue.get("reason")) or "빠른 인쇄기 자료ID가 확정되지 않았습니다.",
        "studentId": sid,
        "studentName": student_name,
        "testId": definition.get("id"),
        "testName": definition.get("name"),
        "testLabel": definition.get("label"),
        "candidates": candidates,
    }


def _write_csv(rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_COLUMNS),
        extrasaction="raise",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + buffer.getvalue()


def build_quick_printer_export(
    *,
    date_str: str,
    ordered_student_ids: list[str],
    students: Any,
    progress: Any,
    tests_config: dict,
    mapping_bundle: dict,
    catalog_rows: list[dict],
    catalog_sha256: str = "",
    log_history: Any = None,
    exported_assignment_keys: Iterable[Any] = (),
    include_previously_exported_carryovers: bool = False,
    allow_empty: bool = False,
) -> dict:
    date_key = _text(date_str)
    if not _DATE_RE.fullmatch(date_key):
        raise QuickPrinterExportFailure("invalid_date", "운영일은 YYYY-MM-DD 형식이어야 합니다.")
    try:
        dt.date.fromisoformat(date_key)
    except ValueError as exc:
        raise QuickPrinterExportFailure("invalid_date", "존재하지 않는 운영일입니다.") from exc

    ordered_sids = _ordered_unique_sids(ordered_student_ids)
    if not ordered_sids:
        raise NoQuickPrinterAssignments(
            "no_board_students",
            "현재 운영판에 내보낼 학생이 없습니다.",
        )

    validated = validate_mapping_bundle(
        tests_config,
        mapping_bundle,
        catalog_rows,
        catalog_sha256=catalog_sha256,
    )
    student_by_sid = _student_index(students)
    progress_day = progress.get(date_key) if isinstance(progress, dict) else {}
    definitions_by_label = validated["definitionsByLabel"]
    definition_order = {
        definition["id"]: index
        for index, definition in enumerate(validated["definitionsById"].values())
    }
    mappings = validated["mappings"]
    stored_issues = validated["issues"]
    known_history_keys = _normalized_history_keys(exported_assignment_keys)

    issues: list[dict] = []
    csv_rows: list[dict] = []
    history_items: list[dict] = []
    exported_students: set[str] = set()
    automatic_exclusions: list[dict] = []
    compact_date = date_key.replace("-", "")

    for sid in ordered_sids:
        student = student_by_sid.get(sid)
        if not isinstance(student, dict):
            issues.append(
                _resource_issue(
                    "board_student_not_found",
                    "운영판 학생이 최신 학생 목록에 없습니다.",
                    studentId=sid,
                )
            )
            continue
        student_name = _text(student.get("name"))
        if not student_name:
            issues.append(
                _resource_issue(
                    "board_student_name_missing",
                    "운영판 학생 이름이 비어 있습니다.",
                    studentId=sid,
                )
            )
            continue

        entry = _sid_entry(progress_day, sid)
        tests = entry.get("tests") if isinstance(entry, dict) else None
        if not isinstance(tests, dict):
            continue
        resolved_assignments: list[dict] = []
        for assignment_label, raw_status in tests.items():
            if normalize_assignment_status(raw_status) != "assigned":
                continue
            label = _text(assignment_label)
            definitions = definitions_by_label.get(label) or []
            if len(definitions) != 1:
                issues.append(
                    _resource_issue(
                        "assignment_test_not_unique",
                        "초록색 배정 이름을 서버 시험 한 개로 정확히 해석할 수 없습니다.",
                        studentId=sid,
                        studentName=student_name,
                        testLabel=label,
                        candidateCount=len(definitions),
                        candidates=[
                            {
                                "testId": item.get("id"),
                                "testName": item.get("name"),
                            }
                            for item in definitions[:10]
                        ],
                    )
                )
                continue

            definition = definitions[0]
            if not _test_matches_student_current_subject(definition, student):
                continue
            resolved_assignments.append(definition)

        resolved_assignments.sort(
            key=lambda definition: definition_order.get(_text(definition.get("id")), 10**9)
        )
        for definition in resolved_assignments:
            test_id = _text(definition.get("id"))
            mapping = mappings.get(test_id)
            if not isinstance(mapping, dict):
                stored_issue = stored_issues.get(test_id)
                if not isinstance(stored_issue, dict):
                    stored_issue = {
                        "code": "quick_printer_material_unmapped",
                        "reason": "서버 시험의 빠른 인쇄기 자료ID 매핑이 없습니다.",
                        "candidates": [],
                    }
                issues.append(
                    _mapping_issue_for_assignment(
                        stored_issue,
                        sid=sid,
                        student_name=student_name,
                        definition=definition,
                    )
                )
                continue

            material_id = _text(mapping.get("materialId"))
            carryover_origin = resolve_absence_carryover_origin_date(
                log_history=log_history,
                date_str=date_key,
                sid=sid,
                definition=definition,
            )
            assignment_date = carryover_origin or date_key
            history_key = quick_printer_history_key(
                sid,
                test_id,
                material_id,
                assignment_date,
            )
            is_absence_carryover_reassignment = bool(carryover_origin)
            was_previously_exported = history_key in known_history_keys
            if is_absence_carryover_reassignment:
                automatic_exclusions.append(
                    {
                        "studentId": sid,
                        "studentName": student_name,
                        "testId": test_id,
                        "testName": definition.get("name"),
                        "materialId": material_id,
                        "assignmentDate": assignment_date,
                        "previouslyExported": was_previously_exported,
                    }
                )
                if not include_previously_exported_carryovers:
                    continue
            csv_rows.append(
                {
                    "주문번호": f"ASSIGN-{compact_date}-{sid}-{test_id}",
                    "자료ID": material_id,
                    "학생이름": student_name,
                    "부수": 1,
                    "메모": "",
                }
            )
            history_items.append(
                {
                    "studentId": sid,
                    "testId": test_id,
                    "materialId": material_id,
                    "assignmentDate": assignment_date,
                    "exportDate": date_key,
                }
            )
            exported_students.add(sid)

    if issues:
        raise QuickPrinterExportFailure(
            "quick_printer_export_blocked",
            "미매칭 또는 중복 매칭 시험이 있어 CSV 전체 생성을 중단했습니다.",
            issues,
        )
    automatic_exclusion_students = {
        item["studentId"] for item in automatic_exclusions if item.get("studentId")
    }
    automatic_exclusion_count = len(automatic_exclusions)
    automatic_exclusion_student_count = len(automatic_exclusion_students)
    if not csv_rows and automatic_exclusion_count:
        message = (
            f"결석 이월 재배정 {automatic_exclusion_count}건({automatic_exclusion_student_count}명)은 "
            "원래 배정 때 이미 출력된 항목으로 보아 자동 제외되었습니다. "
            "재인쇄 옵션을 켜면 포함할 수 있습니다."
        )
        if not allow_empty:
            raise NoQuickPrinterAssignments(
                "no_new_assignments_after_carryover_exclusion",
                message,
                (
                    {
                        "code": "previously_exported_absence_carryover",
                        "reason": message,
                        "studentCount": automatic_exclusion_student_count,
                        "assignmentCount": automatic_exclusion_count,
                    },
                ),
            )
        return {
            "rowCount": 0,
            "studentCount": 0,
            "date": date_key,
            "automaticExclusionCount": automatic_exclusion_count,
            "automaticExclusionStudentCount": automatic_exclusion_student_count,
            "includedReprints": bool(include_previously_exported_carryovers),
            "message": message,
            "historyItems": [],
        }
    if not csv_rows:
        raise NoQuickPrinterAssignments(
            "no_assigned_tests",
            f"{date_key} 운영판에 초록색으로 배정된 테스트가 없습니다.",
        )

    return {
        "filename": f"빠른인쇄기_테스트인쇄_{compact_date}.csv",
        "csv": _write_csv(csv_rows),
        "rowCount": len(csv_rows),
        "studentCount": len(exported_students),
        "date": date_key,
        "automaticExclusionCount": automatic_exclusion_count,
        "automaticExclusionStudentCount": automatic_exclusion_student_count,
        "includedReprints": bool(include_previously_exported_carryovers),
        "historyItems": history_items,
    }


__all__ = (
    "CATEGORY_LABELS",
    "CSV_COLUMNS",
    "MAPPABLE_CATEGORIES",
    "MAPPING_VERSION",
    "NoQuickPrinterAssignments",
    "QuickPrinterExportFailure",
    "QuickPrinterResourceFailure",
    "REGISTERED_CATALOG_COLUMNS",
    "build_quick_printer_export",
    "build_test_definitions",
    "canonical_category_key",
    "catalog_row_signature",
    "file_sha256",
    "normalize_difficulty",
    "normalize_subject",
    "normalize_term",
    "resolve_absence_carryover_origin_date",
    "read_mapping_bundle",
    "read_registered_catalog",
    "test_definition_signature",
    "test_definitions_sha256",
    "validate_mapping_bundle",
)
