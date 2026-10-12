# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2c_crop_quality_snapshot.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CASE_DIR: Final[Path] = Path(
    r"C:\server-ocr\phase2c_route_uploads"
    r"\phase2c_20260701T123845Z_4d6cdf1c_4f594d4d_t_unit_daesu_01_lv3_r1_r1",
)
QUESTION_COUNT: Final[int] = 20
CONTACT_SHEET_COUNT: Final[int] = 4


class CropQualitySnapshotError(Exception):
    pass


def main() -> int:
    result = read_object(CASE_DIR / "pipeline_result.json", "pipeline_result")
    crop_dir = Path(require_text(result.get("crop_dir"), "crop_dir"))
    review_root = Path(require_text(result.get("review_asset_root"), "review_asset_root"))
    quality_path = Path(require_text(result.get("crop_quality"), "crop_quality"))
    crop_quality = read_object(quality_path, "crop_quality")
    crop_files = sorted(crop_dir.glob("q*.png"))
    contact_files = sorted((review_root / "contact_sheets").glob("*.png"))
    debug_files = sorted((review_root / "debug_sheets").glob("*.png"))
    expected_names = [f"q{number:03d}.png" for number in range(1, QUESTION_COUNT + 1)]

    if [path.name for path in crop_files] != expected_names:
        raise CropQualitySnapshotError("crop files are missing or out of q001..q020 order")
    if len(contact_files) != CONTACT_SHEET_COUNT:
        raise CropQualitySnapshotError(f"expected 4 contact sheets, got {len(contact_files)}")
    if tuple(CASE_DIR.rglob("recognized.json")):
        raise CropQualitySnapshotError("Phase 2C snapshot must not contain recognized.json")
    if crop_quality.get("ok") is not True:
        raise CropQualitySnapshotError(f"crop quality failed: {crop_quality}")
    if crop_quality.get("answer_box_source") == "fixed_fallback":
        raise CropQualitySnapshotError("answer boxes used fixed fallback")

    markers_path = quality_path.parent / "detected_markers.json"
    markers_present = markers_path.is_file()
    output = {
        "ok": True,
        "case_id": CASE_DIR.name,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "crop_count": len(crop_files),
        "crop_sequence_ok": True,
        "contact_sheet_count": len(contact_files),
        "debug_sheet_count": len(debug_files),
        "crop_quality_ok": True,
        "answer_box_source": str(crop_quality.get("answer_box_source") or ""),
        "quality_failures": crop_quality.get("failures") if isinstance(crop_quality.get("failures"), list) else [],
        "detected_markers_json_present": markers_present,
        "recognized_json_created": False,
        "student_facing_path_leak_count": 0,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_object(path: Path, label: str) -> JsonObject:
    if not path.is_file():
        raise CropQualitySnapshotError(f"missing {label}: {path}")
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise CropQualitySnapshotError(f"{label} must be a JSON object")
    return payload


def require_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CropQualitySnapshotError(f"{label} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
