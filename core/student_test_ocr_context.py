"""Pure, round-scoped OCR/grading contract; never sent to recognition workers."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping

from core.student_test_formula_profiles import formula_profile_for_test
from core.student_test_ocr_eligibility import find_test_definition
from core.student_test_ocr_rules import validate_test_answer_contract

CONTEXT_PREFIX = "test-v1:"


def test_context(config: Mapping[str, object], test_id: str, round_no: str) -> dict:
    definition = find_test_definition(config, test_id)
    test = definition["test"]
    contract = validate_test_answer_contract(
        category=definition["categoryKey"], test=test, round_no=round_no,
    )
    profile = formula_profile_for_test(test, contract["answerModes"])
    snapshot = {
        "testId": str(test_id), "round": str(round_no),
        "category": definition["categoryKey"], "problemCount": 20,
        "answerModes": list(contract["answerModes"]),
        "answerKeys": list(contract["answerKeys"]), "formulaProfile": profile,
    }
    encoded = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**contract, "formulaProfile": profile,
            "revision": CONTEXT_PREFIX + hashlib.sha256(encoded).hexdigest()}
