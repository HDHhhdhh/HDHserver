from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.network_access import strip_tests_config_answer_links
from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE, CHOICE_NUMBER, answer_modes_for_round


def verify_answer_mode_schema() -> None:
    test = {
        "problems": 3,
        "round": "2",
        "answerModes": {"1": [CHOICE_NUMBER] * 3, "2": [ANSWER_VALUE, CHOICE_NUMBER, "manual_review"]},
    }
    assert answer_modes_for_round(test, 3, 2) == [ANSWER_VALUE, CHOICE_NUMBER, "manual_review"]
    assert answer_modes_for_round(test, 3, 1) == [CHOICE_NUMBER] * 3


def verify_public_projection() -> None:
    config = {
        "categories": {
            "UNIT": {
                "tests": [{
                    "id": "t1",
                    "answerKey": ["1", "2"],
                    "answerKeys": {"1": ["1", "2"]},
                    "answerUrl": "secret",
                    "answerModes": {"1": [CHOICE_NUMBER, ANSWER_VALUE]},
                }],
            },
        },
    }
    public = strip_tests_config_answer_links(config)
    test = public["categories"]["UNIT"]["tests"][0]
    assert test["answerModes"] == {"1": [CHOICE_NUMBER, ANSWER_VALUE]}
    assert "answerKey" not in test and "answerKeys" not in test and "answerUrl" not in test


def verify_short_answers() -> None:
    equivalents = [
        ("1/2", "\\frac{1}{2}", "1/2"),
        ("2√3-√2", r"2\sqrt{3}-\sqrt{2}", "2*sqrt(3)-sqrt(2)"),
        ("０.５０", "0.5", "0.5"),
    ]
    for left, right, expected in equivalents:
        assert normalize_short_answer(left, ANSWER_VALUE) == expected
        assert normalize_short_answer(right, ANSWER_VALUE) == expected
    for unsupported in ("x=2", "1+2+3", "1/2/3", "√2+√3+√5"):
        assert normalize_short_answer(unsupported, ANSWER_VALUE) is None
    assert normalize_short_answer("5", CHOICE_NUMBER) == "5"
    assert normalize_short_answer("6", CHOICE_NUMBER) is None


def verify_test_management_ui() -> None:
    tests_js = (ROOT / "static/js/tests.js").read_text(encoding="utf-8")
    tests_html = (ROOT / "static/tests.html").read_text(encoding="utf-8")
    for snippet in (
        "const ANSWER_MODE_OPTIONS = [",
        "function renderAnswerModeEditor(",
        "#cfgAnswerModes select[data-question-no]",
        "test.answerModes = { ...existingAnswerModes, [round]: answerModes }",
    ):
        assert snippet in tests_js, snippet
    for snippet in (
        'id="cfgAnswerModeSummary"',
        'id="cfgAnswerModes"',
        "body.admin.tests-page .answer-mode-grid",
    ):
        assert snippet in tests_html, snippet

def verify_migration_preview() -> None:
    with tempfile.TemporaryDirectory(prefix="test_answer_modes_") as tmp_dir:
        tmp = Path(tmp_dir)
        config_path = tmp / "tests-config.json"
        evidence_path = tmp / "evidence.json"
        output_path = tmp / "preview.json"
        config = {
            "categories": {
                "UNIT": {
                    "tests": [
                        {
                            "id": f"source_r{round_no}",
                            "sourceId": "source",
                            "round": round_no,
                            "problems": 20,
                            "unknownField": {"keep": True},
                        }
                        for round_no in ("1", "2", "3")
                    ],
                },
            },
        }
        evidence = [
            {"sourceId": "source", "round": round_no, "modes": [CHOICE_NUMBER, ANSWER_VALUE] * 10}
            for round_no in ("1", "2", "3")
        ]
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "apply_unit_test_answer_modes.py"),
                "--config",
                str(config_path),
                "--evidence",
                str(evidence_path),
                "--output",
                str(output_path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        preview = json.loads(output_path.read_text(encoding="utf-8"))
        tests = preview["categories"]["UNIT"]["tests"]
        assert all(test["unknownField"] == {"keep": True} for test in tests)
        assert all(test["answerModes"][test["round"]] == [CHOICE_NUMBER, ANSWER_VALUE] * 10 for test in tests)


def main() -> int:
    verify_answer_mode_schema()
    verify_public_projection()
    verify_short_answers()
    verify_test_management_ui()
    verify_migration_preview()
    print("test answer modes: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
