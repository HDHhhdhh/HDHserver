# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\ocr_local_candidate_tools.py --crop-dir C:\server-ocr\crop_benchmark_inputs\person_03\crops --out-dir C:\tmp\ocr_local_candidate_tools_person03

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_answer_mode_policy import (  # noqa: E402
    CHOICE_NUMBER_VALUES,
    SIMPLE_FINAL_ANSWER_RE,
    answer_mode_for_question,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
SignalKind: TypeAlias = Literal["skip", "blank_like", "candidate", "format_conflict", "multiple_candidates"]

QUESTION_COUNT: Final[int] = 20
DIGIT_RE: Final[re.Pattern[str]] = re.compile(r"\d")


@dataclass(frozen=True, slots=True)
class ToolAvailability:
    tesseract_executable: str | None
    pytesseract_module: bool
    paddleocr_module: bool
    pix2tex_module: bool
    latex_ocr_module: bool


@dataclass(frozen=True, slots=True)
class CheckerSignal:
    tool: str
    question_no: int
    kind: SignalKind
    text: str
    candidate: str | None
    warning: str | None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class CheckerDecision:
    status: str
    warning: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateToolConfig:
    crop_dir: Path
    out_dir: Path
    test_id: str
    questions: tuple[int, ...]
    run_tesseract: bool
    run_paddle: bool
    run_pix2tex: bool
    allow_model_load: bool


class LocalCandidateToolError(Exception):
    pass


def main() -> int:
    config = parse_args()
    report = run_candidate_tool_dry_run(config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> CandidateToolConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--test-id", default="t_unit_daesu_01_lv3_r1")
    parser.add_argument("--questions", default="all")
    parser.add_argument("--run-tesseract", action="store_true")
    parser.add_argument("--run-paddle", action="store_true")
    parser.add_argument("--run-pix2tex", action="store_true")
    parser.add_argument("--allow-model-load", action="store_true")
    args = parser.parse_args()
    return CandidateToolConfig(
        crop_dir=args.crop_dir.resolve(),
        out_dir=args.out_dir.resolve(),
        test_id=str(args.test_id),
        questions=parse_questions(str(args.questions)),
        run_tesseract=bool(args.run_tesseract),
        run_paddle=bool(args.run_paddle),
        run_pix2tex=bool(args.run_pix2tex),
        allow_model_load=bool(args.allow_model_load),
    )


def parse_questions(raw: str) -> tuple[int, ...]:
    value = raw.strip().lower()
    if value == "all":
        return tuple(range(1, QUESTION_COUNT + 1))
    questions = tuple(sorted({int(part.strip()) for part in value.split(",") if part.strip()}))
    if not questions or any(question < 1 or question > QUESTION_COUNT for question in questions):
        raise LocalCandidateToolError("--questions must be all or comma-separated values in 1..20")
    return questions


def run_candidate_tool_dry_run(config: CandidateToolConfig) -> JsonObject:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    availability = detect_tool_availability()
    report: JsonObject = {
        "source": "local_ocr_candidate_tools",
        "student_facing": False,
        "tool_availability": asdict(availability),
        "tesseract": tesseract_section(config, availability),
        "paddleocr": paddle_section(config, availability),
        "pix2tex": pix2tex_section(config, availability),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
    }
    report_path = config.out_dir / "local_ocr_candidate_tools_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def detect_tool_availability() -> ToolAvailability:
    return ToolAvailability(
        tesseract_executable=shutil.which("tesseract"),
        pytesseract_module=module_available("pytesseract"),
        paddleocr_module=module_available("paddleocr"),
        pix2tex_module=module_available("pix2tex"),
        latex_ocr_module=module_available("latex_ocr"),
    )


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def tesseract_section(config: CandidateToolConfig, availability: ToolAvailability) -> JsonObject:
    if availability.tesseract_executable is None:
        return {"status": "skipped", "reason": "tesseract_executable_not_found"}
    if not config.run_tesseract:
        return {"status": "skipped", "reason": "run_tesseract_flag_not_set"}
    signals = [
        asdict(tesseract_signal(question, answer_mode_for_question(config.test_id, question), config.crop_dir / f"q{question:03d}.png"))
        for question in config.questions
    ]
    return {"status": "ran_local_executable", "signals": signals}


def tesseract_signal(question_no: int, answer_mode: str, crop_path: Path) -> CheckerSignal:
    raw_text = run_tesseract_text(crop_path, tesseract_psm(answer_mode))
    return classify_tesseract_text(question_no, answer_mode, raw_text)


def run_tesseract_text(crop_path: Path, psm: str) -> str:
    completed = subprocess.run(
        ["tesseract", str(crop_path), "stdout", "--psm", psm],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def tesseract_psm(answer_mode: str) -> str:
    return "10" if answer_mode == "choice_number" else "7"


def classify_tesseract_text(question_no: int, answer_mode: str, text: str) -> CheckerSignal:
    normalized = normalize_text(text)
    if not normalized:
        return CheckerSignal("tesseract", question_no, "blank_like", text, None, "tesseract_blank_like")
    if answer_mode == "choice_number":
        return choice_signal(question_no, text, normalized)
    if SIMPLE_FINAL_ANSWER_RE.match(normalized):
        return CheckerSignal("tesseract", question_no, "candidate", text, normalized, None)
    if "," in normalized:
        return CheckerSignal("tesseract", question_no, "multiple_candidates", text, None, "tesseract_multiple_candidates")
    return CheckerSignal("tesseract", question_no, "format_conflict", text, None, "tesseract_answer_value_format_conflict")


def choice_signal(question_no: int, text: str, normalized: str) -> CheckerSignal:
    digits = tuple(DIGIT_RE.findall(normalized))
    valid_digits = tuple(digit for digit in digits if digit in CHOICE_NUMBER_VALUES)
    if len(valid_digits) == 1 and normalized == valid_digits[0]:
        return CheckerSignal("tesseract", question_no, "candidate", text, valid_digits[0], None)
    if len(valid_digits) > 1:
        return CheckerSignal("tesseract", question_no, "multiple_candidates", text, None, "tesseract_multiple_choice_candidates")
    return CheckerSignal("tesseract", question_no, "format_conflict", text, None, "tesseract_choice_digit_veto")


def normalize_text(text: str) -> str:
    return "".join(char for char in text.strip() if not char.isspace())


def paddle_section(config: CandidateToolConfig, availability: ToolAvailability) -> JsonObject:
    if not availability.paddleocr_module:
        return {"status": "skipped", "reason": "paddleocr_module_not_installed"}
    if not config.run_paddle:
        return {"status": "available_not_run", "reason": "run_paddle_flag_not_set"}
    if not config.allow_model_load:
        return {"status": "skipped", "reason": "allow_model_load_required_to_avoid_implicit_download"}
    return {"status": "ready_for_local_benchmark", "questions": list(config.questions), "provider_call_count": 0}


def pix2tex_section(config: CandidateToolConfig, availability: ToolAvailability) -> JsonObject:
    pix2tex_available = availability.pix2tex_module or availability.latex_ocr_module
    if not pix2tex_available:
        return {"status": "skipped", "reason": "pix2tex_module_not_installed"}
    answer_value_questions = [question for question in config.questions if answer_mode_for_question(config.test_id, question) == "answer_value"]
    if not config.run_pix2tex:
        return {"status": "available_not_run", "reason": "run_pix2tex_flag_not_set", "eligible_questions": answer_value_questions}
    if not config.allow_model_load:
        return {"status": "skipped", "reason": "allow_model_load_required_to_avoid_implicit_download", "eligible_questions": answer_value_questions}
    return {"status": "ready_for_formula_helper", "eligible_questions": answer_value_questions, "provider_call_count": 0}


def checker_decision(review_item: JsonObject, signal: CheckerSignal) -> CheckerDecision:
    status = text_value(review_item.get("status"))
    recognized = text_value(review_item.get("final_answer")) or text_value(review_item.get("recognized"))
    if signal.kind == "skip":
        return CheckerDecision(status or "review_required", None, "signal_skipped")
    if signal.kind == "blank_like" and recognized:
        return CheckerDecision("review_required", "local_checker_blank_conflict", "checker_saw_blank_but_review_item_has_text")
    if signal.kind in {"format_conflict", "multiple_candidates"}:
        return CheckerDecision("review_required", signal.warning, f"{signal.tool}_veto")
    if signal.kind == "candidate" and signal.candidate is not None and recognized and signal.candidate != recognized:
        return CheckerDecision("review_required", f"{signal.tool}_candidate_conflict", "checker_candidate_disagrees_with_review_item")
    return CheckerDecision(status or "review_required", None, "checker_signal_does_not_promote")


def apply_checker_signal(review_item: JsonObject, signal: CheckerSignal) -> JsonObject:
    decision = checker_decision(review_item, signal)
    if decision.status == text_value(review_item.get("status")) and decision.warning is None:
        return dict(review_item)
    normalized = dict(review_item)
    warnings = [item for item in normalized.get("warnings", []) if isinstance(item, str)] if isinstance(normalized.get("warnings"), list) else []
    if decision.warning is not None and decision.warning not in warnings:
        warnings.append(decision.warning)
    normalized["warnings"] = warnings
    normalized["status"] = "review_required"
    normalized["source"] = None
    normalized["final_answer"] = None
    return normalized


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


if __name__ == "__main__":
    raise SystemExit(main())
