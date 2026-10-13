# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/validate_ocr_review_contract.py

from __future__ import annotations

from ocr_review_payload_validator import (
    ContractError,
    JsonObject,
    JsonValue,
    PayloadMode,
    ROOT,
    read_json,
    require_array,
    require_object,
    require_positive_int,
    require_string,
    validate_all,
    validate_payload,
)


def main() -> int:
    validate_all(ROOT)
    print("ok: OCR review contract fixtures are valid")
    print("ok: final review payload converts to answersText")
    print("ok: unresolved statuses remain blocked from final bridge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
