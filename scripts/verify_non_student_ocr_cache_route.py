from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from flask import Flask

STAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STAGE_ROOT))

from routes.api_non_student_ocr import bp_api_non_student_ocr  # noqa: E402

SOURCE_CAPTURE = Path(
    "C:/server-ocr/gemini_gateway_smoke_outputs/"
    "adult_non_student_20260727_01/teacher_01_gateway_smoke/C"
)
ENV_KEYS = (
    "NON_STUDENT_OCR_CAPTURED_CACHE_ROUTE_ENABLED",
    "NON_STUDENT_OCR_CAPTURED_CACHE_TOKEN",
    "NON_STUDENT_OCR_CAPTURED_CACHE_ROOT",
    "NON_STUDENT_OCR_CAPTURED_CACHE_RELATIVE_DIR",
    "NON_STUDENT_OCR_CAPTURED_CACHE_CASE_ID",
    "NON_STUDENT_OCR_CAPTURED_CACHE_TEST_ID",
    "NON_STUDENT_OCR_CAPTURED_CACHE_ROUND",
)


@contextmanager
def configured_environment(root: Path) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    os.environ.update(
        {
            "NON_STUDENT_OCR_CAPTURED_CACHE_ROUTE_ENABLED": "1",
            "NON_STUDENT_OCR_CAPTURED_CACHE_TOKEN": "test-internal-token",
            "NON_STUDENT_OCR_CAPTURED_CACHE_ROOT": str(root),
            "NON_STUDENT_OCR_CAPTURED_CACHE_RELATIVE_DIR": "capture",
            "NON_STUDENT_OCR_CAPTURED_CACHE_CASE_ID": "adult_teacher_01_capture_001",
            "NON_STUDENT_OCR_CAPTURED_CACHE_TEST_ID": "adult_non_student_benchmark_20",
            "NON_STUDENT_OCR_CAPTURED_CACHE_ROUND": "1",
        }
    )
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_app() -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.register_blueprint(bp_api_non_student_ocr)
    return app


def copy_capture(root: Path) -> Path:
    capture = root / "capture"
    capture.mkdir(parents=True, exist_ok=True)
    for name in ("provider_input_manifest.json", "recognized.json"):
        shutil.copy2(SOURCE_CAPTURE / name, capture / name)
    return capture


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    app = build_app()
    client = app.test_client()

    disabled = client.post(
        "/api/internal/non-student-ocr/review-cache",
        json={"case_id": "adult_teacher_01_capture_001"},
    )
    require(disabled.status_code == 503, "route must be disabled by default")

    with tempfile.TemporaryDirectory(prefix="non_student_ocr_route_") as temp_dir:
        root = Path(temp_dir)
        capture = copy_capture(root)
        with configured_environment(root):
            unauthorized = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_teacher_01_capture_001"},
            )
            require(unauthorized.status_code == 403, "internal token must be required")

            headers = {"X-Internal-OCR-Token": "test-internal-token"}
            injected = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_teacher_01_capture_001", "cache_path": "capture"},
                headers=headers,
            )
            require(injected.status_code == 400, "client cache-path injection must fail closed")

            unknown = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_unknown"},
                headers=headers,
            )
            require(unknown.status_code == 404, "unknown case must fail closed")

            response = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_teacher_01_capture_001"},
                headers=headers,
            )
            require(response.status_code == 200, "captured cache route must return HTTP 200")
            payload = response.get_json()
            require(payload["provider_calls"] == 0, "provider calls must remain zero")
            require(payload["payload"]["problem_count"] == 20, "problem count must be 20")
            items = payload["payload"]["items"]
            require(len(items) == 20, "payload must contain 20 items")
            require(all(item["review_state"] == "review_recommended" for item in items), "all captured candidates must require review")
            require(all(item["final_answer"] is None for item in items), "captured candidates must not create final answers")
            require(all(item["candidate_source"] == "gemini_captured_cache" for item in items), "candidate source must be retained")
            encoded = json.dumps(payload, ensure_ascii=False)
            require("C:\\" not in encoded, "response must not contain a local path")

            manifest_path = capture / "provider_input_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["contact_sha256"][0] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            tampered = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_teacher_01_capture_001"},
                headers=headers,
            )
            require(tampered.status_code == 409, "tampered identity must fail closed")
            require(tampered.get_json()["code"] == "CACHE_IDENTITY_MISMATCH", "tamper code must be explicit")

            copy_capture(root)
            recognized_path = capture / "recognized.json"
            recognized = json.loads(recognized_path.read_text(encoding="utf-8"))
            recognized["items"][0]["recognized"] = "C:\\server\\private"
            recognized_path.write_text(json.dumps(recognized), encoding="utf-8")
            leaking = client.post(
                "/api/internal/non-student-ocr/review-cache",
                json={"case_id": "adult_teacher_01_capture_001"},
                headers=headers,
            )
            require(leaking.status_code == 400, "local paths in cache candidates must fail closed")
            require(leaking.get_json()["code"] == "LOCAL_PATH_DETECTED", "path leak code must be explicit")

    print(
        json.dumps(
            {
                "ok": True,
                "defaultOff": True,
                "tokenRequired": True,
                "clientPathInjectionBlocked": True,
                "localPathLeakBlocked": True,
                "payloadItems": 20,
                "reviewRecommended": 20,
                "autoConfirm": 0,
                "finalAnswers": 0,
                "providerCalls": 0,
                "submitCalls": 0,
                "productionDefault": "NO-GO",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
