from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

TARGET_QUESTIONS: Final[tuple[int, int]] = (16, 17)


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    question_no: int
    recognized: str
    status: str
    warnings: tuple[str, ...]
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class BatchArtifact:
    question_no: int
    artifact_file: str
    enlarged_width: int
    enlarged_height: int
    status: str
    provider_call_count: int


@dataclass(frozen=True, slots=True)
class RequestItem:
    question_no: int
    current_recognized: str
    current_status: str
    warnings: tuple[str, ...]
    artifact_file: str
    enlarged_width: int
    enlarged_height: int
    request_scope: str
    action: str
    auto_confirm_allowed: bool


@dataclass(frozen=True, slots=True)
class RequestManifest:
    source_payload_name: str
    source_batch_name: str
    items: tuple[RequestItem, ...]


@dataclass(frozen=True, slots=True)
class RequestSources:
    manifest: JsonObject
    batch: JsonObject
    source_batch_name: str
    artifact_dir: Path


@dataclass(frozen=True, slots=True)
class BatchRequestManifestError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def build_request_manifest(sources: RequestSources) -> RequestManifest:
    return RequestManifest(
        source_payload_name=require_text(sources.manifest.get("payload_name"), "payload_name"),
        source_batch_name=sources.source_batch_name,
        items=request_items(review_candidates(sources.manifest), batch_artifacts(sources.batch, sources.artifact_dir)),
    )


def review_candidates(payload: JsonObject) -> tuple[ReviewCandidate, ...]:
    raw_candidates = require_list(payload.get("candidates"), "candidates")
    return tuple(parse_review_candidate(raw_candidate) for raw_candidate in raw_candidates)


def parse_review_candidate(raw_candidate: JsonValue) -> ReviewCandidate:
    candidate = require_object(raw_candidate, "candidates[]")
    return ReviewCandidate(
        question_no=require_int(candidate.get("question_no"), "candidate.question_no"),
        recognized=require_text(candidate.get("recognized"), "candidate.recognized"),
        status=require_text(candidate.get("status"), "candidate.status"),
        warnings=require_text_tuple(candidate.get("warnings"), "candidate.warnings"),
        auto_confirm_allowed=require_bool(candidate.get("auto_confirm_allowed"), "candidate.auto_confirm_allowed"),
    )


def batch_artifacts(payload: JsonObject, artifact_dir: Path) -> tuple[BatchArtifact, ...]:
    raw_candidates = require_list(payload.get("candidates"), "batch.candidates")
    return tuple(parse_batch_artifact(raw_candidate, artifact_dir) for raw_candidate in raw_candidates)


def parse_batch_artifact(raw_candidate: JsonValue, artifact_dir: Path) -> BatchArtifact:
    candidate = require_object(raw_candidate, "batch.candidates[]")
    artifact_file = require_text(candidate.get("artifact_file"), "batch.artifact_file")
    if "/" in artifact_file or "\\" in artifact_file:
        raise BatchRequestManifestError("artifact_file must be a filename, not a path")
    artifact_path = artifact_dir / artifact_file
    if not artifact_path.is_file():
        raise BatchRequestManifestError(f"artifact file is missing: {artifact_file}")
    return BatchArtifact(
        question_no=require_int(candidate.get("question_no"), "batch.question_no"),
        artifact_file=artifact_file,
        enlarged_width=require_int(candidate.get("enlarged_width"), "batch.enlarged_width"),
        enlarged_height=require_int(candidate.get("enlarged_height"), "batch.enlarged_height"),
        status=require_text(candidate.get("status"), "batch.status"),
        provider_call_count=require_int(candidate.get("provider_call_count"), "batch.provider_call_count"),
    )


def request_items(candidates: tuple[ReviewCandidate, ...], artifacts: tuple[BatchArtifact, ...]) -> tuple[RequestItem, ...]:
    if len(candidates) != len(artifacts):
        raise BatchRequestManifestError("review candidate count must match batch artifact count")
    artifact_by_question = {artifact.question_no: artifact for artifact in artifacts}
    items: list[RequestItem] = []
    for candidate in candidates:
        artifact = artifact_by_question.get(candidate.question_no)
        if artifact is None:
            raise BatchRequestManifestError(f"artifact missing for q{candidate.question_no:03d}")
        items.append(request_item(candidate, artifact))
    return tuple(items)


def request_item(candidate: ReviewCandidate, artifact: BatchArtifact) -> RequestItem:
    if candidate.question_no != artifact.question_no:
        raise BatchRequestManifestError("candidate/artifact question mismatch")
    if artifact.status != "USER_APPROVAL_REQUIRED":
        raise BatchRequestManifestError("batch artifact must require user approval")
    if artifact.provider_call_count != 0:
        raise BatchRequestManifestError("batch artifact provider call count must be 0")
    return RequestItem(
        question_no=candidate.question_no,
        current_recognized=candidate.recognized,
        current_status=candidate.status,
        warnings=candidate.warnings,
        artifact_file=artifact.artifact_file,
        enlarged_width=artifact.enlarged_width,
        enlarged_height=artifact.enlarged_height,
        request_scope="single_enlarged_crop",
        action="USER_APPROVAL_REQUIRED",
        auto_confirm_allowed=False,
    )


def assert_request(request: RequestManifest) -> None:
    if [item.question_no for item in request.items] != list(TARGET_QUESTIONS):
        raise BatchRequestManifestError("batch request must contain q016 and q017 only")
    if any(item.auto_confirm_allowed for item in request.items):
        raise BatchRequestManifestError("batch request must not auto-confirm")
    if any(item.current_status != "review_required" for item in request.items):
        raise BatchRequestManifestError("batch request items must come from review_required payload items")


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8")), path.name)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise BatchRequestManifestError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise BatchRequestManifestError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise BatchRequestManifestError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_bool(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise BatchRequestManifestError(f"{label} must be a boolean")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            raise BatchRequestManifestError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    raw_values = require_list(value, label)
    return tuple(require_text(raw_value, f"{label}[]") for raw_value in raw_values)
