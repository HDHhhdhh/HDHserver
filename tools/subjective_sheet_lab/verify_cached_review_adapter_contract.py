# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

from __future__ import annotations

import base64
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures  # noqa: E402
from tools.subjective_sheet_lab.phase2c_crop_pipeline_contracts import Phase2CResult  # noqa: E402
from tools.subjective_sheet_lab.phase2d_cached_review_payload_adapter import (  # noqa: E402
    Phase2DCacheUnavailable,
    Phase2DRequest,
    load_recognized_cache,
    load_review_payload_cache,
)

FIXTURE_PATH: Final[Path] = ROOT / "tools" / "subjective_sheet_lab" / "ocr_student_self_review_auto_confirm_fixture.json"
TINY_PNG: Final[bytes] = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9L2NwAAAAASUVORK5CYII="
)
VALID_STATES: Final[frozenset[str]] = frozenset(
    ("auto_confirm", "review_recommended", "direct_input", "retake_required")
)
FORBIDDEN_CONTRACT_KEYS: Final[frozenset[str]] = frozenset(
    (
        "answer_key",
        "expected",
        "canonical_answer",
        "accepted_answers",
        "grading",
        "is_correct",
        "score",
        "safe_auto_grade",
        "filesystem_path",
        "cache_path",
    )
)


