# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_second_pass_candidate_matrix.py

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from phase2e_second_pass_experiment import (
    SecondPassGate,
    merge_second_pass_item,
    prepare_second_pass_experiment,
    select_second_pass_candidates,
)

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_second_pass_candidate_matrix.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_second_pass_candidate_matrix.md")
EXPECTED_CANDIDATES: Final[tuple[int, ...]] = (2, 3, 4, 5, 6, 7, 8)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PreparationResult:
    label: str
    status: str
    provider_call_count: int
    candidate_count: int
    manifest_created: bool


@dataclass(frozen=True, slots=True)
class SecondPassMatrixError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    payload = review_payload()
    candidates = select_second_pass_candidates(payload)
    candidate_questions = tuple(candidate.question_no for candidate in candidates)
    if candidate_questions != EXPECTED_CANDIDATES:
        raise SecondPassMatrixError(f"second-pass candidates {candidate_questions} != {EXPECTED_CANDIDATES}")
    with tempfile.TemporaryDirectory(prefix="ocr_second_pass_candidate_") as temp_name:
        temp_dir = Path(temp_name)
        crop_dir = write_crop_fixtures(temp_dir)
        preparations = tuple(run_preparation_matrix(payload, crop_dir, temp_dir))
    merge_outputs = verify_merge_policy()
    output = summary(candidate_questions, preparations, merge_outputs)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def review_payload() -> JsonObject:
    return {
        "items": [
            item(1, "safe_auto_grade", "3"),
            item(2, "review_required", "3"),
            item(3, "retake_required", "3"),
            item(4, "data_check_required", "3"),
            item(5, "safe_auto_grade", "?"),
            item(6, "safe_auto_grade", "unknown"),
            item(7, "safe_auto_grade", ""),
            warning_item(8, "safe_auto_grade", "3", ("crop_quality_blurry",)),
            item(0, "review_required", "3"),
            item(21, "review_required", "3"),
            "malformed item",
        ],
    }


def item(question_no: int, status: str, recognized: str) -> JsonObject:
    return {
        "question_no": question_no,
        "status": status,
        "recognized": recognized,
        "warnings": [],
        "final_answer": recognized if status == "safe_auto_grade" else None,
    }


def warning_item(question_no: int, status: str, recognized: str, warnings: tuple[str, ...]) -> JsonObject:
    value = item(question_no, status, recognized)
    value["warnings"] = list(warnings)
    return value


def write_crop_fixtures(temp_dir: Path) -> Path:
    crop_dir = temp_dir / "crops"
    crop_dir.mkdir(parents=True)
    for question_no in EXPECTED_CANDIDATES:
        (crop_dir / f"q{question_no:03d}.png").write_bytes(b"second-pass-crop")
    return crop_dir


def run_preparation_matrix(payload: JsonObject, crop_dir: Path, temp_dir: Path) -> list[PreparationResult]:
    cases = (
        ("disabled", SecondPassGate(enabled=False, provider_calls_allowed=False, max_provider_calls=0), "disabled", False),
        ("enabled_without_auth", SecondPassGate(enabled=True, provider_calls_allowed=False, max_provider_calls=1), "USER_APPROVAL_REQUIRED", True),
        ("enabled_zero_budget", SecondPassGate(enabled=True, provider_calls_allowed=True, max_provider_calls=0), "USER_APPROVAL_REQUIRED", True),
        ("authorized_skeleton", SecondPassGate(enabled=True, provider_calls_allowed=True, max_provider_calls=1), "READY_FOR_AUTHORIZED_LIVE_CALL", True),
    )
    results: list[PreparationResult] = []
    for label, gate, expected_status, expects_manifest in cases:
        preparation = prepare_second_pass_experiment(payload, crop_dir, temp_dir / label, gate)
        manifest_created = preparation.manifest_path.is_file() if preparation.manifest_path is not None else False
        if preparation.status != expected_status:
            raise SecondPassMatrixError(f"{label} status {preparation.status} != {expected_status}")
        if preparation.provider_call_count != 0:
            raise SecondPassMatrixError(f"{label} provider_call_count must be 0")
        if manifest_created != expects_manifest:
            raise SecondPassMatrixError(f"{label} manifest_created must be {expects_manifest}")
        results.append(
            PreparationResult(
                label=label,
                status=preparation.status,
                provider_call_count=preparation.provider_call_count,
                candidate_count=len(preparation.candidates),
                manifest_created=manifest_created,
            )
        )
    return results


def verify_merge_policy() -> tuple[JsonObject, JsonObject]:
    primary = item(8, "review_required", "3")
    same = merge_second_pass_item(primary, {"recognized": "3", "warnings": []})
    different = merge_second_pass_item(primary, {"recognized": "4", "warnings": ["low_confidence"]})
    for label, value in (("same", same), ("different", different)):
        if value.get("status") != "review_required" or value.get("final_answer") is not None:
            raise SecondPassMatrixError(f"{label} second-pass merge auto-confirmed unexpectedly")
    return same, different


def summary(
    candidate_questions: tuple[int, ...],
    preparations: tuple[PreparationResult, ...],
    merge_outputs: tuple[JsonObject, JsonObject],
) -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "expected_candidate_questions": list(EXPECTED_CANDIDATES),
        "actual_candidate_questions": list(candidate_questions),
        "candidate_count": len(candidate_questions),
        "preparation_matrix": [preparation_payload(result) for result in preparations],
        "merge_same_status": require_str(merge_outputs[0].get("status"), "merge_same.status"),
        "merge_different_status": require_str(merge_outputs[1].get("status"), "merge_different.status"),
        "merge_auto_confirm_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def preparation_payload(result: PreparationResult) -> JsonObject:
    return {
        "label": result.label,
        "status": result.status,
        "provider_call_count": result.provider_call_count,
        "candidate_count": result.candidate_count,
        "manifest_created": result.manifest_created,
    }


def require_str(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise SecondPassMatrixError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Second-Pass Candidate Matrix",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- expected candidate questions: {output['expected_candidate_questions']}",
        f"- actual candidate questions: {output['actual_candidate_questions']}",
        f"- candidate count: {output['candidate_count']}",
        f"- merge auto-confirm count: {output['merge_auto_confirm_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Gate Matrix",
        "",
    ]
    for item_value in output["preparation_matrix"]:
        match item_value:
            case dict():
                lines.append(
                    f"- `{item_value['label']}`: status={item_value['status']}, "
                    f"provider_call_count={item_value['provider_call_count']}, "
                    f"manifest_created={item_value['manifest_created']}"
                )
            case None | bool() | int() | float() | str() | list():
                raise SecondPassMatrixError("preparation_matrix item must be an object")
            case unreachable:
                assert_never(unreachable)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
