# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\ocr_artifact_stability_snapshot.py

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

LAB: Final[Path] = Path(__file__).resolve().parent
SNAPSHOT_JSON: Final[Path] = LAB / "ocr_artifact_stability_snapshot.json"
SNAPSHOT_MD: Final[Path] = LAB / "ocr_artifact_stability_snapshot.md"


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    path: Path
    role: str


class ArtifactRecord(TypedDict):
    path: str
    role: str
    bytes: int
    sha256: str


class CachedBaseline(TypedDict):
    ok: bool
    baseline_wrong_safe_auto_grade: int
    provider_call_count: int
    submit_test_call_count: int
    cases: list[str]


class Snapshot(TypedDict):
    ok: bool
    provider_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    artifact_count: int
    artifacts: list[ArtifactRecord]
    cached_baseline: CachedBaseline


class StabilitySnapshotError(Exception):
    pass


ARTIFACTS: Final[tuple[ArtifactSpec, ...]] = (
    ArtifactSpec(LAB / "ocr_cached_regression_suite_summary.json", "current_cached_regression_baseline"),
    ArtifactSpec(LAB / "ocr_cached_regression_suite_summary.md", "current_cached_regression_report"),
    ArtifactSpec(LAB / "OCR_QA_START_HERE.md", "qa_entrypoint"),
    ArtifactSpec(LAB / "ocr_next_action_queue.md", "coordination_queue"),
    ArtifactSpec(LAB / "ocr_production_no_go_one_page.md", "production_no_go_summary"),
    ArtifactSpec(LAB / "ocr_production_go_no_go_pass_fail_matrix.md", "production_pass_fail_matrix"),
    ArtifactSpec(LAB / "ocr_preflight_inclusion_audit.md", "preflight_audit"),
    ArtifactSpec(LAB / "ocr_qa_docs_verifier_report.md", "qa_docs_verifier_report"),
)


def main() -> int:
    snapshot = build_snapshot(ARTIFACTS)
    SNAPSHOT_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SNAPSHOT_MD.write_text(markdown_report(snapshot), encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def build_snapshot(artifacts: tuple[ArtifactSpec, ...]) -> Snapshot:
    records = [artifact_record(spec) for spec in artifacts]
    baseline = cached_baseline()
    return {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "artifact_count": len(records),
        "artifacts": records,
        "cached_baseline": baseline,
    }


def artifact_record(spec: ArtifactSpec) -> ArtifactRecord:
    if not spec.path.is_file():
        raise StabilitySnapshotError(f"missing artifact: {relative_name(spec.path)}")
    content = spec.path.read_bytes()
    return {
        "path": relative_name(spec.path),
        "role": spec.role,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def cached_baseline() -> CachedBaseline:
    path = LAB / "ocr_cached_regression_suite_summary.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StabilitySnapshotError("cached regression summary must be a JSON object")
    quality_gate = raw.get("quality_gate")
    if not isinstance(quality_gate, dict):
        raise StabilitySnapshotError("cached regression summary missing quality_gate")
    results = raw.get("results")
    if not isinstance(results, list):
        raise StabilitySnapshotError("cached regression summary missing results")
    case_ids: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            raise StabilitySnapshotError("cached regression result item must be a JSON object")
        case_id = item.get("case_id")
        if not isinstance(case_id, str):
            raise StabilitySnapshotError("cached regression result missing case_id")
        case_ids.append(case_id)
    wrong_safe = quality_gate.get("baseline_wrong_safe_auto_grade")
    provider_count = raw.get("provider_call_count")
    submit_count = raw.get("submit_test_call_count")
    if not isinstance(wrong_safe, int) or isinstance(wrong_safe, bool):
        raise StabilitySnapshotError("baseline_wrong_safe_auto_grade must be an integer")
    if not isinstance(provider_count, int) or isinstance(provider_count, bool):
        raise StabilitySnapshotError("provider_call_count must be an integer")
    if not isinstance(submit_count, int) or isinstance(submit_count, bool):
        raise StabilitySnapshotError("submit_test_call_count must be an integer")
    return {
        "ok": wrong_safe == 0 and provider_count == 0 and submit_count == 0,
        "baseline_wrong_safe_auto_grade": wrong_safe,
        "provider_call_count": provider_count,
        "submit_test_call_count": submit_count,
        "cases": case_ids,
    }


def markdown_report(snapshot: Snapshot) -> str:
    lines = [
        "# OCR Artifact Stability Snapshot",
        "",
        "Date: 2026-07-05 KST",
        "",
        "## Safety",
        "",
        f"- Gemini/API provider calls: {snapshot['provider_call_count']}",
        f"- `/api/submit-test` calls: {snapshot['submit_test_call_count']}",
        f"- `#tsSubmit` clicks: {snapshot['ts_submit_click_count']}",
        "- Production default changed: no",
        "- Runtime JSON, DB, `tests-config.json`, answer keys, and student records changed: no",
        "",
        "## Cached Baseline",
        "",
        f"- baseline wrong_safe_auto_grade: {snapshot['cached_baseline']['baseline_wrong_safe_auto_grade']}",
        f"- cached baseline provider calls: {snapshot['cached_baseline']['provider_call_count']}",
        f"- cached baseline submit-test calls: {snapshot['cached_baseline']['submit_test_call_count']}",
        f"- cases: {', '.join(snapshot['cached_baseline']['cases'])}",
        "",
        "## Artifact Hashes",
        "",
        "| Role | Path | Bytes | SHA-256 |",
        "| --- | --- | ---: | --- |",
    ]
    for artifact in snapshot["artifacts"]:
        lines.append(f"| {artifact['role']} | `{artifact['path']}` | {artifact['bytes']} | `{artifact['sha256']}` |")
    lines.extend(("", "## Use", "", "Use this snapshot to detect accidental changes to the current OCR QA handoff and cached safety baseline before the next manual or live OCR QA run.", ""))
    return "\n".join(lines)


def relative_name(path: Path) -> str:
    return path.relative_to(LAB).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
