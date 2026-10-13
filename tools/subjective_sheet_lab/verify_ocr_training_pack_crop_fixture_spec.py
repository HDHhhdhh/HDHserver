# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_training_pack_crop_fixture_spec.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

LAB: Final[Path] = Path(__file__).resolve().parent
SPEC_JSON: Final[Path] = LAB / "ocr_training_pack_crop_fixture_spec.json"
READINESS_JSON: Final[Path] = LAB / "ocr_training_pack_crop_fixture_readiness.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_crop_fixture_spec_verification.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_crop_fixture_spec_verification.md"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

TARGET_IDS: Final[tuple[str, ...]] = (
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
)


class TargetReport(TypedDict):
    test_id: str
    round: int
    crop_file_count: int
    has_full_sheet: bool
    has_contact_sheet: bool
    has_manifest: bool
    has_quality_report: bool
    has_cache_replay_payload: bool
    capture_ready: bool


class Verification(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    production_default: str
    target_count: int
    required_crop_count_per_target: int
    current_complete_fixture_count: int
    capture_required_count: int
    readiness_status: str
    readiness_complete_crop_set_count: int
    targets: list[TargetReport]
    sensitive_field_leak_count: int
    filesystem_path_leak_count: int


class FixtureSpecError(Exception):
    pass


def main() -> int:
    verification = build_verification()
    REPORT_JSON.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(verification), encoding="utf-8")
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    return 0


def build_verification() -> Verification:
    spec = require_object(read_json(SPEC_JSON), "spec")
    readiness = require_object(read_json(READINESS_JSON), "readiness")
    require_common(spec)
    require_text(spec.get("source_readiness_artifact"), "ocr_training_pack_crop_fixture_readiness.json", "spec.source_readiness_artifact")
    require_int(spec.get("target_count"), 4, "spec.target_count")
    require_int(spec.get("required_crop_count_per_target"), 20, "spec.required_crop_count_per_target")
    require_text(spec.get("required_question_range"), "q001-q020", "spec.required_question_range")
    require_text(spec.get("fixture_root"), "tools/subjective_sheet_lab/visual_evidence/training_pack_crop_fixtures", "spec.fixture_root")
    require_int(readiness.get("target_count"), 4, "readiness.target_count")
    require_int(readiness.get("postprocess_verified_count"), 4, "readiness.postprocess_verified_count")
    require_int(readiness.get("complete_crop_set_count"), 0, "readiness.complete_crop_set_count")
    require_text(readiness.get("status"), "TRAINING_PACK_CROP_FIXTURES_MISSING", "readiness.status")
    target_reports = target_reports_from(spec)
    complete = sum(1 for item in target_reports if item["capture_ready"])
    text = SPEC_JSON.read_text(encoding="utf-8") + REPORT_MD.name
    return {
        "ok": True,
        "student_facing": False,
        "status": "FIXTURE_SPEC_VERIFIED_CAPTURE_REQUIRED",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(target_reports),
        "required_crop_count_per_target": 20,
        "current_complete_fixture_count": complete,
        "capture_required_count": len(target_reports) - complete,
        "readiness_status": "TRAINING_PACK_CROP_FIXTURES_MISSING",
        "readiness_complete_crop_set_count": 0,
        "targets": target_reports,
        "sensitive_field_leak_count": sensitive_leak_count(text),
        "filesystem_path_leak_count": filesystem_path_leak_count(text),
    }


def target_reports_from(spec: dict[str, JsonValue]) -> list[TargetReport]:
    targets = require_array(spec.get("targets"), "spec.targets")
    if len(targets) != len(TARGET_IDS):
        raise FixtureSpecError(f"expected {len(TARGET_IDS)} targets, got {len(targets)}")
    reports: list[TargetReport] = []
    seen: set[str] = set()
    for raw_target in targets:
        target = require_object(raw_target, "spec.targets[]")
        test_id = require_text_only(target.get("test_id"), "target.test_id")
        if test_id not in TARGET_IDS:
            raise FixtureSpecError(f"unexpected target: {test_id}")
        if test_id in seen:
            raise FixtureSpecError(f"duplicate target: {test_id}")
        seen.add(test_id)
        reports.append(target_report(target, test_id))
    if tuple(sorted(seen)) != tuple(sorted(TARGET_IDS)):
        raise FixtureSpecError("target set does not match expected Training Pack ids")
    return reports


