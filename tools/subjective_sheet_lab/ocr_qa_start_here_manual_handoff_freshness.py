# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python -m py_compile tools\subjective_sheet_lab\ocr_qa_start_here_manual_handoff_freshness.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import ExtendedGateError
from ocr_preflight_environment_matrix_model import LAB

HANDOFF_REFRESH_JSON: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh.json"
HANDOFF_REFRESH_GUARD_JSON: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_guard.json"
HANDOFF_REFRESH_SERIAL_GUARD_JSON: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_serial_guard.json"
HANDOFF_REFRESH_SOURCE_JSONS: Final[tuple[Path, ...]] = (
    LAB / "ocr_provider_free_handoff_guard_common_self_check.json",
    LAB / "ocr_provider_free_final_handoff_chain.json",
    LAB / "ocr_provider_free_final_handoff_chain_guard.json",
    LAB / "ocr_provider_free_handoff_status_card.json",
    LAB / "ocr_provider_free_handoff_status_card_guard.json",
    LAB / "ocr_provider_free_operator_summary.json",
    LAB / "ocr_provider_free_operator_summary_guard.json",
)


@dataclass(frozen=True, slots=True)
class ManualHandoffRefreshTimes:
    source_latest_modified_ns: int
    refresh_modified_ns: int
    guard_modified_ns: int


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    blocked: bool
    error: str


def current_manual_handoff_refresh_times() -> ManualHandoffRefreshTimes:
    return ManualHandoffRefreshTimes(
        source_latest_modified_ns=max(path.stat().st_mtime_ns for path in HANDOFF_REFRESH_SOURCE_JSONS),
        refresh_modified_ns=HANDOFF_REFRESH_JSON.stat().st_mtime_ns,
        guard_modified_ns=HANDOFF_REFRESH_GUARD_JSON.stat().st_mtime_ns,
    )


def refresh_newer_than_sources(times: ManualHandoffRefreshTimes) -> bool:
    return times.refresh_modified_ns >= times.source_latest_modified_ns


def guard_newer_than_refresh(times: ManualHandoffRefreshTimes) -> bool:
    return times.guard_modified_ns >= times.refresh_modified_ns


def require_manual_handoff_fresh(times: ManualHandoffRefreshTimes) -> None:
    if not refresh_newer_than_sources(times):
        raise ExtendedGateError("manual QA handoff refresh is older than source artifacts")
    if not guard_newer_than_refresh(times):
        raise ExtendedGateError("manual QA handoff refresh guard is older than refresh report")


def stale_manual_handoff_source_times(current: ManualHandoffRefreshTimes) -> ManualHandoffRefreshTimes:
    stale_source_time = max(
        current.source_latest_modified_ns,
        current.refresh_modified_ns,
        current.guard_modified_ns,
    ) + 1
    return ManualHandoffRefreshTimes(
        source_latest_modified_ns=stale_source_time,
        refresh_modified_ns=stale_source_time - 1,
        guard_modified_ns=stale_source_time - 1,
    )


def stale_manual_handoff_guard_times(current: ManualHandoffRefreshTimes) -> ManualHandoffRefreshTimes:
    refresh_time = max(
        current.source_latest_modified_ns,
        current.refresh_modified_ns,
        current.guard_modified_ns,
    )
    return ManualHandoffRefreshTimes(
        source_latest_modified_ns=refresh_time,
        refresh_modified_ns=refresh_time,
        guard_modified_ns=refresh_time - 1,
    )


def manual_handoff_pass_probe(name: str, times: ManualHandoffRefreshTimes) -> ProbeResult:
    try:
        require_manual_handoff_fresh(times)
    except ExtendedGateError as error:
        return ProbeResult(name=name, ok=False, blocked=False, error=str(error))
    return ProbeResult(name=name, ok=True, blocked=False, error="")


def manual_handoff_block_probe(name: str, times: ManualHandoffRefreshTimes) -> ProbeResult:
    try:
        require_manual_handoff_fresh(times)
    except ExtendedGateError as error:
        return ProbeResult(name=name, ok=True, blocked=True, error=str(error))
    return ProbeResult(name=name, ok=False, blocked=False, error="stale manual handoff input was accepted")
