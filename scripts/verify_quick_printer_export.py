from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quick_printer_export import (  # noqa: E402
    CSV_COLUMNS,
    MAPPING_VERSION,
    NoQuickPrinterAssignments,
    QuickPrinterExportFailure,
    QuickPrinterResourceFailure,
    build_quick_printer_export,
    build_test_definitions,
    file_sha256,
    read_mapping_bundle,
    read_registered_catalog,
    test_definitions_sha256,
    validate_mapping_bundle,
)


RESOURCE_DIR = ROOT / "core" / "resources"
REAL_CATALOG_PATH = RESOURCE_DIR / "quick_printer_registered_tests.csv"
REAL_MAPPING_PATH = RESOURCE_DIR / "quick_printer_test_mapping.json"
REAL_TESTS_CONFIG_PATH = ROOT / "tests-config.json"


def registered_row(material_id: str, name: str) -> dict:
    return {
        "자료ID": material_id,
        "자료유형": "단원평가",
        "과목": "공통수학1",
        "레벨": "Lv.3",
        "시험구분": "",
        "회차": "1",
        "개별번호": "1",
        "표시이름": name,
        "파일명": f"{name}.pdf",
        "상대경로": f"공통수학1/Lv.3/1/{name}.pdf",
    }


def synthetic_config() -> dict:
    return {
        "categories": {
            "UNIT": {
                "label": "단원평가",
                "tests": [
                    {
                        "id": "unit-a",
                        "curriculum": "공수1",
                        "difficulty": "Lv.3",
                        "round": "1",
                        "name": "첫 시험",
                        "sourceOrder": 1,
                    },
                    {
                        "id": "unit-b",
                        "curriculum": "공수1",
                        "difficulty": "Lv.3",
                        "round": "1",
                        "name": "둘째 시험",
                        "sourceOrder": 2,
                    },
                ],
            },
        },
    }


def synthetic_resources(config: dict | None = None):
    config = config or synthetic_config()
    definitions = build_test_definitions(config)
    rows = [
        registered_row("QT-UNIT-AAAAAAAAAAAAAAAA", "첫 시험"),
        registered_row("QT-UNIT-BBBBBBBBBBBBBBBB", "둘째 시험"),
    ]
    mappings = {}
    for definition, row in zip(definitions, rows):
        mappings[definition["id"]] = {
            "materialId": row["자료ID"],
            "matchMethod": "test_fixture",
        }
    bundle = {
        "version": MAPPING_VERSION,
        "catalog": {
            "fileName": "fixture.csv",
            "sha256": "",
            "rowCount": len(rows),
            "uniqueMaterialIdCount": len(rows),
            "duplicateMaterialIdCount": 0,
            "countsByCategory": {"UNIT": len(rows)},
        },
        "server": {
            "definitionCount": len(definitions),
            "signatureSha256": test_definitions_sha256(definitions),
            "matchedCount": len(mappings),
            "issueCount": 0,
            "countsByCategory": {"UNIT": {"matched": len(mappings)}},
        },
        "mappings": mappings,
        "issues": {},
    }
    return config, definitions, rows, bundle


