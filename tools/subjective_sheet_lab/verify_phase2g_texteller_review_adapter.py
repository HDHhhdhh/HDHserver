from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.test_answer_modes import ANSWER_VALUE, CHOICE_NUMBER, MANUAL_REVIEW
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures
from tools.subjective_sheet_lab.ocr_review_payload_validator import PayloadMode, validate_payload
from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import Phase2CResult
from tools.subjective_sheet_lab.phase2g_texteller_review_adapter import (
    CHOICE_RECOGNIZER_PENDING,
    ENABLED_ENV,
    FORMULA_PARSE_UNSUPPORTED,
    FORMULA_WRAPPER_REVIEW_ONLY,
    MANUAL_REVIEW_REQUIRED,
    OVERLINE_SEMANTICS_REVIEW_REQUIRED,
    Phase2GRequest,
    Phase2GTextellerUnavailable,
    load_phase2g_texteller_review_payload,
    review_candidate,
)


def _pipeline_result(root: Path) -> Phase2CResult:
    crop_dir = root / "crops"
    crop_dir.mkdir()
    for question_no in range(1, 21):
        (crop_dir / f"q{question_no:03d}.png").write_bytes(b"fake-image")
    crop_quality = root / "crop_quality.json"
    crop_quality.write_text("{}", encoding="utf-8")
    placeholder = root / "placeholder.json"
    placeholder.write_text("{}", encoding="utf-8")
    return Phase2CResult(
        case_id="deidentified_case",
        case_dir=root,
        source_image=root / "source.png",
        crop_root=root,
        crop_dir=crop_dir,
        review_asset_root=root,
        asset_manifest=placeholder,
        crop_count=20,
        contact_sheet_count=4,
        debug_sheet_count=0,
        contact_sheets=(),
        debug_sheets=(),
        asset_verification=placeholder,
        crop_quality=crop_quality,
        answer_box_source="detected",
        overwritten_ambiguity=None,
    )


def main() -> int:
    old_enabled = os.environ.pop(ENABLED_ENV, None)
    try:
        with tempfile.TemporaryDirectory(prefix="phase2g-texteller-verify-") as raw_tmp:
            root = Path(raw_tmp)
            pipeline_result = _pipeline_result(root)
            modes = [ANSWER_VALUE] * 20
            modes[0] = CHOICE_NUMBER
            modes[3] = MANUAL_REVIEW
            request = Phase2GRequest(
                sid="deidentified",
                test_id="t_unit_contract_fixture",
                round_no=1,
                pipeline_result=pipeline_result,
                answer_modes=tuple(modes),
            )

            called = False

            def must_not_run(_crops):
                nonlocal called
                called = True
                return {}

            try:
                load_phase2g_texteller_review_payload(request, recognizer=must_not_run)
            except Phase2GTextellerUnavailable as exc:
                assert exc.reason == "feature_disabled"
            else:
                raise AssertionError("TexTeller adapter must be disabled by default")
            assert called is False

            os.environ[ENABLED_ENV] = "1"
            received_questions: list[int] = []

            def fake_recognizer(crops):
                received_questions.extend(question_no for question_no, _ in crops)
                outputs = {question_no: str(question_no) for question_no, _ in crops}
                outputs[2] = r"\boxed{\frac{1}{2}}"
                outputs[3] = r"\overline{3\sqrt{2}}"
                outputs[5] = "x+1"
                return outputs

            payload = load_phase2g_texteller_review_payload(
                request,
                recognizer=fake_recognizer,
            )
            assert 1 not in received_questions
            assert 4 not in received_questions
            assert len(received_questions) == 18
            assert payload["provider_call_count"] == 0
            assert forbidden_paths(payload) == []
            assert path_exposures(payload) is False
            validate_payload(payload, PayloadMode.REVIEW, "phase2g")

            by_question = {item["question_no"]: item for item in payload["items"]}
            assert by_question[1]["recognized"] == "?"
            assert CHOICE_RECOGNIZER_PENDING in by_question[1]["warnings"]
            assert by_question[1]["answer_mode"] == CHOICE_NUMBER
            assert by_question[4]["recognized"] == "?"
            assert MANUAL_REVIEW_REQUIRED in by_question[4]["warnings"]
            assert by_question[4]["answer_mode"] == MANUAL_REVIEW
            assert by_question[2]["recognized"] == "1/2"
            assert FORMULA_WRAPPER_REVIEW_ONLY in by_question[2]["warnings"]
            assert by_question[3]["recognized"] == "3*sqrt(2)"
            assert OVERLINE_SEMANTICS_REVIEW_REQUIRED in by_question[3]["warnings"]
            assert by_question[5]["recognized"] == "?"
            assert FORMULA_PARSE_UNSUPPORTED in by_question[5]["warnings"]
            assert all(item["status"] == "review_required" for item in payload["items"])
            assert all(item["source"] is None for item in payload["items"])
            assert all(item["final_answer"] is None for item in payload["items"])

            assert review_candidate(r"\boxed{4\sqrt{2}}") == (
                "4*sqrt(2)",
                (FORMULA_WRAPPER_REVIEW_ONLY,),
            )
            overline_candidate, overline_warnings = review_candidate(r"\overline{12}")
            assert overline_candidate == "12"
            assert OVERLINE_SEMANTICS_REVIEW_REQUIRED in overline_warnings
            assert review_candidate(r"\overline{AB}") == ("?", ())
    finally:
        if old_enabled is None:
            os.environ.pop(ENABLED_ENV, None)
        else:
            os.environ[ENABLED_ENV] = old_enabled

    print("phase2g texteller review adapter: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
