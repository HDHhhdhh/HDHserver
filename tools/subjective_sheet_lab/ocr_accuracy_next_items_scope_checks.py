from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.verify_ocr_mijeok1_draft_postprocess_policy import (  # noqa: E402
    REPORT_JSON as MIJEOK_REPORT_JSON,
)
from tools.subjective_sheet_lab.verify_ocr_mijeok1_draft_postprocess_policy import main as verify_mijeok_policy  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_q003_signal_audit import REPORT_JSON as Q003_REPORT_JSON  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_q003_signal_audit import main as verify_q003_signal_audit  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_training_pack_draft_postprocess_policy import (  # noqa: E402
    REPORT_JSON as TRAINING_REPORT_JSON,
)
from tools.subjective_sheet_lab.verify_ocr_training_pack_draft_postprocess_policy import main as verify_training_policy  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

PHASE2C_ROOT: Final[Path] = Path("C:/server-ocr/phase2c_route_uploads")


@dataclass(frozen=True, slots=True)
class CropSetSummary:
    test_id: str
    crop_set_count: int
    complete_crop_set_count: int
    postprocess_verified: bool


class ScopeCheckError(Exception):
    pass


def mijeok_training_fixture_scope() -> JsonObject:
    if verify_mijeok_policy() != 0:
        raise ScopeCheckError("mijeok draft policy verifier failed")
    if verify_training_policy() != 0:
        raise ScopeCheckError("training pack draft policy verifier failed")
    mijeok = read_json_object(MIJEOK_REPORT_JSON)
    training = read_json_object(TRAINING_REPORT_JSON)
    summaries = [
        crop_set_summary("t_unit_mijeok1_01_lv3_r1", mijeok.get("ok") is True),
        crop_set_summary("t_training_pack_mijeok1_non_frequent_r1", training.get("ok") is True),
        crop_set_summary("t_training_pack_mijeok1_non_frequent_r2", training.get("ok") is True),
        crop_set_summary("t_training_pack_gongsu2_non_frequent_r1", training.get("ok") is True),
        crop_set_summary("t_training_pack_gongsu2_non_frequent_r2", training.get("ok") is True),
    ]
    return {
        "target_count": len(summaries),
        "postprocess_verified_count": sum(1 for summary in summaries if summary.postprocess_verified),
        "crop_set_count": sum(summary.crop_set_count for summary in summaries),
        "complete_crop_set_count": sum(summary.complete_crop_set_count for summary in summaries),
        "targets": [asdict(summary) for summary in summaries],
    }


def q003_threshold_tuning() -> JsonObject:
    if verify_q003_signal_audit() != 0:
        raise ScopeCheckError("q003 signal audit verifier failed")
    report = read_json_object(Q003_REPORT_JSON)
    rows = require_array(report.get("results"), "q003.results")
    signal_biases: list[float] = []
    no_signal_biases: list[float] = []
    useful_signal = False
    for item in rows:
        row = require_object(item, "q003.results[]")
        bias = float_value(row.get("leading_right_bias"), "leading_right_bias")
        flags = string_array(row.get("signal_flags"), "signal_flags")
        if "three_n_shape_conflict" in flags:
            signal_biases.append(bias)
        else:
            no_signal_biases.append(bias)
        if row.get("interpretation") == "useful_review_signal":
            useful_signal = True
    if not useful_signal or not signal_biases or not no_signal_biases:
        raise ScopeCheckError("q003 threshold tuning inputs are incomplete")
    min_signal = min(signal_biases)
    max_no_signal = max(no_signal_biases)
    return {
        "case_count": len(rows),
        "signal_case_count": len(signal_biases),
        "no_signal_case_count": len(no_signal_biases),
        "min_signal_right_bias": round(min_signal, 3),
        "max_no_signal_right_bias": round(max_no_signal, 3),
        "separation_margin": round(min_signal - max_no_signal, 3),
        "recommended_min_right_bias_floor": 0.12,
        "policy": "tune_recognition_candidates_without_relaxing_review_required_guard",
    }


def crop_set_summary(test_id: str, postprocess_verified: bool) -> CropSetSummary:
    crop_dirs = route_crop_dirs(test_id)
    return CropSetSummary(
        test_id=test_id,
        crop_set_count=len(crop_dirs),
        complete_crop_set_count=sum(1 for crop_dir in crop_dirs if complete_crop_set(crop_dir)),
        postprocess_verified=postprocess_verified,
    )


def route_crop_dirs(test_id: str) -> list[Path]:
    pattern = f"phase2c_*_{test_id}*/crop_benchmark_inputs/*/crops"
    return sorted(PHASE2C_ROOT.glob(pattern), reverse=True)


def complete_crop_set(crop_dir: Path) -> bool:
    return all((crop_dir / f"q{question_no:03d}.png").is_file() for question_no in range(1, 21))


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ScopeCheckError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ScopeCheckError(f"{label} must be a JSON array")
    return value


def string_array(value: JsonValue, label: str) -> list[str]:
    return [item for item in require_array(value, label) if isinstance(item, str)]


def float_value(value: JsonValue, label: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ScopeCheckError(f"{label} must be numeric")
    return float(value)
