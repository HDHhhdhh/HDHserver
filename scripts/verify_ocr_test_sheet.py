# /// script
# requires-python = ">=3.10"
# ///
# ─── How to run ───
# python scripts/verify_ocr_test_sheet.py
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
TESTS_PATH = ROOT / "tests.json"
sys.path.insert(0, str(ROOT))

from app import create_app
import core.ocr_test_sheet as ocr_module
from core.ocr_test_sheet import OcrConfigError, OcrResult, extract_test_sheet_answers
from routes import api_tests


@contextmanager
def without_ocr_runtime_env() -> Iterator[None]:
    keys = ("OCR_RUNTIME_DIR", "OCR_RUNTIME_PYTHON", "OCR_WORKER_SCRIPT")
    saved = {key: os.environ.get(key) for key in keys}
    missing_root = ROOT / "tmp" / "verify-missing-ocr-runtime"
    os.environ["OCR_RUNTIME_PYTHON"] = str(missing_root / ".venv" / "Scripts" / "python.exe")
    os.environ["OCR_WORKER_SCRIPT"] = str(missing_root / "ocr_worker.py")
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def assert_config_error() -> None:
    with without_ocr_runtime_env():
        try:
            extract_test_sheet_answers(
                image_bytes=b"not-a-real-image-but-not-read-without-keys",
                filename="answers.png",
                mime_type="image/png",
            )
        except OcrConfigError as exc:
            assert "OCR" in str(exc)
            assert "missing_ocr_runtime" in exc.warnings
        else:
            raise AssertionError("expected missing OCR runtime to fail safely")


def first_gradeable_test() -> tuple[str, int, list[str]]:
    cfg = api_tests._load_tests_cfg()
    cats = cfg.get("categories") if isinstance(cfg, dict) else None
    assert isinstance(cats, dict), "tests-config categories required"
    for cat in cats.values():
        tests = cat.get("tests") if isinstance(cat, dict) else None
        if not isinstance(tests, list):
            continue
        for test_def in tests:
            if not isinstance(test_def, dict):
                continue
            test_id = str(test_def.get("id") or "").strip()
            if not test_id:
                continue
            try:
                problems = int(test_def.get("problems") or 0)
            except (TypeError, ValueError):
                problems = 0
            if problems <= 0:
                continue
            for round_no in (1, 2, 3):
                key = api_tests._get_answer_key_for_round(test_def, problems, round_no)
                if key and any(str(answer or "").strip() for answer in key):
                    return test_id, round_no, key
    raise AssertionError("no gradeable test definition found")


def assert_route_fails_without_writes() -> None:
    before = TESTS_PATH.read_bytes() if TESTS_PATH.exists() else b""
    app = create_app()
    client = app.test_client()
    test_id, round_no, _key = first_gradeable_test()

    with without_ocr_runtime_env():
        response = client.post(
            "/api/ocr-test-sheet",
            data={
                "sid": "ocr-smoke-student",
                "testId": test_id,
                "round": str(round_no),
                "image": (BytesIO(b"fake-image"), "answers.png"),
            },
            content_type="multipart/form-data",
        )

    after = TESTS_PATH.read_bytes() if TESTS_PATH.exists() else b""
    assert before == after, "OCR endpoint must not write tests.json"
    assert response.status_code == 503, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["ok"] is False
    assert "OCR" in payload["error"]
    assert "missing_ocr_runtime" in payload["warnings"]


def assert_route_returns_answer_preview_without_writes() -> None:
    before = TESTS_PATH.read_bytes() if TESTS_PATH.exists() else b""
    app = create_app()
    client = app.test_client()
    test_id, round_no, key = first_gradeable_test()
    answers_text = "\n".join(f"{index + 1}. {answer}" for index, answer in enumerate(key))
    preview_items = [{"number": 1, "answer": str(key[0] or "").strip(), "raw": f"1. {key[0]}"}]

    original_extract = ocr_module.extract_test_sheet_answers

    def fake_extract_test_sheet_answers(*, image_bytes: bytes, filename: str, mime_type: str) -> OcrResult:
        assert image_bytes
        assert filename
        assert mime_type
        return OcrResult(answers_text=answers_text, items=preview_items, warnings=["테스트 경고"])

    ocr_module.extract_test_sheet_answers = fake_extract_test_sheet_answers
    try:
        response = client.post(
            "/api/ocr-test-sheet",
            data={
                "sid": "ocr-smoke-student",
                "testId": test_id,
                "round": str(round_no),
                "image": (BytesIO(b"fake-image"), "answers.png"),
            },
            content_type="multipart/form-data",
        )
    finally:
        ocr_module.extract_test_sheet_answers = original_extract

    after = TESTS_PATH.read_bytes() if TESTS_PATH.exists() else b""
    assert before == after, "OCR preview endpoint must not write tests.json"
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["answersText"] == answers_text
    assert payload["items"] == preview_items
    assert "score" not in payload
    assert "wrong" not in payload
    assert "pct" not in payload
    assert "테스트 경고" in payload["warnings"]


if __name__ == "__main__":
    assert_config_error()
    assert_route_fails_without_writes()
    assert_route_returns_answer_preview_without_writes()
    print("verify_ocr_test_sheet: ok")
