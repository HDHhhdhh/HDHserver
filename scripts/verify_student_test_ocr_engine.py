from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core.student_test_ocr_engine import (
    ConfidencePolicy,
    OcrCrop,
    OcrEngineError,
    WorkerSpec,
    recognize_answer_value_crop,
    recognize_sheet,
    _build_answer_candidate,
)
from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    STATUS_READY_TO_GRADE,
    STATUS_RETAKE_REQUIRED,
    STATUS_STUDENT_ACTION_REQUIRED,
)


FAKE_WORKER = r'''
from __future__ import annotations
import argparse, json, os, sys

parser = argparse.ArgumentParser()
parser.add_argument("--engine", required=True)
parser.add_argument("--mismatch", type=int, default=0)
parser.add_argument("--mismatch-count", type=int, default=0)
parser.add_argument("--incomplete-count", type=int, default=0)
args = parser.parse_args()
payload = json.load(sys.stdin)
assert payload["schema"] == "student_test_ocr_worker_v1"
encoded = json.dumps(payload, sort_keys=True).lower()
assert "answerkey" not in encoded and "correctanswer" not in encoded and "expected" not in encoded
items = []
second_pass = os.environ.get("STUDENT_TEST_OCR_UNIMERNET_SECOND_PASS") == "1"
for item in payload["items"]:
    number = item["questionNo"]
    if args.engine == "paddle":
        text, score = ("3", 0.999) if number % 2 else ("0.5", 0.999)
        items.append({"questionNo": number, "text": text, "score": score, "variantText": text, "variantScore": score, "variantAgreed": True})
    elif args.engine == "choice_digit":
        items.append({"questionNo": number, "text": "3", "score": 0.9999, "margin": 0.999, "variantText": "3", "variantAgreed": True, "accepted": True})
    elif args.engine == "formula":
        items.append({"questionNo": number, "text": "1/2"})
    else:
        text = "3" if number % 2 else "1/2"
        should_mismatch = number == args.mismatch or (
            args.mismatch_count and number % 2 == 0 and number <= args.mismatch_count * 2
        )
        if should_mismatch and not second_pass:
            text = "4"
        variant = text if second_pass else ""
        completed = not (number % 2 == 0 and number <= args.incomplete_count * 2)
        items.append({"questionNo": number, "text": text, "tokenConfidence": 0.9999,
                      "terminated": completed, "tokenCount": 3 if completed else 64,
                      "variantText": variant, "variantAgreed": bool(variant)})
print(json.dumps({"ok": True, "engine": args.engine, "items": items}, separators=(",", ":")))
'''


