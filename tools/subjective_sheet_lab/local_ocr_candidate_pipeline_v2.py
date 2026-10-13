from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Iterator, Literal, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_answer_mode_policy import (  # noqa: E402
    answer_mode_for_question,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ConfidenceTier: TypeAlias = Literal["HIGH", "MEDIUM", "LOW", "UNRESOLVED"]

QUESTION_COUNT: Final[int] = 20
CHOICE_VALUES: Final[frozenset[str]] = frozenset({"1", "2", "3", "4", "5"})
ANSWER_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:"
    r"[-+]?\d+(?:\.\d+)?"
    r"|[-+]?\d+/\d+"
    r"|[A-Za-z]=[-+]?\d+(?:\.\d+)?"
    r"|[-+]?\d*[A-Za-z](?:[+\-]\d+)?"
    r"|sqrt\([-+]?\d+(?:\.\d+)?\)"
    r"|[-+]?\d+sqrt\(\d+\)"
    r")$"
)
FORBIDDEN_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "answer_key",
        "expected",
        "canonical_answer",
        "accepted_answers",
        "is_correct",
        "score",
        "grading",
        "filesystem_path",
        "path",
    }
)
WINDOWS_PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\[^\\\s]+\\)")
LOCAL_MODEL_NAMES: Final[dict[str, str]] = {
    "doc_orientation": "PP-LCNet_x1_0_doc_ori",
    "doc_unwarping": "UVDoc",
    "textline_orientation": "PP-LCNet_x1_0_textline_ori",
    "text_detection": "PP-OCRv5_server_det",
    "text_recognition": "korean_PP-OCRv5_mobile_rec",
}


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    source: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class InkProfile:
    blank_like: bool
    major_group_count: int
    ink_bbox_aspect: float


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate: str | None
    confidence_tier: ConfidenceTier
    reasons: tuple[str, ...]
    vote_count: int
    second_vote_count: int
    max_score: float


@dataclass(frozen=True, slots=True)
class VariantSpec:
    name: str
    padding_ratio: float
    target_height: int
    method: Literal["gray", "clahe", "otsu"]


@dataclass(frozen=True, slots=True)
class HumanEntry:
    question_no: int
    answer: str
    confidence: str
    status: str
    notes: str


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    crop_dir: Path
    human_transcription: Path
    test_id: str


VARIANTS: Final[tuple[VariantSpec, ...]] = (
    VariantSpec("tight_gray_48", 0.25, 48, "gray"),
    VariantSpec("tight_otsu_48", 0.25, 48, "otsu"),
    VariantSpec("medium_gray_48", 0.50, 48, "gray"),
    VariantSpec("medium_clahe_48", 0.50, 48, "clahe"),
    VariantSpec("medium_otsu_48", 0.50, 48, "otsu"),
    VariantSpec("medium_gray_64", 0.50, 64, "gray"),
    VariantSpec("medium_clahe_64", 0.50, 64, "clahe"),
    VariantSpec("loose_gray_64", 1.00, 64, "gray"),
    VariantSpec("loose_clahe_64", 1.00, 64, "clahe"),
)


class LocalOcrV2Error(Exception):
    pass


