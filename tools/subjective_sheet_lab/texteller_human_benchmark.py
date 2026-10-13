from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Final, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures


QUESTION_COUNT: Final[int] = 20
REVIEW_REQUIRED: Final[str] = "review_required"
LOCAL_FORMULA_UNVERIFIED: Final[str] = "local_formula_unverified"
FORMULA_PARSE_UNSUPPORTED: Final[str] = "formula_parse_unsupported"
DEFAULT_HF_HOME: Final[Path] = Path("C:/server-ocr/texteller-cache/huggingface")
Recognizer = Callable[[Sequence[Path]], list[str]]


class TexTellerBenchmarkError(ValueError):
    pass


def run_benchmark(
    case_ids: Sequence[str],
    *,
    crop_root: Path,
    human_root: Path,
    recognizer: Recognizer | None = None,
    hf_home: Path = DEFAULT_HF_HOME,
    batch_size: int = 4,
    max_tokens: int = 64,
    cpu_threads: int = 6,
) -> dict[str, Any]:
    cases = _load_cases(case_ids, crop_root=crop_root, human_root=human_root)
    crop_paths = [path for case in cases for path in case["crop_paths"]]

    model_load_ms = 0.0
    if recognizer is None:
        started = time.perf_counter()
        recognizer = _build_texteller_recognizer(
            hf_home=hf_home,
            batch_size=batch_size,
            max_tokens=max_tokens,
            cpu_threads=cpu_threads,
        )
        model_load_ms = round((time.perf_counter() - started) * 1000, 2)

    started = time.perf_counter()
    raw_outputs = recognizer(crop_paths)
    inference_ms = round((time.perf_counter() - started) * 1000, 2)
    if len(raw_outputs) != len(crop_paths):
        raise TexTellerBenchmarkError(
            f"recognizer returned {len(raw_outputs)} outputs for {len(crop_paths)} crops"
        )

    exact_matches = 0
    unresolved = 0
    mismatches = 0
    high_confidence_in_scope = 0
    outside_supported_scope = 0
    human_low_confidence = 0
    items: list[dict[str, Any]] = []
    output_index = 0
    for case in cases:
        human_by_question = case["human_by_question"]
        for question_no in range(1, QUESTION_COUNT + 1):
            raw_latex = _single_line(raw_outputs[output_index])
            output_index += 1
            recognized = normalize_short_answer(raw_latex, ANSWER_VALUE)
            warnings = [LOCAL_FORMULA_UNVERIFIED]
            if recognized is None:
                warnings.append(FORMULA_PARSE_UNSUPPORTED)

            human_item = human_by_question[question_no]
            confidence = human_item.get("confidence")
            if confidence != "high":
                human_low_confidence += 1
                evaluation = "human_low_confidence"
            else:
                human_normalized = normalize_short_answer(
                    human_item.get("human_answer"), ANSWER_VALUE
                )
                if human_normalized is None:
                    outside_supported_scope += 1
                    evaluation = "outside_supported_scope"
                else:
                    high_confidence_in_scope += 1
                    if recognized is None:
                        unresolved += 1
                        evaluation = "review_required_unresolved"
                    elif recognized == human_normalized:
                        exact_matches += 1
                        evaluation = "exact_match_review_only"
                    else:
                        mismatches += 1
                        evaluation = "mismatch_review_required"

            items.append(
                {
                    "case": case["case_id"],
                    "question": question_no,
                    "raw_latex": raw_latex,
                    "recognized": recognized or "?",
                    "status": REVIEW_REQUIRED,
                    "warnings": warnings,
                    "evaluation": evaluation,
                }
            )

    payload: dict[str, Any] = {
        "source": "texteller_3_local_human_benchmark",
        "developer_lab_only": True,
        "student_facing": False,
        "model": "OleehyO/TexTeller",
        "device": "cpu",
        "provider_calls": 0,
        "unsafe_auto_grade_count": 0,
        "human_transcription_used_for_evaluation_only": True,
        "case_count": len(cases),
        "problem_count": len(items),
        "timing": {
            "model_load_ms": model_load_ms,
            "inference_ms": inference_ms,
            "per_crop_ms": round(inference_ms / len(items), 2),
        },
        "summary": {
            "high_confidence_in_scope": high_confidence_in_scope,
            "exact_matches": exact_matches,
            "unresolved": unresolved,
            "mismatches": mismatches,
            "outside_supported_scope": outside_supported_scope,
            "human_low_confidence": human_low_confidence,
            "exact_match_percent": round(
                100.0 * exact_matches / high_confidence_in_scope, 2
            )
            if high_confidence_in_scope
            else None,
        },
        "items": items,
    }
    _validate_safe_payload(payload)
    return payload


