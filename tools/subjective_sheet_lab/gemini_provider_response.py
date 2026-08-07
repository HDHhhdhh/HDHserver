from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ResponseTextResult: TypeAlias = "ResponseText | ResponseShapeFailure"

BLOCKED_FINISH_REASONS: Final[frozenset[str]] = frozenset(("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"))


@dataclass(frozen=True, slots=True)
class ResponseText:
    text: str


@dataclass(frozen=True, slots=True)
class ResponseShapeFailure:
    reason: str
    message: str
    diagnostic: JsonObject


def response_text_result(response: JsonObject) -> ResponseTextResult:
    shape = response_shape(response)
    if shape.get("prompt_block_reason"):
        return response_failure("provider_response_blocked", "Gemini API response was blocked", shape)

    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return response_failure("provider_response_missing_candidates", "Gemini API response did not include candidates", shape)

    first = candidates[0]
    if not isinstance(first, dict):
        return response_failure("provider_response_malformed_candidate", "Gemini API candidate was not an object", shape)

    content = first.get("content")
    if not isinstance(content, dict):
        reason = blocked_or("provider_response_missing_content", shape)
        return response_failure(reason, "Gemini API candidate did not include content", shape)

    parts = content.get("parts")
    if not isinstance(parts, list):
        reason = blocked_or("provider_response_missing_parts", shape)
        return response_failure(reason, "Gemini API content did not include parts", shape)

    texts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    if not texts:
        reason = blocked_or("provider_response_missing_text", shape)
        return response_failure(reason, "Gemini API response did not include text", shape)
    return ResponseText(text="\n".join(texts))


def response_shape(response: JsonObject) -> JsonObject:
    candidates = response.get("candidates")
    shape: JsonObject = {"candidate_count": len(candidates) if isinstance(candidates, list) else 0}
    prompt_reason = prompt_block_reason(response)
    if prompt_reason:
        shape["prompt_block_reason"] = prompt_reason
    if not isinstance(candidates, list) or not candidates:
        return shape

    first = candidates[0]
    shape["first_candidate_is_object"] = isinstance(first, dict)
    if not isinstance(first, dict):
        return shape

    finish_reason = safe_token(first.get("finishReason"))
    if finish_reason:
        shape["finish_reason"] = finish_reason

    content = first.get("content")
    shape["content_present"] = isinstance(content, dict)
    if not isinstance(content, dict):
        return shape

    parts = content.get("parts")
    shape["parts_count"] = len(parts) if isinstance(parts, list) else 0
    if isinstance(parts, list):
        shape["text_part_count"] = sum(1 for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
    else:
        shape["text_part_count"] = 0
    return shape


def response_failure(reason: str, message: str, shape: JsonObject) -> ResponseShapeFailure:
    return ResponseShapeFailure(reason=reason, message=message, diagnostic=shape)


def blocked_or(default: str, shape: JsonObject) -> str:
    finish_reason = shape.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason in BLOCKED_FINISH_REASONS:
        return "provider_response_blocked"
    return default


def prompt_block_reason(response: JsonObject) -> str:
    prompt_feedback = response.get("promptFeedback")
    if not isinstance(prompt_feedback, dict):
        return ""
    return safe_token(prompt_feedback.get("blockReason"))


def safe_token(value: JsonValue) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(char for char in value.strip() if char.isalnum() or char in "_-")
    return cleaned[:80]
