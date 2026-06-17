from __future__ import annotations

import json
import os
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence, TypedDict

from core.ocr_answer_parse import (
    OcrLine,
    extract_answers_text_from_ocr_lines,
    has_numbered_answer_marker,
    normalize_ocr_text,
)


MAX_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES: Final[frozenset[str]] = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
})
ALLOWED_IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
})
LOW_CONFIDENCE_THRESHOLD: Final[float] = 0.65
MISSING_OCR_RUNTIME: Final[str] = "missing_ocr_runtime"
MISSING_LOCAL_OCR_ENGINE: Final[str] = "missing_local_ocr_engine"
MANUAL_REVIEW_REQUIRED: Final[str] = "manual_review_required"
OCR_RUNTIME_TIMEOUT_SECONDS: Final[float] = 60.0


class OcrError(RuntimeError):
    def __init__(self, message: str, warnings: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.warnings = [str(w) for w in warnings if str(w)]


class OcrInputError(OcrError):
    pass


class OcrConfigError(OcrError):
    pass


class OcrRemoteError(OcrError):
    pass


class OcrItem(TypedDict, total=False):
    no: int
    answer: str
    confidence: float


@dataclass(frozen=True, slots=True)
class OcrRuntimePaths:
    python_exe: Path
    worker_script: Path


@dataclass(frozen=True, slots=True)
class WorkerResponse:
    ok: bool
    lines: list[OcrLine]
    error: str
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class OcrResult:
    answers_text: str
    items: list[OcrItem]
    warnings: list[str]


def extract_test_sheet_answers(
    *,
    image_bytes: bytes,
    filename: str,
    mime_type: str,
) -> OcrResult:
    suffix = _validate_image_upload(image_bytes, filename, mime_type)
    return _recognize_validated_image(image_bytes, suffix=suffix)


def run_local_ocr(image_bytes: bytes, filename: str | None = None) -> list[OcrLine]:
    suffix = _validate_image_upload(image_bytes, filename or "upload.png", "")
    image_path = _write_temp_image(image_bytes, suffix=suffix)
    try:
        response = _run_worker(image_path)
    finally:
        _remove_temp_file(image_path)
    if not response.ok:
        _raise_worker_error(response)
    return response.lines


def recognize_test_sheet(image_bytes: bytes, filename: str | None = None) -> OcrResult:
    suffix = _validate_image_upload(image_bytes, filename or "upload.png", "")
    return _recognize_validated_image(image_bytes, suffix=suffix)


def _recognize_validated_image(image_bytes: bytes, *, suffix: str) -> OcrResult:
    image_path = _write_temp_image(image_bytes, suffix=suffix)
    try:
        response = _run_worker(image_path)
    finally:
        _remove_temp_file(image_path)
    if not response.ok:
        _raise_worker_error(response)

    answers_text = extract_answers_text_from_ocr_lines(response.lines).strip()
    if not answers_text:
        raise OcrRemoteError("OCR 결과에서 답안을 찾지 못했습니다.", [MANUAL_REVIEW_REQUIRED])

    warnings = list(response.warnings)
    if any(line.confidence is not None and line.confidence < LOW_CONFIDENCE_THRESHOLD for line in response.lines):
        _append_warning_once(warnings, MANUAL_REVIEW_REQUIRED)
    if not has_numbered_answer_marker(response.lines):
        _append_warning_once(warnings, MANUAL_REVIEW_REQUIRED)

    return OcrResult(
        answers_text=answers_text,
        items=[],
        warnings=warnings,
    )


def _run_worker(image_path: Path) -> WorkerResponse:
    paths = _runtime_paths()
    _ensure_runtime_ready(paths)
    command = [str(paths.python_exe), str(paths.worker_script), "--image", str(image_path)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=OCR_RUNTIME_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrRemoteError("OCR 처리 시간이 초과되었습니다.", [MANUAL_REVIEW_REQUIRED]) from exc
    except OSError as exc:
        raise OcrConfigError("OCR 런타임을 실행하지 못했습니다.", [MISSING_OCR_RUNTIME]) from exc

    stdout = str(completed.stdout or "").strip()
    if not stdout:
        detail = str(completed.stderr or "").strip()[:300]
        raise OcrRemoteError(f"OCR worker 응답이 비어 있습니다. {detail}".strip(), [MANUAL_REVIEW_REQUIRED])

    response = _parse_worker_stdout(stdout)
    if completed.returncode != 0 and response.ok:
        raise OcrRemoteError("OCR worker 종료 코드가 올바르지 않습니다.", [MANUAL_REVIEW_REQUIRED])
    return response


def _runtime_paths() -> OcrRuntimePaths:
    runtime_root = Path(os.environ.get("OCR_RUNTIME_DIR", r"C:\server-ocr"))
    python_default = runtime_root / ".venv" / "Scripts" / "python.exe"
    worker_default = runtime_root / "ocr_worker.py"
    return OcrRuntimePaths(
        python_exe=Path(os.environ.get("OCR_RUNTIME_PYTHON", str(python_default))),
        worker_script=Path(os.environ.get("OCR_WORKER_SCRIPT", str(worker_default))),
    )


def _ensure_runtime_ready(paths: OcrRuntimePaths) -> None:
    if not paths.worker_script.is_file():
        raise OcrConfigError("OCR worker가 준비되지 않았습니다.", [MISSING_OCR_RUNTIME])
    if not paths.python_exe.is_file():
        raise OcrConfigError("OCR 런타임이 준비되지 않았습니다.", [MISSING_OCR_RUNTIME])


def _parse_worker_stdout(stdout: str) -> WorkerResponse:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise OcrRemoteError("OCR worker JSON 응답을 해석하지 못했습니다.", [MANUAL_REVIEW_REQUIRED]) from exc
    if not isinstance(parsed, dict):
        raise OcrRemoteError("OCR worker 응답 형식이 올바르지 않습니다.", [MANUAL_REVIEW_REQUIRED])

    ok = parsed.get("ok") is True
    error = str(parsed.get("error") or "")
    warnings = _string_list(parsed.get("warnings"))
    lines = _parse_worker_lines(parsed.get("lines"))
    return WorkerResponse(ok=ok, lines=lines, error=error, warnings=warnings)


def _parse_worker_lines(raw_lines) -> list[OcrLine]:
    if not isinstance(raw_lines, list):
        return []
    lines: list[OcrLine] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        text = normalize_ocr_text(str(raw_line.get("text") or ""))
        if not text:
            continue
        lines.append(OcrLine(text=text, confidence=_as_confidence(raw_line.get("confidence"))))
    return lines


def _raise_worker_error(response: WorkerResponse) -> None:
    message = response.error or "OCR 처리에 실패했습니다."
    warnings = response.warnings
    if MISSING_LOCAL_OCR_ENGINE in warnings or MISSING_OCR_RUNTIME in warnings:
        raise OcrConfigError(message, warnings)
    raise OcrRemoteError(message, warnings)


def _write_temp_image(image_bytes: bytes, *, suffix: str) -> Path:
    try:
        with tempfile.NamedTemporaryFile(prefix="ocr-test-sheet-", suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            return Path(tmp.name)
    except OSError as exc:
        raise OcrRemoteError("OCR 임시 이미지 파일을 만들지 못했습니다.", [MANUAL_REVIEW_REQUIRED]) from exc


def _remove_temp_file(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _validate_image_upload(image_bytes: bytes, filename: str, mime_type: str) -> str:
    if not image_bytes:
        raise OcrInputError("이미지 파일이 비어 있습니다.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise OcrInputError("이미지는 8MB 이하만 업로드할 수 있습니다.")

    suffix = _file_suffix(filename)
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if suffix in ALLOWED_IMAGE_EXTENSIONS:
        return suffix
    if normalized_mime in ALLOWED_IMAGE_MIME_TYPES:
        return _suffix_for_mime(normalized_mime)
    raise OcrInputError("jpg, png, webp 이미지 파일만 업로드할 수 있습니다.")


def _file_suffix(filename: str) -> str:
    clean_name = str(filename or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    dot_index = clean_name.rfind(".")
    if dot_index < 0:
        return ""
    return clean_name[dot_index:].lower()


def _suffix_for_mime(mime_type: str) -> str:
    if mime_type == "image/jpeg":
        return ".jpg"
    if mime_type == "image/webp":
        return ".webp"
    return ".png"


def _as_confidence(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        confidence = float(value)
        if 0.0 <= confidence <= 1.0:
            return confidence
    return None


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _append_warning_once(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
