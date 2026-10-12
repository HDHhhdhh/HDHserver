from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_mijeok1_draft_postprocess_model import (
    AnswerMode,
    DraftPostprocessError,
    JsonValue,
    TARGET_TEST_ID,
    markdown,
    modes_from_draft,
    require_object,
    summary_to_json,
    verify_modes,
)

DRAFT_PATH: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets.json")
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_mijeok1_draft_postprocess_verification.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_mijeok1_draft_postprocess_verification.md")


def main() -> int:
    modes = load_target_modes(DRAFT_PATH)
    summary = verify_modes(modes)
    output: dict[str, JsonValue] = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "test_id": TARGET_TEST_ID,
        "summary": summary_to_json(summary),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(summary), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def load_target_modes(path: Path) -> dict[int, AnswerMode]:
    draft = require_object(json.loads(path.read_text(encoding="utf-8")), "draft")
    return modes_from_draft(draft)


if __name__ == "__main__":
    raise SystemExit(main())
