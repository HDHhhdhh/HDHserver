from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Iterable, Mapping, Sequence

from core.student_test_ocr_config import load_student_test_ocr_config
from core.student_test_ocr_engine import (
    OcrCrop,
    _build_answer_candidate,
    run_json_worker,
)
from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    answer_values_equivalent,
    canonicalize_answer_text,
    numeric_answer_value,
)
from scripts.benchmark_student_test_choice_supporters import recognition_crops
from scripts.student_test_choice_worker import (
    REJECT_LABEL,
    build_model,
    checkpoint_contract,
    prepare_variants,
    worker_decision,
)
from scripts.student_test_unimernet_worker import (
    infer_image,
    load_runtime,
    normalized_formula,
)


SCHEMA: Final = "student_test_local_ocr_accuracy_v1"
CHOICE_LABELS: Final = ("1", "2", "3", "4", "5")


@dataclass(frozen=True, slots=True)
class CaseSpec:
    name: str
    crop_dir: Path
    transcription: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provider-free OCR accuracy rerun against human transcription only."
    )
    parser.add_argument("--choice-case", nargs=3, action="append", default=[], metavar=("NAME", "CROPS", "TRANSCRIPTION"))
    parser.add_argument("--formula-case", nargs=3, action="append", default=[], metavar=("NAME", "CROPS", "TRANSCRIPTION"))
    parser.add_argument("--choice-model", nargs=2, action="append", default=[], metavar=("NAME", "CHECKPOINT"))
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--formula-model-dir", type=Path, required=True)
    parser.add_argument("--formula-weight", default="unimernet_tiny.pth")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--choice-confidence", type=float, default=0.995)
    parser.add_argument("--choice-margin", type=float, default=0.90)
    parser.add_argument("--formula-confidence", type=float, default=0.995)
    parser.add_argument("--supporter-timeout", type=float, default=600.0)
    return parser.parse_args()


def cases(values: Sequence[Sequence[str]]) -> tuple[CaseSpec, ...]:
    output = tuple(CaseSpec(str(name), Path(crops).resolve(), Path(transcription).resolve()) for name, crops, transcription in values)
    if len({case.name for case in output}) != len(output):
        raise ValueError("benchmark case names must be unique")
    for case in output:
        if not case.crop_dir.is_dir() or not case.transcription.is_file():
            raise ValueError(f"benchmark case is unavailable: {case.name}")
        expected = {f"q{number:03d}.png" for number in range(1, 21)}
        actual = {path.name for path in case.crop_dir.glob("q*.png") if path.is_file()}
        if not expected.issubset(actual):
            raise ValueError(f"benchmark case must contain q001-q020: {case.name}")
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def case_manifest(case: CaseSpec) -> dict:
    digest = hashlib.sha256()
    crop_files = sorted(path for path in case.crop_dir.glob("q*.png") if path.is_file())
    for path in crop_files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return {
        "name": case.name,
        "cropCount": len(crop_files),
        "cropContentSha256": digest.hexdigest(),
        "humanTranscriptionSha256": sha256_file(case.transcription),
    }


def human_answers(path: Path) -> tuple[dict, ...]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, list):
        raise ValueError("human transcription answers are missing")
    rows = []
    seen: set[int] = set()
    for raw in answers:
        if not isinstance(raw, dict):
            continue
        number = raw.get("question_no")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 20 or number in seen:
            raise ValueError("human transcription question coverage is invalid")
        seen.add(number)
        rows.append(
            {
                "questionNo": number,
                "text": str(raw.get("human_answer") or "").strip(),
                "confidence": str(raw.get("confidence") or "").strip().lower(),
            }
        )
    if seen != set(range(1, 21)):
        raise ValueError("human transcription must cover q001-q020")
    return tuple(sorted(rows, key=lambda row: row["questionNo"]))


def choice_targets(path: Path) -> dict[int, str]:
    targets = {}
    for row in human_answers(path):
        text = row["text"]
        targets[row["questionNo"]] = text if row["confidence"] == "high" and text in CHOICE_LABELS else REJECT_LABEL
    return targets


def formula_targets(path: Path) -> tuple[dict[int, str], tuple[int, ...]]:
    targets: dict[int, str] = {}
    unsupported = []
    for row in human_answers(path):
        text = row["text"]
        if row["confidence"] != "high" or text in CHOICE_LABELS:
            continue
        try:
            numeric_answer_value(text)
        except Exception:
            unsupported.append(row["questionNo"])
            continue
        targets[row["questionNo"]] = text
    return targets, tuple(unsupported)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def zero_error_upper_95(accepted: int, wrong: int) -> float:
    if accepted <= 0 or wrong > 0:
        return 1.0
    return 1.0 - (0.05 ** (1.0 / accepted))


