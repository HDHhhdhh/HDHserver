"""Offline, transcription-preserving selection; NOT an answer normalizer or grader."""
from __future__ import annotations

import re

from core.student_test_ocr_rules import OcrRuleError, numeric_answer_value

TOKEN = re.compile(r"\\[A-Za-z]+|\d+(?:\.\d+)?|[a-zA-Z]|[+*/^=(){}\[\]-]")
COMMANDS = {r"\frac", r"\sqrt", r"\times", r"\cdot", r"\div", r"\pi"}


def focused_label(label: str) -> bool:
    # Aliases affect selection only. The original image transcription is retained.
    if re.search(r"\d\s+\d", label):
        return False
    probe = label.replace(r"\times", "*").replace(r"\cdot", "*").replace(r"\div", "/")
    probe = re.sub(r"\\sqrt\s*\[\s*2\s*\]", r"\\sqrt", probe)
    try:
        numeric_answer_value(probe)
        return True
    except OcrRuleError:
        return False


class FormulaSyntax:
    """Small complete-expression recognizer, never evaluates or rewrites a label."""

    def __init__(self, label: str):
        text = label.strip()
        if text.startswith("$") and text.endswith("$") and len(text) > 2:
            text = text[1:-1]
        text = text.replace(r"\left", "").replace(r"\right", "")
        for spacing in (r"\,", r"\;", r"\!", r"\ "):
            text = text.replace(spacing, " ")
        if not text or len(text) > 120:
            raise ValueError("length")
        if re.search(r"[A-Za-z]{2,}", re.sub(r"\\[A-Za-z]+", "", text)):
            raise ValueError("ambiguous bare word or function name")
        self.tokens = []
        at = 0
        while at < len(text):
            if text[at].isspace():
                at += 1
                continue
            match = TOKEN.match(text, at)
            if match is None:
                raise ValueError("unsupported character")
            value = match.group()
            if value.startswith("\\") and value not in COMMANDS:
                raise ValueError("unsupported command")
            self.tokens.append(value)
            at = match.end()
        if not self.tokens or len(self.tokens) > 80:
            raise ValueError("token length")
        self.at = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def take(self, value):
        if self.peek() != value:
            raise ValueError("missing operand or delimiter")
        self.at += 1

    @staticmethod
    def atom_start(token):
        return token is not None and (token in {"(", "{", r"\frac", r"\sqrt", r"\pi"}
                                      or bool(re.fullmatch(r"[A-Za-z]|\d+(?:\.\d+)?", token)))

    def expression(self):
        self.term()
        while self.peek() in {"+", "-"}:
            self.at += 1
            self.term()

    def term(self):
        self.power()
        while True:
            if self.peek() in {"*", "/", r"\times", r"\cdot", r"\div"}:
                self.at += 1
                self.power()
            elif self.atom_start(self.peek()):
                # Do not silently join spaced digit strings such as "1 2".
                if self.tokens[self.at - 1][0].isdigit() and self.peek()[0].isdigit():
                    raise ValueError("adjacent numbers")
                self.power()
            else:
                return

    def power(self):
        if self.peek() in {"+", "-"}:
            self.at += 1
        self.atom()
        if self.peek() == "^":
            self.at += 1
            self.atom()

    def group(self, opening, closing):
        self.take(opening)
        self.expression()
        self.take(closing)

    def atom(self):
        self.depth += 1
        if self.depth > 16:
            raise ValueError("nesting")
        token = self.peek()
        if token == "(":
            self.group("(", ")")
        elif token == "{":
            self.group("{", "}")
        elif token == r"\frac":
            self.at += 1
            self.group("{", "}")
            self.group("{", "}")
        elif token == r"\sqrt":
            self.at += 1
            if self.peek() == "[":
                self.at += 1
                if self.peek() not in {"2", "3", "4"}:
                    raise ValueError("unsupported root index")
                self.at += 1
                self.take("]")
            self.group("{", "}")
        elif token == r"\pi" or (token and re.fullmatch(r"[A-Za-z]|\d+(?:\.\d+)?", token)):
            self.at += 1
        else:
            raise ValueError("missing atom")
        self.depth -= 1

    def complete(self):
        if not any(token[0].isdigit() for token in self.tokens):
            raise ValueError("no numeric glyph")
        self.expression()
        if self.peek() == "=":
            self.at += 1
            self.expression()
        if self.peek() is not None:
            raise ValueError("incomplete or unsupported formula")


def selection_kind(label: str) -> str | None:
    if focused_label(label):
        return "focused"
    try:
        FormulaSyntax(label).complete()
        return "auxiliary"
    except (ValueError, RecursionError):
        return None
