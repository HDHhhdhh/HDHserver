from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON
from scripts.audit_aihub_education_formula_labels import audit_grade
from scripts.build_student_test_formula_profile_dataset import build_profile
from scripts.import_aihub_education_formula_dataset import (
    convert,
    dataset_grade_code,
    normalized_formula_boxes,
)


def _write_converted_root(root: Path, grade: str, equations: list[str]) -> None:
    from PIL import Image

    images = root / "images"
    images.mkdir(parents=True)
    samples = []
    for index, equation in enumerate(equations):
        filename = f"sample-{index}.png"
        Image.new("RGB", (24 + index, 16), "white").save(images / filename)
        samples.append(
            {
                "image": f"images/{filename}",
                "equation": equation,
                "grade": grade,
                "writerHash": f"writer-{grade}-{index}",
                "sourceHash": f"source-{grade}-{index}",
            }
        )
    (root / "samples.jsonl").write_text(
        "".join(json.dumps(sample, ensure_ascii=False) + "\n" for sample in samples),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "student_test_aihub_formula_crops_v1",
                "grade": grade,
                "count": len(samples),
                "answerKeyFieldsUsed": 0,
            }
        ),
        encoding="utf-8",
    )


def _raises(callback) -> None:
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def run() -> dict:
    from PIL import Image

    assertions = 0
    payload = {
        "Dataset": {"label_path": "OCR(edu)/H/G2"},
        "Images": {"identifier": "page001", "type": "png", "make_id": "writer-secret"},
        "Bbox": [
            {"id": 1, "type": 2, "data": r"\frac{1}{2}", "x": [10, 10, 50, 50], "y": [10, 34, 10, 34]},
            {"id": 2, "type": 2, "data": r"2\sqrt{3}", "x": [55, 55, 95, 95], "y": [10, 34, 10, 34]},
            {"id": 3, "type": 1, "data": "설명", "x": [1, 1, 8, 8], "y": [1, 8, 1, 8]},
        ],
    }
    assert dataset_grade_code(payload) == "H_G2"
    assert [box["equation"] for box in normalized_formula_boxes(payload)] == [r"\frac{1}{2}", r"2\sqrt{3}"]
    assertions += 2

    with tempfile.TemporaryDirectory(prefix="student-test-aihub-formula-") as temp_dir:
        root = Path(temp_dir)
        labels = root / "labels"
        images = root / "images"
        output = root / "converted"
        labels.mkdir()
        images.mkdir()
        Image.new("RGB", (110, 50), "white").save(images / "page001.png")
        (labels / "page001.json").write_text(json.dumps(payload), encoding="utf-8")
        audit = audit_grade(grade="H_G2", labels_root=labels, max_per_writer=1)
        assert audit["formulaBoxes"] == 2 and audit["selectedAfterWriterCap"] == 1
        summary = convert(
            grade="H_G2",
            labels_root=labels,
            images_root=images,
            output_root=output,
            max_per_writer=8,
            minimum_side=4,
            seed=17,
        )
        assert summary["count"] == 2 and summary["formulaKinds"] == {"fraction": 1, "root": 1}
        assert summary["selectedWriters"] == 1 and summary["answerKeyFieldsUsed"] == 0
        samples_text = (output / "samples.jsonl").read_text(encoding="utf-8")
        assert "writer-secret" not in samples_text and "writerHash" in samples_text
        crops = sorted((output / "images").glob("*.png"))
        assert len(crops) == 2
        with Image.open(crops[0]) as crop:
            assert crop.mode == "RGB" and crop.width >= crop.height
        assertions += 6

        m3 = root / "M_G3"
        h1 = root / "H_G1"
        _write_converted_root(m3, "M_G3", ["1/2"])
        _write_converted_root(h1, "H_G1", [r"\sqrt{2}", "3"])
        profile_output = root / "profile"
        profile = build_profile(
            profile=FORMULA_PROFILE_COMMON,
            grade_roots={"M_G3": m3, "H_G1": h1},
            output_root=profile_output,
            seed=19,
        )
        assert profile["grades"] == ["M_G3", "H_G1"]
        assert profile["countsByGrade"] == {"M_G3": 1, "H_G1": 2}
        assert profile["count"] == 3 and sum(profile["materialization"].values()) == 3
        assert len((profile_output / "equations.txt").read_text(encoding="utf-8").splitlines()) == 3
        assert len(list((profile_output / "images").glob("*.png"))) == 3
        _raises(
            lambda: build_profile(
                profile=FORMULA_PROFILE_COMMON,
                grade_roots={"M_G3": m3},
                output_root=root / "invalid-profile",
            )
        )
        assertions += 6
        other = root / "other-h1"
        _write_converted_root(other, "H_G1", ["x+1", "3", "-7"])
        focused = build_profile(profile=FORMULA_PROFILE_COMMON, grade_roots={"M_G3": m3, "H_G1": other},
                                output_root=root / "focused", numeric_answers_only=True)
        assert focused["count"] == 3 and focused["filtered"]["outsideNumericAnswerGrammar"] == 1
        assert "3" in (root / "focused" / "equations.txt").read_text(encoding="utf-8").splitlines()
        strict = build_profile(profile=FORMULA_PROFILE_COMMON, grade_roots={"M_G3": m3, "H_G1": other},
                               output_root=root / "strict", exclude_writers_from=profile_output)
        assert strict["count"] == 1
        assert (root / "strict" / "equations.txt").read_text(encoding="utf-8").strip() == "-7"
        assertions += 4
        empty_training = root / "empty-training"
        empty_training.mkdir()
        (empty_training / "provenance.jsonl").write_text("", encoding="utf-8")
        _raises(lambda: build_profile(profile=FORMULA_PROFILE_COMMON, grade_roots={"M_G3": m3, "H_G1": h1},
            output_root=root / "invalid-strict", exclude_writers_from=empty_training))
        assert not (root / "invalid-strict").exists()
        assertions += 2

    return {"name": "student-test-aihub-formula-import", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
