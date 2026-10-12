from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import torch

LAB_ROOT = Path(__file__).resolve().parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from choice_digit_classifier import INPUT_SIZE, LABELS, ChoiceDigitNet, prepare_digit_array
from train_choice_digit_classifier import ChoiceDigitTrainingError, discover_human_crops


def main() -> int:
    verify_model_shape()
    verify_blank_and_digit_preprocessing()
    verify_human_only_label_gate()
    print("choice digit classifier contract: OK")
    return 0


def verify_model_shape() -> None:
    output = ChoiceDigitNet()(torch.zeros((3, 1, INPUT_SIZE, INPUT_SIZE), dtype=torch.float32))
    assert tuple(output.shape) == (3, len(LABELS))


def verify_blank_and_digit_preprocessing() -> None:
    blank = np.full((116, 485), 255, dtype=np.uint8)
    prepared_blank = prepare_digit_array(blank, "otsu")
    assert prepared_blank.tensor is None
    assert prepared_blank.geometry.blank

    digit = blank.copy()
    cv2.putText(digit, "4", (190, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.8, 0, 7, cv2.LINE_AA)
    for variant in ("otsu", "adaptive"):
        prepared = prepare_digit_array(digit, variant)
        assert prepared.tensor is not None
        assert tuple(prepared.tensor.shape) == (1, INPUT_SIZE, INPUT_SIZE)
        assert not prepared.geometry.blank

    multiple = blank.copy()
    cv2.putText(multiple, "2", (120, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.8, 0, 7, cv2.LINE_AA)
    cv2.putText(multiple, "4", (280, 95), cv2.FONT_HERSHEY_SIMPLEX, 2.8, 0, 7, cv2.LINE_AA)
    rejected = prepare_digit_array(multiple, "otsu")
    assert rejected.tensor is None
    assert rejected.geometry.invalid_reason == "multiple_or_overwritten_marks"


def verify_human_only_label_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="choice_digit_contract_") as raw_root:
        root = Path(raw_root)
        human_dir = root / "crop_benchmark_inputs" / "fixture"
        crop_dir = human_dir / "crops"
        crop_dir.mkdir(parents=True)
        cv2.imwrite(str(crop_dir / "q001.png"), np.full((116, 485), 255, dtype=np.uint8))
        unsafe = {
            "answers": [
                {
                    "question_no": 1,
                    "human_answer": "1",
                    "confidence": "high",
                    "expected": "1",
                }
            ]
        }
        (human_dir / "human_transcription.json").write_text(json.dumps(unsafe), encoding="utf-8")
        try:
            discover_human_crops(root)
        except ChoiceDigitTrainingError as exc:
            assert "forbidden answer-key field" in str(exc)
        else:
            raise AssertionError("answer-key-bearing human label source was accepted")


if __name__ == "__main__":
    raise SystemExit(main())
