from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class VerificationError(Exception):
    pass


def main() -> int:
    from tools.subjective_sheet_lab.local_ocr_candidate_pipeline_v2 import (
        CandidateSignal,
        InkProfile,
        LOCAL_MODEL_NAMES,
        build_review_item,
        normalize_candidate,
        resolve_candidate,
        validate_review_payload,
    )

    verify_symbol_preservation(normalize_candidate)
    verify_local_model_names(LOCAL_MODEL_NAMES)
    verify_ensemble(resolve_candidate, CandidateSignal, InkProfile)
    verify_payload(build_review_item, validate_review_payload)
    print(
        json.dumps(
            {
                "ok": True,
                "provider_call_count": 0,
                "external_ocr_api_call_count": 0,
                "submit_test_call_count": 0,
                "final_submit_click_count": 0,
                "production_default": "NO-GO",
            },
            indent=2,
        )
    )
    return 0


def verify_local_model_names(model_names) -> None:
    expected = {
        "doc_orientation": "PP-LCNet_x1_0_doc_ori",
        "doc_unwarping": "UVDoc",
        "textline_orientation": "PP-LCNet_x1_0_textline_ori",
        "text_detection": "PP-OCRv5_server_det",
        "text_recognition": "korean_PP-OCRv5_mobile_rec",
    }
    if model_names != expected:
        raise VerificationError(f"local model names drifted: {model_names!r}")


def verify_symbol_preservation(normalize_candidate) -> None:
    accepted = {
        "-2": "-2",
        "0.5": "0.5",
        "1/2": "1/2",
        "x=2": "x=2",
        "sqrt(2)": "sqrt(2)",
    }
    for raw, expected in accepted.items():
        actual = normalize_candidate(raw, "answer_value")
        if actual != expected:
            raise VerificationError(f"symbol-preserving normalization failed: {raw!r} -> {actual!r}")
    for raw in ("2,3", "?", "1//2", "x=>2", "C:\\server\\secret"):
        if normalize_candidate(raw, "answer_value") is not None:
            raise VerificationError(f"unsafe answer-value candidate accepted: {raw!r}")
    if normalize_candidate("5", "choice_number") != "5":
        raise VerificationError("valid choice candidate rejected")
    if normalize_candidate("9", "choice_number") is not None:
        raise VerificationError("out-of-range choice candidate accepted")


def verify_ensemble(resolve_candidate, signal_type, profile_type) -> None:
    clean = profile_type(blank_like=False, major_group_count=1, ink_bbox_aspect=0.8)
    agreed = resolve_candidate(
        (
            signal_type("v1", "4", 0.56),
            signal_type("v2", "4", 0.52),
            signal_type("v3", "4", 0.51),
        ),
        "choice_number",
        clean,
    )
    if agreed.candidate != "4" or agreed.confidence_tier != "MEDIUM":
        raise VerificationError("three-way conservative agreement was not retained")

    conflict = resolve_candidate(
        (
            signal_type("v1", "2", 0.91),
            signal_type("v2", "2", 0.82),
            signal_type("v3", "3", 0.88),
            signal_type("v4", "3", 0.81),
        ),
        "choice_number",
        clean,
    )
    if conflict.candidate is not None:
        raise VerificationError("conflicting candidates must remain blank")

    multiple_marks = profile_type(blank_like=False, major_group_count=2, ink_bbox_aspect=0.8)
    blocked = resolve_candidate(
        (
            signal_type("v1", "3", 0.91),
            signal_type("v2", "3", 0.89),
            signal_type("v3", "3", 0.86),
        ),
        "choice_number",
        multiple_marks,
    )
    if blocked.candidate is not None or "ambiguous_ink_groups" not in blocked.reasons:
        raise VerificationError("multiple-mark choice crop must be blocked")

    alpha_confusion = resolve_candidate(
        (
            signal_type("v1", "Y", 0.91),
            signal_type("v2", "Y", 0.89),
            signal_type("v3", "Y", 0.86),
        ),
        "answer_value",
        clean,
    )
    if alpha_confusion.candidate is not None or "single_alpha_ambiguity" not in alpha_confusion.reasons:
        raise VerificationError("single-letter answer-value ambiguity must remain blank")


def verify_payload(build_review_item, validate_review_payload) -> None:
    items = [build_review_item(question_no, None, "UNRESOLVED", ("no_consensus",)) for question_no in range(1, 21)]
    items[0] = build_review_item(1, "4", "HIGH", ("variant_agreement",))
    payload = {"source": "local_ocr_candidate_v2", "problem_count": 20, "items": items}
    validate_review_payload(payload)
    if any(item.get("status") != "review_required" for item in items):
        raise VerificationError("every item must remain review_required")
    if any(item.get("final_answer") is not None for item in items):
        raise VerificationError("final_answer must stay null")
    if any(item.get("safe_auto_grade") for item in items):
        raise VerificationError("safe_auto_grade must stay disabled")
    if items[1].get("allow_direct_input") is not True:
        raise VerificationError("blank candidate must retain direct-input fallback")


if __name__ == "__main__":
    raise SystemExit(main())
