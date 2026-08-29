from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON, FORMULA_PROFILE_UPPER
from scripts.audit_student_test_aihub_validation import SCHEMA, audit_validation


def _payload(*, grade: str, writer: str, identifier: str, formula: str = r"\sqrt{2}") -> dict:
    family, level = grade.split("_")
    boxes = [
        {"id": str(index), "type": 1, "data": label, "x": [0, 10], "y": [0, 10]}
        for index, label in enumerate(("1", "2", "3", "4", "5"), start=1)
    ]
    boxes.append({"id": "formula", "type": 2, "data": formula, "x": [0, 20], "y": [0, 12]})
    return {
        "Dataset": {"label_path": f"OCR(edu)/{family}/{level}"},
        "Images": {"identifier": identifier, "type": "png", "make_id": writer},
        "Bbox": boxes,
    }


def _write(root: Path, name: str, payload: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="verify-aihub-validation-") as temp_dir:
        root = Path(temp_dir)
        grades = ("M_G3", "H_G1", "H_G2", "H_G3")
        training_roots = {grade: root / "training" / grade for grade in grades}
        validation_roots = {grade: root / "validation" / grade for grade in grades}
        for grade in grades:
            _write(
                training_roots[grade],
                "train.json",
                _payload(grade=grade, writer=f"train-{grade}", identifier=f"train-id-{grade}"),
            )
            _write(
                validation_roots[grade],
                "validation.json",
                _payload(
                    grade=grade,
                    writer=f"validation-{grade}",
                    identifier=("train-id-H_G1" if grade == "H_G2" else f"validation-id-{grade}"),
                    formula=r"\frac{1}{2}",
                ),
            )
        _write(
            validation_roots["M_G3"],
            "seen-writer.json",
            _payload(grade="M_G3", writer="train-M_G3", identifier="validation-seen-writer", formula="3"),
        )
        (validation_roots["H_G3"] / "invalid.json").write_text("{", encoding="utf-8")

        summary = audit_validation(training_roots=training_roots, validation_roots=validation_roots)
        assert summary["schema"] == SCHEMA
        assertions += 1
        assert summary["trainingGrades"] == list(grades)
        assertions += 1
        assert summary["choiceTrainingWriters"] == 4
        assertions += 1
        assert summary["formulaProfileTrainingWriters"] == {
            FORMULA_PROFILE_COMMON: 2,
            FORMULA_PROFILE_UPPER: 4,
        }
        assertions += 1
        by_grade = {row["grade"]: row for row in summary["grades"]}
        m3 = by_grade["M_G3"]
        assert m3["validation"]["formulaBoxes"] == 2 and m3["leakage"]["choiceWriterOverlap"] == 1
        assertions += 1
        assert m3["strictChoice"]["counts"] == {
            "1": 1,
            "2": 1,
            "3": 1,
            "4": 1,
            "5": 1,
            "__reject__": 1,
        }
        assertions += 1
        assert m3["formulaProfiles"][FORMULA_PROFILE_COMMON]["strictFormulaKinds"]["fraction"] == 1
        assertions += 1
        assert m3["formulaProfiles"][FORMULA_PROFILE_UPPER]["validationWriterOverlap"] == 1
        assertions += 1
        assert by_grade["H_G1"]["sourceIntegrity"] == "PASS"
        assertions += 1
        assert by_grade["H_G2"]["leakage"]["identifierOverlap"] == 1
        assertions += 1
        assert by_grade["H_G2"]["sourceIntegrity"] == "FAIL"
        assertions += 1
        assert by_grade["H_G3"]["validation"]["invalidJson"] == 1
        assertions += 1
        assert by_grade["H_G3"]["sourceIntegrity"] == "FAIL"
        assertions += 1
        assert summary["overallSourceIntegrity"] == "FAIL"
        assertions += 1
        assert summary["scope"] == "label_and_split_only_no_model_accuracy"
        assertions += 1
        assert summary["answerKeyFieldsUsed"] == 0 and all(
            row["answerKeyFieldsUsed"] == 0 for row in summary["grades"]
        )
        assertions += 1
        try:
            audit_validation(
                training_roots={grade: path for grade, path in training_roots.items() if grade != "H_G3"},
                validation_roots=validation_roots,
            )
        except ValueError:
            assertions += 1
        else:
            raise AssertionError("four-grade validation audit must fail closed")

    print(f"student test AI Hub validation verification passed: {assertions} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
