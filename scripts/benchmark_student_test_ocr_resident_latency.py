"""Opt-in local segment latency diagnostic; never a handwriting accuracy eval."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from dataclasses import replace
from pathlib import Path

from core.student_test_ocr_config import load_student_test_ocr_config
from core.student_test_ocr_engine import OcrCrop
from core.student_test_ocr_readiness import artifact_sha256
from core.student_test_ocr_worker_pool import ResidentWorkerPool


def available_memory_bytes() -> int | None:
    if os.name == "nt":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ("totalPhysical", "availablePhysical", "totalPage", "availablePage", "totalVirtual", "availableVirtual", "extended")]
        state = MemoryStatus()
        state.length = ctypes.sizeof(state)
        return int(state.availablePhysical) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)) else None
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-local-model", action="store_true")
    parser.add_argument("--profile", choices=("m3_h1", "m3_h1_h2_h3"), default="m3_h1")
    parser.add_argument("--engine", choices=("choice_digit", "unimernet"), default="unimernet")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run_local_model:
        parser.error("explicit --run-local-model is required; no automatic inference")
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "generated") or output.exists():
        parser.error("a fresh output directory under generated is required")
    output.mkdir(parents=True, exist_ok=False)
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (432, 189), "white")
    ImageDraw.Draw(image).text((150, 55), "3" if args.engine == "choice_digit" else "1/2", fill="black", font_size=48)
    image_path = output / "synthetic_printed_answer.png"
    image.save(image_path)
    config = load_student_test_ocr_config(project_root=root)
    configured = config.choice_worker if args.engine == "choice_digit" else config.unimernet_worker_for_profile(args.profile)
    environment = {**configured.environment, "STUDENT_TEST_OCR_DEVICE": "cpu",
                   "STUDENT_TEST_OCR_UNIMERNET_VARIANT_PASS": "0",
                   "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "NO_ALBUMENTATIONS_UPDATE": "1"}
    spec = replace(configured, environment=environment)
    if args.engine == "choice_digit":
        weight = Path(environment["STUDENT_TEST_OCR_CHOICE_MODEL_PATH"])
    else:
        directory = Path(environment["STUDENT_TEST_OCR_UNIMERNET_MODEL_DIR"])
        weight = directory / environment["STUDENT_TEST_OCR_UNIMERNET_WEIGHT"]
    crops = [OcrCrop(number, "choice_number" if args.engine == "choice_digit" else "answer_value", image_path)
             for number in range(1, 21 if args.engine == "choice_digit" else 2)]
    report = {
        "schema": "student_test_ocr_resident_latency_v1", "createdAt": dt.datetime.now().astimezone().isoformat(),
        "engine": args.engine, "cropCount": len(crops),
        "profile": None if args.engine == "choice_digit" else args.profile, "python": str(spec.python_path), "weightPath": str(weight),
        "providerCallCount": 0, "deploymentReady": False, "modelInferenceExecuted": False,
        "accuracyEvaluated": False, "scope": "two identical synthetic printed segment requests; not handwriting, camera, sheet p90 or grading",
        "deadlineSeconds": spec.timeout_seconds, "records": [],
        "availableMemoryBytes": available_memory_bytes(),
        "minimumFreeMemoryBytes": (768 * 1024**2 if args.engine == "choice_digit" else 6 * 1024**3),
    }
    pool = ResidentWorkerPool()
    try:
        if report["availableMemoryBytes"] is None or report["availableMemoryBytes"] < report["minimumFreeMemoryBytes"]:
            raise RuntimeError("insufficient memory for this diagnostic")
        report["weightSha256"] = artifact_sha256(weight)
        report["inputSha256"] = artifact_sha256(image_path)
        report["workerSha256"] = artifact_sha256(spec.script_path)
        report["transportSha256"] = artifact_sha256(spec.script_path.with_name("student_test_ocr_worker_server.py"))
        report["generationSha256"] = artifact_sha256(spec.script_path.with_name("student_test_formula_inference.py"))
        report["poolSha256"] = artifact_sha256(root / "core/student_test_ocr_worker_pool.py")
        report["benchmarkSha256"] = artifact_sha256(Path(__file__))
        for phase in ("cold", "warm"):
            started = time.perf_counter()
            report["modelInferenceExecuted"] = True
            try:
                result = pool.run(spec, crops)
                item = result["items"][0]
                report["records"].append({"phase": phase, "state": "succeeded",
                    "wallSeconds": round(time.perf_counter() - started, 4),
                    "generationSeconds": item.get("seconds"), "tokenCount": item.get("tokenCount"),
                    "terminated": item.get("terminated"), "blank": item.get("blank")})
            except Exception as error:
                report["records"].append({"phase": phase, "state": "failed",
                    "wallSeconds": round(time.perf_counter() - started, 4),
                    "errorCode": str(getattr(error, "code", type(error).__name__))})
                if phase == "cold":
                    report["records"].append({"phase": "warm", "state": "not_run", "reason": "cold failed"})
                break
    except Exception as error:
        report["preflightError"] = type(error).__name__
    finally:
        pool.shutdown()
        report["ok"] = len(report["records"]) == 2 and all(row["state"] == "succeeded" for row in report["records"])
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
