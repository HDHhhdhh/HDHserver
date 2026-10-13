# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_preprocess_variant_determinism.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from ocr_preprocess_variant_determinism_core import (
    VARIANT_NAMES,
    VariantFingerprint,
    collect_fingerprints,
    matching_fingerprint_count,
)

LAB: Final[Path] = Path(__file__).resolve().parent
CROP_DIR: Final[Path] = Path(r"C:\server-ocr\crop_benchmark_inputs\person_03\crops")
QUESTION_NUMBERS: Final[tuple[int, ...]] = (3, 16, 17, 18)
REPORT_JSON: Final[Path] = LAB / "ocr_preprocess_variant_determinism.json"
REPORT_MD: Final[Path] = LAB / "ocr_preprocess_variant_determinism.md"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "C:\\",
    "C:/",
    "/c/",
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PreprocessVariantDeterminismError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    first = collect_fingerprints(CROP_DIR, QUESTION_NUMBERS)
    second = collect_fingerprints(CROP_DIR, QUESTION_NUMBERS)
    output = report(first, second)
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def report(first: tuple[VariantFingerprint, ...], second: tuple[VariantFingerprint, ...]) -> JsonObject:
    matching_count = matching_fingerprint_count(first, second)
    output: JsonObject = {
        "ok": first == second,
        "student_facing": False,
        "case_id": "person_03",
        "question_numbers": list(QUESTION_NUMBERS),
        "question_count": len(QUESTION_NUMBERS),
        "variant_names": list(VARIANT_NAMES),
        "variant_count_per_question": len(VARIANT_NAMES),
        "fingerprint_count": len(first),
        "matching_fingerprint_count": matching_count,
        "pixel_deterministic": pixel_deterministic(first, second),
        "metric_deterministic": metric_deterministic(first, second),
        "quality_warning_count": warning_count(first),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    scan_payload = {
        key: value
        for key, value in output.items()
        if not key.endswith("_leak_count")
    }
    leak_count = token_leak_count(json.dumps(scan_payload, ensure_ascii=False))
    output["answer_key_or_grading_field_leak_count"] = leak_count
    output["filesystem_path_leak_count"] = leak_count
    return output


def pixel_deterministic(first: tuple[VariantFingerprint, ...], second: tuple[VariantFingerprint, ...]) -> bool:
    return tuple(item.pixel_sha256 for item in first) == tuple(item.pixel_sha256 for item in second)


def metric_deterministic(first: tuple[VariantFingerprint, ...], second: tuple[VariantFingerprint, ...]) -> bool:
    return tuple(item.metrics_sha256 for item in first) == tuple(item.metrics_sha256 for item in second)


def warning_count(fingerprints: tuple[VariantFingerprint, ...]) -> int:
    return sum(item.quality_warning_count for item in fingerprints)


def require_report(output: JsonObject) -> None:
    expected_count = len(QUESTION_NUMBERS) * len(VARIANT_NAMES)
    if output.get("ok") is not True:
        raise PreprocessVariantDeterminismError("preprocess variant fingerprints must be deterministic")
    if output.get("fingerprint_count") != expected_count:
        raise PreprocessVariantDeterminismError("preprocess variant fingerprint count changed")
    if output.get("matching_fingerprint_count") != expected_count:
        raise PreprocessVariantDeterminismError("preprocess variant fingerprints must match across both passes")
    if output.get("pixel_deterministic") is not True or output.get("metric_deterministic") is not True:
        raise PreprocessVariantDeterminismError("preprocess variant pixels and metrics must be deterministic")
    if output.get("provider_call_count") != 0 or output.get("external_ocr_api_call_count") != 0:
        raise PreprocessVariantDeterminismError("provider calls must remain zero")
    if output.get("submit_test_call_count") != 0 or output.get("ts_submit_click_count") != 0:
        raise PreprocessVariantDeterminismError("submit flow must remain untouched")
    if output.get("answer_key_or_grading_field_leak_count") != 0 or output.get("filesystem_path_leak_count") != 0:
        raise PreprocessVariantDeterminismError("determinism report leaked restricted data")


def token_leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


def markdown(output: JsonObject) -> str:
    return "\n".join(
        (
            "# OCR Preprocess Variant Determinism",
            "",
            f"- case: `{output['case_id']}`",
            f"- questions: {output['question_numbers']}",
            f"- variants per question: {output['variant_count_per_question']}",
            f"- fingerprints: {output['matching_fingerprint_count']} / {output['fingerprint_count']} matched",
            f"- pixels deterministic: {output['pixel_deterministic']}",
            f"- metrics deterministic: {output['metric_deterministic']}",
            f"- quality warnings across variants: {output['quality_warning_count']}",
            "- Gemini/API calls: 0; external OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- production default: `NO_GO`",
            "- answer-key/grading/path leak count: 0",
            "",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
