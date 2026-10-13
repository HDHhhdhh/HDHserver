# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias


ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_overwritten_ambiguity_artifact import (  # noqa: E402
    OverwrittenAmbiguityArtifactError,
    parse_warning_map,
)


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ArtifactSchemaVerificationError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def main() -> int:
    # Given: a complete local-only artifact plus malformed variants.
    valid = valid_artifact()
    # When: the parser receives a valid artifact.
    warnings = parse_warning_map(valid)
    # Then: all 20 questions are available.
    if len(warnings) != 20:
        raise ArtifactSchemaVerificationError("valid artifact did not retain 20 questions")
    # Given: extra fields that could carry paths or non-contract metadata.
    extra_root = valid | {"filesystem_path": "internal-only"}
    extra_item = valid_artifact()
    items = extra_item["items"]
    if not isinstance(items, list) or not isinstance(items[0], dict):
        raise ArtifactSchemaVerificationError("fixture item is invalid")
    items[0]["extra"] = "not-allowed"
    duplicate_question = valid_artifact()
    duplicate_items = require_items(duplicate_question)
    duplicate_items[1]["question_no"] = 1
    unknown_question = valid_artifact()
    unknown_items = require_items(unknown_question)
    unknown_items[-1]["question_no"] = 21
    unknown_warning = valid_artifact()
    unknown_warning_items = require_items(unknown_warning)
    unknown_warning_items[15]["warnings"] = ["unexpected_warning"]
    duplicate_warning = valid_artifact()
    duplicate_warning_items = require_items(duplicate_warning)
    duplicate_warning_items[15]["warnings"] = ["overwritten_answer", "overwritten_answer"]
    nonzero_call_count = valid | {"provider_call_count": 1}
    nonzero_external_count = valid | {"external_ocr_api_call_count": 1}
    nonzero_submit_count = valid | {"submit_test_call_count": 1}
    bad_production_default = valid | {"production_default": "GO"}
    # When / Then: each malformed artifact fails closed before payload construction.
    assert_rejected(extra_root, "extra root field")
    assert_rejected(extra_item, "extra item field")
    assert_rejected(duplicate_question, "duplicate question")
    assert_rejected(unknown_question, "unknown question")
    assert_rejected(unknown_warning, "unknown warning")
    assert_rejected(duplicate_warning, "duplicate warning")
    assert_rejected(nonzero_call_count, "nonzero provider call count")
    assert_rejected(nonzero_external_count, "nonzero external OCR call count")
    assert_rejected(nonzero_submit_count, "nonzero submit call count")
    assert_rejected(bad_production_default, "bad production default")
    print('{"ok": true, "rejected_variants": 10, "provider_call_count": 0, "submit_test_call_count": 0}')
    return 0


def assert_rejected(payload: JsonObject, label: str) -> None:
    try:
        parse_warning_map(payload)
    except OverwrittenAmbiguityArtifactError:
        return
    raise ArtifactSchemaVerificationError(f"{label} was accepted")


def valid_artifact() -> JsonObject:
    return {
        "schema_version": "overwritten_ambiguity_v1",
        "ok": True,
        "student_facing": False,
        "items": [{"question_no": question, "warnings": []} for question in range(1, 21)],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
    }


def require_items(payload: JsonObject) -> list[JsonObject]:
    items = payload.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ArtifactSchemaVerificationError("fixture items are invalid")
    return items


if __name__ == "__main__":
    raise SystemExit(main())
