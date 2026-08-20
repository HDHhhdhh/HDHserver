from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from core.test_answer_modes import ANSWER_VALUE, CHOICE_NUMBER


CHOICE_VALUES: Final[frozenset[str]] = frozenset({"1", "2", "3", "4", "5"})
MAX_INPUT_LENGTH: Final[int] = 96
MAX_ADDITIVE_OPERATORS: Final[int] = 1
MAX_FRACTIONS: Final[int] = 1
MAX_RADICALS: Final[int] = 2
MAX_MULTIPLICATIONS: Final[int] = 2
MAX_NUMBERS: Final[int] = 4
MAX_GROUP_DEPTH: Final[int] = 4

_FULLWIDTH_TRANSLATION: Final[dict[int, str]] = str.maketrans(
    "０１２３４５６７８９＋－−×÷／（）｛｝",
    "0123456789+--*//(){}",
)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"\\frac|\\sqrt|\\cdot|\d+(?:\.\d+)?|[+\-*/(){}]"
)
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")
_UNICODE_SQRT_GROUP_RE: Final[re.Pattern[str]] = re.compile(r"√\(([^()]*)\)")
_UNICODE_SQRT_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"√(\d+(?:\.\d+)?)")
_ASCII_SQRT_GROUP_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![A-Za-z\\])sqrt\(([^()]*)\)"
)


@dataclass(frozen=True, slots=True)
class _ExpressionNode:
    kind: str
    value: str = ""
    left: "_ExpressionNode | None" = None
    right: "_ExpressionNode | None" = None


class _UnsupportedExpression(ValueError):
    pass


class _ShortExpressionParser:
    def __init__(self, tokens: tuple[str, ...]) -> None:
        self.tokens = tokens
        self.index = 0
        self.additive_operators = 0
        self.fractions = 0
        self.radicals = 0
        self.multiplications = 0
        self.numbers = 0
        self.group_depth = 0

    def parse(self) -> _ExpressionNode:
        if not self.tokens:
            raise _UnsupportedExpression("empty_expression")
        node = self._parse_expression()
        if self.index != len(self.tokens):
            raise _UnsupportedExpression("trailing_tokens")
        return node

    def _parse_expression(self) -> _ExpressionNode:
        node = self._parse_product()
        while self._peek() in {"+", "-"}:
            operator = self._take()
            self.additive_operators += 1
            if self.additive_operators > MAX_ADDITIVE_OPERATORS:
                raise _UnsupportedExpression("too_many_terms")
            node = _ExpressionNode(
                "add" if operator == "+" else "sub",
                left=node,
                right=self._parse_product(),
            )
        return node

    def _parse_product(self) -> _ExpressionNode:
        node = self._parse_factor()
        while True:
            token = self._peek()
            if token == "/":
                self._take()
                self.fractions += 1
                if self.fractions > MAX_FRACTIONS:
                    raise _UnsupportedExpression("too_many_fractions")
                node = _ExpressionNode("frac", left=node, right=self._parse_factor())
                continue
            if token in {"*", "\\cdot"}:
                self._take()
                node = self._multiply(node, self._parse_factor())
                continue
            if self._starts_factor(token):
                node = self._multiply(node, self._parse_factor())
                continue
            return node

    def _parse_factor(self) -> _ExpressionNode:
        token = self._peek()
        if token in {"+", "-"}:
            operator = self._take()
            child = self._parse_factor()
            return child if operator == "+" else _ExpressionNode("neg", left=child)
        if token is not None and _NUMBER_RE.fullmatch(token):
            self._take()
            self.numbers += 1
            if self.numbers > MAX_NUMBERS:
                raise _UnsupportedExpression("too_many_numbers")
            return _ExpressionNode("number", value=_normalize_number(token))
        if token == "\\sqrt":
            self._take()
            self.radicals += 1
            if self.radicals > MAX_RADICALS:
                raise _UnsupportedExpression("too_many_radicals")
            return _ExpressionNode("sqrt", left=self._parse_group(require_braces=False))
        if token == "\\frac":
            self._take()
            self.fractions += 1
            if self.fractions > MAX_FRACTIONS:
                raise _UnsupportedExpression("too_many_fractions")
            numerator = self._parse_group(require_braces=True)
            denominator = self._parse_group(require_braces=True)
            return _ExpressionNode("frac", left=numerator, right=denominator)
        if token == "(":
            return self._parse_group(require_braces=False)
        raise _UnsupportedExpression("factor_expected")

    def _parse_group(self, *, require_braces: bool) -> _ExpressionNode:
        opening = self._peek()
        if require_braces:
            if opening != "{":
                raise _UnsupportedExpression("brace_group_expected")
        elif opening not in {"{", "("}:
            raise _UnsupportedExpression("group_expected")
        self._take()
        closing = "}" if opening == "{" else ")"
        self.group_depth += 1
        if self.group_depth > MAX_GROUP_DEPTH:
            raise _UnsupportedExpression("group_too_deep")
        try:
            node = self._parse_expression()
            if self._take() != closing:
                raise _UnsupportedExpression("group_not_closed")
            return node
        finally:
            self.group_depth -= 1

    def _multiply(self, left: _ExpressionNode, right: _ExpressionNode) -> _ExpressionNode:
        self.multiplications += 1
        if self.multiplications > MAX_MULTIPLICATIONS:
            raise _UnsupportedExpression("too_many_multiplications")
        return _ExpressionNode("mul", left=left, right=right)

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise _UnsupportedExpression("unexpected_end")
        self.index += 1
        return token

    @staticmethod
    def _starts_factor(token: str | None) -> bool:
        return token in {"\\sqrt", "\\frac", "("} or bool(
            token and _NUMBER_RE.fullmatch(token)
        )


