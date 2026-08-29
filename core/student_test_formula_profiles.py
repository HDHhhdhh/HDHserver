from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Mapping, Sequence

from core.student_test_ocr_rules import ANSWER_VALUE


FORMULA_PROFILE_COMMON: Final = "m3_h1"
FORMULA_PROFILE_UPPER: Final = "m3_h1_h2_h3"
FORMULA_PROFILE_DATASETS: Final = {
    FORMULA_PROFILE_COMMON: ("M_G3", "H_G1"),
    FORMULA_PROFILE_UPPER: ("M_G3", "H_G1", "H_G2", "H_G3"),
}

_COMMON_CURRICULA: Final = frozenset({"공통수학1", "공통수학2", "공수1", "공수2"})
_UPPER_CURRICULA: Final = frozenset(
    {"대수", "미적분1", "미적분2", "확통", "확률과통계", "확률통계", "기하"}
)


@dataclass(frozen=True, slots=True)
class FormulaProfileError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def normalize_formula_curriculum(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\s·_\-:]+", "", text)
    aliases = {
        "공통수학ii": "공통수학2",
        "공통수학i": "공통수학1",
        "미적분ii": "미적분2",
        "미적분i": "미적분1",
    }
    return aliases.get(text, text)


def formula_profile_for_curriculum(curriculum: object) -> str:
    normalized = normalize_formula_curriculum(curriculum)
    if normalized in _COMMON_CURRICULA:
        return FORMULA_PROFILE_COMMON
    if normalized in _UPPER_CURRICULA:
        return FORMULA_PROFILE_UPPER
    raise FormulaProfileError(
        "unsupported_formula_curriculum",
        "subjective OCR is not configured for this test curriculum",
    )


def formula_profile_for_test(
    test: Mapping[str, object],
    answer_modes: Sequence[object],
) -> str | None:
    if ANSWER_VALUE not in answer_modes:
        return None
    return formula_profile_for_curriculum(test.get("curriculum"))


def formula_profile_datasets(profile: object) -> tuple[str, ...]:
    normalized = str(profile or "").strip()
    datasets = FORMULA_PROFILE_DATASETS.get(normalized)
    if datasets is None:
        raise FormulaProfileError("invalid_formula_profile", "subjective OCR data profile is invalid")
    return datasets