def target_report(target: dict[str, JsonValue], test_id: str) -> TargetReport:
    round_no = require_int_only(target.get("round"), "target.round")
    fixture_dir = LAB.parent.parent / require_text_only(target.get("fixture_dir"), "target.fixture_dir")
    crop_count = len(list((fixture_dir / "crops").glob("q[0-9][0-9][0-9].png")))
    has_full_sheet = (fixture_dir / "full_sheet.jpg").is_file() or (fixture_dir / "full_sheet.png").is_file()
    has_contact_sheet = (fixture_dir / "contact_sheets" / "contact_01.png").is_file()
    has_manifest = (fixture_dir / "asset_manifest.json").is_file()
    has_quality_report = (fixture_dir / "crop_quality_report.json").is_file()
    has_cache_replay_payload = (fixture_dir / "review_payload_cache.json").is_file()
    ready = crop_count == 20 and has_full_sheet and has_contact_sheet and has_manifest and has_quality_report and has_cache_replay_payload
    return {
        "test_id": test_id,
        "round": round_no,
        "crop_file_count": crop_count,
        "has_full_sheet": has_full_sheet,
        "has_contact_sheet": has_contact_sheet,
        "has_manifest": has_manifest,
        "has_quality_report": has_quality_report,
        "has_cache_replay_payload": has_cache_replay_payload,
        "capture_ready": ready,
    }


def require_common(payload: dict[str, JsonValue]) -> None:
    if payload.get("ok") is not True or payload.get("student_facing") is not False:
        raise FixtureSpecError("spec common safety flags are invalid")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int(payload.get(key), 0, f"spec.{key}")
    require_text(payload.get("production_default"), "NO_GO", "spec.production_default")
    require_int(payload.get("sensitive_field_leak_count"), 0, "spec.sensitive_field_leak_count")
    require_int(payload.get("filesystem_path_leak_count"), 0, "spec.filesystem_path_leak_count")


def markdown_report(verification: Verification) -> str:
    lines = [
        "# OCR Training Pack Crop Fixture Spec Verification",
        "",
        f"- status: `{verification['status']}`",
        f"- targets: {verification['target_count']}",
        f"- complete fixture sets: {verification['current_complete_fixture_count']}",
        f"- capture-required targets: {verification['capture_required_count']}",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- production default: `NO-GO`",
        "",
        "| test_id | round | crops | full sheet | contact | manifest | quality | cache | ready |",
        "|---|---:|---:|---|---|---|---|---|---|",
    ]
    for target in verification["targets"]:
        lines.append(target_row(target))
    lines.append("")
    return "\n".join(lines)


def target_row(target: TargetReport) -> str:
    return (
        f"| `{target['test_id']}` | {target['round']} | {target['crop_file_count']} | {target['has_full_sheet']} | "
        f"{target['has_contact_sheet']} | {target['has_manifest']} | {target['has_quality_report']} | "
        f"{target['has_cache_replay_payload']} | {target['capture_ready']} |"
    )


def sensitive_leak_count(text: str) -> int:
    forbidden = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect")
    return sum(text.count(token) for token in forbidden)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/")


def read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise FixtureSpecError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise FixtureSpecError(f"{label} must be a JSON array")
    return value


def require_int(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int_only(value, label)
    if actual != expected:
        raise FixtureSpecError(f"{label} expected {expected}, got {actual}")


def require_int_only(value: JsonValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FixtureSpecError(f"{label} must be an integer")
    return value


def require_text(value: JsonValue, expected: str, label: str) -> None:
    actual = require_text_only(value, label)
    if actual != expected:
        raise FixtureSpecError(f"{label} expected {expected}, got {actual}")


def require_text_only(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise FixtureSpecError(f"{label} must be text")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
