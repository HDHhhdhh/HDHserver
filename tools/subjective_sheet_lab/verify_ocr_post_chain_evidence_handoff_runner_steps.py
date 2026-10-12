#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_handoff_runner_steps.py

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

import verify_ocr_post_chain_cleanup_candidate_manifest_rendered_summary as cleanup_rendered_summary
import verify_ocr_post_chain_evidence_index as evidence_index
import verify_ocr_post_chain_evidence_index_common_self_check as common_self_check
import verify_ocr_post_chain_evidence_index_freshness_guard as freshness_guard
import verify_ocr_post_chain_evidence_index_guard as evidence_guard
import verify_ocr_post_chain_evidence_index_rendered_summary as evidence_rendered_summary
import verify_ocr_post_chain_evidence_index_rendered_summary_guard as evidence_rendered_guard
import verify_ocr_post_chain_evidence_index_rendered_summary_guard_rendered_summary as evidence_rendered_guard_summary
import verify_ocr_post_chain_handoff_retention_manifest_guard_rendered_summary as retention_guard_summary
import verify_ocr_qa_start_here as qa_start_here
import verify_ocr_qa_start_here_evidence_index_freshness as qa_evidence_freshness
import verify_ocr_qa_start_here_freshness_guard as qa_freshness_guard
import verify_ocr_qa_start_here_rendered_summary as qa_rendered_summary
import verify_ocr_qa_start_here_rendered_summary_guard as qa_rendered_guard

Verifier: TypeAlias = Callable[[], int]


@dataclass(frozen=True, slots=True)
class HandoffStepSpec:
    name: str
    verifier: Verifier
    report_path: Path
    expected_status: str


STEP_SPECS: Final[tuple[HandoffStepSpec, ...]] = (
    HandoffStepSpec(
        "qa_start_here_freshness_guard",
        qa_freshness_guard.main,
        qa_freshness_guard.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "qa_start_here",
        qa_start_here.main,
        qa_start_here.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
    ),
    HandoffStepSpec(
        "qa_start_here_rendered_summary",
        qa_rendered_summary.main,
        qa_rendered_summary.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "qa_start_here_rendered_summary_guard",
        qa_rendered_guard.main,
        qa_rendered_guard.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "common_self_check",
        common_self_check.main,
        common_self_check.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_COMMON_SELF_CHECK_VERIFIED",
    ),
    HandoffStepSpec(
        "freshness_guard",
        freshness_guard.main,
        freshness_guard.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "evidence_index",
        evidence_index.main,
        evidence_index.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED",
    ),
    HandoffStepSpec(
        "evidence_index_rendered_summary",
        evidence_rendered_summary.main,
        evidence_rendered_summary.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "evidence_index_rendered_summary_guard",
        evidence_rendered_guard.main,
        evidence_rendered_guard.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "evidence_index_rendered_summary_guard_rendered_summary",
        evidence_rendered_guard_summary.main,
        evidence_rendered_guard_summary.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_RENDERED_SUMMARY_GUARD_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "retention_manifest_guard_rendered_summary",
        retention_guard_summary.main,
        retention_guard_summary.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "cleanup_candidate_manifest_rendered_summary",
        cleanup_rendered_summary.main,
        cleanup_rendered_summary.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "evidence_index_guard",
        evidence_guard.main,
        evidence_guard.REPORT_JSON_OUT,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "qa_start_here_post_evidence_refresh",
        qa_start_here.main,
        qa_start_here.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
    ),
    HandoffStepSpec(
        "qa_start_here_post_evidence_rendered_summary",
        qa_rendered_summary.main,
        qa_rendered_summary.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_VERIFIED",
    ),
    HandoffStepSpec(
        "qa_start_here_post_evidence_rendered_summary_guard",
        qa_rendered_guard.main,
        qa_rendered_guard.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_GUARD_VERIFIED",
    ),
    HandoffStepSpec(
        "qa_start_here_evidence_index_freshness",
        qa_evidence_freshness.main,
        qa_evidence_freshness.REPORT_JSON_OUT,
        "OCR_QA_START_HERE_EVIDENCE_INDEX_FRESHNESS_VERIFIED",
    ),
)


if __name__ == "__main__":
    for spec in STEP_SPECS:
        print(spec.name)