def summarize_choice_rows(rows: Sequence[Mapping[str, object]]) -> dict:
    choice_rows = [row for row in rows if row["humanLabel"] in CHOICE_LABELS]
    reject_rows = [row for row in rows if row["humanLabel"] == REJECT_LABEL]
    accepted = [row for row in rows if row["autoAccepted"] is True]
    wrong = sum(row["rawCorrect"] is not True for row in accepted)
    per_class = {}
    for label in (*CHOICE_LABELS, REJECT_LABEL):
        label_rows = [row for row in rows if row["humanLabel"] == label]
        per_class[label] = {
            "evaluated": len(label_rows),
            "rawCorrect": sum(row["rawCorrect"] is True for row in label_rows),
            "accepted": sum(row["autoAccepted"] is True for row in label_rows),
            "wrongAutoGrades": sum(row["autoAccepted"] is True and row["rawCorrect"] is not True for row in label_rows),
        }
    return {
        "evaluated": len(rows),
        "choiceEvaluated": len(choice_rows),
        "rejectEvaluated": len(reject_rows),
        "rawAccuracy": _ratio(sum(row["rawCorrect"] is True for row in rows), len(rows)),
        "choiceRawAccuracy": _ratio(sum(row["rawCorrect"] is True for row in choice_rows), len(choice_rows)),
        "rejectRecall": _ratio(sum(row["rawCorrect"] is True for row in reject_rows), len(reject_rows)),
        "accepted": len(accepted),
        "coverage": _ratio(len(accepted), len(choice_rows)),
        "wrongAutoGrades": wrong,
        "acceptedErrorUpper95": zero_error_upper_95(len(accepted), wrong),
        "perClass": per_class,
    }


def evaluate_choice_model(
    *,
    model_name: str,
    checkpoint_path: Path,
    prepared_cases: Mapping[str, tuple[CaseSpec, Sequence[tuple[int, Path]]]],
    confidence: float,
    margin: float,
) -> dict:
    import cv2
    import numpy as np
    import torch

    checkpoint_path = checkpoint_path.resolve()
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model_version, labels, input_size = checkpoint_contract(checkpoint)
    model = build_model(torch, output_count=len(labels))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    all_rows = []
    per_case = {}
    for case_name, (case, items) in prepared_cases.items():
        targets = choice_targets(case.transcription)
        case_rows = []
        for number, path in items:
            variants, density = prepare_variants(cv2, np, path, input_size)
            if not variants:
                decision = {
                    "text": "",
                    "score": None,
                    "margin": None,
                    "variantAgreed": False,
                    "accepted": False,
                    "blank": True,
                    "rejected": False,
                }
                predicted = REJECT_LABEL
            else:
                batch = torch.from_numpy(np.stack(variants)[:, None, :, :]).float()
                with torch.inference_mode():
                    probabilities = torch.softmax(model(batch), dim=1)
                variant_rows = []
                for probability in probabilities:
                    values, indices = torch.topk(probability, k=2)
                    variant_rows.append((labels[int(indices[0])], float(values[0]), float(values[0] - values[1])))
                decision = worker_decision(variant_rows, minimum=confidence, margin_minimum=margin)
                predicted = REJECT_LABEL if decision["rejected"] else str(decision["text"] or REJECT_LABEL)
            human = targets[number]
            row = {
                "case": case_name,
                "questionNo": number,
                "humanLabel": human,
                "predicted": predicted,
                "rawCorrect": predicted == human,
                "autoAccepted": bool(decision["accepted"]),
                "score": decision["score"],
                "margin": decision["margin"],
                "variantAgreed": decision["variantAgreed"],
                "blank": decision["blank"],
                "rejected": decision["rejected"],
                "inkDensity": round(float(density), 6),
            }
            case_rows.append(row)
            all_rows.append(row)
        per_case[case_name] = summarize_choice_rows(case_rows)
    return {
        "name": model_name,
        "modelVersion": model_version,
        "checkpointSha256": sha256_file(checkpoint_path),
        "thresholds": {"confidence": confidence, "margin": margin},
        "aggregate": summarize_choice_rows(all_rows),
        "cases": per_case,
        "rows": all_rows,
    }