class QuickPrinterExportContractTests(unittest.TestCase):
    def test_real_mapping_inventory_and_revalidation(self):
        config = json.loads(REAL_TESTS_CONFIG_PATH.read_text(encoding="utf-8-sig"))
        catalog = read_registered_catalog(REAL_CATALOG_PATH)
        mapping = read_mapping_bundle(REAL_MAPPING_PATH)
        validated = validate_mapping_bundle(
            config,
            mapping,
            catalog,
            catalog_sha256=file_sha256(REAL_CATALOG_PATH),
        )

        self.assertEqual(len(catalog), 1515)
        self.assertEqual(len({row["자료ID"] for row in catalog}), 1515)
        self.assertEqual(mapping["server"]["definitionCount"], 1494)
        self.assertEqual(mapping["server"]["matchedCount"], 1484)
        self.assertEqual(mapping["server"]["issueCount"], 10)
        self.assertEqual(len(validated["mappings"]), 1484)
        self.assertEqual(len(validated["issues"]), 10)
        self.assertEqual(
            sum(issue["code"] == "ambiguous_registered_material" for issue in validated["issues"].values()),
            2,
        )
        self.assertEqual(
            sum(issue["code"] == "registered_material_not_found" for issue in validated["issues"].values()),
            8,
        )
        mapped_materials = [entry["materialId"] for entry in validated["mappings"].values()]
        self.assertEqual(len(mapped_materials), len(set(mapped_materials)))

    def test_green_only_date_order_bom_header_and_csv_escaping(self):
        config, definitions, rows, bundle = synthetic_resources()
        label_a, label_b = [definition["label"] for definition in definitions]
        special_name = '김, "철\n수"'
        result = build_quick_printer_export(
            date_str="2026-08-28",
            ordered_student_ids=["002", "1", "002"],
            students=[{"id": "1", "name": "한동훈"}, {"id": "2", "name": special_name}],
            progress={
                "2026-08-27": {"2": {"tests": {label_b: "assigned"}}},
                "2026-08-28": {
                    "2": {"tests": {label_b: "assigned", label_a: {"status": "assigned"}}},
                    "1": {
                        "tests": {
                            label_a: "assigned",
                            label_b: "done",
                            "제외 시험": "skip",
                            "배부 시험": "interrupted",
                        }
                    },
                },
            },
            tests_config=config,
            mapping_bundle=bundle,
            catalog_rows=rows,
        )

        self.assertEqual(result["filename"], "빠른인쇄기_테스트인쇄_20260828.csv")
        self.assertTrue(result["csv"].startswith("\ufeff"))
        self.assertEqual(result["rowCount"], 3)
        self.assertEqual(result["studentCount"], 2)
        parsed = list(csv.DictReader(io.StringIO(result["csv"][1:], newline="")))
        self.assertEqual(tuple(parsed[0].keys()), CSV_COLUMNS)
        self.assertEqual(
            [(row["학생이름"], row["자료ID"]) for row in parsed],
            [
                (special_name, "QT-UNIT-AAAAAAAAAAAAAAAA"),
                (special_name, "QT-UNIT-BBBBBBBBBBBBBBBB"),
                ("한동훈", "QT-UNIT-AAAAAAAAAAAAAAAA"),
            ],
        )
        self.assertTrue(all(row["부수"] == "1" and row["메모"] == "" for row in parsed))
        self.assertNotIn("20260827", result["csv"])
        self.assertIn('"김, ""철', result["csv"])

    def test_green_assignments_are_limited_to_student_current_curriculum(self):
        config = synthetic_config()
        config["categories"]["UNIT"]["tests"][0]["curriculum"] = "미적분1"
        config["categories"]["UNIT"]["tests"][1]["curriculum"] = "대수"
        config, definitions, rows, bundle = synthetic_resources(config)
        current_label = next(
            definition["label"]
            for definition in definitions
            if definition["curriculum"] == "미적분1"
        )
        stale_label = next(
            definition["label"]
            for definition in definitions
            if definition["curriculum"] == "대수"
        )

        result = build_quick_printer_export(
            date_str="2026-08-29",
            ordered_student_ids=["1"],
            students=[{"id": "1", "name": "학생", "curriculum": "미적1 APEX"}],
            progress={
                "2026-08-29": {
                    "1": {
                        "tests": {
                            current_label: "assigned",
                            stale_label: "assigned",
                        }
                    }
                }
            },
            tests_config=config,
            mapping_bundle=bundle,
            catalog_rows=rows,
        )

        parsed = list(csv.DictReader(io.StringIO(result["csv"][1:], newline="")))
        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(parsed[0]["자료ID"], bundle["mappings"]["unit-a"]["materialId"])
        self.assertNotIn(bundle["mappings"]["unit-b"]["materialId"], result["csv"])

    def test_selected_mapping_issue_blocks_every_row(self):
        config, definitions, rows, bundle = synthetic_resources()
        bundle["mappings"].pop("unit-b")
        bundle["issues"]["unit-b"] = {
            "code": "ambiguous_registered_material",
            "reason": "정확히 일치하는 자료가 두 개입니다.",
            "matchMethod": "fixture",
            "candidates": [
                {
                    "materialId": rows[1]["자료ID"],
                    "displayName": rows[1]["표시이름"],
                    "relativePath": rows[1]["상대경로"],
                }
            ],
        }
        label_a, label_b = [definition["label"] for definition in definitions]

        with self.assertRaises(QuickPrinterExportFailure) as raised:
            build_quick_printer_export(
                date_str="2026-08-28",
                ordered_student_ids=["1"],
                students=[{"id": "1", "name": "한동훈"}],
                progress={"2026-08-28": {"1": {"tests": {label_a: "assigned", label_b: "assigned"}}}},
                tests_config=config,
                mapping_bundle=bundle,
                catalog_rows=rows,
            )
        self.assertEqual(raised.exception.code, "quick_printer_export_blocked")
        self.assertEqual(len(raised.exception.issues), 1)
        self.assertEqual(raised.exception.issues[0]["testId"], "unit-b")
        self.assertNotIn("csv", raised.exception.__dict__)

    def test_unknown_or_duplicate_assignment_label_blocks_export(self):
        config, _, rows, bundle = synthetic_resources()
        with self.assertRaises(QuickPrinterExportFailure) as raised:
            build_quick_printer_export(
                date_str="2026-08-28",
                ordered_student_ids=["1"],
                students=[{"id": "1", "name": "한동훈"}],
                progress={"2026-08-28": {"1": {"tests": {"없는 시험": "assigned"}}}},
                tests_config=config,
                mapping_bundle=bundle,
                catalog_rows=rows,
            )
        self.assertEqual(raised.exception.issues[0]["code"], "assignment_test_not_unique")

    def test_no_green_assignment_returns_guidance_instead_of_empty_csv(self):
        config, definitions, rows, bundle = synthetic_resources()
        with self.assertRaises(NoQuickPrinterAssignments) as raised:
            build_quick_printer_export(
                date_str="2026-08-28",
                ordered_student_ids=["1"],
                students=[{"id": "1", "name": "한동훈"}],
                progress={"2026-08-28": {"1": {"tests": {definitions[0]["label"]: "done"}}}},
                tests_config=config,
                mapping_bundle=bundle,
                catalog_rows=rows,
            )
        self.assertEqual(raised.exception.code, "no_assigned_tests")

    def test_stale_catalog_or_duplicate_material_id_is_rejected_before_export(self):
        config, _, rows, bundle = synthetic_resources()
        duplicate_rows = rows + [deepcopy(rows[0])]
        stale_bundle = deepcopy(bundle)
        stale_bundle["catalog"]["rowCount"] = len(duplicate_rows)
        with self.assertRaises(QuickPrinterResourceFailure) as raised:
            validate_mapping_bundle(config, stale_bundle, duplicate_rows)
        codes = {issue["code"] for issue in raised.exception.issues}
        self.assertIn("catalog_material_id_duplicate", codes)

        with self.assertRaises(QuickPrinterResourceFailure) as hash_raised:
            validate_mapping_bundle(config, bundle, rows, catalog_sha256="changed")
        self.assertIn("catalog_hash_mismatch", {issue["code"] for issue in hash_raised.exception.issues})

    def test_actual_flask_route_returns_success_conflict_and_empty_guidance(self):
        from flask import Flask
        from core.progress_store import reset_progress_cache
        from routes import api_tests as route_module

        config, definitions, rows, bundle = synthetic_resources()
        label_a, label_b = [definition["label"] for definition in definitions]

        with tempfile.TemporaryDirectory(prefix="quick-printer-route-") as temp_dir:
            temp = Path(temp_dir)
            config_path = temp / "tests-config.json"
            students_path = temp / "students.json"
            progress_path = temp / "progress.json"
            catalog_path = temp / "catalog.csv"
            mapping_path = temp / "mapping.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            students_path.write_text(
                json.dumps([{"id": "1", "name": "한동훈"}], ensure_ascii=False),
                encoding="utf-8",
            )
            progress_path.write_text(
                json.dumps(
                    {"2026-08-28": {"1": {"tests": {label_a: "assigned", label_b: "done"}}}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\r\n")
                writer.writeheader()
                writer.writerows(rows)
            bundle["catalog"]["sha256"] = file_sha256(catalog_path)
            mapping_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

            app = Flask(__name__)
            app.register_blueprint(route_module.bp_api_tests)
            patches = (
                patch.object(route_module, "TESTS_CFG_PATH", config_path),
                patch.object(route_module, "STU_PATH", students_path),
                patch.object(route_module, "PRG_PATH", progress_path),
                patch.object(route_module, "QUICK_PRINTER_CATALOG_PATH", catalog_path),
                patch.object(route_module, "QUICK_PRINTER_MAPPING_PATH", mapping_path),
            )
            for active_patch in patches:
                active_patch.start()
            try:
                reset_progress_cache()
                client = app.test_client()
                success = client.post(
                    "/api/tests/quick-printer-export",
                    json={"date": "2026-08-28", "studentIds": ["1"]},
                )
                self.assertEqual(success.status_code, 200)
                self.assertEqual(success.headers.get("Cache-Control"), "no-store")
                success_payload = success.get_json()
                self.assertTrue(success_payload["ok"])
                self.assertEqual(success_payload["rowCount"], 1)
                self.assertTrue(success_payload["csv"].startswith("\ufeff"))

                blocked_bundle = deepcopy(bundle)
                blocked_bundle["mappings"].pop("unit-a")
                blocked_bundle["issues"]["unit-a"] = {
                    "code": "registered_material_not_found",
                    "reason": "등록 자료가 없습니다.",
                    "matchMethod": "fixture",
                    "candidates": [],
                }
                mapping_path.write_text(json.dumps(blocked_bundle, ensure_ascii=False), encoding="utf-8")
                blocked = client.post(
                    "/api/tests/quick-printer-export",
                    json={"date": "2026-08-28", "studentIds": ["1"]},
                )
                self.assertEqual(blocked.status_code, 409)
                blocked_payload = blocked.get_json()
                self.assertFalse(blocked_payload["ok"])
                self.assertNotIn("csv", blocked_payload)
                self.assertEqual(blocked_payload["issues"][0]["testId"], "unit-a")

                mapping_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
                progress_path.write_text(
                    json.dumps(
                        {"2026-08-28": {"1": {"tests": {label_a: "done"}}}},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                reset_progress_cache()
                empty = client.post(
                    "/api/tests/quick-printer-export",
                    json={"date": "2026-08-28", "studentIds": ["1"]},
                )
                self.assertEqual(empty.status_code, 422)
                empty_payload = empty.get_json()
                self.assertEqual(empty_payload["code"], "no_assigned_tests")
                self.assertNotIn("csv", empty_payload)
            finally:
                for active_patch in reversed(patches):
                    active_patch.stop()
                reset_progress_cache()


if __name__ == "__main__":
    unittest.main(verbosity=2)
