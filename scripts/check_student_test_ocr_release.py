"""NO_GO-only release preparation. Read saved evidence; never infer, migrate or enable."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from core.student_test_ocr_config import load_student_test_ocr_config
from core.student_test_ocr_readiness import artifact_sha256, deployment_artifacts
from core.student_test_ocr_rules import normalize_recognized_answer, canonicalize_answer_text
from scripts import student_test_camera_dataset as camera


def source_snapshot(code_root: Path) -> dict:
    artifacts = deployment_artifacts(required_files=(), code_root=code_root)
    result = {}
    for path in artifacts.values():
        name = path.relative_to(code_root).as_posix()
        try:
            camera._ancestors(path)
            result[name] = {"bytes": path.stat().st_size, "sha256": artifact_sha256(path)}
        except (OSError, ValueError) as error:
            result[name] = {"status": "unavailable", "errorType": type(error).__name__}
    return result


def check_frozen_slots(frozen: dict) -> None:
    rows = frozen.get("samples", [])
    if not isinstance(rows, list) or not rows or len({row.get("sampleId") for row in rows}) != len(rows):
        raise ValueError("unique complete frozen sample inventory required")
    photos = defaultdict(list)
    for row in rows:
        photos[row["photoId"]].append(row)
    inventory = {row["path"]: row["sha256"] for row in frozen["snapshotInventory"]}
    root = Path(frozen["snapshotRoot"]).absolute()
    sheets, writer_splits = defaultdict(list), {}
    for photo, values in photos.items():
        if len(values) != 20 or any(type(row.get("questionNo")) is not int for row in values) or {row["questionNo"] for row in values} != set(range(1, 21)):
            raise ValueError("frozen photo must retain exactly twenty slots")
        for key in ("writerId", "sheetId", "split", "originalPath", "parentPhotoSha256"):
            if len({row[key] for row in values}) != 1:
                raise ValueError("inconsistent frozen photo ownership")
        ordinals = {row.get("captureOrdinal") for row in values}
        if len(ordinals) != 1:
            raise ValueError("one ordinal per photo required")
        ordinal = values[0].get("captureOrdinal")
        if ordinal is not None and (type(ordinal) is not int or ordinal not in {1, 2}):
            raise ValueError("invalid frozen capture ordinal")
        owner = values[0]
        if writer_splits.setdefault(owner["writerId"], owner["split"]) != owner["split"]:
            raise ValueError("global writer cannot cross splits")
        sheets[owner["sheetId"]].append(owner)
        for row in values:
            if row["sampleId"] != f"{photo}:{row['questionNo']:02d}":
                raise ValueError("frozen sample/photo/question binding changed")
            for key, sha_key in (("cropPath", "cropSha256"), ("originalPath", "parentPhotoSha256")):
                try:
                    relative = Path(row[key]).absolute().relative_to(root).as_posix()
                except ValueError as error:
                    raise ValueError("frozen input escapes snapshot") from error
                if inventory.get(relative) != row[sha_key]:
                    raise ValueError("frozen row is not bound to snapshot inventory")
    for pair in sheets.values():
        if len(pair) != 2 or any(pair[0][key] != pair[1][key] for key in ("writerId", "split", "testCourse", "studentGrade")):
            raise ValueError("complete two-photo paper with one owner/route required")
        ordinals = {row.get("captureOrdinal") for row in pair}
        if ordinals not in ({None}, {1, 2}):
            raise ValueError("both legacy ordinals unknown or exactly captures one/two required")
        if pair[0]["parentPhotoSha256"] == pair[1]["parentPhotoSha256"]:
            raise ValueError("two copies of one photo are not two captures")
    counts = {"writers": len({row["writerId"] for row in rows}), "sheets": len({row["sheetId"] for row in rows}),
        "photos": len(photos), "slots": len(rows)}
    if frozen.get("counts") != counts:
        raise ValueError("frozen counts disagree with actual full inventory")


def review_saved_camera(frozen_path: Path, predictions_path: Path, run_path: Path) -> dict:
    paths = (frozen_path, predictions_path, run_path)
    for path in paths:
        camera._ancestors(path)
    original_bytes = [path.read_bytes() for path in paths]
    frozen, run = camera.load_json(original_bytes[0]), camera.load_json(original_bytes[2])
    check_frozen_slots(frozen)
    rows = [camera.load_json(line) for line in original_bytes[1].decode("utf-8").splitlines()]
    root = Path(frozen["snapshotRoot"])
    camera._ancestors(root)
    for ref in frozen["snapshotInventory"]:
        camera.asset(root, ref)
    sha = hashlib.sha256(original_bytes[0]).hexdigest()
    score = camera.score_saved(frozen, rows, run, sha)
    samples = {row["sampleId"]: row for row in frozen["samples"] if row["split"] == run["split"]}
    routes = {"choice" if name == "choice_number" else name: metrics for name, metrics in score["by"]["ocrRoute"].items()}
    choice_classes, reject_evaluated, reject_correct = Counter(), 0, 0
    formula_kinds = defaultdict(Counter)
    first_photos = defaultdict(list)
    missing_ordinals = False
    for prediction in rows:
        target = samples[prediction["sampleId"]]
        if target["answerMode"] == "choice_number":
            truth = normalize_recognized_answer("choice_number", target["transcription"])
            if target["supportedTarget"]:
                choice_classes[truth] += 1
            else:
                reject_evaluated += 1
                reject_correct += int(not prediction["autoAccepted"])
        elif target["supportedTarget"]:
            text = canonicalize_answer_text(target["transcription"])
            kinds = formula_kinds[target["formulaProfile"]]
            if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
                kinds["number"] += 1
            if "/" in text:
                kinds["fraction"] += 1
            if "sqrt" in text:
                kinds["root"] += 1
        ordinal = target.get("captureOrdinal")
        if type(ordinal) is not int or ordinal not in {1, 2}:
            missing_ordinals = True
        elif ordinal == 1:
            first_photos[target["photoId"]].append(prediction)
    first = {"status": "unverified_capture_ordinal_missing"}
    if not missing_ordinals:
        if any(len(values) != 20 for values in first_photos.values()):
            raise ValueError("first photograph must retain all twenty slots")
        count = len(first_photos)
        first = {"status": "saved_prediction_diagnostic_not_server_trace", "denominator": count,
            "predictedAllTwentyAccepted": sum(all(p["autoAccepted"] for p in ps) for ps in first_photos.values()),
            "predictedUncertaintyFourOrMore": sum(sum(not p["autoAccepted"] for p in ps) >= 4 for ps in first_photos.values()),
            "secondPhotographExcluded": True,
            "limitation": "accepted is a reported policy decision, not proof of correct grade or actual retake behavior"}
    for ref in frozen["snapshotInventory"]:
        camera.asset(root, ref)
    if any(path.read_bytes() != before for path, before in zip(paths, original_bytes)):
        raise ValueError("saved evidence changed during review")
    return {"status": "diagnostic_reviewed_not_release_approval", "datasetSplit": run["split"],
        "frozenLabelsSha256": sha, "predictionSha256": hashlib.sha256(original_bytes[1]).hexdigest(),
        "runSha256": hashlib.sha256(original_bytes[2]).hexdigest(),
        "reportedModelBindings": run["modelBindings"], "reportedPolicySha256": run["acceptancePolicySha256"],
        "reportedInferenceCodeSha256": run["inferenceCodeSha256"],
        "fixedDenominator": score["denominator"], "routes": routes,
        "choiceTargetClasses": {str(n): choice_classes[str(n)] for n in range(1, 6)},
        "choiceRejectDiagnostic": {"evaluated": reject_evaluated, "correctlyNotAccepted": reject_correct,
            "basis": "pre-frozen unsupported/blank/ambiguous choice slots; distribution needs independent review"},
        "formulaKinds": {name: dict(values) for name, values in formula_kinds.items()},
        "formulaKindBasis": "human transcription, not OCR output; fraction/root counts can overlap",
        "firstCaptureDiagnostic": first, "reportedLatency": score["latency"],
        "pendingAfterRecapture": score["pendingAfterRecapture"],
        "reviewLimit": "byte contracts and reported decisions; not independent writer/label/grade/latency authentication",
        "providerCallCount": 0, "deploymentReady": False}


def inspect_release(*, project_root: Path, camera_paths=None) -> dict:
    project_root = project_root.absolute()
    camera._ancestors(project_root)
    config = load_student_test_ocr_config(project_root=project_root)
    readiness = config.readiness_report()
    inspector_sha = artifact_sha256(Path(__file__))
    # These are the imported server code bytes, not arbitrary files under --project-root.
    code_root = Path(__file__).resolve().parents[1]
    source = source_snapshot(code_root)
    camera_review = review_saved_camera(*camera_paths) if camera_paths else {"status": "not_supplied"}
    if source_snapshot(code_root) != source or artifact_sha256(Path(__file__)) != inspector_sha:
        raise ValueError("release source bytes changed during inspection")
    return {"schema": "student_test_ocr_release_preflight_v1", "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "NO_GO_PREPARATION_ONLY", "deploymentReady": False, "providerCallCount": 0,
        "inspectorCodeSha256": inspector_sha, "cameraScorerCodeSha256": artifact_sha256(Path(camera.__file__)),
        "rolloutAuthorized": False, "trainingExecuted": False, "inferenceExecuted": False,
        "inspectedEnvironment": {"ocrEnabled": config.enabled, "maintenanceEnabled": config.maintenance_enabled,
            "allowUnreadyModels": config.allow_unready_models,
            "scope": "this CLI process configuration; not observation of the running production process"},
        "readinessContractInspection": readiness,
        "runtimeArtifactHashScope": "runtime readiness hashes model artifacts only when all review-contract gates pass; not a new checkpoint inventory validation",
        "policy": asdict(config.confidence_policy), "policySha256": hashlib.sha256(camera.encoded(asdict(config.confidence_policy))).hexdigest(),
        "codeRoot": str(code_root), "projectRoot": str(project_root), "releaseCodeSha256": source,
        "cameraReview": camera_review,
        "unverifiedReleaseGates": [
            "new writer-disjoint natural-handwriting release holdout and reviewed source/consent/exclusion registry",
            "independent image transcription, pre-evaluation lock, no tuning use and writer-cluster review",
            "all three route quality and reject/class/type coverage under canonical readiness rules",
            "actual first-capture, full-retake and two-question-recapture correction traces",
            "independently checked final/initial grading and false incorrect finalization",
            "target-host end-to-end queue/crop/OCR/grading-store latency and cold/warm scope",
            "browser camera-region/rendered-flow QA bound to these current frontend bytes",
            "reviewed model adoption, quiescent backup/migration/maintenance/activation/rollback approval",
        ],
        "gateOwner": ["core/student_test_ocr_readiness.py", "docs/STUDENT_TEST_OCR_PUBLIC_DATA.md#품질-gate",
            "docs/PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약"],
        "evidenceLimit": "never writes deployment evidence v1/GO; source inspection and saved-output review do not prove release readiness"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    for name in ("camera-frozen", "camera-predictions", "camera-run"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    supplied = (args.camera_frozen, args.camera_predictions, args.camera_run)
    if any(supplied) and not all(supplied):
        parser.error("camera frozen/predictions/run must be supplied together")
    result = inspect_release(project_root=args.project_root, camera_paths=supplied if all(supplied) else None)
    # No overwrite and no operational evidence filename, even after a future valid review.
    camera.fresh_directory(args.output)
    (args.output / "RELEASE_PREFLIGHT.json").write_bytes(camera.encoded(result))
    print(json.dumps({"output": str(args.output.absolute()), "status": result["status"],
        "readiness": result["readinessContractInspection"], "cameraReview": result["cameraReview"]["status"],
        "providerCallCount": 0, "deploymentReady": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
