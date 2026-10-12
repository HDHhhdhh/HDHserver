from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, require_int_value


TARGET_IDS: Final[tuple[str, ...]] = (
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
)
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class TrainingPackInventoryError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class SourceRow:
    source_alias: str
    test_id: str
    crop_count: int
    contact_sheet_count: int
    enhanced_crop_count: int
    full_sheet_present: bool
    crop_manifest_present: bool
    crop_quality_present: bool
    marker_report_present: bool
    warped_sheet_present: bool
    asset_manifest_present: bool
    asset_verification_present: bool
    request_manifest_present: bool
    pipeline_result_present: bool
    cache_replay_present: bool

    @property
    def source_assets_ready(self) -> bool:
        return (
            self.crop_count == 20
            and self.contact_sheet_count == 4
            and self.enhanced_crop_count == 20
            and self.full_sheet_present
            and self.crop_manifest_present
            and self.crop_quality_present
            and self.marker_report_present
            and self.warped_sheet_present
            and self.asset_manifest_present
            and self.asset_verification_present
            and self.request_manifest_present
            and self.pipeline_result_present
        )


def training_pack_inventory(route_uploads: Path) -> JsonObject:
    output = inventory_summary(source_rows(route_uploads))
    require_inventory(output)
    return output


def source_rows(route_uploads: Path) -> tuple[SourceRow, ...]:
    rows = tuple(
        sorted((source_row(root) for root in route_uploads.glob("*training_pack*")), key=lambda row: row.test_id)
    )
    if len(rows) != 4:
        raise TrainingPackInventoryError(f"Training Pack source candidate count changed: {len(rows)}")
    return rows


def source_row(root: Path) -> SourceRow:
    alias = root.name
    return SourceRow(
        source_alias=alias,
        test_id=test_id_from_alias(alias),
        crop_count=len(list(root.glob("crop_benchmark_inputs/*/crops/q[0-9][0-9][0-9].png"))),
        contact_sheet_count=len(list((root / "review_assets" / "contact_sheets").glob("*.png"))),
        enhanced_crop_count=len(list((root / "review_assets" / "enhanced").glob("q*.png"))),
        full_sheet_present=(root / "incoming" / "full_sheet.jpg").exists(),
        crop_manifest_present=has_file(root, "crop_benchmark_inputs/*/crop_manifest.json"),
        crop_quality_present=has_file(root, "crop_benchmark_inputs/*/crop_quality.json"),
        marker_report_present=has_file(root, "crop_benchmark_inputs/*/detected_markers.json"),
        warped_sheet_present=has_file(root, "crop_benchmark_inputs/*/warped_sheet.png"),
        asset_manifest_present=(root / "review_assets" / "asset_manifest.json").exists(),
        asset_verification_present=(root / "review_assets" / "asset_verification.json").exists(),
        request_manifest_present=(root / "request_manifest.json").exists(),
        pipeline_result_present=(root / "pipeline_result.json").exists(),
        cache_replay_present=cache_replay_present(root),
    )


def has_file(root: Path, pattern: str) -> bool:
    return next(root.glob(pattern), None) is not None


def test_id_from_alias(alias: str) -> str:
    course = "gongsu2" if "gongsu2" in alias else "mijeok1" if "mijeok1" in alias else ""
    round_no = "r1" if alias.endswith("_r1") else "r2" if alias.endswith("_r2") else ""
    match (course, round_no):
        case ("gongsu2", "r1"):
            return "t_training_pack_gongsu2_non_frequent_r1"
        case ("gongsu2", "r2"):
            return "t_training_pack_gongsu2_non_frequent_r2"
        case ("mijeok1", "r1"):
            return "t_training_pack_mijeok1_non_frequent_r1"
        case ("mijeok1", "r2"):
            return "t_training_pack_mijeok1_non_frequent_r2"
        case ("", _) | (_, ""):
            raise TrainingPackInventoryError(f"unmapped Training Pack source alias: {alias}")
        case unreachable:
            assert_never(unreachable)


def cache_replay_present(root: Path) -> bool:
    names = {path.name for path in root.glob("*.json")}
    return bool({"recognized.json", "review_payload.json", "gemini_provider_cache.json"} & names)


