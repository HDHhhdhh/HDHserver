from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from ocr_post_chain_evidence_index_common import path_mtime


class HandoffGuardStep(TypedDict):
    name: str
    report_path: str
    exit_code: int
    ok: bool


@dataclass(frozen=True, slots=True)
class StepOverride:
    name: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    modified_ns: tuple[int, ...]


def copied_steps_with_override(
    steps: Iterable[HandoffGuardStep],
    override: StepOverride,
) -> list[HandoffGuardStep]:
    return [copied_step_with_override(step, override) for step in steps]


def copied_step_with_override(
    step: HandoffGuardStep,
    override: StepOverride,
) -> HandoffGuardStep:
    copied = copy_step(step)
    if copied["name"] == override.name:
        copied["exit_code"] = override.exit_code
        copied["ok"] = False
    return copied


def copy_step(step: HandoffGuardStep) -> HandoffGuardStep:
    return {
        "name": step["name"],
        "report_path": step["report_path"],
        "exit_code": step["exit_code"],
        "ok": step["ok"],
    }


def snapshot_artifacts(paths: Iterable[Path]) -> ArtifactSnapshot:
    return ArtifactSnapshot(tuple(path_mtime(path) for path in paths))


def failed_probe_count(probe_results: Iterable[bool]) -> int:
    return sum(1 for passed in probe_results if not passed)
