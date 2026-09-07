"""Separate installed OCR assets from reviewed deployment evidence. No runtime writes."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Mapping

READINESS_SCHEMA = "student_test_ocr_deployment_evidence_v1"
UNIMERNET_ASSETS = ("config.json", "preprocessor_config.json", "tokenizer_config.json", "tokenizer.json")


@lru_cache(maxsize=128)
def _cached_digest(path: str, signature: tuple[int, int, int, int]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_sha256(path: Path) -> str:
    resolved = path.resolve()
    before = resolved.stat()
    signature = (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
    result = _cached_digest(str(resolved), signature)
    after = resolved.stat()
    if signature != (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino):
        raise ValueError("OCR artifact changed during verification")
    return result


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def deployment_evidence_reasons(
    evidence_path: Path,
    *,
    artifacts: Mapping[str, Path],
    policy: Mapping[str, object],
    profiles: tuple[str, ...],
) -> list[str]:
    """A training receipt or a legacy crop diagnostic cannot authorize deployment.

    This checks the review artifact's contract, not the truth of its attestations.
    Independent collection/review remains a human-owned release gate.
    """
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return ["deployment_evidence_missing_or_unreadable"]
    if not isinstance(evidence, dict) or evidence.get("schema") != READINESS_SCHEMA:
        return ["deployment_evidence_schema_invalid"]
    reasons: list[str] = []
    if evidence.get("status") != "GO" or evidence.get("evidenceClass") != "independent_v4_camera_holdout":
        reasons.append("independent_camera_holdout_not_approved")
    if evidence.get("policy") != dict(policy):
        reasons.append("evaluated_policy_changed")
    holdout = evidence.get("holdout")
    required = ("writerDisjoint", "labelsCheckedAgainstImages", "lockedBeforeEvaluation", "notUsedForTuning", "writerClusterReviewPassed")
    if not isinstance(holdout, dict) or any(holdout.get(key) is not True for key in required):
        reasons.append("holdout_independence_unverified")
    if isinstance(holdout, dict):
        digest = holdout.get("manifestSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            reasons.append("holdout_manifest_unbound")
    route_metrics = evidence.get("routes")
    if not isinstance(route_metrics, dict) or set(route_metrics) != {"choice", *profiles}:
        reasons.append("route_evidence_incomplete")
    else:
        for route, metrics in route_metrics.items():
            if not isinstance(metrics, dict):
                reasons.append(f"route_evidence_invalid:{route}")
                continue
            evaluated, accepted, wrong = (metrics.get(key) for key in ("evaluated", "accepted", "wrongAccepted"))
            if (any(type(x) is not int for x in (evaluated, accepted, wrong))
                    or not 299 <= accepted <= evaluated or wrong != 0
                    or (route == "choice" and accepted / evaluated < 0.98)):
                reasons.append(f"route_quality_not_met:{route}")
            if route == "choice":
                rejects, rejected = metrics.get("rejectEvaluated"), metrics.get("rejectCorrect")
                counts = metrics.get("perChoiceClass")
                if (type(rejects) is not int or type(rejected) is not int or rejects < 20
                        or not 0 <= rejected <= rejects or rejected / rejects < 0.98
                        or not isinstance(counts, dict) or set(counts) != set("12345")
                        or any(type(n) is not int or n < 20 for n in counts.values())):
                    reasons.append("choice_reject_or_class_coverage_not_met")
            elif not isinstance(metrics.get("kinds"), dict) or any(
                type(metrics["kinds"].get(kind)) is not int or metrics["kinds"][kind] < 1
                for kind in ("number", "fraction", "root")
            ):
                reasons.append(f"formula_type_coverage_missing:{route}")
    sheet = evidence.get("sheetMetrics")
    limits = {"p90Seconds": (0, 30), "firstCaptureSuccessRate": (0.90, 1), "fullRetakeRate": (0, 0.05), "pendingRate": (0, 0.02)}
    if not isinstance(sheet, dict) or any(
        _number(sheet.get(key)) is None or not low <= sheet[key] <= high
        for key, (low, high) in limits.items()
    ):
        reasons.append("sheet_quality_or_latency_unverified")
    recorded = evidence.get("artifactSha256")
    if not isinstance(recorded, dict) or set(recorded) != set(artifacts):
        reasons.append("artifact_evidence_incomplete")
    elif not reasons:
        for name, path in artifacts.items():
            try:
                if recorded[name] != artifact_sha256(path):
                    reasons.append(f"artifact_changed:{name}")
            except (OSError, ValueError):
                reasons.append(f"artifact_unavailable:{name}")
    return reasons
