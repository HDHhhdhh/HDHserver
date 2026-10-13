from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_answer_mode_draft_targets_model import (
    AnswerModeDraftVerificationError,
    JsonValue,
    markdown,
    require_object,
    verify_draft,
)

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
TESTS_CONFIG: Final[Path] = ROOT / "tests-config.json"
DRAFT_PATH: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets.json")
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets_verification.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets_verification.md")


def main() -> int:
    draft = require_object(load_json(DRAFT_PATH), "draft")
    tests_config_text = TESTS_CONFIG.read_text(encoding="utf-8-sig")
    output = verify_draft(draft, tests_config_text)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def load_json(path: Path) -> JsonValue:
    if not path.is_file():
        raise AnswerModeDraftVerificationError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    raise SystemExit(main())