def main() -> int:
    args = parse_args()
    manifest = read_json_object(args.manifest)
    cases = read_case_specs(manifest)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with deny_external_network():
        engine = LocalPaddleEngines(args.model_cache_root.resolve())
        case_reports = [run_case(case, engine, out_dir / case.case_id) for case in cases]
    elapsed = time.perf_counter() - started
    summary = build_benchmark_summary(case_reports, elapsed)
    write_json(out_dir / "benchmark_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--model-cache-root", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args()


@contextmanager
def deny_external_network() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("external_network_disabled_for_local_ocr_benchmark")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.create_connection = blocked_connect  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


class LocalPaddleEngines:
    def __init__(self, cache_root: Path) -> None:
        official = cache_root / "official_models"
        required = {
            "doc_orientation": official / "PP-LCNet_x1_0_doc_ori",
            "doc_unwarping": official / "UVDoc",
            "textline_orientation": official / "PP-LCNet_x1_0_textline_ori",
            "text_detection": official / "PP-OCRv5_server_det",
            "text_recognition": official / "korean_PP-OCRv5_mobile_rec",
        }
        missing = [name for name, path in required.items() if not path.is_dir()]
        if missing:
            raise LocalOcrV2Error(f"local model directories missing: {', '.join(missing)}")
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_root)
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        import paddlex
        from paddleocr import PaddleOCR

        self._recognizer = paddlex.create_model(
            "korean_PP-OCRv5_mobile_rec",
            model_dir=str(required["text_recognition"]),
        )
        self._detector = PaddleOCR(
            doc_orientation_classify_model_name=LOCAL_MODEL_NAMES["doc_orientation"],
            doc_orientation_classify_model_dir=str(required["doc_orientation"]),
            doc_unwarping_model_name=LOCAL_MODEL_NAMES["doc_unwarping"],
            doc_unwarping_model_dir=str(required["doc_unwarping"]),
            textline_orientation_model_name=LOCAL_MODEL_NAMES["textline_orientation"],
            textline_orientation_model_dir=str(required["textline_orientation"]),
            text_detection_model_name=LOCAL_MODEL_NAMES["text_detection"],
            text_detection_model_dir=str(required["text_detection"]),
            text_recognition_model_name=LOCAL_MODEL_NAMES["text_recognition"],
            text_recognition_model_dir=str(required["text_recognition"]),
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
        )

    def recognize_variant(self, image: Any, source: str) -> CandidateSignal:
        result = list(self._recognizer.predict(image))[0]
        return CandidateSignal(source, str(result.get("rec_text", "")), float(result.get("rec_score", 0.0)))

    def recognize_original(self, crop_path: Path) -> tuple[CandidateSignal, ...]:
        try:
            result = self._detector.predict(str(crop_path))
        except (OSError, RuntimeError, TypeError, ValueError):
            return ()
        lines = collect_lines(result)
        return tuple(CandidateSignal("original_detector", text, score or 0.0) for text, score in lines)


def collect_lines(value: Any) -> list[tuple[str, float | None]]:
    lines: list[tuple[str, float | None]] = []

    def append_line(text_value: Any, confidence_value: Any = None) -> None:
        text = " ".join(str(text_value or "").split())
        if not text:
            return
        confidence = (
            float(confidence_value)
            if isinstance(confidence_value, (int, float)) and not isinstance(confidence_value, bool)
            else None
        )
        if not lines or lines[-1] != (text, confidence):
            lines.append((text, confidence))

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            texts = item.get("rec_texts")
            if isinstance(texts, (list, tuple)):
                scores = item.get("rec_scores")
                for index, text_value in enumerate(texts):
                    score = scores[index] if isinstance(scores, (list, tuple)) and index < len(scores) else None
                    append_line(text_value, score)
                return
            if isinstance(item.get("rec_text"), str):
                append_line(item["rec_text"], item.get("rec_score"))
                return
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return lines


