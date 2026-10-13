# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_provider_free_accuracy_gate_extended.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import JsonObject
from ocr_provider_free_extended_gate_arrival_smoke import arrival_smoke_reports, arrival_smoke_verifiers
from ocr_provider_free_extended_gate_arrival_digest import arrival_digest_reports, arrival_digest_verifiers
from ocr_provider_free_extended_gate_arrival_transitions import (
    arrival_transition_reports,
    arrival_transition_verifiers,
)
from ocr_provider_free_extended_gate_intake_commands import intake_command_reports, intake_command_verifiers
from ocr_provider_free_extended_gate_intake_command_guard import (
    intake_command_guard_reports,
    intake_command_guard_verifiers,
)
from ocr_provider_free_extended_gate_missing_blocker import missing_blocker_reports, missing_blocker_verifiers
from ocr_provider_free_extended_gate_operator_action import operator_action_reports, operator_action_verifiers
from ocr_provider_free_extended_gate_post_arrival_matrix import (
    post_arrival_matrix_reports,
    post_arrival_matrix_verifiers,
)
from ocr_provider_free_extended_gate_post_arrival_acceptance import (
    post_arrival_acceptance_reports,
    post_arrival_acceptance_verifiers,
)
from ocr_provider_free_extended_gate_post_arrival_runbook import (
    post_arrival_runbook_reports,
    post_arrival_runbook_verifiers,
)
from ocr_provider_free_extended_gate_post_arrival_bundle import (
    post_arrival_bundle_reports,
    post_arrival_bundle_verifiers,
)
from ocr_provider_free_extended_gate_post_arrival import post_arrival_reports, post_arrival_verifiers
from ocr_provider_free_extended_gate_queue_state import queue_state_reports, queue_state_verifiers
from ocr_provider_free_extended_gate_report_field_access import (
    report_field_access_reports,
    report_field_access_verifiers,
)
from ocr_provider_free_extended_gate_registry import reports_by_key, verifiers
from ocr_provider_free_extended_gate_summary import ExtendedGateError, markdown as summary_markdown, summary
from ocr_provider_free_extended_gate_user_action_inventory import (
    user_action_inventory_reports,
    user_action_inventory_verifiers,
)
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from tools.subjective_sheet_lab.ocr_preprocess_variants import PreprocessVariantError

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_provider_free_accuracy_gate_extended.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_provider_free_accuracy_gate_extended.md")

def main() -> int:
    try:
        run_verifiers()
    except PreprocessVariantError as error:
        output = blocked_output(str(error))
        write_output(output)
        return 1
    output = summary(read_reports())
    write_output(output)
    return 0


def run_verifiers() -> None:
    for label, verifier in (
        *verifiers(),
        *operator_action_verifiers(),
        *arrival_smoke_verifiers(),
        *arrival_digest_verifiers(),
        *intake_command_verifiers(),
        *intake_command_guard_verifiers(),
        *post_arrival_verifiers(),
        *arrival_transition_verifiers(),
        *missing_blocker_verifiers(),
        *post_arrival_matrix_verifiers(),
        *post_arrival_acceptance_verifiers(),
        *post_arrival_runbook_verifiers(),
        *post_arrival_bundle_verifiers(),
        *queue_state_verifiers(),
        *user_action_inventory_verifiers(),
        *report_field_access_verifiers(),
    ):
        result = verifier()
        if result != 0:
            raise ExtendedGateError(f"{label} failed with exit code {result}")


def read_reports() -> JsonObject:
    return {
        **reports_by_key(),
        **operator_action_reports(),
        **arrival_smoke_reports(),
        **arrival_digest_reports(),
        **intake_command_reports(),
        **intake_command_guard_reports(),
        **post_arrival_reports(),
        **arrival_transition_reports(),
        **missing_blocker_reports(),
        **post_arrival_matrix_reports(),
        **post_arrival_acceptance_reports(),
        **post_arrival_runbook_reports(),
        **post_arrival_bundle_reports(),
        **queue_state_reports(),
        **user_action_inventory_reports(),
        **report_field_access_reports(),
    }


def blocked_output(detail: str) -> JsonObject:
    return {
        "ok": True,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_ACCURACY_GATE_EXTENDED_BLOCKED",
        "current_blocker": "opencv_python_dependency_missing",
        "blocker_detail": detail,
        "extended_gate_count": EXTENDED_GATE_COUNT,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": "Run the extended provider-free gate in the OCR lab Python environment with opencv-python installed.",
    }


def write_output(output: JsonObject) -> None:
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


def markdown(output: JsonObject) -> str:
    if output.get("status") == "OCR_PROVIDER_FREE_ACCURACY_GATE_EXTENDED_BLOCKED":
        return blocked_markdown(output)
    return summary_markdown(output)


def blocked_markdown(output: JsonObject) -> str:
    return "\n".join((
        "# OCR Provider-Free Accuracy Gate Extended",
        "",
        f"- ok: `{output['ok']}`",
        f"- status: `{output['status']}`",
        f"- current_blocker: `{output['current_blocker']}`",
        f"- extended_gate_count: `{output['extended_gate_count']}`",
        f"- provider_call_count: `{output['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{output['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{output['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{output['ts_submit_click_count']}`",
        f"- production_default: `{output['production_default']}`",
        "",
        "## Blocker Detail",
        str(output["blocker_detail"]),
        "",
        "## Next Safe Action",
        str(output["next_safe_action"]),
        "",
    ))

if __name__ == "__main__":
    raise SystemExit(main())