def inventory_summary(rows: tuple[SourceRow, ...]) -> JsonObject:
    row_payloads = [row_payload(row) for row in rows]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source_candidate_count": len(rows),
        "target_count": len({row.test_id for row in rows}),
        "source_assets_ready_count": sum(1 for row in rows if row.source_assets_ready),
        "complete_crop_source_count": sum(1 for row in rows if row.crop_count == 20),
        "contact_sheet_source_count": sum(1 for row in rows if row.contact_sheet_count == 4),
        "enhanced_crop_source_count": sum(1 for row in rows if row.enhanced_crop_count == 20),
        "cache_replay_payload_count": sum(1 for row in rows if row.cache_replay_present),
        "fixture_promotion_candidate_count": sum(1 for row in rows if row.source_assets_ready),
        "ready_for_provider_free_ui_replay": False,
        "next_action": "promote_route_upload_sources_to_provider_free_fixture_variant_then_add_cache_replay",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "targets": row_payloads,
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def row_payload(row: SourceRow) -> JsonObject:
    return {
        "source_alias": row.source_alias,
        "test_id": row.test_id,
        "crop_count": row.crop_count,
        "contact_sheet_count": row.contact_sheet_count,
        "enhanced_crop_count": row.enhanced_crop_count,
        "source_assets_ready": row.source_assets_ready,
        "cache_replay_present": row.cache_replay_present,
        "promotion_status": "source_assets_ready_cache_replay_missing",
    }


def require_inventory(output: JsonObject) -> None:
    require_int_value(output.get("source_candidate_count"), 4, "source_candidate_count")
    require_int_value(output.get("target_count"), 4, "target_count")
    require_int_value(output.get("source_assets_ready_count"), 4, "source_assets_ready_count")
    require_int_value(output.get("complete_crop_source_count"), 4, "complete_crop_source_count")
    require_int_value(output.get("contact_sheet_source_count"), 4, "contact_sheet_source_count")
    require_int_value(output.get("enhanced_crop_source_count"), 4, "enhanced_crop_source_count")
    require_int_value(output.get("cache_replay_payload_count"), 0, "cache_replay_payload_count")
    require_int_value(output.get("fixture_promotion_candidate_count"), 4, "fixture_promotion_candidate_count")
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(output.get("external_ocr_api_call_count"), 0, "external_ocr_api_call_count")
    require_int_value(output.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(output.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    require_int_value(output.get("sensitive_field_leak_count"), 0, "sensitive_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")
    targets = targets_from_output(output)
    if targets != set(TARGET_IDS):
        raise TrainingPackInventoryError(f"Training Pack target set changed: {sorted(targets)}")


def targets_from_output(output: JsonObject) -> set[str]:
    raw_targets = output.get("targets")
    match raw_targets:
        case list():
            return {test_id_from_item(item) for item in raw_targets}
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackInventoryError("targets must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def test_id_from_item(item: JsonValue) -> str:
    match item:
        case {"test_id": str(test_id)}:
            return test_id
        case None | bool() | int() | float() | str() | list() | dict():
            raise TrainingPackInventoryError("target item must contain a text test_id")
        case unreachable:
            assert_never(unreachable)


def sensitive_leak_count(text: str) -> int:
    return sum(text.count(token) for token in SENSITIVE_TOKENS)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def markdown(output: JsonObject) -> str:
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    lines = [
        "# OCR Training Pack Source Inventory",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- source candidates: {output['source_candidate_count']}",
        f"- complete crop sources: {output['complete_crop_source_count']}",
        f"- contact-sheet sources: {output['contact_sheet_source_count']}",
        f"- enhanced crop sources: {output['enhanced_crop_source_count']}",
        f"- cache replay payloads: {output['cache_replay_payload_count']}",
        f"- fixture promotion candidates: {output['fixture_promotion_candidate_count']}",
        f"- next action: `{output['next_action']}`",
        "- sensitive/path leak count: 0",
        "",
        "| test_id | source alias | crops | contact sheets | enhanced crops | promotion status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in targets_array(output):
        lines.append(
            f"| `{item['test_id']}` | `{item['source_alias']}` | {item['crop_count']} | "
            f"{item['contact_sheet_count']} | {item['enhanced_crop_count']} | `{item['promotion_status']}` |"
        )
    return "\n".join(lines) + "\n"


def targets_array(output: JsonObject) -> list[JsonObject]:
    raw_targets = output.get("targets")
    match raw_targets:
        case list():
            return [target_object(item) for item in raw_targets]
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackInventoryError("targets must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def target_object(value: JsonValue) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise TrainingPackInventoryError("target item must be a JSON object")
        case unreachable:
            assert_never(unreachable)
