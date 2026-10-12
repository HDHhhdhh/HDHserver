from __future__ import annotations

import tempfile
import subprocess
import sys
from pathlib import Path

from scripts import student_test_choice_worker as choice
from scripts import student_test_formula_worker as formula
from scripts import student_test_paddle_worker as paddle
from scripts import student_test_unimernet_worker as unimernet
from scripts.verify_student_test_formula_generation import run as verify_generation


ROOT = Path(__file__).resolve().parents[1]


def _valid_payload(root: Path) -> dict:
    items = []
    for number in range(1, 21):
        path = root / f"q{number:03d}.jpg"
        path.write_bytes(b"fixture")
        items.append({"questionNo": number, "imagePath": str(path)})
    return {"schema": "student_test_ocr_worker_v1", "items": items}


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-worker-contract-") as temp_dir:
        root = Path(temp_dir)
        payload = _valid_payload(root)
        for parser in (choice.parse_request, formula.parse_request, paddle.parse_request, unimernet.parse_request):
            assert [number for number, _path in parser(payload)] == list(range(1, 21))
        assertions += 4

        single = {"schema": payload["schema"], "items": [payload["items"][7]]}
        for parser in (choice.parse_request, formula.parse_request, paddle.parse_request, unimernet.parse_request):
            assert parser(single)[0][0] == 8
        assertions += 4

        leaked = {**payload, "answerKeys": ["3"] * 20}
        for parser in (choice.parse_request, formula.parse_request, paddle.parse_request, unimernet.parse_request):
            try:
                parser(leaked)
            except (choice.WorkerInputError, formula.WorkerInputError, paddle.WorkerInputError, unimernet.WorkerInputError):
                pass
            else:
                raise AssertionError("worker accepted an answer-key field")
        assertions += 4

        text, score = paddle.extract_recognition({"res": {"rec_text": " ③ ", "rec_score": 0.998}})
        assert text == "③" and score == 0.998
        assert paddle.extract_recognition({"res": {"rec_text": "x", "rec_score": 5}}) == ("x", None)
        assert formula.extract_formula({"res": {"rec_formula": r"\frac{1}{2}"}}) == r"\frac{1}{2}"
        assertions += 3

        assert unimernet.normalized_formula(r"\frac { 1 } { 2 }") == r"\frac{1}{2}"
        assert unimernet.normalized_formula(r"\left( 2 \right)") == "(2)"
        unimernet_source = (ROOT / "scripts" / "student_test_unimernet_worker.py").read_text(
            encoding="utf-8"
        )
        assert "STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS" in unimernet_source
        assert "UnsharpMask" in unimernet_source
        assertions += 4

        config = unimernet.runtime_config_text(Path("C:/models/unimernet"), "weights.pth")
        assert "device: cpu" in config and "do_sample: false" in config
        assert "max_seq_len: 64" in config
        assert "answer" not in config.lower()
        assertions += 3
        direct = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/student_test_unimernet_worker.py")],
                                input="{}", text=True, capture_output=True, cwd=root, timeout=15)
        assert direct.returncode == 1 and '"error":"WorkerInputError"' in direct.stdout
        assert "ModuleNotFoundError" not in direct.stderr
        assertions += 2

        v3 = {"model_version": "choice_digit_v3", "labels": ("1", "2", "3", "4", "5")}
        v4 = {
            "model_version": "choice_digit_v4",
            "labels": ("1", "2", "3", "4", "5", "__reject__"),
            "input_size": 48,
        }
        assert choice.checkpoint_contract(v3) == ("choice_digit_v3", choice.V3_LABELS, 48)
        assert choice.checkpoint_contract(v4) == ("choice_digit_v4", choice.V4_LABELS, 48)
        accepted = choice.worker_decision(
            (("3", 0.999, 0.98), ("3", 0.998, 0.97)),
            minimum=0.995,
            margin_minimum=0.90,
        )
        assert accepted["text"] == "3" and accepted["accepted"] is True and accepted["rejected"] is False
        rejected = choice.worker_decision(
            (("__reject__", 0.999, 0.98), ("__reject__", 0.998, 0.97)),
            minimum=0.995,
            margin_minimum=0.90,
        )
        assert rejected["text"] == "" and rejected["accepted"] is False and rejected["rejected"] is True
        disagreement = choice.worker_decision(
            (("3", 0.999, 0.98), ("__reject__", 0.998, 0.97)),
            minimum=0.995,
            margin_minimum=0.90,
        )
        assert disagreement["variantAgreed"] is False and disagreement["accepted"] is False
        assertions += 5

        manager_source = (ROOT / "scripts" / "manage_isolated_design_server.ps1").read_text(encoding="utf-8")
        for worker_name in (
            "student_test_choice_worker.py",
            "student_test_formula_worker.py",
            "student_test_paddle_worker.py",
            "student_test_unimernet_worker.py",
            "student_test_formula_inference.py",
            "student_test_ocr_worker_server.py",
            "student_test_sheet_crop_worker.py",
        ):
            assert worker_name in manager_source
        assert "copiedWorkerScripts = 7" in manager_source
        assert "STUDENT_TEST_OCR_ASSET_ROOT" in manager_source
        assert "STUDENT_TEST_OCR_ALLOW_UNREADY_MODELS" in manager_source
        assert "studentTestOcrEnabled" in manager_source
        assert "studentTestOcrAllowUnreadyModels" in manager_source
        assertions += 11

    assertions += verify_generation()["assertions"]

    return {"name": "student-test-ocr-worker-contracts", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