def run_case(case: CaseSpec, engine: LocalPaddleEngines, out_dir: Path) -> JsonObject:
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    human = read_human_transcription(case.human_transcription)
    diagnostics: list[JsonObject] = []
    review_items: list[JsonObject] = []
    started = time.perf_counter()
    for question_no in range(1, QUESTION_COUNT + 1):
        crop_path = case.crop_dir / f"q{question_no:03d}.png"
        gray = cv2.imread(str(crop_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise LocalOcrV2Error(f"missing crop for {case.case_id} q{question_no:03d}")
        mode = answer_mode_for_question(case.test_id, question_no)
        profile = ink_profile(gray)
        signals = list(engine.recognize_original(crop_path))
        for spec in VARIANTS:
            variant = prepare_variant(gray, spec)
            bgr = cv2.cvtColor(variant, cv2.COLOR_GRAY2BGR)
            signals.append(engine.recognize_variant(bgr, spec.name))
        decision = resolve_candidate(tuple(signals), mode, profile)
        review_items.append(build_review_item(question_no, decision.candidate, decision.confidence_tier, decision.reasons))
        entry = human[question_no]
        diagnostics.append(
            {
                "question_no": question_no,
                "answer_mode": mode,
                "candidate": decision.candidate,
                "candidate_confidence": decision.confidence_tier,
                "candidate_matches_human": decision.candidate == compact_text(entry.answer) if decision.candidate else None,
                "human_confidence": entry.confidence,
                "human_status": entry.status,
                "crop_complete": True,
                "blank_reason": None if decision.candidate else list(decision.reasons),
                "correction_reason": None,
                "ink_profile": asdict(profile),
                "vote_count": decision.vote_count,
                "second_vote_count": decision.second_vote_count,
                "max_score": round(decision.max_score, 6),
                "signals": [asdict(signal) for signal in signals],
            }
        )
    payload: JsonObject = {
        "source": "local_ocr_candidate_v2",
        "case_id": case.case_id,
        "problem_count": QUESTION_COUNT,
        "items": review_items,
    }
    validate_review_payload(payload)
    metrics = evaluate_case(case.case_id, diagnostics, human, time.perf_counter() - started)
    write_json(out_dir / "review_payload.json", payload)
    write_json(out_dir / "question_diagnostics.json", {"case_id": case.case_id, "items": diagnostics})
    write_json(out_dir / "evaluation.json", metrics)
    return metrics


def prepare_variant(gray: Any, spec: VariantSpec) -> Any:
    import cv2
    import numpy as np

    height, width = gray.shape[:2]
    roi = gray[int(height * 0.38) : int(height * 0.94), int(width * 0.08) : int(width * 0.92)]
    _, threshold = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    components = component_stats(255 - threshold)
    if components:
        x0 = min(item[0] for item in components)
        y0 = min(item[1] for item in components)
        x1 = max(item[0] + item[2] for item in components)
        y1 = max(item[1] + item[3] for item in components)
        pad = max(3, int(max(1, y1 - y0) * spec.padding_ratio))
        roi = roi[max(0, y0 - pad) : min(roi.shape[0], y1 + pad), max(0, x0 - pad) : min(roi.shape[1], x1 + pad)]
    if spec.method == "clahe":
        roi = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(roi)
    elif spec.method == "otsu":
        _, roi = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    scale = spec.target_height / max(1, roi.shape[0])
    target_width = max(1, round(roi.shape[1] * scale))
    resized = cv2.resize(roi, (target_width, spec.target_height), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((spec.target_height + 32, max(target_width + 32, spec.target_height * 4)), 255, dtype=np.uint8)
    y_offset = (canvas.shape[0] - spec.target_height) // 2
    x_offset = (canvas.shape[1] - target_width) // 2
    canvas[y_offset : y_offset + spec.target_height, x_offset : x_offset + target_width] = resized
    return canvas


def ink_profile(gray: Any) -> InkProfile:
    import cv2
    import numpy as np

    height, width = gray.shape[:2]
    roi = gray[int(height * 0.30) : int(height * 0.96), int(width * 0.05) : int(width * 0.95)]
    _, threshold = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    components = component_stats(255 - threshold)
    if not components:
        return InkProfile(True, 0, 0.0)
    x0 = min(item[0] for item in components)
    y0 = min(item[1] for item in components)
    x1 = max(item[0] + item[2] for item in components)
    y1 = max(item[1] + item[3] for item in components)
    bbox_height = max(1, y1 - y0)
    bbox_width = max(1, x1 - x0)
    mask = np.zeros_like(threshold)
    for x, y, item_width, item_height, _area in components:
        mask[y : y + item_height, x : x + item_width] = (255 - threshold)[y : y + item_height, x : x + item_width]
    kernel_width = max(3, round(bbox_height * 0.18))
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, kernel_width), dtype=np.uint8))
    groups = component_stats(joined, min_area=max(12, round(bbox_height * bbox_height * 0.025)))
    return InkProfile(False, len(groups), round(bbox_width / bbox_height, 4))


