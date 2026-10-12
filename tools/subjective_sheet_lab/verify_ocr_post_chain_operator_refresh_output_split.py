# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_operator_refresh_output_split.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_int_value,
    require_text_value,
)

REFRESH_SCRIPT: Final[Path] = LAB / "verify_ocr_post_chain_operator_refresh.py"
MODEL_SCRIPT: Final[Path] = LAB / "ocr_post_chain_operator_refresh_model.py"
OUTPUT_SCRIPT: Final[Path] = LAB / "ocr_post_chain_operator_refresh_output.py"
REFRESH_REPORT: Final[Path] = LAB / "ocr_post_chain_operator_refresh.json"
REPORT_JSON: Final[Path] = LAB / "ocr_post_chain_operator_refresh_output_split.json"
REPORT_MD: Final[Path] = LAB / "ocr_post_chain_operator_refresh_output_split.md"


@dataclass(frozen=True, slots=True)
class FileContract:
    label: str
    path: Path
    max_pure_loc: int
    required_snippets: tuple[str, ...]
    forbidden_snippets: tuple[str, ...]


CONTRACTS: Final[tuple[FileContract, ...]] = (
    FileContract(
        "refresh_wrapper",
        REFRESH_SCRIPT,
        220,
        (
            "from ocr_post_chain_operator_refresh_model import PostChainOperatorRefreshReport, RefreshStepRow",
            "from ocr_post_chain_operator_refresh_output import markdown",
        ),
        (
            "def markdown(",
            "class RefreshStepRow",
            "class PostChainOperatorRefreshReport",
        ),
    ),
    FileContract(
        "refresh_model",
        MODEL_SCRIPT,
        80,
        ("class RefreshStepRow(TypedDict):", "class PostChainOperatorRefreshReport(TypedDict):"),
        (),
    ),
    FileContract(
        "refresh_output",
        OUTPUT_SCRIPT,
        80,
        ("SUMMARY_FIELDS", "def markdown(report: PostChainOperatorRefreshReport) -> str:"),
        (),
    ),
)


def main() -> int:
    refresh_report = read_json_object(REFRESH_REPORT)
    checks = [check_contract(contract) for contract in CONTRACTS]
    report = build_report(checks, refresh_report)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def check_contract(contract: FileContract) -> JsonObject:
    text = contract.path.read_text(encoding="utf-8")
    pure_count = pure_loc(text)
    missing = [snippet for snippet in contract.required_snippets if snippet not in text]
    forbidden = [snippet for snippet in contract.forbidden_snippets if snippet in text]
    return {
        "label": contract.label,
        "path": display_path(contract.path),
        "pure_loc": pure_count,
        "max_pure_loc": contract.max_pure_loc,
        "missing_required_snippet_count": len(missing),
        "forbidden_snippet_count": len(forbidden),
        "ok": pure_count <= contract.max_pure_loc and not missing and not forbidden,
    }


def build_report(checks: list[JsonObject], refresh_report: JsonObject) -> JsonObject:
    require_text_value(
        refresh_report.get("status"),
        "OCR_POST_CHAIN_OPERATOR_REFRESH_VERIFIED",
        "refresh.status",
    )
    require_int_value(refresh_report.get("ordered_step_count"), 8, "refresh.ordered_step_count")
    require_int_value(refresh_report.get("failed_step_count"), 0, "refresh.failed_step_count")
    ok = all(check.get("ok") is True for check in checks)
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_OPERATOR_REFRESH_OUTPUT_SPLIT_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_OPERATOR_REFRESH_OUTPUT_SPLIT_FAILED",
        "file_contract_count": len(checks),
        "failed_file_contract_count": sum(1 for check in checks if check.get("ok") is not True),
        "checks": checks,
        "refresh_status": refresh_report.get("status"),
        "refresh_step_count": refresh_report.get("ordered_step_count"),
        "refresh_failed_step_count": refresh_report.get("failed_step_count"),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def pure_loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the refresh wrapper output split before adding new post-chain refresh checks."
    return "Restore the refresh wrapper/model/output split and rerun this verifier."


def markdown(report: JsonObject) -> str:
    check_lines = [
        f"- {check['label']}: ok `{check['ok']}`, pure LOC `{check['pure_loc']}` / `{check['max_pure_loc']}`"
        for check in report["checks"]
        if isinstance(check, dict)
    ]
    return "\n".join((
        "# OCR Post-Chain Refresh Output Split",
        "",
        f"- ok: `{report['ok']}`",
        f"- status: `{report['status']}`",
        f"- file contract count: `{report['file_contract_count']}`",
        f"- failed file contract count: `{report['failed_file_contract_count']}`",
        f"- refresh status: `{report['refresh_status']}`",
        f"- refresh step count: `{report['refresh_step_count']}`",
        "- provider/Gemini/API calls: `0`",
        "- external OCR API calls: `0`",
        "- `/api/submit-test` calls: `0`",
        "- `#tsSubmit` clicks: `0`",
        "- answer-key/grading leak count: `0`",
        "- filesystem path leak count: `0`",
        "- production default: `NO_GO`",
        "",
        "## File Contracts",
        *check_lines,
        "",
        "## Next Safe Action",
        str(report["next_safe_action"]),
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