class ContractVerificationError(Exception):
    pass


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cached_review_adapter_") as temp_dir:
        root = Path(temp_dir)
        request = build_request(root)
        versioned = verify_versioned_contract(root, request)
        legacy = verify_legacy_contract(root, request)
        malformed = verify_malformed_contracts(root, request)
    print(
        json.dumps(
            {
                "ok": True,
                "classification": "PASS_CACHED_REVIEW_ADAPTER_CONTRACT_UNIT",
                "versioned": versioned,
                "legacy": legacy,
                "malformed": malformed,
                "provider_call_count": 0,
                "submit_test_call_count": 0,
                "ts_submit_click_count": 0,
                "production_default": "NO_GO",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_request(root: Path) -> Phase2DRequest:
    crop_dir = root / "crops"
    crop_dir.mkdir(parents=True)
    for question_no in range(1, 21):
        (crop_dir / f"q{question_no:03d}.png").write_bytes(TINY_PNG)
    source_image = root / "full_sheet.png"
    source_image.write_bytes(TINY_PNG)
    placeholder_json = root / "placeholder.json"
    placeholder_json.write_text("{}\n", encoding="utf-8")
    pipeline = Phase2CResult(
        case_id="anonymous_contract_case",
        case_dir=root,
        source_image=source_image,
        crop_root=root,
        crop_dir=crop_dir,
        review_asset_root=root,
        asset_manifest=placeholder_json,
        crop_count=20,
        contact_sheet_count=4,
        debug_sheet_count=0,
        contact_sheets=(),
        debug_sheets=(),
        asset_verification=placeholder_json,
        crop_quality=placeholder_json,
        answer_box_source="contract_fixture",
        overwritten_ambiguity=None,
    )
    return Phase2DRequest(
        sid="anonymous",
        test_id="t_unit_daesu_01_lv3_r1",
        round_no=1,
        pipeline_result=pipeline,
    )


def verify_versioned_contract(root: Path, request: Phase2DRequest) -> dict[str, object]:
    fixture = require_object(json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig")), "fixture")
    payload = deepcopy(require_object(fixture.get("mixed_payload"), "mixed_payload"))
    payload["schema_version"] = "student_self_review_v1"
    require_object(require_list(payload.get("items"), "items")[7], "q008")["warnings"] = ["pipeline_warning"]
    path = write_json(root / "versioned.json", {"review_meta": {}, "review_payload": payload})
    result = load_review_payload_cache(path, request)
    normalized = result.review_payload
    assert_common_payload(normalized)
    if normalized.get("source_schema_version") != "student_self_review_v1":
        raise ContractVerificationError("versioned source schema was not preserved")
    if normalized.get("normalized_schema_version") != "cached_review_adapter_v1":
        raise ContractVerificationError("normalized schema version missing")
    if normalized.get("auto_confirm_policy_version") != "gemini_flash_lite_policy_d_boundary_v1":
        raise ContractVerificationError("auto-confirm policy version was not preserved")
    counts = state_counts(normalized)
    expected = {"auto_confirm": 7, "review_recommended": 8, "direct_input": 3, "retake_required": 2}
    if counts != expected:
        raise ContractVerificationError(f"versioned states changed: {counts} != {expected}")
    for item in require_items(normalized):
        for field in ("candidate", "warning", "crop_preview", "allow_edit", "requires_confirmation", "retake_reason"):
            if field not in item:
                raise ContractVerificationError(f"q{item.get('question_no')} missing {field}")
        if item.get("final_answer") is not None:
            raise ContractVerificationError("adapter generated a final_answer")
    q008 = require_items(normalized)[7]
    if "pipeline_warning" not in require_string_list(q008.get("warning")):
        raise ContractVerificationError("singular and plural warning fields were not merged")
    return {
        "source_schema_version": normalized.get("source_schema_version"),
        "normalized_schema_version": normalized.get("normalized_schema_version"),
        "states": counts,
        "actionable_items": len(require_items(normalized)),
    }


def verify_legacy_contract(root: Path, request: Phase2DRequest) -> dict[str, object]:
    items = [
        {
            "question": question_no,
            "recognized": "?" if question_no in {7, 18} else str(((question_no - 1) % 5) + 1),
            "candidates": [],
        }
        for question_no in range(1, 21)
    ]
    path = write_json(root / "legacy.json", {"items": items})
    normalized = load_recognized_cache(path, request).review_payload
    assert_common_payload(normalized)
    counts = state_counts(normalized)
    expected = {"review_recommended": 18, "direct_input": 2}
    if counts != expected:
        raise ContractVerificationError(f"legacy fail-closed states changed: {counts} != {expected}")
    if counts.get("auto_confirm", 0) != 0:
        raise ContractVerificationError("legacy cache created auto-confirm items")
    if normalized.get("source_schema_version") != "recognized_legacy_v0":
        raise ContractVerificationError("legacy source schema missing")
    for item in require_items(normalized):
        preview = item.get("crop_preview")
        if not isinstance(preview, str) or not preview.startswith("data:image/png;base64,"):
            raise ContractVerificationError("legacy item lacks safe inline crop preview")
        if item.get("requires_confirmation") is not True or item.get("allow_edit") is not True:
            raise ContractVerificationError("legacy item is not safely actionable")
    return {
        "source_schema_version": normalized.get("source_schema_version"),
        "states": counts,
        "auto_confirm": 0,
    }


def verify_malformed_contracts(root: Path, request: Phase2DRequest) -> dict[str, str]:
    fixture = require_object(json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig")), "fixture")
    base = deepcopy(require_object(fixture.get("mixed_payload"), "mixed_payload"))
    base["schema_version"] = "student_self_review_v1"

    unknown_version = deepcopy(base)
    unknown_version["schema_version"] = "student_self_review_v999"
    expect_unavailable(root, request, "unknown_version", unknown_version, "cache_schema_unsupported")

    unknown_state = deepcopy(base)
    first = require_object(require_list(unknown_state.get("items"), "items")[0], "item")
    first["review_state"] = "mystery_state"
    downgraded = load_review_payload_cache(
        write_json(root / "unknown_state.json", {"review_meta": {}, "review_payload": unknown_state}),
        request,
    ).review_payload
    q001 = require_items(downgraded)[0]
    if q001.get("review_state") != "direct_input" or "unknown_review_state" not in require_string_list(q001.get("warning")):
        raise ContractVerificationError("unknown state did not fail closed")

    duplicate = deepcopy(base)
    duplicate_items = require_list(duplicate.get("items"), "items")
    require_object(duplicate_items[-1], "last item")["question_no"] = 1
    expect_unavailable(root, request, "duplicate", duplicate, "cache_malformed")

    missing = deepcopy(base)
    require_list(missing.get("items"), "items").pop()
    expect_unavailable(root, request, "missing", missing, "cache_malformed")

    forbidden = deepcopy(base)
    require_object(require_list(forbidden.get("items"), "items")[0], "first item")["grading"] = {"score": 1}
    expect_unavailable(root, request, "forbidden", forbidden, "cache_forbidden_fields")

    path_leak = deepcopy(base)
    require_object(require_list(path_leak.get("items"), "items")[0], "first item")["warning"] = [r"C:\server-ocr\secret"]
    expect_unavailable(root, request, "path_leak", path_leak, "cache_path_leak")

    return {
        "unknown_version": "fail_closed",
        "unknown_state": "direct_input",
        "duplicate": "rejected",
        "missing": "rejected",
        "forbidden": "rejected",
        "path_leak": "rejected",
    }


def expect_unavailable(
    root: Path,
    request: Phase2DRequest,
    name: str,
    payload: dict[str, object],
    expected_reason: str,
) -> None:
    path = write_json(root / f"{name}.json", {"review_meta": {}, "review_payload": payload})
    try:
        load_review_payload_cache(path, request)
    except Phase2DCacheUnavailable as exc:
        if exc.reason != expected_reason:
            raise ContractVerificationError(f"{name} reason {exc.reason} != {expected_reason}") from exc
    else:
        raise ContractVerificationError(f"{name} was accepted")


def assert_common_payload(payload: dict[str, object]) -> None:
    items = require_items(payload)
    question_numbers = [item.get("question_no") for item in items]
    if len(items) != 20 or question_numbers != list(range(1, 21)):
        raise ContractVerificationError("payload is not exactly q001..q020")
    if forbidden_paths(payload) or path_exposures(payload):
        raise ContractVerificationError("payload leaked a forbidden field or path")
    forbidden_hits = find_keys(payload, FORBIDDEN_CONTRACT_KEYS)
    if forbidden_hits:
        raise ContractVerificationError(f"payload leaked forbidden contract keys: {forbidden_hits}")
    for item in items:
        if item.get("review_state") not in VALID_STATES:
            raise ContractVerificationError("payload contains an unsupported review state")


def state_counts(payload: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in require_items(payload):
        state = str(item.get("review_state") or "")
        counts[state] = counts.get(state, 0) + 1
    return counts


def find_keys(value: object, forbidden: frozenset[str], path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in forbidden:
                found.append(child_path)
            found.extend(find_keys(child, forbidden, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_keys(child, forbidden, f"{path}[{index}]"))
    return found


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContractVerificationError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ContractVerificationError(f"{label} must be a list")
    return value


def require_items(payload: dict[str, object]) -> list[dict[str, object]]:
    return [require_object(item, "payload item") for item in require_list(payload.get("items"), "payload.items")]


def require_string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ContractVerificationError("warning must be a string list")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