def component_stats(binary_ink: Any, min_area: int = 8) -> list[tuple[int, int, int, int, int]]:
    import cv2

    _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary_ink, 8)
    return [
        (int(x), int(y), int(width), int(height), int(area))
        for x, y, width, height, area in stats[1:]
        if int(area) >= min_area and int(width) >= 2 and int(height) >= 3
    ]


def normalize_candidate(text: str, answer_mode: str) -> str | None:
    compact = compact_text(text)
    if not compact or compact in {"?", "??"} or WINDOWS_PATH_RE.search(compact):
        return None
    if answer_mode == "choice_number":
        return compact if compact in CHOICE_VALUES else None
    if answer_mode != "answer_value":
        return None
    return compact if ANSWER_VALUE_RE.fullmatch(compact) else None


def resolve_candidate(signals: tuple[CandidateSignal, ...], answer_mode: str, profile: InkProfile) -> CandidateDecision:
    normalized = [
        (candidate, signal.score, signal.source)
        for signal in signals
        if (candidate := normalize_candidate(signal.text, answer_mode)) is not None
    ]
    if not normalized:
        return CandidateDecision(None, "UNRESOLVED", ("no_valid_local_candidate",), 0, 0, 0.0)
    counts = Counter(candidate for candidate, _score, _source in normalized)
    ranked = counts.most_common()
    candidate, votes = ranked[0]
    second_votes = ranked[1][1] if len(ranked) > 1 else 0
    max_score = max(score for value, score, _source in normalized if value == candidate)
    sources = {source for value, _score, source in normalized if value == candidate}
    original_agrees = "original_detector" in sources
    enough_agreement = (
        (votes >= 3 and max_score >= 0.50 and second_votes < 2)
        or (votes >= 2 and max_score >= 0.80 and second_votes < 2)
        or (original_agrees and votes >= 3 and votes > second_votes and max_score >= 0.80)
    )
    if not enough_agreement:
        return CandidateDecision(None, "LOW", ("local_candidate_disagreement",), votes, second_votes, max_score)
    symbol_count = len(re.sub(r"[^0-9A-Za-z]", "", candidate))
    if answer_mode == "choice_number" and profile.major_group_count >= 2:
        return CandidateDecision(None, "UNRESOLVED", ("ambiguous_ink_groups",), votes, second_votes, max_score)
    if answer_mode == "answer_value" and re.fullmatch(r"[A-Za-z]", candidate):
        return CandidateDecision(None, "UNRESOLVED", ("single_alpha_ambiguity",), votes, second_votes, max_score)
    if (
        profile.major_group_count >= 2
        and profile.ink_bbox_aspect >= 1.80
        and symbol_count < profile.major_group_count
    ):
        return CandidateDecision(None, "UNRESOLVED", ("ambiguous_ink_groups",), votes, second_votes, max_score)
    tier: ConfidenceTier = "HIGH" if votes >= 3 and max_score >= 0.80 and second_votes == 0 else "MEDIUM"
    return CandidateDecision(candidate, tier, ("variant_agreement",), votes, second_votes, max_score)


def build_review_item(question_no: int, candidate: str | None, confidence: ConfidenceTier, reasons: tuple[str, ...]) -> JsonObject:
    candidates: list[JsonValue] = []
    if candidate is not None:
        candidates.append({"value": candidate, "source": "local_ocr_candidate_v2", "confidence": confidence})
    return {
        "question_no": question_no,
        "status": "review_required",
        "recognized": candidate,
        "candidates": candidates,
        "candidate_confidence": confidence,
        "requires_confirmation": True,
        "allow_direct_input": True,
        "warnings": list(reasons),
        "safe_auto_grade": False,
        "final_answer": None,
        "source": None,
    }


