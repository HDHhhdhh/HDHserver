from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Sequence


_NUMBER_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:문항\s*)?\(?\s*\d{1,3}\s*\)?\s*[\.\):：-]\s*"
)
_INLINE_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<=^)|(?<=\s))(?:문항\s*)?\(?\s*\d{1,3}\s*\)?\s*[\.\):：]\s*"
)
_ANSWER_LABEL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:답|정답|answer|ans)\s*[:：]?\s*",
    re.IGNORECASE,
)
_NON_ANSWER_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:synthetic\s+ocr\s+answer\s+sheet|ocr\s+answer\s+sheet|answer\s+sheet|답안|답안지)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    confidence: float | None = None


def extract_answers_text_from_ocr_lines(lines: Sequence[OcrLine]) -> str:
    answers: list[str] = []
    seen_answers: set[str] = set()
    for line in lines:
        text = normalize_ocr_text(line.text)
        if not text or _is_non_answer_line(text):
            continue
        for part in _split_inline_numbered_answers(text):
            answer = _strip_answer_prefix(part)
            if answer and answer not in seen_answers and not _is_non_answer_line(answer):
                seen_answers.add(answer)
                answers.append(answer)
    return "\n".join(answers)


def has_numbered_answer_marker(lines: Sequence[OcrLine]) -> bool:
    return any(_NUMBER_PREFIX_RE.search(line.text) or _INLINE_NUMBER_RE.search(line.text) for line in lines)


def normalize_ocr_text(text: str) -> str:
    normalized = str(text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("−", "-").replace("－", "-").replace("–", "-")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _split_inline_numbered_answers(text: str) -> list[str]:
    markers = list(_INLINE_NUMBER_RE.finditer(text))
    if len(markers) < 2:
        return [text]

    parts: list[str] = []
    for idx, marker in enumerate(markers):
        start = marker.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        part = text[start:end].strip()
        if part:
            parts.append(part)
    return parts or [text]


def _strip_answer_prefix(text: str) -> str:
    cleaned = _ANSWER_LABEL_RE.sub("", text.strip())
    cleaned = _NUMBER_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.strip(" \t:：")
    return cleaned


def _is_non_answer_line(text: str) -> bool:
    return bool(_NON_ANSWER_LINE_RE.fullmatch(text.strip()))