def _safe_numeric_equivalent(left: object, right: object) -> bool:
    try:
        return answer_values_equivalent(canonicalize_answer_text(left), canonicalize_answer_text(right))
    except Exception:
        return False


def benchmark_formula_kind(value: object) -> str:
    text = str(value or "").strip().lower()
    if "\\sqrt" in text or "√" in text or "sqrt" in text:
        return "root"
    if "\\frac" in text or "/" in text:
        return "fraction"
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return "number"
    return "other"


def summarize_formula_rows(rows: Sequence[Mapping[str, object]]) -> dict:
    accepted = [row for row in rows if row["autoAccepted"] is True]
    wrong = sum(row["rawCorrect"] is not True for row in accepted)
    kinds = {}
    for kind in ("number", "fraction", "root", "other"):
        kind_rows = [row for row in rows if row["kind"] == kind]
        kinds[kind] = {
            "evaluated": len(kind_rows),
            "rawCorrect": sum(row["rawCorrect"] is True for row in kind_rows),
            "accepted": sum(row["autoAccepted"] is True for row in kind_rows),
            "wrongAutoGrades": sum(row["autoAccepted"] is True and row["rawCorrect"] is not True for row in kind_rows),
        }
    return {
        "evaluated": len(rows),
        "rawCorrect": sum(row["rawCorrect"] is True for row in rows),
        "rawAccuracy": _ratio(sum(row["rawCorrect"] is True for row in rows), len(rows)),
        "variantAgreed": sum(row["variantAgreed"] is True for row in rows),
        "accepted": len(accepted),
        "coverage": _ratio(len(accepted), len(rows)),
        "wrongAutoGrades": wrong,
        "acceptedErrorUpper95": zero_error_upper_95(len(accepted), wrong),
        "kinds": kinds,
    }


def _worker_items(response: Mapping[str, object]) -> dict[int, dict]:
    items = response.get("items")
    if not isinstance(items, list):
        raise ValueError("supporter worker items are missing")
    return {int(item["questionNo"]): dict(item) for item in items if isinstance(item, dict)}


