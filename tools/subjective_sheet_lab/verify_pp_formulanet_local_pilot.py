from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from pp_formulanet_human_eval import evaluate_against_human_transcription
from pp_formulanet_local_adapter import (
    FORMULA_PARSE_UNSUPPORTED,
    REVIEW_REQUIRED,
    preprocess_formula_crop,
    run_local_formula_pilot,
)


class FakeResult:
    def __init__(self, latex: str) -> None:
        self.json = {"res": {"input_path": "must-not-leak", "rec_formula": latex}}


class FakeModel:
    def __init__(self, latex_values: list[str]) -> None:
        self.latex_values = latex_values

    def predict(self, *, input: list[Any], batch_size: int) -> list[FakeResult]:
        assert batch_size == 1
        assert len(input) == len(self.latex_values)
        return [FakeResult(value) for value in self.latex_values]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pp-formulanet-verify-") as raw_tmp:
        tmp = Path(raw_tmp)
        crop_paths = [tmp / "q005.png", tmp / "q009.png", tmp / "q020.png"]
        for index, path in enumerate(crop_paths):
            image = np.full((220, 699), 235, dtype=np.uint8)
            cv2.line(image, (0, 28), (698, 28), 70, 6)
            cv2.line(image, (690, 30), (690, 219), 100, 3)
            cv2.putText(
                image,
                str(index + 1),
                (150, 170),
                cv2.FONT_HERSHEY_SIMPLEX,
                2.0,
                20,
                5,
                cv2.LINE_AA,
            )
            assert cv2.imwrite(str(path), image)

        processed = preprocess_formula_crop(crop_paths[0])
        assert processed.shape[0] >= 128
        processed_gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
        assert int((processed_gray < 128).sum(axis=1).max()) < int(
            processed_gray.shape[1] * 0.8
        )

        latex_values = [r"\frac{1}{2}", r"3\sqrt{2}", "x=2"]
        fake_model = FakeModel(latex_values)
        payload = run_local_formula_pilot(
            crop_paths,
            model_factory=lambda *_: fake_model,
        )
        assert payload["provider_calls"] == 0
        assert [item["recognized"] for item in payload["items"]] == [
            "1/2",
            "3*sqrt(2)",
            "?",
        ]
        assert all(item["status"] == REVIEW_REQUIRED for item in payload["items"])
        assert FORMULA_PARSE_UNSUPPORTED in payload["items"][2]["warnings"]
        assert "must-not-leak" not in str(payload)

        human = {
            "answers": [
                {"question_no": 5, "human_answer": "1/2", "confidence": "high"},
                {
                    "question_no": 9,
                    "human_answer": "3sqrt(2)",
                    "confidence": "high",
                },
                {"question_no": 20, "human_answer": "x=2", "confidence": "high"},
            ]
        }
        report = evaluate_against_human_transcription(payload, human)
        assert report["provider_calls"] == 0
        assert report["unsafe_auto_grade_count"] == 0
        assert report["summary"] == {
            "selected_crops": 3,
            "high_confidence_in_scope": 2,
            "exact_matches": 2,
            "unresolved": 0,
            "mismatches": 0,
            "outside_supported_scope": 1,
            "human_low_confidence": 0,
            "exact_match_percent": 100.0,
        }

    print("pp formulanet local pilot: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
