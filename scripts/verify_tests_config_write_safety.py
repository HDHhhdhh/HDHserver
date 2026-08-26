# /// script
# requires-python = ">=3.11"
# ///
"""Verify that tests-config writes cannot silently destroy catalog data."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]

import routes.api_tests as api_tests
import scripts.import_unit_test_catalog_csv as unit_catalog_import
from core.test_config_safety import tests_config_revision


def _fixture() -> dict:
    return {
        "categories": {
            "UNIT": {
                "label": "Unit",
                "tests": [
                    {
                        "id": "keep",
                        "name": "Keep",
                        "answerKey": ["1"],
                        "answerKeys": {"1": ["1"]},
                        "sourceFiles": {
                            "solutionFileId": "solution-keep",
                            "name": "keep.pdf",
                        },
                        "answerUrl": "https://drive.google.com/keep",
                    },
                    {
                        "id": "remove",
                        "name": "Remove",
                        "answerKey": ["2"],
                    },
                ],
            },
        },
        "unknownField": {"mustRemain": True},
    }


def _write_config(config_path: Path, value: dict) -> None:
    config_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _headers(config: dict) -> dict[str, str]:
    return {"X-Tests-Config-Revision": tests_config_revision(config)}


def _verify_unit_import_guard() -> None:
    with tempfile.TemporaryDirectory(prefix="unit-import-write-safety-") as temp_dir:
        temp_path = Path(temp_dir)
        config_path = temp_path / "tests-config.json"
        csv_path = temp_path / "unit.csv"
        original = {"categories": {"UNIT": {"tests": [{"id": "orphan_r1"}]}}}
        _write_config(config_path, original)
        csv_path.write_text(
            "id,name,problems,subject,difficulty,answers1\n"
            "new,New test,1,공수2,Lv.4,1\n",
            encoding="utf-8",
        )
        try:
            unit_catalog_import.main(["--config", str(config_path), "--csv", str(csv_path)])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("UNIT importer accepted an implicit removal")
        assert json.loads(config_path.read_text(encoding="utf-8")) == original

        valid = {
            "categories": {
                "UNIT": {
                    "tests": [
                        {
                            "id": "new_r1",
                            "sourceFiles": {"solutionFileId": "keep-solution"},
                            "unknownField": "preserve",
                        },
                    ],
                },
            },
        }
        _write_config(config_path, valid)
        assert unit_catalog_import.main(
            ["--config", str(config_path), "--csv", str(csv_path)]
        ) == 0
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        saved_ids = [
            item["id"] for item in saved["categories"]["UNIT"]["tests"]
        ]
        assert saved_ids == ["new_r1", "new_r2", "new_r3"]
        saved_first = saved["categories"]["UNIT"]["tests"][0]
        assert saved_first["sourceFiles"]["solutionFileId"] == "keep-solution"
        assert saved_first["unknownField"] == "preserve"


def _verify_frontend_delete_contract() -> None:
    source = (ROOT / "static/js/tests.js").read_text(encoding="utf-8")
    assert "async function saveConfig(removedTestIds = [])" in source
    assert "async function saveTestDefinition(test, categoryKey, categoryLabel)" in source
    assert "fetch('/api/tests-config/test'" in source
    assert "method: 'PATCH'" in source
    assert "payload.__removedTestIds = removedTestIds.map(id => String(id));" in source
    assert "const deletedTestId = String(ui.selectedId);" in source
    assert "await saveConfig([deletedTestId]);" in source


def main() -> None:
    _verify_unit_import_guard()
    _verify_frontend_delete_contract()
    current = _fixture()
    app = Flask("tests-config-write-safety")
    app.register_blueprint(api_tests.bp_api_tests)
    original_path = api_tests.TESTS_CFG_PATH
    original_academy_allowed = api_tests._academy_request_allowed
    try:
        api_tests._academy_request_allowed = lambda: True
        with tempfile.TemporaryDirectory(prefix="tests-config-write-safety-") as temp_dir:
            config_path = Path(temp_dir) / "tests-config.json"
            api_tests.TESTS_CFG_PATH = config_path

            _write_config(config_path, current)
            with app.test_client() as client:
                response = client.get(
                    "/api/tests-config",
                    base_url="http://127.0.0.1",
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            assert response.get_json() == current
            assert response.headers.get("X-Tests-Config-Revision") == tests_config_revision(current)

            missing = copy.deepcopy(current)
            missing["categories"]["UNIT"]["tests"] = [
                {"id": "keep", "name": "Keep"},
            ]
            with app.test_client() as client:
                response = client.post(
                    "/api/tests-config",
                    json=missing,
                    headers=_headers(current),
                )
            assert response.status_code == 409, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == current

            with app.test_client() as client:
                response = client.post("/api/tests-config", json=current)
            assert response.status_code == 428, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == current

            stale = copy.deepcopy(current)
            server_changed = copy.deepcopy(current)
            server_changed["categories"]["UNIT"]["tests"][0]["name"] = "Server edit"
            server_changed["categories"]["UNIT"]["tests"] = [
                server_changed["categories"]["UNIT"]["tests"][0]
            ]
            _write_config(config_path, server_changed)
            with app.test_client() as client:
                response = client.post(
                    "/api/tests-config",
                    json=stale,
                    headers=_headers(current),
                )
            assert response.status_code == 409, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == server_changed

            _write_config(config_path, current)

            sanitized = copy.deepcopy(current)
            keep = sanitized["categories"]["UNIT"]["tests"][0]
            keep.pop("answerKey")
            keep.pop("answerKeys")
            keep.pop("answerUrl")
            keep["sourceFiles"].pop("solutionFileId")
            with app.test_client() as client:
                response = client.post(
                    "/api/tests-config",
                    json=sanitized,
                    headers=_headers(current),
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            saved_revision = response.headers.get("X-Tests-Config-Revision", "")
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            assert saved_revision == tests_config_revision(saved)
            saved_keep = saved["categories"]["UNIT"]["tests"][0]
            assert saved_keep["answerKey"] == ["1"]
            assert saved_keep["answerKeys"] == {"1": ["1"]}
            assert saved_keep["answerUrl"] == "https://drive.google.com/keep"
            assert saved_keep["sourceFiles"]["solutionFileId"] == "solution-keep"
            assert saved["unknownField"] == {"mustRemain": True}

            deleted = copy.deepcopy(saved)
            deleted["categories"]["UNIT"]["tests"] = [
                saved_keep,
            ]
            deleted["__removedTestIds"] = ["remove"]
            with app.test_client() as client:
                response = client.post(
                    "/api/tests-config",
                    json=deleted,
                    headers=_headers(saved),
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            final = json.loads(config_path.read_text(encoding="utf-8"))
            final_ids = [
                item["id"] for item in final["categories"]["UNIT"]["tests"]
            ]
            assert final_ids == ["keep"]
            assert "__removedTestIds" not in final

            _write_config(config_path, current)
            with app.test_client() as client:
                response = client.patch(
                    "/api/tests-config/test",
                    json={
                        "categoryKey": "UNIT",
                        "categoryLabel": "Unit",
                        "test": {"id": "keep", "name": "Patched"},
                    },
                    headers=_headers(current),
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            patched = json.loads(config_path.read_text(encoding="utf-8"))
            patched_keep = patched["categories"]["UNIT"]["tests"][0]
            assert patched_keep["name"] == "Patched"
            assert patched_keep["answerKey"] == ["1"]
            assert patched_keep["sourceFiles"]["solutionFileId"] == "solution-keep"
            assert [row["id"] for row in patched["categories"]["UNIT"]["tests"]] == [
                "keep",
                "remove",
            ]
            assert patched["unknownField"] == {"mustRemain": True}

            patched_revision = tests_config_revision(patched)
            with app.test_client() as client:
                response = client.patch(
                    "/api/tests-config/test",
                    json={
                        "categoryKey": "REVIEW",
                        "categoryLabel": "Review",
                        "test": {"id": "keep", "name": "Moved"},
                    },
                    headers={"X-Tests-Config-Revision": patched_revision},
                )
            assert response.status_code == 200, response.get_data(as_text=True)
            moved = json.loads(config_path.read_text(encoding="utf-8"))
            assert [row["id"] for row in moved["categories"]["UNIT"]["tests"]] == ["remove"]
            moved_keep = moved["categories"]["REVIEW"]["tests"][0]
            assert moved_keep["id"] == "keep"
            assert moved_keep["name"] == "Moved"
            assert moved_keep["sourceFiles"]["solutionFileId"] == "solution-keep"

            before_rejected_patch = copy.deepcopy(moved)
            with app.test_client() as client:
                response = client.patch(
                    "/api/tests-config/test",
                    json={"categoryKey": "REVIEW", "test": {"id": "keep", "name": "Stale"}},
                    headers={"X-Tests-Config-Revision": patched_revision},
                )
            assert response.status_code == 409, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == before_rejected_patch

            with app.test_client() as client:
                response = client.patch(
                    "/api/tests-config/test",
                    json={"categoryKey": "REVIEW", "test": {"id": "keep", "name": "No revision"}},
                )
            assert response.status_code == 428, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == before_rejected_patch
    finally:
        api_tests.TESTS_CFG_PATH = original_path
        api_tests._academy_request_allowed = original_academy_allowed


if __name__ == "__main__":
    main()