def normalize_short_answer(value: object, answer_mode: str) -> str | None:
    if not isinstance(value, str):
        return None
    compact = _prepare_expression(value)
    if not compact:
        return None
    if answer_mode == CHOICE_NUMBER:
        return compact if compact in CHOICE_VALUES else None
    if answer_mode != ANSWER_VALUE:
        return None
    tokens = _tokenize(compact)
    if tokens is None:
        return None
    try:
        node = _ShortExpressionParser(tokens).parse()
    except _UnsupportedExpression:
        return None
    return _render(node)


def is_supported_short_answer(value: object, answer_mode: str) -> bool:
    return normalize_short_answer(value, answer_mode) is not None


def _prepare_expression(value: str) -> str:
    compact = value.strip().translate(_FULLWIDTH_TRANSLATION)
    if not compact or len(compact) > MAX_INPUT_LENGTH:
        return ""
    for left, right in (("\\(", "\\)"), ("\\[", "\\]"), ("$", "$")):
        if compact.startswith(left) and compact.endswith(right) and len(compact) > len(left) + len(right):
            compact = compact[len(left) : -len(right)]
            break
    compact = re.sub(r"\\(?:left|right|displaystyle)", "", compact)
    compact = re.sub(r"\\(?:,|!|;|:|quad|qquad)", "", compact)
    compact = compact.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    compact = compact.replace("\\times", "*").replace("×", "*").replace("÷", "/")
    compact = _UNICODE_SQRT_GROUP_RE.sub(r"\\sqrt{\1}", compact)
    compact = _UNICODE_SQRT_NUMBER_RE.sub(r"\\sqrt{\1}", compact)
    compact = _ASCII_SQRT_GROUP_RE.sub(r"\\sqrt{\1}", compact)
    return "".join(char for char in compact if not char.isspace())


def _tokenize(value: str) -> tuple[str, ...] | None:
    tokens: list[str] = []
    cursor = 0
    while cursor < len(value):
        matched = _TOKEN_RE.match(value, cursor)
        if matched is None:
            return None
        tokens.append(matched.group(0))
        cursor = matched.end()
    return tuple(tokens)


def _normalize_number(value: str) -> str:
    integer, separator, fractional = value.partition(".")
    integer = integer.lstrip("0") or "0"
    if not separator:
        return integer
    fractional = fractional.rstrip("0")
    return f"{integer}.{fractional}" if fractional else integer


def _render(node: _ExpressionNode, parent_precedence: int = 0) -> str:
    precedence = {
        "add": 1,
        "sub": 1,
        "mul": 2,
        "frac": 2,
        "neg": 3,
        "sqrt": 4,
        "number": 4,
    }[node.kind]
    if node.kind == "number":
        rendered = node.value
    elif node.kind == "sqrt":
        rendered = f"sqrt({_render(_required(node.left))})"
    elif node.kind == "neg":
        rendered = f"-{_render(_required(node.left), precedence)}"
    elif node.kind in {"add", "sub", "mul"}:
        operator = {"add": "+", "sub": "-", "mul": "*"}[node.kind]
        left = _render(_required(node.left), precedence)
        right_precedence = precedence + 1 if node.kind == "sub" else precedence
        right = _render(_required(node.right), right_precedence)
        rendered = f"{left}{operator}{right}"
    elif node.kind == "frac":
        left_node = _required(node.left)
        right_node = _required(node.right)
        left = _render(left_node)
        right = _render(right_node)
        if left_node.kind in {"add", "sub"}:
            left = f"({left})"
        if right_node.kind in {"add", "sub", "frac"}:
            right = f"({right})"
        rendered = f"{left}/{right}"
    else:
        raise _UnsupportedExpression("unknown_node")
    return f"({rendered})" if precedence < parent_precedence else rendered


def _required(node: _ExpressionNode | None) -> _ExpressionNode:
    if node is None:
        raise _UnsupportedExpression("missing_node")
    return node