def write_payload(payload: dict[str, Any], output_path: Path) -> None:
    _validate_safe_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_cases(
    case_ids: Sequence[str], *, crop_root: Path, human_root: Path
) -> list[dict[str, Any]]:
    normalized_case_ids = [str(case_id).strip() for case_id in case_ids]
    if not normalized_case_ids or any(not case_id for case_id in normalized_case_ids):
        raise TexTellerBenchmarkError("at least one non-empty case is required")
    if len(set(normalized_case_ids)) != len(normalized_case_ids):
        raise TexTellerBenchmarkError("duplicate case ids are not allowed")

    cases: list[dict[str, Any]] = []
    for case_id in normalized_case_ids:
        crop_dir = (crop_root / case_id / "crops").resolve()
        crop_paths = [crop_dir / f"q{question_no:03d}.png" for question_no in range(1, 21)]
        missing = [path.name for path in crop_paths if not path.is_file()]
        if missing:
            raise TexTellerBenchmarkError(
                f"{case_id} is missing crop files: {', '.join(missing)}"
            )
        human_path = human_root / f"{case_id}_same_contact" / "human_transcription.json"
        if not human_path.is_file():
            human_path = human_root / case_id / "human_transcription.json"
        human_payload = _read_json_object(human_path)
        human_by_question = _human_items_by_question(human_payload.get("answers"))
        cases.append(
            {
                "case_id": case_id,
                "crop_paths": crop_paths,
                "human_by_question": human_by_question,
            }
        )
    return cases


def _build_texteller_recognizer(
    *, hf_home: Path, batch_size: int, max_tokens: int, cpu_threads: int
) -> Recognizer:
    if batch_size < 1 or max_tokens < 1 or cpu_threads < 1:
        raise TexTellerBenchmarkError("batch size, max tokens, and CPU threads must be positive")
    os.environ["HF_HOME"] = str(hf_home.resolve())
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        import torch
        from texteller import img2latex, load_model, load_tokenizer
    except (ImportError, ModuleNotFoundError) as exc:
        raise TexTellerBenchmarkError("TexTeller runtime is not installed") from exc

    torch.set_num_threads(cpu_threads)
    try:
        model = load_model(use_onnx=False)
        tokenizer = load_tokenizer()
    except (OSError, RuntimeError, ValueError) as exc:
        raise TexTellerBenchmarkError(
            "TexTeller model is not available in the offline cache"
        ) from exc
    model.eval()
    device = torch.device("cpu")

    def recognize(paths: Sequence[Path]) -> list[str]:
        outputs: list[str] = []
        with torch.inference_mode():
            for start in range(0, len(paths), batch_size):
                batch = [str(path) for path in paths[start : start + batch_size]]
                outputs.extend(
                    img2latex(
                        model,
                        tokenizer,
                        batch,
                        device=device,
                        out_format="latex",
                        keep_style=False,
                        max_tokens=max_tokens,
                        num_beams=1,
                    )
                )
        return outputs

    return recognize


def _human_items_by_question(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list) or len(value) != QUESTION_COUNT:
        raise TexTellerBenchmarkError("human transcription must contain 20 rows")
    result: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise TexTellerBenchmarkError("human transcription contains a non-object")
        question_no = item.get("question_no")
        if not isinstance(question_no, int) or not 1 <= question_no <= 20:
            raise TexTellerBenchmarkError("human transcription has an invalid question")
        if question_no in result:
            raise TexTellerBenchmarkError(
                f"human transcription has duplicate q{question_no:03d}"
            )
        result[question_no] = item
    if sorted(result) != list(range(1, QUESTION_COUNT + 1)):
        raise TexTellerBenchmarkError("human transcription question coverage is incomplete")
    return result


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TexTellerBenchmarkError(
            f"could not read human transcription: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise TexTellerBenchmarkError("human transcription root must be an object")
    return value


def _single_line(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "?"
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _validate_safe_payload(payload: dict[str, Any]) -> None:
    if forbidden_paths(payload):
        raise TexTellerBenchmarkError("benchmark output contains forbidden fields")
    if path_exposures(payload):
        raise TexTellerBenchmarkError("benchmark output exposes a local path")
    if payload.get("provider_calls") != 0:
        raise TexTellerBenchmarkError("local benchmark must report zero provider calls")
    if payload.get("unsafe_auto_grade_count") != 0:
        raise TexTellerBenchmarkError("local benchmark cannot auto-grade")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise TexTellerBenchmarkError("benchmark output has no items")
    if any(
        not isinstance(item, dict) or item.get("status") != REVIEW_REQUIRED
        for item in items
    ):
        raise TexTellerBenchmarkError("all local benchmark rows must require review")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline TexTeller benchmark against human transcription only."
    )
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument(
        "--crop-root", type=Path, default=Path("C:/server-ocr/crop_benchmark_inputs")
    )
    parser.add_argument(
        "--human-root", type=Path, default=Path("C:/server-ocr/gemini_outputs")
    )
    parser.add_argument("--hf-home", type=Path, default=DEFAULT_HF_HOME)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--cpu-threads", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    payload = run_benchmark(
        args.case,
        crop_root=args.crop_root,
        human_root=args.human_root,
        hf_home=args.hf_home,
        batch_size=args.batch_size,
        max_tokens=args.max_tokens,
        cpu_threads=args.cpu_threads,
    )
    write_payload(payload, args.out)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TexTellerBenchmarkError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from None