def validate_review_payload(payload: JsonObject) -> None:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != QUESTION_COUNT:
        raise LocalOcrV2Error("review payload must contain exactly 20 items")
    question_numbers = [item.get("question_no") for item in items if isinstance(item, dict)]
    if question_numbers != list(range(1, QUESTION_COUNT + 1)):
        raise LocalOcrV2Error("review payload question contract is not q001..q020")
    if any(not isinstance(item, dict) or item.get("status") != "review_required" for item in items):
        raise LocalOcrV2Error("all local candidates must remain review_required")
    if any(isinstance(item, dict) and (item.get("final_answer") is not None or item.get("safe_auto_grade") is not False) for item in items):
        raise LocalOcrV2Error("local candidate payload attempted automatic confirmation")
    scan_forbidden(payload)


def scan_forbidden(value: JsonValue) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in FORBIDDEN_FIELD_NAMES:
                raise LocalOcrV2Error(f"forbidden student-facing field: {key}")
            scan_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            scan_forbidden(nested)
    elif isinstance(value, str) and WINDOWS_PATH_RE.search(value):
        raise LocalOcrV2Error("local filesystem path leaked into review payload")


def evaluate_case(case_id: str, diagnostics: list[JsonObject], human: dict[int, HumanEntry], elapsed: float) -> JsonObject:
    candidates = [item for item in diagnostics if isinstance(item.get("candidate"), str)]
    correct = [item for item in candidates if item.get("candidate_matches_human") is True]
    high_candidates = [item for item in candidates if human[int(item["question_no"])].confidence == "high"]
    high_correct = [item for item in high_candidates if item.get("candidate_matches_human") is True]
    wrong = [int(item["question_no"]) for item in candidates if item.get("candidate_matches_human") is False]
    unsafe = [
        int(item["question_no"])
        for item in candidates
        if human[int(item["question_no"])].status == "unresolved"
        or any(token in human[int(item["question_no"])].notes.lower() for token in ("erased", "overwritten", "crossed-out", "multiple"))
    ]
    fatal = [
        question_no
        for question_no in wrong
        if any(symbol in human[question_no].answer for symbol in ("-", ".", "/", "sqrt"))
    ]
    return {
        "case_id": case_id,
        "question_count": QUESTION_COUNT,
        "candidate_count": len(candidates),
        "candidate_coverage": round(len(candidates) / QUESTION_COUNT, 4),
        "correct_candidate_count": len(correct),
        "candidate_accuracy": round(len(correct) / len(candidates), 4) if candidates else None,
        "high_confidence_candidate_count": len(high_candidates),
        "high_confidence_candidate_accuracy": round(len(high_correct) / len(high_candidates), 4) if high_candidates else None,
        "wrong_candidate_count": len(wrong),
        "wrong_question_numbers": wrong,
        "unsafe_ambiguity_candidate_count": len(unsafe),
        "unsafe_ambiguity_question_numbers": unsafe,
        "fatal_symbolic_error_count": len(fatal),
        "fatal_symbolic_error_questions": fatal,
        "unresolved_count": QUESTION_COUNT - len(candidates),
        "average_processing_seconds_per_question": round(elapsed / QUESTION_COUNT, 4),
        "wrong_safe_auto_grade": 0,
        "unsafe_auto_fill": 0,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "final_submit_click_count": 0,
        "production_default": "NO-GO",
    }