def evaluate_formula(
    *,
    prepared_cases: Mapping[str, tuple[CaseSpec, Sequence[tuple[int, Path]]]],
    model_dir: Path,
    weight_filename: str,
    device_name: str,
    confidence: float,
    supporter_timeout: float,
) -> dict:
    from PIL import Image, ImageOps

    os.environ["STUDENT_TEST_OCR_DEVICE"] = device_name
    config = load_student_test_ocr_config()
    paddle_spec = replace(config.paddle_worker, timeout_seconds=supporter_timeout)
    formula_spec = replace(config.formula_worker, timeout_seconds=supporter_timeout)
    all_rows = []
    per_case = {}
    unsupported_by_case = {}
    supporter_failures = []
    model_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="student-test-formula-accuracy-") as temp_dir:
        torch, model, processor, device = load_runtime(
            Path(temp_dir) / "runtime.yaml",
            model_dir.resolve(),
            weight_filename,
        )
        model_load_seconds = round(time.perf_counter() - model_started, 4)
        for case_name, (case, items) in prepared_cases.items():
            targets, unsupported = formula_targets(case.transcription)
            unsupported_by_case[case_name] = list(unsupported)
            selected = [(number, path) for number, path in items if number in targets]
            if not selected:
                per_case[case_name] = summarize_formula_rows([])
                continue
            crops = tuple(OcrCrop(number, ANSWER_VALUE, path) for number, path in selected)
            paddle_items: dict[int, dict] = {}
            formula_items: dict[int, dict] = {}
            with ThreadPoolExecutor(max_workers=2) as pool:
                paddle_future = pool.submit(run_json_worker, paddle_spec, crops)
                formula_future = pool.submit(run_json_worker, formula_spec, crops)
                try:
                    paddle_items = _worker_items(paddle_future.result())
                except Exception as error:
                    supporter_failures.append({"case": case_name, "engine": "paddle", "error": type(error).__name__})
                try:
                    formula_items = _worker_items(formula_future.result())
                except Exception as error:
                    supporter_failures.append({"case": case_name, "engine": "formula", "error": type(error).__name__})
            case_rows = []
            for number, path in selected:
                started = time.perf_counter()
                with Image.open(path) as opened:
                    original = opened.convert("RGB")
                    enhanced = ImageOps.autocontrast(ImageOps.grayscale(opened)).convert("RGB")
                primary, token_confidence, minimum_confidence = infer_image(torch, model, processor, device, original)
                variant, variant_confidence, variant_minimum = infer_image(torch, model, processor, device, enhanced)
                variant_agreed = bool(
                    normalized_formula(primary)
                    and normalized_formula(primary) == normalized_formula(variant)
                )
                unimernet_item = {
                    "questionNo": number,
                    "text": primary,
                    "tokenConfidence": token_confidence,
                    "minTokenConfidence": minimum_confidence,
                    "variantText": variant,
                    "variantAgreed": variant_agreed,
                }
                candidate = _build_answer_candidate(
                    OcrCrop(number, ANSWER_VALUE, path),
                    paddle_items.get(number, {}),
                    unimernet_item,
                    formula_items.get(number, {}),
                    replace(config.confidence_policy, unimernet_token_minimum=confidence),
                )
                human = targets[number]
                row = {
                    "case": case_name,
                    "questionNo": number,
                    "kind": benchmark_formula_kind(human),
                    "human": human,
                    "recognized": primary,
                    "variant": variant,
                    "rawCorrect": _safe_numeric_equivalent(primary, human),
                    "variantAgreed": variant_agreed,
                    "tokenConfidence": token_confidence,
                    "minTokenConfidence": minimum_confidence,
                    "variantTokenConfidence": variant_confidence,
                    "variantMinTokenConfidence": variant_minimum,
                    "paddle": str(paddle_items.get(number, {}).get("text") or ""),
                    "formula": str(formula_items.get(number, {}).get("text") or ""),
                    "autoAccepted": candidate.get("confident") is True,
                    "seconds": round(time.perf_counter() - started, 4),
                }
                case_rows.append(row)
                all_rows.append(row)
                print(
                    json.dumps(
                        {
                            "progress": "formula",
                            "case": case_name,
                            "questionNo": number,
                            "completed": len(all_rows),
                            "correct": row["rawCorrect"],
                            "accepted": row["autoAccepted"],
                            "seconds": row["seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            per_case[case_name] = summarize_formula_rows(case_rows)
    return {
        "engine": "unimernet_tiny+paddle+pp_formulanet_s",
        "modelSha256": sha256_file(model_dir.resolve() / weight_filename),
        "device": str(device),
        "modelLoadSeconds": model_load_seconds,
        "threshold": confidence,
        "aggregate": summarize_formula_rows(all_rows),
        "cases": per_case,
        "unsupportedHighConfidenceQuestions": unsupported_by_case,
        "supporterFailures": supporter_failures,
        "rows": all_rows,
    }


def render_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# OCR Accuracy Rerun",
        "",
        f"- created: {report['createdAt']}",
        f"- operational status: {report.get('operationalStatus', 'not evaluated')}",
        f"- profile models ready: {report.get('profileModelsReady', False)}",
        f"- provider calls: {report['safety']['providerCallCount']}",
        f"- answer-key fields used: {report['safety']['answerKeyFieldsUsed']}",
        f"- production state changed: {report['safety']['productionStateChanged']}",
        "",
        "## Choice models",
        "",
        "| model | raw | accepted | coverage | wrong auto grades |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in report["choice"]["models"]:
        summary = model["aggregate"]
        lines.append(
            f"| {model['name']} | {summary['rawAccuracy']:.2%} | {summary['accepted']} | "
            f"{summary['coverage']:.2%} | {summary['wrongAutoGrades']} |"
        )
    lines.extend(
        [
            "",
            "## Choice cases",
            "",
            "| model | case | choice raw | accepted / choice | coverage | wrong auto grades | reject recall |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for model in report["choice"]["models"]:
        for case_name, summary in model.get("cases", {}).items():
            lines.append(
                f"| {model['name']} | {case_name} | {summary['choiceRawAccuracy']:.2%} | "
                f"{summary['accepted']} / {summary['choiceEvaluated']} | {summary['coverage']:.2%} | "
                f"{summary['wrongAutoGrades']} | {summary['rejectRecall']:.2%} |"
            )
    formula = report["formula"]
    lines.extend(
        [
            "",
            "## Formula model",
            "",
            f"- engine: {formula['engine']}",
            f"- device: {formula['device']}",
            f"- evaluated: {formula['aggregate']['evaluated']}",
            f"- raw accuracy: {formula['aggregate']['rawAccuracy']:.2%}",
            f"- accepted: {formula['aggregate']['accepted']}",
            f"- coverage: {formula['aggregate']['coverage']:.2%}",
            f"- wrong auto grades: {formula['aggregate']['wrongAutoGrades']}",
            f"- supporter failures: {len(formula['supporterFailures'])}",
            "",
            "| kind | evaluated | raw correct | accepted | wrong auto grades |",
            "|---|---:|---:|---:|---:|",
            *(
                f"| {kind} | {values['evaluated']} | {values['rawCorrect']} | {values['accepted']} | {values['wrongAutoGrades']} |"
                for kind, values in formula["aggregate"]["kinds"].items()
            ),
            "",
            "This is a local, key-free diagnostic. Missing profile checkpoints keep production at NO_GO.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    if not (0 <= args.choice_confidence <= 1 and 0 <= args.choice_margin <= 1 and 0 <= args.formula_confidence <= 1):
        raise ValueError("benchmark thresholds must be between zero and one")
    choice_cases = cases(args.choice_case)
    formula_cases = cases(args.formula_case)
    if not choice_cases or not formula_cases or not args.choice_model:
        raise ValueError("choice cases, formula cases, and choice models are required")
    template = args.template.resolve()
    model_dir = args.formula_model_dir.resolve()
    if not template.is_file() or not model_dir.is_dir() or not (model_dir / args.formula_weight).is_file():
        raise ValueError("benchmark template or formula model is unavailable")
    all_cases = {case.name: case for case in (*choice_cases, *formula_cases)}
    if len(all_cases) != len(choice_cases) + len(formula_cases):
        raise ValueError("choice and formula case names must be globally unique")
    before_manifests = {name: case_manifest(case) for name, case in all_cases.items()}
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-accuracy-") as temp_dir:
        prepared = {}
        for name, case in all_cases.items():
            output = Path(temp_dir) / name
            output.mkdir(parents=True, exist_ok=True)
            prepared[name] = (case, recognition_crops(case.crop_dir, template, output))
        choice_prepared = {case.name: prepared[case.name] for case in choice_cases}
        formula_prepared = {case.name: prepared[case.name] for case in formula_cases}
        choice_models = []
        for name, raw_path in args.choice_model:
            result = evaluate_choice_model(
                model_name=str(name),
                checkpoint_path=Path(raw_path),
                prepared_cases=choice_prepared,
                confidence=args.choice_confidence,
                margin=args.choice_margin,
            )
            choice_models.append(result)
            print(json.dumps({"progress": "choice", "model": name, "summary": result["aggregate"]}, ensure_ascii=False), flush=True)
        formula = evaluate_formula(
            prepared_cases=formula_prepared,
            model_dir=model_dir,
            weight_filename=args.formula_weight,
            device_name=args.device,
            confidence=args.formula_confidence,
            supporter_timeout=max(60.0, args.supporter_timeout),
        )
    after_manifests = {name: case_manifest(case) for name, case in all_cases.items()}
    if before_manifests != after_manifests:
        raise RuntimeError("benchmark inputs changed during evaluation")
    profile_models_ready = bool(
        Path(r"C:\server-ocr\models\unimernet_m3_h1\unimernet_m3_h1.pth").is_file()
        and Path(r"C:\server-ocr\models\unimernet_m3_h1_h2_h3\unimernet_m3_h1_h2_h3.pth").is_file()
    )
    report = {
        "schema": SCHEMA,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "durationSeconds": round(time.perf_counter() - started, 4),
        "inputManifests": list(before_manifests.values()),
        "choice": {
            "policy": "digit_model_only_current_runtime_policy",
            "models": choice_models,
        },
        "formula": formula,
        "profileModelsReady": profile_models_ready,
        "operationalStatus": "NO_GO" if not profile_models_ready else "REQUIRES_GATE_REVIEW",
        "safety": {
            "humanTranscriptionOnly": True,
            "answerKeyFieldsUsed": 0,
            "providerCallCount": 0,
            "submitCalls": 0,
            "studentUiCalls": 0,
            "productionStateChanged": False,
            "inputHashesUnchanged": True,
        },
    }
    print(
        json.dumps(
            {
                "completedSummary": {
                    "choice": [
                        {"name": model["name"], "aggregate": model["aggregate"]}
                        for model in choice_models
                    ],
                    "formula": formula["aggregate"],
                    "supporterFailures": formula["supporterFailures"],
                    "profileModelsReady": profile_models_ready,
                    "operationalStatus": report["operationalStatus"],
                }
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "operationalStatus": report["operationalStatus"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
