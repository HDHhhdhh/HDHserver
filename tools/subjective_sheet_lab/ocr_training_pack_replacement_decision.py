# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_replacement_sandbox.py

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplacementDecisionProbe:
    contract_ready: bool
    replacement_ready: bool
    accepted_evidence_count: int
    rejected_evidence_count: int
    safe_auto_grade_rejected_count: int
    target_count: int


def replacement_attempt_allowed(
    probe: ReplacementDecisionProbe,
) -> bool:
    return (
        probe.contract_ready
        and probe.replacement_ready
        and probe.accepted_evidence_count == probe.target_count
        and probe.rejected_evidence_count == 0
        and probe.safe_auto_grade_rejected_count == 0
    )


def replacement_decision_probes() -> tuple[bool, ...]:
    probes = (
        ReplacementDecisionProbe(
            contract_ready=True,
            replacement_ready=True,
            accepted_evidence_count=4,
            rejected_evidence_count=0,
            safe_auto_grade_rejected_count=0,
            target_count=4,
        ),
        ReplacementDecisionProbe(
            contract_ready=True,
            replacement_ready=False,
            accepted_evidence_count=0,
            rejected_evidence_count=0,
            safe_auto_grade_rejected_count=0,
            target_count=4,
        ),
        ReplacementDecisionProbe(
            contract_ready=False,
            replacement_ready=True,
            accepted_evidence_count=4,
            rejected_evidence_count=0,
            safe_auto_grade_rejected_count=0,
            target_count=4,
        ),
        ReplacementDecisionProbe(
            contract_ready=True,
            replacement_ready=True,
            accepted_evidence_count=3,
            rejected_evidence_count=1,
            safe_auto_grade_rejected_count=0,
            target_count=4,
        ),
        ReplacementDecisionProbe(
            contract_ready=True,
            replacement_ready=True,
            accepted_evidence_count=4,
            rejected_evidence_count=1,
            safe_auto_grade_rejected_count=1,
            target_count=4,
        ),
    )
    return tuple(replacement_attempt_allowed(probe) for probe in probes)
