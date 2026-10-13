# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/subjective_review_pipeline_dry_run.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from final_review_payload_bridge import JsonValue
from subjective_review_dry_run_core import (
    BlockingCheck,
    DryRunResult,
    require_object,
    run_dry_flow,
)

ROOT: Final = Path(__file__).resolve().parent
FIXTURE_PATH: Final = ROOT / "subjective_review_dry_run_fixture.json"
REVIEW_PAYLOAD_PATH: Final = ROOT / "subjective_review_dry_run_review_payload.json"
FINAL_PAYLOAD_PATH: Final = ROOT / "subjective_review_dry_run_final_payload.json"
ANSWERS_TEXT_PATH: Final = ROOT / "subjective_review_dry_run_answersText.txt"
REPORT_PATH: Final = ROOT / "subjective_review_dry_run_report.md"


def read_json(path: Path) -> dict[str, JsonValue]:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def write_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_paths() -> tuple[Path, ...]:
    return (REVIEW_PAYLOAD_PATH, FINAL_PAYLOAD_PATH, ANSWERS_TEXT_PATH, REPORT_PATH)


def output_leak_paths() -> list[str]:
    leaks: list[str] = []
    for path in output_paths():
        if not path.exists():
            continue
        if path.suffix == ".json":
            payload = read_json(path)
            for key in ("expected", "canonical_answer", "accepted_answers"):
                if key in json.dumps(payload, ensure_ascii=False):
                    leaks.append(f"{path.name}:{key}")
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("canonical_answer", "accepted_answers", "\"expected\""):
            if token in text:
                leaks.append(f"{path.name}:{token}")
    return leaks


def write_outputs(result: DryRunResult, report: str) -> None:
    write_json(REVIEW_PAYLOAD_PATH, result.outputs.review_payload)
    write_json(FINAL_PAYLOAD_PATH, result.outputs.final_payload)
    ANSWERS_TEXT_PATH.write_text(result.outputs.answers_text + "\n", encoding="utf-8")
    REPORT_PATH.write_text(report, encoding="utf-8")


def build_report(result: DryRunResult, leak_paths: list[str]) -> str:
    blocking_lines = "\n".join(format_check(check) for check in result.blocking_checks)
    leak_line = "none" if not leak_paths else ", ".join(leak_paths)
    escaped_answers = result.outputs.answers_text.replace("\n", "\\n")
    return f"""# Subjective Review Pipeline Dry Run Report

## Scope

- Lab-only dry run.
- No Gemini/API call.
- No `/api/submit-test` call.
- No operating app files modified.

## Flow Verified

recognized/evaluated OCR result -> review payload -> simulated student review decisions -> final review payload -> answersText conversion

## Result

- safe_auto_grade items passed through.
- review_required blocked conversion until simulated confirmation.
- candidate-selected answers converted.
- keypad/direct-input answers converted.
- retake_required blocked until resolved.
- retake_uploaded blocked until re-recognized.
- data_check_required blocked conversion.
- final answersText has stable 20-question order.
- student-facing output leak scan: {leak_line}.

## Blocking Checks

{blocking_lines}

## answersText

```text
{result.outputs.answers_text}
```

Escaped one-line form:

```text
{escaped_answers}
```
"""


def format_check(check: BlockingCheck) -> str:
    status = "pass" if check.passed else "fail"
    return f"- {check.name}: {status} ({check.detail})"


def main() -> int:
    result = run_dry_flow(read_json(FIXTURE_PATH))
    write_outputs(result, build_report(result, []))
    leaks = output_leak_paths()
    write_outputs(result, build_report(result, leaks))
    if leaks:
        joined = ", ".join(leaks)
        raise RuntimeError(f"student-facing outputs leaked answer-key fields: {joined}")
    print(json.dumps({"ok": True, "answers": 20, "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
