from __future__ import annotations

import hashlib
import json
import random
import tempfile
from pathlib import Path

from scripts.evaluate_student_test_aihub_choice_validation import (
    choice_training_writers,
    discover_validation_samples,
    empty_stats,
    prepare_output_path,
    public_stats,
    update_stats,
)
from scripts.import_aihub_education_choice_dataset import normalized_boxes


def _payload(*, grade: str, writer: str, boxes: list[dict]) -> dict:
    level, year = grade.split("_")
    return {
        "Dataset": {"label_path": f"fixture/{level}/{year}"},
        "Images": {"identifier": f"{writer}.png", "type": "png", "make_id": writer},
        "Bbox": boxes,
    }


def _box(box_id: str, text: str) -> dict:
    return {"id": box_id, "data": text, "x": [1, 20], "y": [2, 24]}


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="aihub-choice-eval-") as temp_dir:
        root = Path(temp_dir)
        train = root / "train"
        validation = root / "validation"
        crops = root / "crops"
        train.mkdir()
        validation.mkdir()
        for label in ("1", "2", "3", "4", "5", "__reject__"):
            (crops / label).mkdir(parents=True)
        (train / "one.json").write_text(
            json.dumps(_payload(grade="H_G1", writer="seen", boxes=[_box("t1", "1")])),
            encoding="utf-8",
        )
        known = choice_training_writers([("H_G1", train)])
        assert known == {"seen"}
        assertions += 1

        fixtures = [
            ("seen.json", "seen", [_box("s1", "1")]),
            ("fresh.json", "fresh", [_box("f1", "2"), _box("f2", "x")]),
        ]
        for filename, writer, boxes in fixtures:
            path = validation / filename
            path.write_text(json.dumps(_payload(grade="H_G1", writer=writer, boxes=boxes)), encoding="utf-8")
            relative = path.relative_to(validation).as_posix()
            shuffled = normalized_boxes(json.loads(path.read_text(encoding="utf-8")))
            random.Random(f"20260829:{relative}").shuffle(shuffled)
            for position, box in enumerate(shuffled):
                token = hashlib.sha256(f"{relative}\n{box['id']}\n{position}".encode("utf-8")).hexdigest()[:24]
                (crops / box["label"] / f"{token}.png").write_bytes(b"fixture")
        counts = {label: len(list((crops / label).glob("*.png"))) for label in ("1", "2", "3", "4", "5", "__reject__")}
        (crops / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": "student_test_aihub_choice_crops_v1",
                    "counts": counts,
                    "answerKeyFieldsUsed": 0,
                }
            ),
            encoding="utf-8",
        )
        samples, source = discover_validation_samples(
            grade="H_G1",
            labels_root=validation,
            crops_root=crops,
            known_training_writers=known,
        )
        assert len(samples) == 3 and source["strictSamples"] == 2
        assert sorted(sample.label for sample in samples) == ["1", "2", "__reject__"]
        assertions += 2

        output = prepare_output_path(root / "report.json")
        assert output == (root / "report.json").resolve() and not output.exists()
        assertions += 1

    stats = empty_stats()
    update_stats(stats, human_label="1", predicted="1", score=0.999, margin=0.99, minimum=0.995, margin_minimum=0.9)
    update_stats(stats, human_label="2", predicted="3", score=0.999, margin=0.99, minimum=0.995, margin_minimum=0.9)
    update_stats(stats, human_label="__reject__", predicted="__reject__", score=0.9, margin=0.8, minimum=0.995, margin_minimum=0.9)
    public = public_stats(stats)
    assert public["rawAccuracy"] == 2 / 3 and public["choiceCoverage"] == 1.0
    assert public["wrongAutoGrades"] == 1 and public["rejectRecall"] == 1.0
    assertions += 2
    return {"name": "student-test-aihub-choice-validation", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
