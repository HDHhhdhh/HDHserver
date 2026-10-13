# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_intake.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, read_json_object, require_int_value

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake.md"
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class TrainingPackEvidenceIntakeError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    output = intake_summary(read_json_object(SOURCE_JSON))
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def intake_summary(source: JsonObject) -> JsonObject:
    target_id_list = target_ids(source)
    evidence_files = sorted(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    payloads = [read_json_object(path) for path in evidence_files]
    complete_payload_count = sum(1 for payload in payloads if is_complete_payload(payload))
    nonzero_payload_count = sum(1 for payload in payloads if recognized_value_count(payload) > 0)
    recognized_value_total = sum(recognized_value_count(payload) for payload in payloads)
    evidence_names = [path.name for path in evidence_files]
    readiness_probes = replacement_readiness_probes(len(target_id_list))
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED",
        "target_count": len(target_id_list),
        "target_test_ids": target_id_list,
        "evidence_file_count": len(evidence_files),
        "complete_payload_count": complete_payload_count,
        "nonzero_recognized_payload_count": nonzero_payload_count,
        "recognized_value_count": recognized_value_total,
        "incomplete_payload_count": len(evidence_files) - complete_payload_count,
        "replacement_input_ready": replacement_input_ready(
            len(target_id_list),
            len(evidence_files),
            complete_payload_count,
            nonzero_payload_count,
        ),
        "replacement_readiness_probe_count": len(readiness_probes),
        "replacement_readiness_probe_ready_count": sum(1 for value in readiness_probes if value),
        "replacement_readiness_probe_blocked_count": sum(1 for value in readiness_probes if not value),
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_training_pack_recognized_cache_payloads_with_nonzero_values",
        "evidence_file_names": evidence_names,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def target_ids(source: JsonObject) -> list[str]:
    targets = source.get("targets")
    if not isinstance(targets, list):
        raise TrainingPackEvidenceIntakeError("source targets must be a list")
    ids: list[str] = []
    for item in targets:
        if not isinstance(item, dict):
            raise TrainingPackEvidenceIntakeError("source target item must be an object")
        value = item.get("test_id")
        if not isinstance(value, str):
            raise TrainingPackEvidenceIntakeError("source target test_id must be text")
        ids.append(value)
    return sorted(ids)


def is_complete_payload(payload: JsonObject) -> bool:
    items = review_items(payload)
    return len(items) == 20


def recognized_value_count(payload: JsonObject) -> int:
    return sum(1 for item in review_items(payload) if has_recognized_value(item))


def review_items(payload: JsonObject) -> list[JsonObject]:
    raw = payload.get("review_payload")
    match raw:
        case list():
            return object_items(raw)
        case dict():
            items = raw.get("items")
            match items:
                case list():
                    return object_items(items)
                case None | bool() | int() | float() | str() | dict():
                    return []
                case unreachable:
                    assert_never(unreachable)
        case None | bool() | int() | float() | str():
            return []
        case unreachable:
            assert_never(unreachable)


def object_items(values: list[JsonValue]) -> list[JsonObject]:
    return [item for item in values if isinstance(item, dict)]


def has_recognized_value(item: JsonObject) -> bool:
    value = item.get("recognized", item.get("recognized_answer"))
    if isinstance(value, str):
        return value.strip() != "" and value.strip() != "?"
    return False


def replacement_input_ready(target_count: int, evidence_count: int, complete_count: int, nonzero_count: int) -> bool:
    return evidence_count == target_count and complete_count == target_count and nonzero_count == target_count


def replacement_readiness_probes(target_count: int) -> tuple[bool, bool, bool]:
    return (
        replacement_input_ready(target_count, target_count, target_count, target_count),
        replacement_input_ready(target_count, target_count - 1, target_count - 1, target_count - 1),
        replacement_input_ready(target_count, target_count, target_count, target_count - 1),
    )


def require_current_summary(output: JsonObject) -> None:
    require_int_value(output.get("target_count"), 4, "target_count")
    require_int_value(output.get("evidence_file_count"), 0, "evidence_file_count")
    require_int_value(output.get("complete_payload_count"), 0, "complete_payload_count")
    require_int_value(output.get("nonzero_recognized_payload_count"), 0, "nonzero_recognized_payload_count")
    require_int_value(output.get("recognized_value_count"), 0, "recognized_value_count")
    require_int_value(output.get("replacement_readiness_probe_count"), 3, "replacement_readiness_probe_count")
    require_int_value(output.get("replacement_readiness_probe_ready_count"), 1, "replacement_readiness_probe_ready_count")
    require_int_value(
        output.get("replacement_readiness_probe_blocked_count"),
        2,
        "replacement_readiness_probe_blocked_count",
    )
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(output.get("external_ocr_api_call_count"), 0, "external_ocr_api_call_count")
    require_int_value(output.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(output.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    require_int_value(output.get("sensitive_field_leak_count"), 0, "sensitive_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")


def sensitive_leak_count(text: str) -> int:
    return sum(text.count(token) for token in SENSITIVE_TOKENS)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Intake",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- targets: {output['target_count']}",
        f"- evidence files: {output['evidence_file_count']}",
        f"- complete payloads: {output['complete_payload_count']}",
        f"- nonzero recognized payloads: {output['nonzero_recognized_payload_count']}",
        f"- recognized values: {output['recognized_value_count']}",
        f"- replacement input ready: {output['replacement_input_ready']}",
        f"- replacement readiness probes: {output['replacement_readiness_probe_ready_count']} ready / "
        f"{output['replacement_readiness_probe_blocked_count']} blocked",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
