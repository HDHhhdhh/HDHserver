from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

OCR_ROOT: Final[Path] = Path(r"C:\server-ocr")
OCR_PYTHON: Final[Path] = OCR_ROOT / ".venv" / "Scripts" / "python.exe"
ROUTE_UPLOAD_ROOT: Final[Path] = OCR_ROOT / "phase2c_route_uploads"
EXTRACT_SCRIPT: Final[Path] = OCR_ROOT / "extract_answer_sheet_crops.py"
CONTACT_SCRIPT: Final[Path] = OCR_ROOT / "make_review_contact_assets.py"
VERIFY_ASSETS_SCRIPT: Final[Path] = OCR_ROOT / "verify_review_contact_assets.py"
OVERWRITTEN_AMBIGUITY_SCRIPT: Final[Path] = OCR_ROOT / "detect_overwritten_ambiguity.py"
QUESTION_COUNT: Final[int] = 20
CONTACT_SHEET_COUNT: Final[int] = 4
DEFAULT_DEBUG_QUESTIONS: Final[tuple[int, ...]] = (3, 10, 12, 14, 15, 16, 18, 20)
COMMAND_TIMEOUT_SECONDS: Final[int] = 90


@dataclass(frozen=True, slots=True)
class Phase2CRequest:
    sid: str
    test_id: str
    round_no: int
    image_stream: BinaryIO
    original_filename: str
    content_type: str


@dataclass(frozen=True, slots=True)
class PipelineCommand:
    label: str
    error_code: str
    student_message: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Phase2CResult:
    case_id: str
    case_dir: Path
    source_image: Path
    crop_root: Path
    crop_dir: Path
    review_asset_root: Path
    asset_manifest: Path
    crop_count: int
    contact_sheet_count: int
    debug_sheet_count: int
    contact_sheets: tuple[Path, ...]
    debug_sheets: tuple[Path, ...]
    asset_verification: Path
    crop_quality: Path
    answer_box_source: str
    overwritten_ambiguity: Path | None = None


@dataclass(frozen=True, slots=True)
class Phase2CPipelineError(Exception):
    error_code: str
    student_message: str
    http_status: int = 500
    detail: str = ""

    def __str__(self) -> str:
        return self.detail or self.student_message
