from __future__ import annotations

import re
from typing import Final

ARROW_TOKENS: Final[tuple[str, ...]] = ("\u2192", "->", "=>", "\u21a6")
RELATION_OPERATOR_TOKENS: Final[tuple[str, ...]] = (
    "<=",
    ">=",
    "->",
    "=>",
    "\u2192",
    "\u21a6",
    "=",
    "<",
    ">",
)
RELATION_OPERATOR_WARNING_NAMES: Final[frozenset[str]] = frozenset(
    {
        "arrow_equal_confusion",
        "relation_symbol_confusion",
        "expression_operator_confusion",
    },
)

TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    "|".join(re.escape(token) for token in sorted(RELATION_OPERATOR_TOKENS, key=len, reverse=True)),
)


def relation_ambiguity_warnings(left: str, right: str) -> tuple[str, ...]:
    left_tokens = relation_tokens(left)
    right_tokens = relation_tokens(right)
    if not left_tokens or not right_tokens or left_tokens == right_tokens:
        return ()
    if relation_skeleton(left) != relation_skeleton(right):
        return ()
    warnings: list[str] = []
    if arrow_equals_confusion(left_tokens, right_tokens):
        warnings.append("arrow_equal_confusion")
    warnings.extend(("relation_symbol_confusion", "expression_operator_confusion"))
    return tuple(dict.fromkeys(warnings))


def any_relation_ambiguity_warnings(*answers: str) -> tuple[str, ...]:
    warnings: list[str] = []
    for index, left in enumerate(answers):
        for right in answers[index + 1 :]:
            warnings.extend(relation_ambiguity_warnings(left, right))
    return tuple(dict.fromkeys(warnings))


def has_relation_or_operator(value: str) -> bool:
    return TOKEN_RE.search(compact(value)) is not None


def relation_tokens(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in TOKEN_RE.finditer(compact(value)))


def relation_skeleton(value: str) -> str:
    return TOKEN_RE.sub("#", compact(value))


def arrow_equals_confusion(left_tokens: tuple[str, ...], right_tokens: tuple[str, ...]) -> bool:
    left = frozenset(left_tokens)
    right = frozenset(right_tokens)
    return (bool(left & frozenset(ARROW_TOKENS)) and "=" in right) or (bool(right & frozenset(ARROW_TOKENS)) and "=" in left)


def compact(value: str) -> str:
    return "".join(value.split()).lower()
