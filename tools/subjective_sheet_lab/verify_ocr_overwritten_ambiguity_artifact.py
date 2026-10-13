# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias


OCR_PYTHON: Final[Path] = Path(r"C:\server-ocr\.venv\Scripts\python.exe")
DETECTOR: Final[Path] = Path(r"C:\server-ocr\detect_overwritten_ambiguity.py")
CROP_DIR: Final[Path] = Path(r"C:\server-ocr\crop_benchmark_inputs\person_03\crops")
QUESTION_COUNT: Final[int] = 20
FORBIDDEN_TOKENS: Final[tuple[str, ...]] = ("expected", "canonical_answer", "accepted_answers", "C:\\", "C:/")
JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class OverwrittenAmbiguityVerificationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    # Given: the person_03 crop set with known overwritten handwriting geometry.
    with tempfile.TemporaryDirectory(prefix="ocr_overwritten_ambiguity_") as directory:
        artifact_path = Path(directory) / "overwritten_ambiguity.json"
        repeat_path = Path(directory) / "overwritten_ambiguity_repeat.json"
        # When: the local-only detector writes its internal warning artifact.
        completed = subprocess.run(
            (str(OCR_PYTHON), str(DETECTOR), "--crop-dir", str(CROP_DIR), "--out", str(artifact_path)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "detector command failed").strip()
            raise OverwrittenAmbiguityVerificationError(message)
        payload = load_artifact(artifact_path)
        repeat = run_detector(repeat_path)
        if artifact_path.read_bytes() != repeat_path.read_bytes() or repeat.get("items") != payload.get("items"):
            raise OverwrittenAmbiguityVerificationError("detector artifact is not deterministic")
    # Then: only q016/q017 receive the non-grading overwritten warning.
    warnings = warning_map(payload)
    if warnings[15] or warnings[18]:
        raise OverwrittenAmbiguityVerificationError("clean control crops received overwritten warning")
    if warnings[16] != ("overwritten_answer",) or warnings[17] != ("overwritten_answer",):
        raise OverwrittenAmbiguityVerificationError(f"unexpected q016/q017 warnings: {warnings[16]}, {warnings[17]}")
    serialized = json.dumps(payload, ensure_ascii=False)
    if any(token.lower() in serialized.lower() for token in FORBIDDEN_TOKENS):
        raise OverwrittenAmbiguityVerificationError("artifact leaked forbidden student data")
    print(json.dumps({"ok": True, "warning_questions": [16, 17], "provider_call_count": 0, "submit_test_call_count": 0}, ensure_ascii=False))
    return 0


def load_artifact(path: Path) -> JsonObject:
    if not path.is_file():
        raise OverwrittenAmbiguityVerificationError("detector did not create artifact")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("student_facing") is not False:
        raise OverwrittenAmbiguityVerificationError("artifact contract is invalid")
    return payload


def run_detector(output_path: Path) -> JsonObject:
    completed = subprocess.run(
        (str(OCR_PYTHON), str(DETECTOR), "--crop-dir", str(CROP_DIR), "--out", str(output_path)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "detector command failed").strip()
        raise OverwrittenAmbiguityVerificationError(message)
    return load_artifact(output_path)


def warning_map(payload: JsonObject) -> dict[int, tuple[str, ...]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != QUESTION_COUNT:
        raise OverwrittenAmbiguityVerificationError("artifact must contain 20 items")
    result: dict[int, tuple[str, ...]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise OverwrittenAmbiguityVerificationError("artifact item is invalid")
        question_no = raw_item.get("question_no")
        warnings = raw_item.get("warnings")
        if not isinstance(question_no, int) or not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
            raise OverwrittenAmbiguityVerificationError("artifact item fields are invalid")
        result[question_no] = tuple(warnings)
    if sorted(result) != list(range(1, QUESTION_COUNT + 1)):
        raise OverwrittenAmbiguityVerificationError("artifact questions must be 1..20")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
