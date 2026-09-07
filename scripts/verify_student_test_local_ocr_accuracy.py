from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.benchmark_student_test_local_ocr_accuracy import (
    REJECT_LABEL,
    benchmark_formula_kind,
    choice_targets,
    formula_targets,
    render_markdown,
    summarize_choice_rows,
    summarize_formula_rows,
    zero_error_upper_95,
)


def main() -> int:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="verify-local-ocr-accuracy-") as temp_dir:
        transcription = Path(temp_dir) / "human_transcription.json"
        answers = []
        for number in range(1, 21):
            if number == 1:
                text, confidence = "3", "high"
            elif number == 2:
                text, confidence = r"\frac{1}{2}", "high"
            elif number == 3:
                text, confidence = "x+1", "high"
            else:
                text, confidence = "", "low"
            answers.append({"question_no": number, "human_answer": text, "confidence": confidence})
        transcription.write_text(json.dumps({"answers": answers}, ensure_ascii=False), encoding="utf-8")
        targets = choice_targets(transcription)
        assert targets[1] == "3" and targets[2] == REJECT_LABEL and targets[20] == REJECT_LABEL
        assertions += 1
        formulas, unsupported = formula_targets(transcription)
        assert formulas == {1: "3", 2: r"\frac{1}{2}"} and unsupported == (3,)
        assertions += 1

    choice_rows = [
        {"humanLabel": "3", "rawCorrect": True, "autoAccepted": True},
        {"humanLabel": "4", "rawCorrect": False, "autoAccepted": False},
        {"humanLabel": REJECT_LABEL, "rawCorrect": True, "autoAccepted": False},
    ]
    choice = summarize_choice_rows(choice_rows)
    assert choice["evaluated"] == 3 and choice["choiceEvaluated"] == 2 and choice["rejectEvaluated"] == 1
    assertions += 1

    from scripts.student_test_ocr_evidence import check_transcription_source, validate_eval_inputs
    observed = {"case": {"cropCount": 20, "cropContentSha256": "a" * 64, "humanTranscriptionSha256": "b" * 64}}
    manifest = {"schema": "student_test_ocr_eval_inputs_v1", "templateSha256": "c" * 64,
                "cases": {"case": {**observed["case"], "answerMode": "answer_value"}}}
    validate_eval_inputs(manifest, observed, template_sha256="c" * 64, choice_cases=(), formula_cases=("case",))
    changed = {"case": {**observed["case"], "cropContentSha256": "d" * 64}}
    for callback in (
        lambda: validate_eval_inputs(manifest, changed, template_sha256="c" * 64, choice_cases=(), formula_cases=("case",)),
        lambda: validate_eval_inputs(manifest, observed, template_sha256="e" * 64, choice_cases=(), formula_cases=("case",)),
        lambda: check_transcription_source({"visual_sources": [str(Path("first/crops").resolve())]}, Path("other/crops")),
    ):
        try:
            callback()
        except ValueError:
            pass
        else:
            raise AssertionError("mismatched OCR evidence was accepted")
    assertions += 4
    assert choice["rawAccuracy"] == 2 / 3 and choice["coverage"] == 1 / 2
    assertions += 1
    assert choice["wrongAutoGrades"] == 0 and choice["rejectRecall"] == 1.0
    assertions += 1

    formula_rows = [
        {"kind": "fraction", "rawCorrect": True, "variantAgreed": True, "autoAccepted": True},
        {"kind": "root", "rawCorrect": False, "variantAgreed": False, "autoAccepted": False},
    ]
    formula = summarize_formula_rows(formula_rows)
    assert formula["evaluated"] == 2 and formula["rawCorrect"] == 1 and formula["rawAccuracy"] == 0.5
    assertions += 1
    assert formula["accepted"] == 1 and formula["coverage"] == 0.5 and formula["wrongAutoGrades"] == 0
    assertions += 1
    assert formula["kinds"]["fraction"]["rawCorrect"] == 1 and formula["kinds"]["root"]["rawCorrect"] == 0
    assertions += 1
    assert 0 < zero_error_upper_95(299, 0) <= 0.01
    assertions += 1
    assert zero_error_upper_95(10, 1) == 1.0
    assertions += 1
    assert benchmark_formula_kind("1/2") == "fraction" and benchmark_formula_kind(r"\frac{1}{2}") == "fraction"
    assertions += 1
    assert benchmark_formula_kind("3sqrt(2)") == "root" and benchmark_formula_kind(r"2\sqrt{3}") == "root"
    assertions += 1

    report = {
        "createdAt": "2026-08-29T00:00:00+00:00",
        "safety": {"providerCallCount": 0, "answerKeyFieldsUsed": 0, "productionStateChanged": False},
        "choice": {"models": [{"name": "test", "aggregate": choice}]},
        "formula": {
            "engine": "test",
            "device": "cpu",
            "aggregate": formula,
            "supporterFailures": [],
        },
    }
    markdown = render_markdown(report)
    assert "wrong auto grades" in markdown and "provider calls: 0" in markdown
    assertions += 1
    assert "Missing profile checkpoints keep production at NO_GO." in markdown
    assertions += 1
    ready_markdown = render_markdown({**report, "profileModelsReady": True})
    assert "Production activation remains gated by the configured readiness checks." in ready_markdown
    assert "Missing profile checkpoints" not in ready_markdown
    assertions += 1

    print(f"student test local OCR accuracy verification passed: {assertions} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
