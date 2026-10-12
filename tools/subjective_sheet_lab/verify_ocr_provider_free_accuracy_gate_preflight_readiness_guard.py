# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_provider_free_accuracy_gate_preflight_readiness_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
)
from ocr_provider_free_accuracy_gate_preflight_readiness_guard_model import (
    build_guard_report,
    require_guard_report,
)
from verify_ocr_provider_free_accuracy_gate_preflight_readiness import (
    REPORT_JSON as READINESS_JSON,
)
from verify_ocr_provider_free_accuracy_gate_preflight_readiness import (
    main as verify_preflight_readiness,
)

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_readiness_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_readiness_guard.md"


def main() -> int:
    result = verify_preflight_readiness()
    if result != 0:
        raise ExtendedGateError(f"preflight readiness failed with exit code {result}")
    live_readiness = read_json_object(READINESS_JSON)
    output = build_guard_report(live_readiness)
    require_guard_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def markdown(output: JsonObject) -> str:
    return "\n".join((
        "# OCR Provider-Free Preflight Readiness Guard",
        "",
        f"- status: `{output['status']}`",
        f"- probe_count: `{output['probe_count']}`",
        f"- failed_probe_count: `{output['failed_probe_count']}`",
        f"- live readiness passed: `{output['live_readiness_passed']}`",
        f"- preflight modified blocked: `{output['preflight_modified_blocked']}`",
        f"- preflight check present without approval blocked: `{output['preflight_check_present_blocked']}`",
        f"- ready-to-add false blocked: `{output['ready_to_add_false_blocked']}`",
        f"- operator copy ready mutation blocked: `{output['operator_copy_ready_blocked']}`",
        f"- provider-call mutation blocked: `{output['nonzero_provider_count_blocked']}`",
        f"- submit-test mutation blocked: `{output['nonzero_submit_count_blocked']}`",
        f"- production-enable mutation blocked: `{output['production_default_enable_blocked']}`",
        f"- answer-key leak mutation blocked: `{output['answer_key_leak_blocked']}`",
        f"- absolute patch path mutation blocked: `{output['absolute_patch_path_blocked']}`",
        "- Gemini/API calls: `0`",
        "- external OCR API calls: `0`",
        "- `/api/submit-test` calls: `0`",
        "- `#tsSubmit` clicks: `0`",
        "- answer-key/grading/path leak count: `0`",
        "- production default: `NO_GO`",
        "",
        "## Next Safe Action",
        str(output["next_safe_action"]),
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
