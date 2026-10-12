from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SECOND_PASS_ENABLED_ENV: Final[str] = "OCR_SECOND_PASS_EXPERIMENT_ENABLED"
SECOND_PASS_PROVIDER_ALLOWED_ENV: Final[str] = "OCR_SECOND_PASS_PROVIDER_CALLS_ALLOWED"
SECOND_PASS_MAX_CALLS_ENV: Final[str] = "OCR_SECOND_PASS_MAX_PROVIDER_CALLS"
TRUTHY_VALUES: Final[frozenset[str]] = frozenset(("1", "true", "yes", "on"))
LOW_CONFIDENCE_STATUSES: Final[frozenset[str]] = frozenset(("review_required", "retake_required", "data_check_required"))
UNCLEAR_VALUES: Final[frozenset[str]] = frozenset(("", "?", "??", "unknown", "unclear"))


@dataclass(frozen=True, slots=True)
class SecondPassGate:
    enabled: bool
    provider_calls_allowed: bool
    max_provider_calls: int


@dataclass(frozen=True, slots=True)
class SecondPassCandidate:
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecondPassPreparation:
    status: str
    provider_call_count: int
    candidates: tuple[SecondPassCandidate, ...]
    manifest_path: Path | None
    reason: str


def second_pass_gate_from_env() -> SecondPassGate:
    return SecondPassGate(
        enabled=env_bool(SECOND_PASS_ENABLED_ENV),
        provider_calls_allowed=env_bool(SECOND_PASS_PROVIDER_ALLOWED_ENV),
        max_provider_calls=env_int(SECOND_PASS_MAX_CALLS_ENV),
    )


def prepare_second_pass_experiment(review_payload: JsonObject, crop_dir: Path, out_dir: Path, gate: SecondPassGate | None = None) -> SecondPassPreparation:
    active_gate = second_pass_gate_from_env() if gate is None else gate
    candidates = select_second_pass_candidates(review_payload)
    if not active_gate.enabled:
        return SecondPassPreparation("disabled", 0, candidates, None, "experiment_flag_disabled")
    if not active_gate.provider_calls_allowed or active_gate.max_provider_calls < 1:
        manifest = write_second_pass_manifest(candidates, crop_dir, out_dir)
        return SecondPassPreparation("USER_APPROVAL_REQUIRED", 0, candidates, manifest, "provider_authorization_required")
    manifest = write_second_pass_manifest(candidates, crop_dir, out_dir)
    return SecondPassPreparation("READY_FOR_AUTHORIZED_LIVE_CALL", 0, candidates, manifest, "skeleton_only_no_provider_call")


def select_second_pass_candidates(review_payload: JsonObject) -> tuple[SecondPassCandidate, ...]:
    items = review_payload.get("items")
    if not isinstance(items, list):
        return ()
    candidates: list[SecondPassCandidate] = []
    for value in items:
        if not isinstance(value, dict):
            continue
        candidate = candidate_from_item(value)
        if should_second_pass(candidate):
            candidates.append(candidate)
    return tuple(candidates)


def candidate_from_item(item: JsonObject) -> SecondPassCandidate:
    question = item.get("question_no", item.get("question"))
    question_no = question if isinstance(question, int) and not isinstance(question, bool) else 0
    warnings = tuple(value for value in item.get("warnings", []) if isinstance(value, str)) if isinstance(item.get("warnings"), list) else ()
    return SecondPassCandidate(
        question_no=question_no,
        recognized=text_value(item.get("recognized")),
        status=text_value(item.get("status")),
        warnings=warnings,
    )


def should_second_pass(candidate: SecondPassCandidate) -> bool:
    if not 1 <= candidate.question_no <= 20:
        return False
    if candidate.status in LOW_CONFIDENCE_STATUSES:
        return True
    if candidate.recognized.strip().lower() in UNCLEAR_VALUES:
        return True
    return bool(candidate.warnings)


def write_second_pass_manifest(candidates: tuple[SecondPassCandidate, ...], crop_dir: Path, out_dir: Path) -> Path:
    manifest_dir = out_dir / "second_pass"
    crops_out = manifest_dir / "candidate_crops"
    crops_out.mkdir(parents=True, exist_ok=True)
    copied: list[JsonObject] = []
    for candidate in candidates:
        source = crop_dir / f"q{candidate.question_no:03d}.png"
        target = crops_out / f"q{candidate.question_no:03d}_candidate.png"
        if source.is_file():
            shutil.copyfile(source, target)
        copied.append(
            {
                "question_no": candidate.question_no,
                "recognized": candidate.recognized,
                "status": candidate.status,
                "warnings": list(candidate.warnings),
                "candidate_crop": str(target),
                "recommended_scale": 3,
                "student_facing": False,
            }
        )
    manifest = manifest_dir / "second_pass_manifest.json"
    payload: JsonObject = {
        "mode": "phase2e_second_pass_experiment_skeleton",
        "provider_call_count": 0,
        "status": "USER_APPROVAL_REQUIRED",
        "candidates": copied,
        "merge_policy": "do_not_auto_confirm_if_second_pass_differs_or_has_warnings",
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def merge_second_pass_item(primary: JsonObject, secondary: JsonObject) -> JsonObject:
    merged = dict(primary)
    primary_text = text_value(primary.get("recognized"))
    secondary_text = text_value(secondary.get("recognized"))
    secondary_warnings = tuple(value for value in secondary.get("warnings", []) if isinstance(value, str)) if isinstance(secondary.get("warnings"), list) else ()
    warnings = tuple(value for value in primary.get("warnings", []) if isinstance(value, str)) if isinstance(primary.get("warnings"), list) else ()
    combined_warnings = list(dict.fromkeys([*warnings, *secondary_warnings, "second_pass_requires_manual_confirmation"]))
    if secondary_text and secondary_text == primary_text and not secondary_warnings:
        combined_warnings.append("second_pass_match_observed")
    else:
        combined_warnings.append("second_pass_mismatch_or_warning")
    merged["status"] = "review_required"
    merged["source"] = None
    merged["final_answer"] = None
    merged["warnings"] = combined_warnings
    return merged


def env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUTHY_VALUES


def env_int(name: str) -> int:
    try:
        return max(0, int(os.environ.get(name, "0").strip()))
    except ValueError:
        return 0


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def preparation_payload(preparation: SecondPassPreparation) -> JsonObject:
    payload = asdict(preparation)
    manifest = preparation.manifest_path
    payload["manifest_path"] = str(manifest) if manifest is not None else None
    return payload
