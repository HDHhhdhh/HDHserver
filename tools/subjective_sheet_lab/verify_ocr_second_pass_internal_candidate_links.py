# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_second_pass_internal_candidate_links.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_local_candidate_tools import CandidateToolConfig, run_candidate_tool_dry_run  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

REQUEST_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_person_second_pass_request_manifests.json"
OUT_DIR: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/person_second_pass_request_manifests/person_03_local_candidate_report"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_internal_candidate_links.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_second_pass_internal_candidate_links.md"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "report_path",
    "C:\\",
    "C:/",
    "/c/",
)


@dataclass(frozen=True, slots=True)
class RequestItem:
    question_no: int
    artifact_file: str
    action: str


@dataclass(frozen=True, slots=True)
class CandidateLink:
    question_no: int
    artifact_file: str
    local_candidate_status: str
    model_load_allowed: bool
    candidate_signal_count: int
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class CandidateToolStatus:
    tesseract: str
    paddleocr: str
    pix2tex: str


@dataclass(frozen=True, slots=True)
class InternalCandidateLinkError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    request_items = person_03_request_items(read_json_object(REQUEST_JSON))
    tool_report = run_candidate_tool_dry_run(candidate_config())
    status = tool_status(tool_report)
    assert_tool_report(tool_report)
    links = tuple(candidate_link(item) for item in request_items)
    output = output_json(links, status)
    output["sensitive_field_leak_count"] = leak_count(json.dumps(output, ensure_ascii=False))
    if output["sensitive_field_leak_count"] != 0:
        raise InternalCandidateLinkError("sensitive token leaked into internal candidate links")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(links, status), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def candidate_config() -> CandidateToolConfig:
    return CandidateToolConfig(
        crop_dir=Path("C:/server-ocr/crop_benchmark_inputs/person_03/crops"),
        out_dir=OUT_DIR,
        test_id="t_unit_daesu_01_lv3_r1",
        questions=(16, 17),
        run_tesseract=False,
        run_paddle=False,
        run_pix2tex=False,
        allow_model_load=False,
    )


def person_03_request_items(payload: JsonObject) -> tuple[RequestItem, ...]:
    cases = require_list(payload.get("cases"), "cases")
    for raw_case in cases:
        case = require_object(raw_case, "cases[]")
        if require_text(case.get("case_id"), "case_id") == "person_03":
            return tuple(parse_request_item(value) for value in require_list(case.get("request_items"), "request_items"))
    raise InternalCandidateLinkError("person_03 request case missing")


def parse_request_item(value: JsonValue) -> RequestItem:
    item = require_object(value, "request_items[]")
    return RequestItem(
        question_no=require_int(item.get("question_no"), "question_no"),
        artifact_file=require_text(item.get("artifact_file"), "artifact_file"),
        action=require_text(item.get("action"), "action"),
    )


def candidate_link(item: RequestItem) -> CandidateLink:
    if item.action != "USER_APPROVAL_REQUIRED":
        raise InternalCandidateLinkError("request item must require user approval")
    return CandidateLink(item.question_no, item.artifact_file, "dry_run_candidate_slot_only", False, 0, False)


def tool_status(report: JsonObject) -> CandidateToolStatus:
    return CandidateToolStatus(
        tesseract=section_status(report, "tesseract"),
        paddleocr=section_status(report, "paddleocr"),
        pix2tex=section_status(report, "pix2tex"),
    )


def section_status(report: JsonObject, key: str) -> str:
    section = require_object(report.get(key), key)
    return require_text(section.get("status"), f"{key}.status")


def assert_tool_report(report: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count"):
        require_int_value(report.get(key), 0, key)
    if require_bool(report.get("student_facing"), "student_facing"):
        raise InternalCandidateLinkError("local candidate report must not be student-facing")


def output_json(links: tuple[CandidateLink, ...], status: CandidateToolStatus) -> JsonObject:
    if [link.question_no for link in links] != [16, 17]:
        raise InternalCandidateLinkError("internal candidate links must be q016/q017")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "linked_question_count": len(links),
        "candidate_signal_count": 0,
        "model_load_allowed": False,
        "auto_confirm_allowed_count": 0,
        "tool_status": asdict(status),
        "links": [asdict(link) for link in links],
        "filesystem_path_leak_count": 0,
    }


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise InternalCandidateLinkError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise InternalCandidateLinkError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise InternalCandidateLinkError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_bool(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise InternalCandidateLinkError(f"{label} must be boolean")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise InternalCandidateLinkError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise InternalCandidateLinkError(f"{label} expected {expected}, got {actual}")


def markdown_report(links: tuple[CandidateLink, ...], status: CandidateToolStatus) -> str:
    lines = ["# OCR Second-Pass Internal Candidate Links", "", "| q | Artifact | Local candidate status | Auto-confirm |", "|---:|---|---|---:|"]
    for link in links:
        lines.append(f"| {link.question_no} | `{link.artifact_file}` | `{link.local_candidate_status}` | 0 |")
    lines.extend(
        (
            "",
            f"- Tesseract status: `{status.tesseract}`",
            f"- PaddleOCR status: `{status.paddleocr}`",
            f"- pix2tex status: `{status.pix2tex}`",
            "- Model load allowed: false",
            "- Candidate signal count: 0",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
        )
    )
    return "\n".join(lines) + "\n"


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
