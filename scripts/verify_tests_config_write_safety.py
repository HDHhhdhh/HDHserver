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
    try:
        with tempfile.TemporaryDirectory(prefix="tests-config-write-safety-") as temp_dir:
            config_path = Path(temp_dir) / "tests-config.json"
            api_tests.TESTS_CFG_PATH = config_path

            _write_config(config_path, current)
            missing = copy.deepcopy(current)
            missing["categories"]["UNIT"]["tests"] = [
                {"id": "keep", "name": "Keep"},
            ]
            with app.test_client() as client:
                response = client.post("/api/tests-config", json=missing)
            assert response.status_code == 409, response.get_data(as_text=True)
            assert json.loads(config_path.read_text(encoding="utf-8")) == current

            sanitized = copy.deepcopy(current)
            keep = sanitized["categories"]["UNIT"]["tests"][0]
            keep.pop("answerKey")
            keep.pop("answerKeys")
            keep.pop("answerUrl")
            keep["sourceFiles"].pop("solutionFileId")
            with app.test_client() as client:
                response = client.post("/api/tests-config", json=sanitized)
            assert response.status_code == 200, response.get_data(as_text=True)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
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
                response = client.post("/api/tests-config", json=deleted)
            assert response.status_code == 200, response.get_data(as_text=True)
            final = json.loads(config_path.read_text(encoding="utf-8"))
            final_ids = [
                item["id"] for item in final["categories"]["UNIT"]["tests"]
            ]
            assert final_ids == ["keep"]
            assert "__removedTestIds" not in final
    finally:
        api_tests.TESTS_CFG_PATH = original_path


if __name__ == "__main__":
    main()
