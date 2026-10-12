from __future__ import annotations

import json
from pathlib import Path
from typing import Final

TEMPLATE: Final[Path] = Path(__file__).with_name("ocr_live_call_authorization_templates.md")
REQUIRED_PHRASES: Final[tuple[str, ...]] = (
    "Google/Gemini 외부 provider",
    "학생 자료 외부 전송 위험",
    "fresh provider call budget은 총 1회",
    "/api/submit-test는 호출하지 않는다",
    "#tsSubmit은 클릭하지 않는다",
    "API key/.env는 출력하지 않는다",
    "Production default: `NO-GO`",
)


class LiveAuthorizationTemplateError(Exception):
    pass


def main() -> int:
    text = TEMPLATE.read_text(encoding="utf-8")
    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in text]
    if missing:
        raise LiveAuthorizationTemplateError(f"missing required phrases: {missing}")
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "template": TEMPLATE.name,
        "required_phrase_count": len(REQUIRED_PHRASES),
        "templates_present": {
            "unit_no_submit": "UNIT Live OCR, No Submit" in text,
            "training_pack_no_submit": "Training Pack Live OCR, No Submit" in text,
            "live_plus_submit": "Live OCR And One Local Submit Record" in text,
            "repeat_one_call": "Repeat Live OCR 1 Call" in text,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
