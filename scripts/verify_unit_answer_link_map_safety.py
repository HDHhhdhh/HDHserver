from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_unit_test_answer_link_map_from_gdown as builder
from core.network_access import strip_tests_config_answer_links


CONFIG_PATH = ROOT / "tests-config.json"
LINK_MAP_PATH = ROOT / "static/js/test_answer_link_map.json"
TESTS_JS_PATH = ROOT / "static/js/tests.js"
TESTS_HTML_PATH = ROOT / "static/tests.html"
EXPECTED_ROUNDS = frozenset({"1", "2", "3"})
EXPECTED_PROBLEMS = 20
MISSING_ANSWER_LINK_STATUS = "missing"


class VerificationError(AssertionError):
    pass


def require(condition: object, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def synthetic_config() -> dict:
    return {
        "categories": {
            "UNIT": {
                "tests": [
                    {
                        "id": "s16_r1",
                        "sourceId": "s16",
                        "curriculum": "subject",
                        "difficulty": "Lv.3",
                        "name": "unit1",
                        "sourceOrder": 16,
                    },
                    {
                        "id": "s17_r1",
                        "sourceId": "s17",
                        "curriculum": "subject",
                        "difficulty": "Lv.3",
                        "name": "unit2",
                        "sourceOrder": 17,
                        "answerLinkStatus": "missing",
                    },
                ]
            }
        }
    }


def answer_file(name: str, source_order: int | None, file_id: str) -> dict:
    title = f"{source_order}. {name}.pdf" if source_order is not None else f"{name}.pdf"
    return {
        "subject": "subject",
        "level": "Lv.3",
        "round": "1",
        "name": name,
        "title": title,
        "fileId": file_id,
        "sourceOrder": source_order,
    }


def verify_matching_rules() -> None:
    config = synthetic_config()
    aliases = {"generic": ["unit1", "unit2"]}

    require(builder.source_order_from_title("16. generic.pdf") == 16, "dot source order parsing failed")
    require(builder.source_order_from_title("17) generic.pdf") == 17, "paren source order parsing failed")
    require(builder.source_order_from_title("generic.pdf") is None, "unordered title must stay unordered")

    with (
        patch.object(builder, "ANSWER_NAME_ALIASES", aliases),
        patch.object(
            builder,
            "iter_drive_answer_files",
            return_value=iter([answer_file("generic Lv.3", 16, "file-a")]),
        ),
    ):
        link_map, issues = builder.build_link_map(config, "unused")
    require(link_map.get("s16", {}).get("1", {}).get("fileId") == "file-a", "order match failed")
    require("s17" not in link_map, "order mismatch received a link")
    require(not any(issue["type"] == "ambiguous_answer_file" for issue in issues), "ordered match stayed ambiguous")
    expected_missing = [issue for issue in issues if issue.get("sourceId") == "s17"]
    require(len(expected_missing) == 3, "explicit missing source must report all three rounds")
    require(
        all(issue["type"] == "expected_missing_round" for issue in expected_missing),
        "explicit missing source reported a fatal missing_round",
    )
    require(
        "expected_missing_round" in builder.NON_FATAL_ISSUE_TYPES,
        "expected missing rounds must be non-fatal",
    )

    with (
        patch.object(builder, "ANSWER_NAME_ALIASES", aliases),
        patch.object(
            builder,
            "iter_drive_answer_files",
            return_value=iter([answer_file("generic Lv.3", None, "file-b")]),
        ),
    ):
        link_map, issues = builder.build_link_map(config, "unused")
    require(not link_map, "ambiguous unordered file received a link")
    require(any(issue["type"] == "ambiguous_answer_file" for issue in issues), "ambiguity was not reported")

    with patch.object(
        builder,
        "iter_drive_answer_files",
        return_value=iter(
            [
                answer_file("unit1 Lv.3", 16, "shared-file"),
                answer_file("unit2 Lv.3", 17, "shared-file"),
            ]
        ),
    ):
        link_map, issues = builder.build_link_map(config, "unused")
    require(link_map.get("s16", {}).get("1", {}).get("fileId") == "shared-file", "first owner missing")
    require("s17" not in link_map, "reused fileId received a second owner")
    require(any(issue["type"] == "reused_answer_file" for issue in issues), "fileId reuse was not reported")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_live_catalog() -> dict:
    config = load_json(CONFIG_PATH)
    link_map = load_json(LINK_MAP_PATH)
    unit_tests = config.get("categories", {}).get("UNIT", {}).get("tests", [])
    require(isinstance(unit_tests, list), "UNIT tests must be an array")
    require(isinstance(link_map, dict), "answer link map must be an object")

    tests_by_source: dict[str, list[dict]] = {}
    for test in unit_tests:
        require(isinstance(test, dict), "UNIT test rows must be objects")
        source_id = str(test.get("sourceId") or "").strip()
        require(source_id, "UNIT test is missing sourceId")
        tests_by_source.setdefault(source_id, []).append(test)

    unknown_sources = sorted(set(link_map) - set(tests_by_source))
    require(not unknown_sources, f"link map has unknown sourceIds: {unknown_sources[:5]}")

    file_owners: dict[str, tuple[str, str]] = {}
    for source_id, rounds in link_map.items():
        for row in tests_by_source[source_id]:
            status = str(row.get("answerLinkStatus") or row.get("answer_link_status") or "").strip().casefold()
            require(status != MISSING_ANSWER_LINK_STATUS, f"linked source is marked missing: {source_id}")
        require(isinstance(rounds, dict), f"link rounds must be an object: {source_id}")
        require(set(rounds) == EXPECTED_ROUNDS, f"incomplete link rounds: {source_id}")
        for round_no, link in rounds.items():
            require(isinstance(link, dict), f"link must be an object: {source_id}/{round_no}")
            file_id = str(link.get("fileId") or "").strip()
            require(file_id, f"missing fileId: {source_id}/{round_no}")
            require(file_id not in file_owners, f"reused fileId: {file_id}")
            require(file_id in str(link.get("answerUrl") or ""), f"answerUrl/fileId mismatch: {source_id}/{round_no}")
            file_owners[file_id] = (source_id, round_no)

    missing_sources = sorted(set(tests_by_source) - set(link_map))
    for source_id in missing_sources:
        rows = tests_by_source[source_id]
        require({str(row.get("round") or "") for row in rows} == EXPECTED_ROUNDS, f"missing source rounds: {source_id}")
        for row in rows:
            round_no = str(row.get("round") or "")
            status = str(row.get("answerLinkStatus") or row.get("answer_link_status") or "").strip().casefold()
            require(
                status == MISSING_ANSWER_LINK_STATUS,
                f"unlinked source must declare answerLinkStatus=missing: {source_id}/{round_no}",
            )
            modes = row.get("answerModes", {}).get(round_no, [])
            require(
                modes == ["manual_review"] * EXPECTED_PROBLEMS,
                f"unlinked source must be manual_review: {source_id}/{round_no}",
            )

    return {
        "unitSources": len(tests_by_source),
        "linkedSources": len(link_map),
        "linkedRounds": len(file_owners),
        "missingSources": len(missing_sources),
        "reusedFileIds": 0,
    }


def verify_test_management_ui_contract() -> None:
    tests_js = TESTS_JS_PATH.read_text(encoding="utf-8")
    tests_html = TESTS_HTML_PATH.read_text(encoding="utf-8")
    for snippet in (
        "MISSING_ANSWER_LINK_STATUS = 'missing'",
        "function answerLinkStatus(test)",
        "answerLinkStatus(test) === MISSING_ANSWER_LINK_STATUS",
        "test-link-status is-missing",
        "해설 미연결",
    ):
        require(snippet in tests_js, f"test management missing-link badge contract is absent: {snippet}")
    require(
        "body.admin.tests-page .test-link-status" in tests_html,
        "test management missing-link badge styles are absent",
    )


def verify_public_projection_contract() -> None:
    projected = strip_tests_config_answer_links(
        {
            "answerLinkStatus": "missing",
            "answer_link_status": "missing",
            "answerUrl": "https://example.invalid/answer.pdf",
            "answerKeys": {"1": ["1"]},
            "answerModes": {"1": ["manual_review"]},
            "sourceFiles": {"solutionFileId": "secret-file-id"},
        }
    )
    require(projected.get("answerLinkStatus") == "missing", "camel-case link status was stripped")
    require(projected.get("answer_link_status") == "missing", "snake-case link status was stripped")
    require("answerUrl" not in projected, "answer URL leaked through public projection")
    require("answerKeys" not in projected, "answer keys leaked through public projection")
    require(projected.get("answerModes") == {"1": ["manual_review"]}, "answer modes were stripped")
    require(
        "solutionFileId" not in projected.get("sourceFiles", {}),
        "solution file ID leaked through public projection",
    )

def main() -> int:
    verify_matching_rules()
    verify_test_management_ui_contract()
    verify_public_projection_contract()
    summary = verify_live_catalog()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("unit answer-link safety: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
