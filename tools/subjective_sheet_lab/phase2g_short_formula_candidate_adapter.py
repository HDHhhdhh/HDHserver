from __future__ import annotations

import os
import socket
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Iterator, TypeAlias

from tools.subjective_sheet_lab.ocr_short_answer_policy import normalize_short_answer_candidate

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

FORMULA_MODEL_NAME: Final[str] = "PP-FormulaNet-S"
FORMULA_MODEL_SUBDIR: Final[Path] = Path("official_models") / FORMULA_MODEL_NAME
FORMULA_SOURCE: Final[str] = "local_pp_formulanet_s"
MIN_DISTINCT_VIEW_VOTES: Final[int] = 3


@dataclass(frozen=True, slots=True)
class FormulaCandidateSignal:
    view: str
    text: str


@dataclass(frozen=True, slots=True)
class FormulaCandidateDecision:
    candidate: str | None
    vote_count: int
    second_vote_count: int
    warning: str


class FormulaCandidateUnavailable(RuntimeError):
    pass


class OfflinePPFormulaNet:
    def __init__(self, model_dir: Path, *, device: str = "cpu") -> None:
        resolved = model_dir.resolve()
        if not resolved.is_dir():
            raise FormulaCandidateUnavailable(f"local formula model directory is missing: {resolved}")
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            with deny_external_network():
                from paddleocr import FormulaRecognition

                self._model = FormulaRecognition(
                    model_name=FORMULA_MODEL_NAME,
                    model_dir=str(resolved),
                    device=device,
                )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise FormulaCandidateUnavailable(str(exc)) from exc

    def recognize_views(self, views: Iterable[tuple[str, Any]]) -> tuple[FormulaCandidateSignal, ...]:
        signals: list[FormulaCandidateSignal] = []
        with deny_external_network():
            for view, image in views:
                try:
                    output = self._model.predict(input=image, batch_size=1)
                    texts = collect_formula_texts(output)
                except (OSError, RuntimeError, TypeError, ValueError):
                    continue
                signals.extend(FormulaCandidateSignal(view, text) for text in texts)
        return tuple(signals)


def formula_model_dir(cache_root: Path) -> Path:
    return cache_root.resolve() / FORMULA_MODEL_SUBDIR


def resolve_formula_candidate(
    signals: Iterable[FormulaCandidateSignal],
    *,
    blank_like: bool = False,
    visually_ambiguous: bool = False,
) -> FormulaCandidateDecision:
    if blank_like:
        return FormulaCandidateDecision(None, 0, 0, "blank_like")
    if visually_ambiguous:
        return FormulaCandidateDecision(None, 0, 0, "ambiguous_ink_groups")

    normalized_by_view: dict[str, str] = {}
    conflicting_views: set[str] = set()
    for signal in signals:
        candidate = normalize_short_answer_candidate(signal.text, "answer_value")
        if candidate is None:
            continue
        prior = normalized_by_view.get(signal.view)
        if prior is not None and prior != candidate:
            conflicting_views.add(signal.view)
            continue
        normalized_by_view[signal.view] = candidate
    for view in conflicting_views:
        normalized_by_view.pop(view, None)

    if not normalized_by_view:
        return FormulaCandidateDecision(None, 0, 0, "no_supported_formula_candidate")

    counts = Counter(normalized_by_view.values())
    ranked = counts.most_common()
    candidate, votes = ranked[0]
    second_votes = ranked[1][1] if len(ranked) > 1 else 0
    if votes < MIN_DISTINCT_VIEW_VOTES or second_votes >= 2 or votes <= second_votes:
        return FormulaCandidateDecision(None, votes, second_votes, "formula_candidate_disagreement")
    return FormulaCandidateDecision(candidate, votes, second_votes, "formula_variant_agreement")


def apply_formula_candidate(review_item: JsonObject, decision: FormulaCandidateDecision) -> JsonObject:
    item = dict(review_item)
    warnings = _string_list(item.get("warnings"))
    candidates = _candidate_list(item.get("candidates"))
    recognized = item.get("recognized") if isinstance(item.get("recognized"), str) else None

    if decision.candidate is not None:
        if recognized and normalize_short_answer_candidate(recognized, "answer_value") not in {None, decision.candidate}:
            warning = "formula_candidate_conflict"
            recognized = item.get("recognized")
        else:
            warning = decision.warning
            recognized = item.get("recognized")
            candidate_record: JsonObject = {
                "value": decision.candidate,
                "source": FORMULA_SOURCE,
                "confidence": "MEDIUM",
            }
            if candidate_record not in candidates:
                candidates.append(candidate_record)
    else:
        warning = decision.warning

    if warning not in warnings:
        warnings.append(warning)
    item.update(
        {
            "status": "review_required",
            "recognized": recognized,
            "candidates": candidates[:5],
            "warnings": warnings,
            "candidate_confidence": "MEDIUM" if decision.candidate is not None else "UNRESOLVED",
            "requires_confirmation": True,
            "allow_direct_input": not bool(candidates),
            "allow_manual_after_rejecting_candidates": True,
            "safe_auto_grade": False,
            "final_answer": None,
            "source": None,
        }
    )
    return item


def collect_formula_texts(value: Any) -> tuple[str, ...]:
    found: list[str] = []
    visited: set[int] = set()

    def append(text: Any) -> None:
        if not isinstance(text, str):
            return
        normalized = " ".join(text.split())
        if normalized and normalized not in found:
            found.append(normalized)

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (dict, list, tuple)):
            identity = id(item)
            if identity in visited:
                return
            visited.add(identity)
        if isinstance(item, dict):
            append(item.get("rec_formula"))
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)
            return
        json_value = getattr(item, "json", None)
        if callable(json_value):
            try:
                json_value = json_value()
            except (OSError, RuntimeError, TypeError, ValueError):
                json_value = None
        if json_value is not None and json_value is not item:
            visit(json_value)

    visit(value)
    return tuple(found)


@contextmanager
def deny_external_network() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked_connect(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("external_network_disabled_for_local_formula_ocr")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.create_connection = blocked_connect  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


def _string_list(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _candidate_list(value: JsonValue) -> list[JsonObject]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
