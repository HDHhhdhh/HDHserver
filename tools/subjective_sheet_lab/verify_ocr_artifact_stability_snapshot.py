# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_artifact_stability_snapshot.py

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

LAB: Final[Path] = Path(__file__).resolve().parent
SNAPSHOT_JSON: Final[Path] = LAB / "ocr_artifact_stability_snapshot.json"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


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


class StabilityVerification(TypedDict):
    ok: bool
    checked_artifacts: int
    provider_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    cached_baseline: CachedBaseline


class StabilityVerificationError(Exception):
    def __init__(self, failures: tuple[str, ...]) -> None:
        self.failures = failures
        super().__init__("\n".join(failures))


def main() -> int:
    snapshot = require_object(read_json(SNAPSHOT_JSON), "snapshot")
    failures = verify_snapshot(snapshot)
    if failures:
        raise StabilityVerificationError(failures)
    print(json.dumps(verification_summary(snapshot), ensure_ascii=False, indent=2))
    return 0


def verify_snapshot(snapshot: dict[str, JsonValue]) -> tuple[str, ...]:
    failures: list[str] = []
    artifacts = require_array(snapshot.get("artifacts"), "snapshot.artifacts")
    for index, raw_artifact in enumerate(artifacts, start=1):
        artifact = artifact_record(raw_artifact, index)
        path = LAB / artifact["path"]
        if not path.is_file():
            failures.append(f"missing artifact: {artifact['path']}")
            continue
        content = path.read_bytes()
        actual_bytes = len(content)
        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_bytes != artifact["bytes"]:
            failures.append(f"byte mismatch for {artifact['path']}: {actual_bytes} != {artifact['bytes']}")
        if actual_sha != artifact["sha256"]:
            failures.append(f"sha256 mismatch for {artifact['path']}: {actual_sha} != {artifact['sha256']}")
    baseline = cached_baseline(snapshot.get("cached_baseline"))
    if not baseline["ok"]:
        failures.append("cached baseline is not ok")
    if baseline["baseline_wrong_safe_auto_grade"] != 0:
        failures.append("cached baseline wrong_safe_auto_grade is not 0")
    if baseline["provider_call_count"] != 0:
        failures.append("cached baseline provider_call_count is not 0")
    if baseline["submit_test_call_count"] != 0:
        failures.append("cached baseline submit_test_call_count is not 0")
    return tuple(failures)


def verification_summary(snapshot: dict[str, JsonValue]) -> StabilityVerification:
    artifacts = require_array(snapshot.get("artifacts"), "snapshot.artifacts")
    return {
        "ok": True,
        "checked_artifacts": len(artifacts),
        "provider_call_count": require_int(snapshot.get("provider_call_count"), "snapshot.provider_call_count"),
        "submit_test_call_count": require_int(snapshot.get("submit_test_call_count"), "snapshot.submit_test_call_count"),
        "ts_submit_click_count": require_int(snapshot.get("ts_submit_click_count"), "snapshot.ts_submit_click_count"),
        "cached_baseline": cached_baseline(snapshot.get("cached_baseline")),
    }


def artifact_record(value: JsonValue, index: int) -> ArtifactRecord:
    raw = require_object(value, f"snapshot.artifacts[{index}]")
    return {
        "path": require_str(raw.get("path"), f"snapshot.artifacts[{index}].path"),
        "role": require_str(raw.get("role"), f"snapshot.artifacts[{index}].role"),
        "bytes": require_int(raw.get("bytes"), f"snapshot.artifacts[{index}].bytes"),
        "sha256": require_str(raw.get("sha256"), f"snapshot.artifacts[{index}].sha256"),
    }


def cached_baseline(value: JsonValue) -> CachedBaseline:
    raw = require_object(value, "snapshot.cached_baseline")
    cases = [require_str(case, "snapshot.cached_baseline.cases[]") for case in require_array(raw.get("cases"), "snapshot.cached_baseline.cases")]
    return {
        "ok": require_bool(raw.get("ok"), "snapshot.cached_baseline.ok"),
        "baseline_wrong_safe_auto_grade": require_int(raw.get("baseline_wrong_safe_auto_grade"), "snapshot.cached_baseline.baseline_wrong_safe_auto_grade"),
        "provider_call_count": require_int(raw.get("provider_call_count"), "snapshot.cached_baseline.provider_call_count"),
        "submit_test_call_count": require_int(raw.get("submit_test_call_count"), "snapshot.cached_baseline.submit_test_call_count"),
        "cases": cases,
    }


def read_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise StabilityVerificationError((f"{label} must be a JSON object",))
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise StabilityVerificationError((f"{label} must be a JSON array",))
    return value


def require_str(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise StabilityVerificationError((f"{label} must be a string",))
    return value


def require_int(value: JsonValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise StabilityVerificationError((f"{label} must be an integer",))
    return value


def require_bool(value: JsonValue, label: str) -> bool:
    if not isinstance(value, bool):
        raise StabilityVerificationError((f"{label} must be a boolean",))
    return value


if __name__ == "__main__":
    raise SystemExit(main())
