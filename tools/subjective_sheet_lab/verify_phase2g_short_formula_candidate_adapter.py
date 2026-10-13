from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.phase2g_short_formula_candidate_adapter import (  # noqa: E402
    FormulaCandidateSignal,
    apply_formula_candidate,
    collect_formula_texts,
    formula_model_dir,
    resolve_formula_candidate,
)


class VerificationError(Exception):
    pass


class _ResultWrapper:
    def __init__(self, payload):
        self.json = payload


def main() -> int:
    verify_result_collection()
    verify_three_view_consensus()
    verify_disagreement_and_ambiguity()
    verify_review_only_payload()
    verify_model_path()
    print(
        json.dumps(
            {
                "ok": True,
                "provider_call_count": 0,
                "external_ocr_api_call_count": 0,
                "submit_test_call_count": 0,
                "student_facing": False,
                "runtime_wired": False,
                "production_default": "NO-GO",
            },
            indent=2,
        )
    )
    return 0


def verify_result_collection() -> None:
    payload = [
        {"res": {"rec_formula": r"\frac{1}{2}"}},
        _ResultWrapper({"res": {"rec_formula": r"\sqrt{2}+\sqrt{3}"}}),
    ]
    actual = collect_formula_texts(payload)
    expected = (r"\frac{1}{2}", r"\sqrt{2}+\sqrt{3}")
    if actual != expected:
        raise VerificationError(f"formula result collection failed: {actual!r}")


def verify_three_view_consensus() -> None:
    decision = resolve_formula_candidate(
        (
            FormulaCandidateSignal("gray", r"\frac{1}{2}"),
            FormulaCandidateSignal("otsu", "1/2"),
            FormulaCandidateSignal("loose", r"\dfrac{1}{2}"),
        )
    )
    if decision.candidate != "1/2" or decision.vote_count != 3 or decision.warning != "formula_variant_agreement":
        raise VerificationError(f"three-view formula consensus failed: {decision!r}")


def verify_disagreement_and_ambiguity() -> None:
    conflict = resolve_formula_candidate(
        (
            FormulaCandidateSignal("a", "1/2"),
            FormulaCandidateSignal("b", "1/2"),
            FormulaCandidateSignal("c", "2/3"),
            FormulaCandidateSignal("d", "2/3"),
        )
    )
    if conflict.candidate is not None or conflict.warning != "formula_candidate_disagreement":
        raise VerificationError("two-versus-two formula conflict must remain unresolved")
    duplicate_view = resolve_formula_candidate(
        (
            FormulaCandidateSignal("same", "1/2"),
            FormulaCandidateSignal("same", "1/2"),
            FormulaCandidateSignal("other", "1/2"),
        )
    )
    if duplicate_view.candidate is not None or duplicate_view.vote_count != 2:
        raise VerificationError("duplicate signals from one view must not inflate consensus")
    blank = resolve_formula_candidate((FormulaCandidateSignal("a", "1/2"),), blank_like=True)
    if blank.candidate is not None or blank.warning != "blank_like":
        raise VerificationError("blank-like crop must not receive a formula candidate")
    ambiguous = resolve_formula_candidate(
        (FormulaCandidateSignal("a", "1/2"),), visually_ambiguous=True
    )
    if ambiguous.candidate is not None or ambiguous.warning != "ambiguous_ink_groups":
        raise VerificationError("ambiguous crop must not receive a formula candidate")


def verify_review_only_payload() -> None:
    decision = resolve_formula_candidate(
        (
            FormulaCandidateSignal("gray", "√2+√3"),
            FormulaCandidateSignal("otsu", r"\sqrt{2}+\sqrt{3}"),
            FormulaCandidateSignal("loose", "sqrt(2)+sqrt(3)"),
        )
    )
    item = apply_formula_candidate(
        {
            "question_no": 2,
            "status": "review_required",
            "recognized": None,
            "warnings": [],
            "candidates": [],
        },
        decision,
    )
    if item.get("recognized") != "sqrt(2)+sqrt(3)":
        raise VerificationError("agreed formula candidate was not exposed for review")
    if item.get("status") != "review_required" or item.get("safe_auto_grade") is not False:
        raise VerificationError("formula candidate attempted to bypass review")
    if item.get("final_answer") is not None or item.get("source") is not None:
        raise VerificationError("formula candidate attempted automatic confirmation")
    if item.get("requires_confirmation") is not True or item.get("allow_direct_input") is not True:
        raise VerificationError("review and direct-input fallbacks must remain enabled")


def verify_model_path() -> None:
    actual = formula_model_dir(Path("C:/model-cache"))
    if actual.as_posix().lower() != "c:/model-cache/official_models/pp-formulanet-s".lower():
        raise VerificationError(f"formula model cache path changed: {actual}")


if __name__ == "__main__":
    raise SystemExit(main())
