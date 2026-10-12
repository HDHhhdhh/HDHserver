from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
COMMANDS: Final[tuple[tuple[str, ...], ...]] = (
    (sys.executable, "scripts/verify_admin_tests_record_details.py"),
    ("node", "scripts/verify_admin_tests_record_details_ui.js"),
    ("node", "scripts/verify_admin_tests_record_detail_answer_link_ui.js"),
)


class AdminLeakExtendedError(Exception):
    pass


def main() -> int:
    results = [run(command) for command in COMMANDS]
    failures = [item for item in results if item["exit_code"] != 0]
    if failures:
        raise AdminLeakExtendedError(json.dumps(failures, ensure_ascii=False, indent=2))
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "checked_commands": len(results),
        "public_submitted_answers_leak": False,
        "public_answers_text_leak": False,
        "public_wrong_details_leak": False,
        "admin_sensitive_field_leak": False,
        "admin_answer_link_policy": "API detail answerUrl wins; restricted fallback hidden",
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run(command: tuple[str, ...]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    parsed = parse_json(completed.stdout)
    return {
        "command": command_label(command),
        "exit_code": completed.returncode,
        "stdout_json": parsed,
        "stderr_tail": completed.stderr[-1000:],
    }


def command_label(command: tuple[str, ...]) -> str:
    if command and Path(command[0]).name.startswith("python"):
        return "python " + " ".join(command[1:])
    return " ".join(command)


def parse_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value[-1000:]


if __name__ == "__main__":
    raise SystemExit(main())
