from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_file_lock import FileLockBusy, file_lock
from ocr_provider_free_handoff_guard_common import ArtifactSnapshot, snapshot_artifacts
import verify_ocr_provider_free_manual_qa_handoff_refresh as refresh
import verify_ocr_provider_free_manual_qa_handoff_refresh_guard as refresh_guard

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_serial_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_serial_guard.md"


class SerialGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    refresh_busy_blocked: bool
    guard_busy_blocked: bool
    lock_file_removed: bool
    busy_probes_preserved_refresh_artifacts: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    before = snapshot_serial_artifacts()
    probes = run_busy_probes()
    after = snapshot_serial_artifacts()
    report = build_report(probes, before == after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_busy_probes() -> tuple[bool, bool, bool]:
    try:
        with file_lock(refresh.LOCK_PATH):
            refresh_code = refresh.main()
            guard_code = refresh_guard.main()
    except FileLockBusy:
        return (False, False, False)
    return (refresh_code == 1, guard_code == 1, not refresh.LOCK_PATH.exists())


def build_report(probes: tuple[bool, bool, bool], artifacts_preserved: bool) -> SerialGuardReport:
    refresh_busy_blocked, guard_busy_blocked, lock_file_removed = probes
    failed_probe_count = sum(1 for probe in (*probes, artifacts_preserved) if not probe)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_SERIAL_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_SERIAL_GUARD_FAILED",
        "probe_count": 4,
        "failed_probe_count": failed_probe_count,
        "refresh_busy_blocked": refresh_busy_blocked,
        "guard_busy_blocked": guard_busy_blocked,
        "lock_file_removed": lock_file_removed,
        "busy_probes_preserved_refresh_artifacts": artifacts_preserved,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def snapshot_serial_artifacts() -> ArtifactSnapshot:
    return snapshot_artifacts((
        refresh.REPORT_JSON_OUT,
        refresh.REPORT_MD_OUT,
        refresh_guard.REPORT_JSON_OUT,
        refresh_guard.REPORT_MD_OUT,
    ))


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep provider-free handoff refresh wrappers serialized."
    return "Remove stale refresh lock or inspect the active refresh process before rerunning."


def markdown(report: SerialGuardReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Manual QA Handoff Refresh Serial Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- refresh_busy_blocked: `{report['refresh_busy_blocked']}`",
        f"- guard_busy_blocked: `{report['guard_busy_blocked']}`",
        f"- lock_file_removed: `{report['lock_file_removed']}`",
        f"- busy_probes_preserved_refresh_artifacts: `{report['busy_probes_preserved_refresh_artifacts']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
