"""Freeze independently reviewed camera inputs; score saved outputs, never run OCR."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat

from core.student_test_ocr_rules import (
    OcrRuleError, answer_values_equivalent, canonicalize_answer_text, numeric_answer_value,
    normalize_recognized_answer,
)
from core.student_test_formula_profiles import formula_profile_for_curriculum
from scripts.student_test_formula_inference import MAX_FORMULA_TOKENS

SPLITS = {"development", "calibration", "release_holdout"}
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA = re.compile(r"^[a-f0-9]{64}$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _plain(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("links/reparse points are not allowed")


def _ancestors(path: Path) -> None:
    for item in (path.absolute(), *path.absolute().parents):
        if item.exists() or item.is_symlink():
            _plain(item)


def _aware(value) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise ValueError("aware ISO timestamp required") from error
    if result.tzinfo is None:
        raise ValueError("timestamp offset required")
    return result


def load_json(raw: str | bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def asset(root: Path, ref: dict) -> Path:
    name = ref.get("path", "")
    parts = PurePosixPath(name).parts
    if not name or "\\" in name or ":" in name or name.startswith("/") or any(p in {".", ".."} for p in parts):
        raise ValueError("unsafe relative asset path")
    if str(PurePosixPath(name)) != name or not SHA.fullmatch(str(ref.get("sha256", ""))):
        raise ValueError("asset path/hash must be canonical")
    if any(p.endswith((" ", ".")) or any(ord(c) < 32 for c in p) or
        p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))} for p in parts):
        raise ValueError("ambiguous/device asset path")
    current = root
    for part in parts:
        current = current / part
        _plain(current)
    if not stat.S_ISREG(current.stat().st_mode) or current.stat().st_size == 0:
        raise ValueError("nonempty regular asset required")
    if digest(current) != ref["sha256"]:
        raise ValueError("asset SHA mismatch: " + name)
    return current


def fresh_directory(path: Path) -> None:
    path = path.absolute()
    for parent in reversed(path.parents):
        if parent.exists():
            _plain(parent)
    if path.exists() or path.is_symlink():
        raise ValueError("fresh output directory required")
    path.mkdir(parents=True, exist_ok=False)


def _no_targets(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            flat = re.sub(r"[^a-z]", "", str(key).lower())
            if any(word in flat for word in ("answerkey", "correctanswer", "expectedvalue", "writingprompt", "prediction", "modeloutput")):
                raise ValueError("answer keys/prompts/model outputs cannot enter intake")
            _no_targets(item)
    elif isinstance(value, list):
        for item in value:
            _no_targets(item)


def _identifier(value) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("global pseudonymous identifier required")
    return value


def _supported(mode, text) -> bool:
    if mode == "choice_number":
        return bool(normalize_recognized_answer(mode, text))
    try:
        numeric_answer_value(text)
        return True
    except OcrRuleError:
        return False


def _route(row: dict) -> str:
    return "choice_number" if row["answerMode"] == "choice_number" else row["formulaProfile"]


def validate_intake(intake: dict, root: Path) -> dict:
    _no_targets(intake)
    _ancestors(root)
    if intake.get("schema") != "student_test_camera_intake_v1":
        raise ValueError("invalid camera intake schema")
    permissions = intake.get("permissions", {})
    if permissions.get("confirmed") is not True or permissions.get("deidentified") is not True:
        raise ValueError("usage permission and deidentification attestations required")
    if not all(isinstance(permissions.get(k), str) and permissions[k].strip() for k in ("reference", "retentionReference")):
        raise ValueError("usage/retention references required; attestations are not legal verification")
    review = intake.get("review", {})
    _identifier(review.get("reviewerId"))
    if review.get("actualHandwriting") is not True or set(review.get("blindTo", [])) != {"writingPrompts", "answerKeys", "modelOutputs"}:
        raise ValueError("actual handwriting, independently blinded review required")
    completed = _aware(review.get("completedAt"))
    if completed > datetime.now(timezone.utc):
        raise ValueError("review time must be aware and not in the future")
    template = intake.get("template", {})
    for key in ("pdf", "coordinates", "warpedReference"):
        asset(root, template[key])
    photos = intake.get("photos")
    if not isinstance(photos, list) or not photos:
        raise ValueError("actual camera photos required")
    writer_splits, sheets, photo_ids, file_owners = {}, defaultdict(list), set(), {}
    rows = []
    for photo in photos:
        writer, sheet, photo_id = (_identifier(photo.get(k)) for k in ("writerId", "sheetId", "photoId"))
        split = photo.get("split")
        if split not in SPLITS or writer_splits.setdefault(writer, split) != split:
            raise ValueError("one split per global writer; cross-grade IDs must stay global")
        if photo_id in photo_ids:
            raise ValueError("duplicate photoId")
        photo_ids.add(photo_id)
        if photo.get("studentGrade") not in {"M_G3", "H_G1", "H_G2", "H_G3"}:
            raise ValueError("grade and test course must be explicit")
        profile = formula_profile_for_curriculum(photo.get("testCourse"))
        if type(photo.get("captureOrdinal")) is not int or photo["captureOrdinal"] not in {1, 2}:
            raise ValueError("exactly two real-camera captures per paper")
        original = asset(root, photo["original"])
        receipt_path = asset(root, photo["cropReceipt"])
        receipt = load_json(receipt_path.read_bytes())
        if receipt.get("schema") != "student_test_camera_crop_receipt_v1" or receipt.get("parentPhotoSha256") != photo["original"]["sha256"]:
            raise ValueError("crop receipt must bind original photo")
        if receipt.get("templateCoordinatesSha256") != template["coordinates"]["sha256"] or not SHA.fullmatch(str(receipt.get("cropperCodeSha256", ""))):
            raise ValueError("cropper/template provenance required")
        crop_refs = receipt.get("questions", [])
        if len(crop_refs) != 20 or any(type(q.get("questionNo")) is not int for q in crop_refs) or {q["questionNo"] for q in crop_refs} != set(range(1, 21)):
            raise ValueError("crop receipt must contain all twenty slots")
        crop_refs = {q["questionNo"]: q for q in crop_refs}
        questions = photo.get("questions", [])
        if len(questions) != 20 or any(type(q.get("questionNo")) is not int for q in questions) or {q["questionNo"] for q in questions} != set(range(1, 21)):
            raise ValueError("blank/ambiguous/unsupported slots cannot leave the denominator")
        for ref in [photo["original"]] + [q["crop"] for q in questions]:
            owner = (writer, sheet)
            if ref["sha256"] in file_owners and file_owners[ref["sha256"]] != owner:
                raise ValueError("exact duplicate crosses writer/paper boundary")
            file_owners[ref["sha256"]] = owner
        sheets[sheet].append(photo)
        for q in sorted(questions, key=lambda item: item["questionNo"]):
            no, mode = q["questionNo"], q.get("answerMode")
            if mode not in {"choice_number", "answer_value"} or q.get("expressionKind") not in {"integer", "fraction", "radical", "two_term", "other"}:
                raise ValueError("question-level route and expression kind required")
            status, text = q.get("legibility"), q.get("transcription")
            if status not in {"readable", "blank", "ambiguous", "unsupported"} or not isinstance(text, str) or len(text) > 200:
                raise ValueError("independent legibility/transcription required")
            if status == "readable" and not text.strip() or status != "readable" and text:
                raise ValueError("do not invent a target for blank/ambiguous/unsupported slots")
            crop_path = asset(root, q["crop"])
            bound = crop_refs[no]
            if bound.get("cropSha256") != q["crop"]["sha256"] or not isinstance(bound.get("transform"), dict) or not bound["transform"]:
                raise ValueError("crop hash/transform receipt mismatch")
            rows.append({"sampleId": f"{photo_id}:{no:02d}", "writerId": writer, "sheetId": sheet,
                "photoId": photo_id, "split": split, "studentGrade": photo["studentGrade"],
                "captureOrdinal": photo["captureOrdinal"],
                "testCourse": photo["testCourse"], "formulaProfile": profile,
                "questionNo": no, "answerMode": mode, "expressionKind": q["expressionKind"],
                "parentPhotoSha256": photo["original"]["sha256"], "originalPath": str(original.absolute()),
                "cropPath": str(crop_path.absolute()), "cropSha256": q["crop"]["sha256"],
                "cropReceiptSha256": photo["cropReceipt"]["sha256"], "legibility": status,
                "transcription": text, "supportedTarget": status == "readable" and _supported(mode, text)})
    for pair in sheets.values():
        if len(pair) != 2 or {p["captureOrdinal"] for p in pair} != {1, 2}:
            raise ValueError("same paper needs two distinct camera photographs")
        if pair[0]["original"]["sha256"] == pair[1]["original"]["sha256"]:
            raise ValueError("two copies of one photo are not two captures")
        for key in ("writerId", "studentGrade", "testCourse", "split"):
            if pair[0][key] != pair[1][key]:
                raise ValueError("paper ownership/routing changed between captures")
        ordered = [sorted(p["questions"], key=lambda q: q["questionNo"]) for p in pair]
        for left, right in zip(*ordered):
            if any(left[k] != right[k] for k in ("answerMode", "expressionKind")):
                raise ValueError("same paper question route differs")
            if left["legibility"] == right["legibility"] == "readable" and canonicalize_answer_text(left["transcription"]) != canonicalize_answer_text(right["transcription"]):
                raise ValueError("readable transcriptions of same paper disagree; human reconciliation required")
    return {"schema": "student_test_camera_frozen_v1", "review": review, "permissions": permissions,
        "template": template, "samples": rows, "counts": {"writers": len(writer_splits), "sheets": len(sheets),
        "photos": len(photos), "slots": len(rows)}, "independenceLimit": "global IDs and exact hashes; identity/near-duplicates not independently proven",
        "reviewEvidence": "operator attestations and byte bindings; human independence and geometric crop accuracy not independently proven",
        "providerCallCount": 0, "deploymentReady": False}


def freeze(intake_path: Path, output: Path) -> dict:
    _ancestors(intake_path)
    raw = intake_path.read_bytes()
    result = validate_intake(load_json(raw), intake_path.parent.absolute())
    if any(row["split"] == "release_holdout" for row in result["samples"]):
        raise ValueError("initial diagnostic tool cannot export release holdout; separate approved workflow required")
    result["intakeSha256"] = hashlib.sha256(raw).hexdigest()
    result["scorerCodeSha256"] = digest(Path(__file__))
    result["normalizerCodeSha256"] = digest(Path(__file__).resolve().parents[1] / "core/student_test_ocr_rules.py")
    result["routingCodeSha256"] = digest(Path(__file__).resolve().parents[1] / "core/student_test_formula_profiles.py")
    intake = load_json(raw)
    refs = list(intake["template"].values())
    for photo in intake["photos"]:
        refs += [photo["original"], photo["cropReceipt"]] + [q["crop"] for q in photo["questions"]]
    bound = {}
    names = {}
    for ref in refs:
        if names.setdefault(ref["path"].casefold(), ref["path"]) != ref["path"]:
            raise ValueError("case-insensitive snapshot path collision")
        if ref["path"] in bound and bound[ref["path"]] != ref["sha256"]:
            raise ValueError("one asset path has multiple declared hashes")
        bound[ref["path"]] = ref["sha256"]
    fresh_directory(output)
    snapshot = output / "snapshot"
    snapshot.mkdir()
    for name, sha in bound.items():
        source = asset(intake_path.parent.absolute(), {"path": name, "sha256": sha})
        destination = snapshot / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as original, destination.open("xb") as copied:
            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                copied.write(chunk)
        if digest(destination) != sha or digest(source) != sha:
            raise ValueError("asset changed during snapshot; no success labels emitted")
    if intake_path.read_bytes() != raw:
        raise ValueError("intake changed during freeze")
    validate_intake(intake, intake_path.parent.absolute())
    for row in result["samples"]:
        photo = next(p for p in intake["photos"] if p["photoId"] == row["photoId"])
        question = next(q for q in photo["questions"] if q["questionNo"] == row["questionNo"])
        row["originalPath"] = str((snapshot / photo["original"]["path"]).absolute())
        row["cropPath"] = str((snapshot / question["crop"]["path"]).absolute())
    result["snapshotInventory"] = [{"path": name, "sha256": sha} for name, sha in sorted(bound.items())]
    result["snapshotRoot"] = str(snapshot.absolute())
    result["snapshotLimit"] = "hash-bound fresh copy, not an OS-enforced immutable store; inference must recheck before/after"
    model_inputs = {"schema": "student_test_camera_model_inputs_v1", "intakeSha256": result["intakeSha256"],
        "role": "inference_only; calibration images/labels must not enter training",
        "samples": [{key: row[key] for key in ("sampleId", "split", "answerMode", "formulaProfile", "cropPath", "cropSha256")} for row in result["samples"]]}
    for ref in result["snapshotInventory"]:
        asset(snapshot, ref)
    result["frozenAt"] = datetime.now(timezone.utc).isoformat()
    (output / "FROZEN_LABELS.json").write_bytes(encoded(result))
    (output / "MODEL_INPUTS.json").write_bytes(encoded(model_inputs))
    return {"counts": result["counts"], "frozenLabelsSha256": digest(output / "FROZEN_LABELS.json"),
        "modelInputsSha256": digest(output / "MODEL_INPUTS.json"), "providerCallCount": 0, "deploymentReady": False}


def _summary(scored) -> dict:
    n = len(scored)
    count = lambda key: sum(r[key] for r in scored)
    accepted = count("accepted")
    return {"denominator": n, "numericCorrect": count("numeric"), "textExact": count("text"),
        "numericFailures": n - count("numeric"), "generationFailures": count("generationFailure"),
        "autoAccepted": accepted, "falseAccepted": count("falseAccepted"),
        "coverage": accepted / n if n else None,
        "falseAcceptanceAmongAccepted": count("falseAccepted") / accepted if accepted else None,
        "supportedReadableTargets": count("supportedTarget")}


def score_saved(frozen: dict, predictions: list, run: dict, frozen_sha: str) -> dict:
    if frozen.get("schema") != "student_test_camera_frozen_v1" or run.get("schema") != "student_test_camera_prediction_run_v1":
        raise ValueError("frozen/run schema required")
    if run.get("frozenLabelsSha256") != frozen_sha or run.get("providerCallCount") != 0 or run.get("deploymentReady") is not False:
        raise ValueError("run must bind pre-frozen labels and offline/non-release scope")
    executed = _aware(run.get("executedAt"))
    if run.get("split") not in SPLITS or executed <= _aware(frozen.get("frozenAt")) or executed > datetime.now(timezone.utc):
        raise ValueError("run after label freeze on one explicit split required")
    for key in ("inferenceCodeSha256", "acceptancePolicySha256"):
        if not SHA.fullmatch(str(run.get(key, ""))):
            raise ValueError("model/code/acceptance policy hash required")
    if digest(Path(__file__)) != frozen.get("scorerCodeSha256") or digest(Path(__file__).resolve().parents[1] / "core/student_test_ocr_rules.py") != frozen.get("normalizerCodeSha256") or digest(Path(__file__).resolve().parents[1] / "core/student_test_formula_profiles.py") != frozen.get("routingCodeSha256"):
        raise ValueError("frozen scorer/normalizer changed; do not silently rescore")
    if run["split"] == "release_holdout" and run.get("releaseAccessApproved") is not True:
        raise ValueError("release holdout access needs separate approval")
    expected = {r["sampleId"]: r for r in frozen["samples"] if r["split"] == run["split"]}
    if not expected or len(predictions) != len(expected):
        raise ValueError("fixed denominator needs every slot exactly once")
    routes = {_route(row) for row in expected.values()}
    models = run.get("modelBindings", {})
    if set(models) != routes:
        raise ValueError("one model binding per actual question route required")
    for model in models.values():
        if not isinstance(model, dict) or any(not SHA.fullmatch(str(model.get(k, ""))) for k in ("checkpointSha256", "architectureSha256", "tokenizerSha256")):
            raise ValueError("checkpoint/architecture/tokenizer hashes required per route")
    seen, scored = set(), []
    for p in predictions:
        sid = p.get("sampleId")
        if sid not in expected or sid in seen:
            raise ValueError("unknown/duplicate prediction")
        seen.add(sid)
        target = expected[sid]
        if p.get("modelRoute") != _route(target) or p.get("modelSha256") != models[_route(target)]["checkpointSha256"]:
            raise ValueError("prediction used an unbound model/question route")
        if p.get("cropSha256") != target["cropSha256"] or type(p.get("autoAccepted")) is not bool or not isinstance(p.get("text"), str):
            raise ValueError("prediction crop/acceptance/text contract mismatch")
        failure = False
        if target["answerMode"] == "answer_value":
            tokens, eos = p.get("tokenCount"), p.get("eosSeen")
            if type(tokens) is not int or tokens < 0 or type(eos) is not bool:
                raise ValueError("formula tokenCount and reported EOS metadata required")
            failure = not (eos and 0 < tokens < MAX_FORMULA_TOKENS)
        got = normalize_recognized_answer(target["answerMode"], p["text"])
        truth = normalize_recognized_answer(target["answerMode"], target["transcription"])
        eligible = target["supportedTarget"] and not failure
        numeric = bool(eligible and (got == truth if target["answerMode"] == "choice_number" else answer_values_equivalent(got, truth)))
        exact = bool(target["legibility"] == "readable" and not failure and got and got == truth)
        scored.append({**target, "numeric": numeric, "text": exact, "generationFailure": failure,
            "accepted": p["autoAccepted"], "falseAccepted": p["autoAccepted"] and not numeric})
    if seen != set(expected):
        raise ValueError("missing predictions cannot leave the denominator")
    grouped = {}
    for row in scored:
        row["ocrRoute"] = _route(row)
    for field in ("studentGrade", "writerId", "expressionKind", "answerMode", "formulaProfile", "ocrRoute"):
        buckets = defaultdict(list)
        for row in scored:
            buckets[row[field]].append(row)
        grouped[field] = {key: _summary(rows) for key, rows in sorted(buckets.items())}
    photo_rows = defaultdict(list)
    for row in scored:
        photo_rows[row["photoId"]].append(row)
    sheet_counts = Counter()
    for rows in photo_rows.values():
        uncertain = sum(not r["accepted"] for r in rows)
        sheet_counts["allTwentySafelyAccepted"] += int(all(r["accepted"] and r["numeric"] for r in rows))
        sheet_counts["retakeFourOrMore"] += int(uncertain >= 4)
        sheet_counts["supplementOneToThree"] += int(1 <= uncertain <= 3)
    latency = run.get("latency")
    latency_report = {"status": "not_measured"}
    if latency is not None:
        if latency.get("scope") not in {"crop_inference_only", "photo_to_saved_grade"}:
            raise ValueError("latency scope must be explicit")
        measurements = latency.get("photoSeconds", {})
        if set(measurements) != set(photo_rows) or any(type(v) not in {int, float} or not math.isfinite(v) or v < 0 for v in measurements.values()):
            raise ValueError("one finite timing per photo required")
        values = sorted(measurements.values())
        latency_report = {"scope": latency["scope"], "photoCount": len(values),
            "p90Seconds": values[math.ceil(.9 * len(values)) - 1], "method": "nearest_rank",
            "limitation": "two captures of the same paper are correlated; small diagnostic, not release speed proof"}
    return {"schema": "student_test_camera_score_v1", "split": run["split"], **_summary(scored),
        "by": grouped, "firstPassPhotos": {"denominator": len(photo_rows), **dict(sheet_counts)},
        "pendingAfterRecapture": "not_measured_requires_actual_correction_trace", "latency": latency_report,
        "eosEvidence": "reported metadata bound by inference code hash; token IDs not independently reobserved",
        "frozenLabelsSha256": frozen_sha, "run": run, "providerCallCount": 0, "deploymentReady": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("freeze")
    command.add_argument("--intake", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = sub.add_parser("score-saved")
    for name in ("frozen", "predictions", "run", "output"):
        command.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze(args.intake, args.output)
    else:
        for path in (args.frozen, args.predictions, args.run):
            _ancestors(path)
        rows = [load_json(line) for line in args.predictions.read_text(encoding="utf-8").splitlines()]
        frozen = load_json(args.frozen.read_bytes())
        snapshot = Path(frozen["snapshotRoot"])
        _ancestors(snapshot)
        for ref in frozen["snapshotInventory"]:
            asset(snapshot, ref)
        result = score_saved(frozen, rows, load_json(args.run.read_bytes()), digest(args.frozen))
        for ref in frozen["snapshotInventory"]:
            asset(snapshot, ref)
        result["predictionSha256"] = digest(args.predictions)
        fresh_directory(args.output)
        (args.output / "REPORT.json").write_bytes(encoded(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
