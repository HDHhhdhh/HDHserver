from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias, TypedDict

from ocr_preflight_environment_matrix_model import LAB, JsonValue

FreshnessStatus: TypeAlias = Literal["fresh_and_consistent", "stale_or_inconsistent"]
REPORT_FRESHNESS_JSON: Final[Path] = LAB / "ocr_preflight_report_freshness.json"
REPORT_FRESHNESS_MD: Final[Path] = LAB / "ocr_preflight_report_freshness.md"
ZERO_COUNT_FIELDS: Final[tuple[str, ...]] = (
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
)
AGREEMENT_FIELDS: Final[tuple[str, ...]] = (
    *ZERO_COUNT_FIELDS,
    "production_default",
    "extended_gate_count",
    "preflight_script_modified",
)


@dataclass(frozen=True, slots=True)
class ParsedReport:
    label: str
    path: Path
    exists: bool
    modified_ns: int | None
    data: dict[str, JsonValue] | None


class FreshnessReport(TypedDict):
    ok: bool
    status: FreshnessStatus
    student_facing: bool
    matrix_report: str
    classifier_report: str
    matrix_exists: bool
    classifier_exists: bool
    matrix_modified_ns: int | None
    classifier_modified_ns: int | None
    classifier_newer_than_matrix: bool
    matrix_ok: bool
    classifier_ok: bool
    classifier_status: str
    matrix_path_matches: bool
    counts_agree: bool
    zero_call_counts: bool
    zero_leak_counts: bool
    production_default: str
    production_default_no_go: bool
    preflight_script_modified: bool
    extended_gate_count: int | None
    issue_count: int
    issues: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    next_safe_action: str