def _raises(code: str, callback) -> None:
    try:
        callback()
    except OcrEngineError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-engine-") as temp_dir:
        root = Path(temp_dir)
        worker = root / "fake_worker.py"
        worker.write_text(FAKE_WORKER, encoding="utf-8")
        asset_root = root / "assets"
        asset_root.mkdir()
        crops = []
        for number in range(1, 21):
            crop_path = asset_root / f"q{number:03d}.jpg"
            crop_path.write_bytes(b"fake-image")
            crops.append(OcrCrop(number, CHOICE_NUMBER if number % 2 else ANSWER_VALUE, crop_path))

        paddle = WorkerSpec("paddle", Path(sys.executable), worker, arguments=("--engine", "paddle"))
        unimernet = WorkerSpec("unimernet", Path(sys.executable), worker, arguments=("--engine", "unimernet"))
        decision = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=unimernet,
        )
        assert decision["status"] == STATUS_READY_TO_GRADE and decision["uncertainCount"] == 0
        assert decision["items"][0]["rawAnswer"] == "3"
        assert decision["items"][1]["normalizedAnswer"] == "1/2"
        assert set(decision["workers"]) == {"paddle", "unimernet"}
        assertions += 4

        choice = WorkerSpec("choice_digit", Path(sys.executable), worker, arguments=("--engine", "choice_digit"))
        formula = WorkerSpec("formula", Path(sys.executable), worker, arguments=("--engine", "formula"))
        routed = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=unimernet,
            choice_worker=choice,
            formula_worker=formula,
            policy=ConfidencePolicy(require_choice_cross_engine_agreement=False),
        )
        assert routed["status"] == STATUS_READY_TO_GRADE and routed["uncertainCount"] == 0
        assert set(routed["workers"]) == {"choice_digit", "paddle", "formula", "unimernet"}
        assertions += 2

        primary = {"text": "1/2", "tokenConfidence": 0.9999, "variantText": "1/2", "variantAgreed": True,
                   "terminated": True, "tokenCount": 3}
        assert _build_answer_candidate(crops[1], {}, primary, {}, ConfidencePolicy())["confident"] is False
        assert _build_answer_candidate(crops[1], {"text": "0.5"}, primary, {}, ConfidencePolicy())["confident"] is True
        assert _build_answer_candidate(crops[1], {"text": "0.6"}, primary, {}, ConfidencePolicy())["confident"] is False
        assertions += 3
        for invalid in ({"terminated": False}, {"tokenCount": 64}, {"tokenCount": True}, {"tokenCount": 0},
                        {"tokenConfidence": float("nan")}, {"tokenConfidence": float("inf")}, {"text": "1 2"}):
            assert not _build_answer_candidate(crops[1], {"text": "0.5"}, {**primary, **invalid}, {}, ConfidencePolicy())["confident"]
            assertions += 1
        missing = {key: value for key, value in primary.items() if key not in {"terminated", "tokenCount"}}
        assert not _build_answer_candidate(crops[1], {"text": "0.5"}, missing, {}, ConfidencePolicy())["confident"]
        assertions += 1
        for incomplete_count, status in ((3, STATUS_STUDENT_ACTION_REQUIRED), (4, STATUS_RETAKE_REQUIRED)):
            incomplete_worker = WorkerSpec("unimernet", Path(sys.executable), worker,
                arguments=("--engine", "unimernet", "--incomplete-count", str(incomplete_count)))
            incomplete = recognize_sheet(crops=crops, asset_root=asset_root, paddle_worker=paddle,
                unimernet_worker=incomplete_worker, choice_worker=choice, formula_worker=formula,
                policy=ConfidencePolicy(require_choice_cross_engine_agreement=False, enable_adaptive_formula_second_pass=False))
            assert incomplete["status"] == status and incomplete["uncertainCount"] == incomplete_count
            assertions += 1
        all_choice = [OcrCrop(c.question_no, CHOICE_NUMBER, c.image_path) for c in crops]
        absent_worker = WorkerSpec("paddle", root / "missing.exe", root / "missing.py")
        only_choice = recognize_sheet(crops=all_choice, asset_root=asset_root, paddle_worker=absent_worker,
                                     unimernet_worker=absent_worker, choice_worker=choice, formula_worker=absent_worker,
                                     policy=ConfidencePolicy(require_choice_cross_engine_agreement=False))
        assert only_choice["status"] == STATUS_READY_TO_GRADE
        assert set(only_choice["workers"]) == {"choice_digit"}
        assertions += 2

        adaptive_unimernet = WorkerSpec(
            "unimernet",
            Path(sys.executable),
            worker,
            arguments=("--engine", "unimernet", "--mismatch", "2"),
        )
        adaptive = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=adaptive_unimernet,
            choice_worker=choice,
            formula_worker=formula,
            policy=ConfidencePolicy(require_choice_cross_engine_agreement=False),
        )
        assert adaptive["status"] == STATUS_READY_TO_GRADE and adaptive["uncertainCount"] == 0
        assert "unimernet_second_pass" in adaptive["workers"]
        assertions += 2

        four_uncertain_unimernet = WorkerSpec(
            "unimernet",
            Path(sys.executable),
            worker,
            arguments=("--engine", "unimernet", "--mismatch-count", "4"),
        )
        four_uncertain = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=four_uncertain_unimernet,
            choice_worker=choice,
            formula_worker=formula,
            policy=ConfidencePolicy(require_choice_cross_engine_agreement=False),
        )
        assert four_uncertain["status"] == STATUS_RETAKE_REQUIRED
        assert four_uncertain["uncertainQuestionNos"] == (2, 4, 6, 8)
        assert "unimernet_second_pass" not in four_uncertain["workers"]
        assertions += 3

        recaptured = recognize_answer_value_crop(
            question_no=2,
            image_path=crops[1].image_path,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=unimernet,
        )
        assert recaptured["questionNo"] == 2 and recaptured["confident"] is True
        assert recaptured["rawAnswer"] == "1/2"
        assertions += 2

        routed_recapture = recognize_answer_value_crop(
            question_no=2,
            image_path=crops[1].image_path,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=unimernet,
            formula_worker=formula,
        )
        assert routed_recapture["confident"] is True
        assert set(routed_recapture["workers"]) == {"paddle", "formula", "unimernet"}
        assertions += 2

        adaptive_recapture = recognize_answer_value_crop(
            question_no=2,
            image_path=crops[1].image_path,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=adaptive_unimernet,
            formula_worker=formula,
        )
        assert adaptive_recapture["confident"] is True
        assert "unimernet_second_pass" in adaptive_recapture["workers"]
        assertions += 2

        mismatched_unimernet = WorkerSpec(
            "unimernet",
            Path(sys.executable),
            worker,
            arguments=("--engine", "unimernet", "--mismatch", "1"),
        )
        mismatch = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=mismatched_unimernet,
        )
        assert mismatch["status"] == STATUS_STUDENT_ACTION_REQUIRED
        assert mismatch["uncertainQuestionNos"] == (1,)
        assert mismatch["items"][0]["studentAction"] == "student_choice"
        assertions += 3

        low_paddle = ConfidencePolicy(choice_paddle_minimum=1.0)
        low_confidence = recognize_sheet(
            crops=crops,
            asset_root=asset_root,
            paddle_worker=paddle,
            unimernet_worker=unimernet,
            policy=low_paddle,
        )
        assert low_confidence["uncertainCount"] == 10
        assertions += 1

        outside = root / "outside.jpg"
        outside.write_bytes(b"outside")
        escaped = list(crops)
        escaped[0] = OcrCrop(1, CHOICE_NUMBER, outside)
        _raises(
            "invalid_crop_path",
            lambda: recognize_sheet(
                crops=escaped,
                asset_root=asset_root,
                paddle_worker=paddle,
                unimernet_worker=unimernet,
            ),
        )
        assertions += 1

        unsafe = WorkerSpec(
            "paddle",
            Path(sys.executable),
            worker,
            arguments=("--engine", "paddle"),
            environment={"OCR_API_TOKEN": "must-not-forward"},
        )
        _raises(
            "unsafe_worker_environment",
            lambda: recognize_sheet(
                crops=crops,
                asset_root=asset_root,
                paddle_worker=unsafe,
                unimernet_worker=unimernet,
            ),
        )
        assertions += 1

    return {"name": "student-test-ocr-engine", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
