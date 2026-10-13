from __future__ import annotations

import tempfile
from pathlib import Path

from scripts.train_student_test_choice_classifier import (
    CHOICE_LABELS,
    REJECT_LABEL,
    RealCase,
    aihub_public_data,
    balanced_indices,
    case_manifest,
    labeled_crop_samples,
    pooled_labeled_crop_samples,
    summarize,
    transcription_answers,
    zero_error_upper_95,
)


def run() -> dict:
    assertions = 0

    targets = [1, 1, 1, 2, 2, 2, 3, 3, 3, 9]
    selected = balanced_indices(targets, (1, 2, 3), limit=6, seed=11)
    assert len(selected) == 6
    assert sorted(targets[index] for index in selected) == [1, 1, 2, 2, 3, 3]
    assert selected == balanced_indices(targets, (1, 2, 3), limit=6, seed=11)
    assertions += 3

    rows = [
        {
            "humanLabel": "1",
            "predicted": "1",
            "correct": True,
            "variantAgreed": True,
            "score": 0.999,
            "margin": 0.98,
        },
        {
            "humanLabel": "3",
            "predicted": "2",
            "correct": False,
            "variantAgreed": True,
            "score": 0.999,
            "margin": 0.98,
        },
        {
            "humanLabel": REJECT_LABEL,
            "predicted": REJECT_LABEL,
            "correct": True,
            "variantAgreed": True,
            "score": 0.999,
            "margin": 0.98,
        },
        {
            "humanLabel": REJECT_LABEL,
            "predicted": "5",
            "correct": False,
            "variantAgreed": True,
            "score": 0.999,
            "margin": 0.98,
        },
    ]
    summary = summarize(rows, 0.995, 0.90)
    assert summary["choiceEvaluated"] == 2 and summary["rejectEvaluated"] == 2
    assert summary["accepted"] == 3 and summary["coverage"] == 1.0
    assert summary["wrongAutoGrades"] == 2 and summary["rejectRecall"] == 0.5
    assert set(summary["perClass"]) == {*CHOICE_LABELS, REJECT_LABEL}
    assertions += 4

    assert 0.009 < zero_error_upper_95(299, 0) <= 0.01
    assert zero_error_upper_95(11, 0) > 0.23
    assert zero_error_upper_95(299, 1) == 1.0
    assertions += 3

    direct = transcription_answers(
        {"answers": [{"question_no": 1, "human_answer": "3", "confidence": "high"}]},
        case_name="direct",
    )
    evaluation = transcription_answers(
        {
            "items": [
                {
                    "question_no": 2,
                    "human_answer": "5",
                    "human_confidence": "high",
                    "notes": "visual transcription",
                    "expected": "1",
                }
            ]
        },
        case_name="evaluation",
    )
    assert direct[0]["human_answer"] == "3"
    assert evaluation == [
        {
            "question_no": 2,
            "human_answer": "5",
            "confidence": "high",
            "notes": "visual transcription",
        }
    ]
    assertions += 2

    with tempfile.TemporaryDirectory(prefix="choice-training-aihub-") as temp_dir:
        root = Path(temp_dir)
        for label in (*CHOICE_LABELS, REJECT_LABEL):
            directory = root / label
            directory.mkdir()
            for index in range(3):
                (directory / f"{index}.png").write_bytes(b"fixture")
        try:
            labeled_crop_samples(
                root,
                choice_limit_per_class=2,
                reject_limit=1,
                seed=19,
            )
        except ValueError as error:
            assert "manifest" in str(error)
        else:
            raise AssertionError("AI Hub samples must require the converter manifest")
        assertions += 1
        (root / "manifest.json").write_text(
            '{"schema":"student_test_aihub_choice_crops_v1","answerKeyFieldsUsed":0}\n',
            encoding="utf-8",
        )
        samples = labeled_crop_samples(
            root,
            choice_limit_per_class=2,
            reject_limit=1,
            seed=19,
        )
        counts = {label: sum(item_label == label for _path, item_label in samples) for label in (*CHOICE_LABELS, REJECT_LABEL)}
        assert all(counts[label] == 2 for label in CHOICE_LABELS)
        assert counts[REJECT_LABEL] == 1
        automatic_samples = labeled_crop_samples(
            root,
            choice_limit_per_class=0,
            reject_limit=0,
            seed=19,
        )
        automatic_counts = {
            label: sum(item_label == label for _path, item_label in automatic_samples)
            for label in (*CHOICE_LABELS, REJECT_LABEL)
        }
        assert all(automatic_counts[label] == 3 for label in CHOICE_LABELS)
        assert automatic_counts[REJECT_LABEL] == 3
        assertions += 4

    with tempfile.TemporaryDirectory(prefix="choice-training-aihub-pool-") as temp_dir:
        pool_root = Path(temp_dir)
        grade_a = pool_root / "H_G1"
        grade_b = pool_root / "H_G2"
        grade_counts = {
            grade_a: {"1": 1, "2": 1, "3": 1, "4": 1, "5": 5, REJECT_LABEL: 8},
            grade_b: {"1": 4, "2": 4, "3": 4, "4": 4, "5": 1, REJECT_LABEL: 12},
        }
        for grade_root, counts_by_label in grade_counts.items():
            grade_root.mkdir()
            (grade_root / "manifest.json").write_text(
                '{"schema":"student_test_aihub_choice_crops_v1","answerKeyFieldsUsed":0}\n',
                encoding="utf-8",
            )
            for label, count in counts_by_label.items():
                directory = grade_root / label
                directory.mkdir()
                for index in range(count):
                    (directory / f"{index}.png").write_bytes(b"fixture")
        pooled, by_root = pooled_labeled_crop_samples(
            [grade_a, grade_b],
            choice_limit_per_class=0,
            reject_limit=0,
            seed=23,
        )
        pooled_counts = {
            label: sum(item_label == label for _path, item_label in pooled)
            for label in (*CHOICE_LABELS, REJECT_LABEL)
        }
        assert all(pooled_counts[label] == 6 for label in CHOICE_LABELS)
        assert pooled_counts[REJECT_LABEL] == 20
        assert len({path for path, label in by_root[grade_a] if label != REJECT_LABEL}) == 9
        assert len({path for path, label in by_root[grade_b] if label != REJECT_LABEL}) == 17
        provenance = aihub_public_data([(grade_a, by_root[grade_a]), (grade_b, by_root[grade_b])])
        assert provenance["counts"] == pooled_counts
        assert all(
            sum(root_item["effectiveCounts"][label] for root_item in provenance["roots"])
            == pooled_counts[label]
            for label in (*CHOICE_LABELS, REJECT_LABEL)
        )
        assert provenance["roots"][0]["effectiveCounts"]["5"] == sum(
            label == "5" for _path, label in by_root[grade_a]
        )
        assert provenance["roots"][0]["uniqueCounts"][REJECT_LABEL] == 8
        assertions += 8

    with tempfile.TemporaryDirectory(prefix="choice-training-manifest-") as temp_dir:
        root = Path(temp_dir)
        crops = root / "crops"
        crops.mkdir()
        (crops / "q001.png").write_bytes(b"one")
        (crops / "q002.png").write_bytes(b"two")
        transcription = root / "human_transcription.json"
        transcription.write_text('{"answers": []}\n', encoding="utf-8")
        manifest = case_manifest(RealCase("writer-a", crops, transcription))
        assert manifest["name"] == "writer-a" and manifest["cropCount"] == 2
        assert len(manifest["cropNameSha256"]) == 64
        assert len(manifest["transcriptionSha256"]) == 64
        assertions += 3

    return {"name": "student-test-choice-training", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
