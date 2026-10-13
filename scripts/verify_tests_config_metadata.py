"""Literal catalog metadata/answer-link oracle and actual temp POST boundary."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType

from flask import Blueprint, Flask, current_app, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage import file_lock, load, save_atomic
from core.test_answer_links import resolve_test_assignment_answer_url


def revision(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(source_root, guarded=True):
    rules = ModuleType("catalog_metadata_fixture")
    exec(compile((source_root / "core/test_config_safety.py").read_text(encoding="utf-8"), "actual-catalog-rules", "exec"), rules.__dict__)
    a = {"id": "A", "name": "Original", "problems": 2, "round": "1", "rounds": 2,
         "sourceId": "mapped-source", "source_id": "mapped-source", "sourceOrder": 17,
         "unknownTest": {"keep": [1, 2]}, "answerKeys": {"1": ["1", "2"], "2": ["2", "1"]},
         "answerModes": {"1": ["choice_number", "choice_number"], "2": ["choice_number", "choice_number"]},
         "sourceFiles": {"originalFileId": "paper", "name": "paper.pdf", "unknown": {"keep": True}}}
    b = {"id": "B", "name": "Legacy", "sourceId": "b-source", "unknown": "keep"}
    current = {"unknownTop": {"keep": ["yes"]}, "globalRules": {"old": True},
               "categories": {
                   "UNIT": {"label": "Unit", "unknownCategory": {"keep": True}, "tests": [a, b]},
                   "REVIEW": {"label": "Review", "unknownCategory": ["retained"], "tests": []},
                   "EMPTY": {"label": "Can be removed", "tests": []},
               }}
    incoming_a = {"id": "A", "name": "Updated", "problems": 2, "round": "1", "rounds": 1,
                  "sourceFiles": {"name": "new.pdf"}, "answerKeys": {"1": ["3", "4"]},
                  "answerModes": {"1": ["choice_number", "choice_number"]}}
    incoming = {"globalRules": {"new": True}, "categories": {
        "UNIT": {"tests": [incoming_a]}, "REVIEW": {"tests": [{"id": "B", "name": "Moved"}]},
    }}
    inputs = deepcopy((current, incoming))
    expected_a = {**deepcopy(a), **deepcopy(incoming_a),
                  "sourceFiles": {**deepcopy(a["sourceFiles"]), "name": "new.pdf"}}
    expected = {"unknownTop": {"keep": ["yes"]}, "globalRules": {"new": True}, "categories": {
        "UNIT": {"label": "Unit", "unknownCategory": {"keep": True}, "tests": [expected_a]},
        "REVIEW": {"label": "Review", "unknownCategory": ["retained"], "tests": [{**b, "name": "Moved"}]},
    }}
    merged = rules.merge_tests_config_for_write(current, incoming)
    if guarded:
        assert merged == expected
    else:
        assert "unknownTop" not in merged and "label" not in merged["categories"]["UNIT"]
        assert "sourceId" not in merged["categories"]["UNIT"]["tests"][0]
    assert (current, incoming) == inputs
    answer_map = {"mapped-source": {"1": {"url": "https://drive.google.com/file/d/literal-answer/view"}}}
    assignment = {"id": "A", "categoryKey": "UNIT", "round": "1"}
    url = resolve_test_assignment_answer_url(assignment, tests_config=merged, answer_link_map=answer_map)
    assert url == ("https://drive.google.com/file/d/literal-answer/view" if guarded else "")
    if guarded:
        moved = {"categories": {"UNIT": {"label": "Changed"}, "REVIEW": {"tests": [incoming_a, {"id": "B"}]}}}
        result = rules.merge_tests_config_for_write(current, moved)
        assert "tests" not in result["categories"]["UNIT"]
        assert [row["id"] for row in result["categories"]["REVIEW"]["tests"]] == ["A", "B"]
        deleted = rules.merge_tests_config_for_write(current, {"categories": {"UNIT": {}, "REVIEW": {"tests": [{"id": "B"}]}}}, ["A"])
        assert "tests" not in deleted["categories"]["UNIT"]
        assert [row["id"] for row in deleted["categories"]["REVIEW"]["tests"]] == ["B"]

    with tempfile.TemporaryDirectory(prefix="catalog-metadata-post-") as raw:
        path = Path(raw) / "tests-config.json"
        path.write_text(json.dumps(current), encoding="utf-8")
        blueprint = Blueprint("metadata_tests", __name__)
        scope = dict(globals(), bp_api_tests=blueprint, TESTS_CFG_PATH=path,
                     tests_config_revision=rules.tests_config_revision,
                     merge_tests_config_for_write=rules.merge_tests_config_for_write,
                     TestsConfigWriteConflict=rules.TestsConfigWriteConflict)
        tree = ast.parse((source_root / "routes/api_tests.py").read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_tests_config_lock", "post_tests_config"}]
        assert len(functions) == 2
        exec(compile(ast.Module(body=functions, type_ignores=[]), "actual-catalog-post-route", "exec"), scope)
        app = Flask("catalog-metadata-post")
        app.register_blueprint(blueprint)
        client = app.test_client()
        for body, headers, status in (
            (incoming, {}, 428),
            (incoming, {"X-Tests-Config-Revision": "0" * 64}, 409),
            ({"categories": {}}, {"X-Tests-Config-Revision": revision(current)}, 409),
            ({"categories": []}, {"X-Tests-Config-Revision": revision(current)}, 400),
        ):
            before = path.stat().st_mtime_ns, path.read_bytes()
            rejected = client.post("/api/tests-config", json=body, headers=headers)
            assert rejected.status_code == status
            assert (path.stat().st_mtime_ns, path.read_bytes()) == before
        response = client.post("/api/tests-config", json=incoming, headers={"X-Tests-Config-Revision": revision(current)})
        assert response.status_code == 200 and response.json == {"ok": True}
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored == merged and response.headers["X-Tests-Config-Revision"] == revision(stored)
        assert resolve_test_assignment_answer_url(assignment, tests_config=stored, answer_link_map=answer_map) == url
        if guarded:
            removed = {"categories": {"REVIEW": {"tests": [{"id": "B"}]}}, "__removedTestIds": ["A"]}
            response = client.post("/api/tests-config", json=removed, headers={"X-Tests-Config-Revision": revision(stored)})
            assert response.status_code == 200
            stored = json.loads(path.read_text(encoding="utf-8"))
            assert set(stored["categories"]) == {"REVIEW"} and [test["id"] for test in stored["categories"]["REVIEW"]["tests"]] == ["B"]
    print("tests metadata passed: root/category/test omissions, source-ID answer links, explicit replacement, move/delete, revision and no-write failures")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expect", choices=("guarded", "vulnerable"), default="guarded")
    args = parser.parse_args()
    verify(args.source_root, args.expect == "guarded")
