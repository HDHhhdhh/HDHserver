from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_short_answer_policy import (  # noqa: E402
    normalize_short_answer_candidate,
    structural_symbol_count,
)


class VerificationError(Exception):
    pass


def main() -> int:
    verify_choice_policy()
    verify_supported_math()
    verify_unsupported_math()
    verify_symbol_count()
    print(
        json.dumps(
            {
                "ok": True,
                "provider_call_count": 0,
                "external_ocr_api_call_count": 0,
                "submit_test_call_count": 0,
                "student_facing": False,
                "production_default": "NO-GO",
            },
            indent=2,
        )
    )
    return 0


def verify_choice_policy() -> None:
    for value in ("1", "2", "3", "4", "5"):
        if normalize_short_answer_candidate(value, "choice_number") != value:
            raise VerificationError(f"valid choice was rejected: {value}")
    if normalize_short_answer_candidate("５", "choice_number") != "5":
        raise VerificationError("full-width choice normalization failed")
    for value in ("0", "6", "15", "1,2", "?", ""):
        if normalize_short_answer_candidate(value, "choice_number") is not None:
            raise VerificationError(f"invalid choice was accepted: {value!r}")


def verify_supported_math() -> None:
    cases = {
        "-2": "-2",
        "00.500": "0.5",
        "1/2": "1/2",
        r"\frac { 1 } { 2 }": "1/2",
        "√2+√3": "sqrt(2)+sqrt(3)",
        r"\sqrt{2}+\sqrt{3}": "sqrt(2)+sqrt(3)",
        r"\frac{1+\sqrt{2}}{2}": "(1+sqrt(2))/2",
        r"2\sqrt{3}": "2*sqrt(3)",
        r"\left(1+\sqrt{2}\right)/2": "(1+sqrt(2))/2",
    }
    for raw, expected in cases.items():
        actual = normalize_short_answer_candidate(raw, "answer_value")
        if actual != expected:
            raise VerificationError(f"math normalization failed: {raw!r} -> {actual!r}, expected {expected!r}")


def verify_unsupported_math() -> None:
    cases = (
        "x=2",
        "2,3",
        "1//2",
        "sqrt(x)",
        "sqrt(2)+sqrt(3)+sqrt(5)",
        "1/2+1/3",
        r"\int_0^1 x dx",
        r"\sqrt{1+2+3}",
        "C:\\server\\secret",
        "?",
        "",
    )
    for raw in cases:
        if normalize_short_answer_candidate(raw, "answer_value") is not None:
            raise VerificationError(f"unsupported math was accepted: {raw!r}")


def verify_symbol_count() -> None:
    if structural_symbol_count("1/2") != 3:
        raise VerificationError("fraction symbol count changed")
    if structural_symbol_count("sqrt(2)+sqrt(3)") != 5:
        raise VerificationError("radical symbol count changed")


if __name__ == "__main__":
    raise SystemExit(main())