def build_benchmark_summary(case_reports: list[JsonObject], elapsed: float) -> JsonObject:
    total_candidates = sum(int(report["candidate_count"]) for report in case_reports)
    total_correct = sum(int(report["correct_candidate_count"]) for report in case_reports)
    total_questions = len(case_reports) * QUESTION_COUNT
    total_wrong = sum(int(report["wrong_candidate_count"]) for report in case_reports)
    total_unsafe = sum(int(report["unsafe_ambiguity_candidate_count"]) for report in case_reports)
    total_fatal = sum(int(report["fatal_symbolic_error_count"]) for report in case_reports)
    target_met = (
        all(int(report["candidate_count"]) >= 16 for report in case_reports)
        and all(float(report.get("candidate_accuracy") or 0.0) >= 0.90 for report in case_reports)
        and total_wrong == 0
        and total_unsafe == 0
        and total_fatal == 0
    )
    conditional = (
        all(int(report["candidate_count"]) >= 14 for report in case_reports)
        and all(float(report.get("candidate_accuracy") or 0.0) >= 0.90 for report in case_reports)
        and total_wrong == 0
        and total_unsafe == 0
    )
    classification = (
        "PASS_LOCAL_OCR_COVERAGE_ACCURACY_TARGET"
        if target_met
        else "CONDITIONAL_GO_LOCAL_OCR"
        if conditional
        else "NO_GO_LOCAL_OCR"
    )
    return {
        "classification": classification,
        "case_count": len(case_reports),
        "question_count": total_questions,
        "candidate_count": total_candidates,
        "candidate_coverage": round(total_candidates / total_questions, 4) if total_questions else 0.0,
        "correct_candidate_count": total_correct,
        "candidate_accuracy": round(total_correct / total_candidates, 4) if total_candidates else None,
        "wrong_candidate_count": total_wrong,
        "unsafe_ambiguity_candidate_count": total_unsafe,
        "fatal_symbolic_error_count": total_fatal,
        "wrong_safe_auto_grade": 0,
        "unsafe_auto_fill": 0,
        "elapsed_seconds": round(elapsed, 3),
        "cases": case_reports,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "final_submit_click_count": 0,
        "production_default": "NO-GO",
    }


def read_case_specs(manifest: JsonObject) -> list[CaseSpec]:
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise LocalOcrV2Error("manifest cases must be a non-empty list")
    cases: list[CaseSpec] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise LocalOcrV2Error("manifest case must be an object")
        case_id = require_text(raw.get("case_id"), "case_id")
        crop_dir = Path(require_text(raw.get("crop_dir"), "crop_dir")).resolve()
        human_path = Path(require_text(raw.get("human_transcription"), "human_transcription")).resolve()
        test_id = require_text(raw.get("test_id"), "test_id")
        if not crop_dir.is_dir() or not human_path.is_file():
            raise LocalOcrV2Error(f"case input missing: {case_id}")
        cases.append(CaseSpec(case_id, crop_dir, human_path, test_id))
    return cases


def read_human_transcription(path: Path) -> dict[int, HumanEntry]:
    raw = read_json_object(path)
    entries = raw.get("answers") if isinstance(raw.get("answers"), list) else raw.get("items")
    if not isinstance(entries, list):
        raise LocalOcrV2Error("human transcription items missing")
    result: dict[int, HumanEntry] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("question_no"), int):
            continue
        question_no = int(raw_entry["question_no"])
        answer = raw_entry.get("human_answer", raw_entry.get("observed_writing"))
        confidence = raw_entry.get("confidence")
        status = raw_entry.get("transcription_status", "confirmed")
        notes = raw_entry.get("notes", raw_entry.get("reason", ""))
        if isinstance(answer, str) and isinstance(confidence, str) and isinstance(status, str) and isinstance(notes, str):
            result[question_no] = HumanEntry(question_no, compact_text(answer), confidence.lower(), status.lower(), notes)
    if set(result) != set(range(1, QUESTION_COUNT + 1)):
        raise LocalOcrV2Error("human transcription must contain q001..q020")
    return result


def read_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise LocalOcrV2Error(f"JSON object required: {path}")
    return value


def require_text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalOcrV2Error(f"{label} must be non-empty text")
    return value.strip()


def compact_text(value: str) -> str:
    return "".join(value.split())


def write_json(path: Path, payload: JsonObject) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
