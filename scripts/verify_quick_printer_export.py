from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
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
    resolve_absence_carryover_origin_date,
    test_definitions_sha256,
    validate_mapping_bundle,
)
from core.quick_printer_export_history import (  # noqa: E402
    QuickPrinterExportHistoryRepository,
    quick_printer_history_key,
)
from core.log_repository import LogRepository  # noqa: E402


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

    def test_exact_absence_carryover_reassignment_is_excluded_even_without_history(self):
        config, definitions, rows, bundle = synthetic_resources()
        label_a, label_b = [definition["label"] for definition in definitions]
        material_a = bundle["mappings"]["unit-a"]["materialId"]
        source_date = "2026-08-28"
        target_date = "2026-08-29"
        log_history = {
            source_date: {
                "1": {
                    "testAssignmentAbsenceCarryover": {
                        "sourceDate": source_date,
                        "assignedTests": [
                            {"id": "unit-a", "label": label_a, "status": "assigned"},
                        ],
                    }
                }
            },
            target_date: {
                "1": {
                    "testAssignmentAbsenceSourceDate": source_date,
                    "assignedTests": [
                        {"id": "unit-a", "label": label_a, "status": "assigned"},
                        {"id": "unit-b", "label": label_b, "status": "assigned"},
                    ],
                }
            },
        }
        history_key = quick_printer_history_key("1", "unit-a", material_a, source_date)
        common = {
            "date_str": target_date,
            "ordered_student_ids": ["1"],
            "students": [{"id": "1", "name": "학생", "curriculum": "공수1"}],
            "progress": {target_date: {"1": {"tests": {label_a: "assigned", label_b: "assigned"}}}},
            "tests_config": config,
            "mapping_bundle": bundle,
            "catalog_rows": rows,
            "log_history": log_history,
        }

        default_result = build_quick_printer_export(
            **common,
            exported_assignment_keys={history_key},
        )
        parsed_default = list(csv.DictReader(io.StringIO(default_result["csv"][1:], newline="")))
        self.assertEqual([row["자료ID"] for row in parsed_default], [bundle["mappings"]["unit-b"]["materialId"]])
        self.assertEqual(default_result["automaticExclusionStudentCount"], 1)
        self.assertEqual(default_result["automaticExclusionCount"], 1)
        self.assertEqual(default_result["historyItems"][0]["assignmentDate"], target_date)

        reprint_result = build_quick_printer_export(
            **common,
            exported_assignment_keys={history_key},
            include_previously_exported_carryovers=True,
        )
        parsed_reprint = list(csv.DictReader(io.StringIO(reprint_result["csv"][1:], newline="")))
        self.assertEqual(
            [row["자료ID"] for row in parsed_reprint],
            [material_a, bundle["mappings"]["unit-b"]["materialId"]],
        )
        self.assertEqual(reprint_result["historyItems"][0]["assignmentDate"], source_date)

        never_exported = build_quick_printer_export(**common, exported_assignment_keys=set())
        parsed_never_exported = list(
            csv.DictReader(io.StringIO(never_exported["csv"][1:], newline=""))
        )
        self.assertEqual(
            [row["자료ID"] for row in parsed_never_exported],
            [bundle["mappings"]["unit-b"]["materialId"]],
        )
        self.assertEqual(never_exported["automaticExclusionStudentCount"], 1)
        self.assertEqual(never_exported["automaticExclusionCount"], 1)

        manual_log_history = deepcopy(log_history)
        manual_log_history[target_date]["1"].pop("testAssignmentAbsenceSourceDate")
        manual_result = build_quick_printer_export(
            **{**common, "log_history": manual_log_history},
            exported_assignment_keys={history_key},
        )
        self.assertEqual(manual_result["rowCount"], 2)
        self.assertEqual(manual_result["automaticExclusionCount"], 0)

        completed_source_history = deepcopy(log_history)
        completed_source_history[source_date]["1"]["testAssignmentAbsenceCarryover"][
            "assignedTests"
        ][0]["status"] = "done"
        completed_source_result = build_quick_printer_export(
            **{**common, "log_history": completed_source_history},
            exported_assignment_keys={history_key},
        )
        self.assertEqual(completed_source_result["rowCount"], 2)
        self.assertEqual(completed_source_result["automaticExclusionCount"], 0)

    def test_exclusion_to_zero_never_builds_an_empty_csv(self):
        config, definitions, rows, bundle = synthetic_resources()
        definition = definitions[0]
        label = definition["label"]
        source_date = "2026-08-28"
        target_date = "2026-08-29"
        material_id = bundle["mappings"][definition["id"]]["materialId"]
        log_history = {
            source_date: {
                "1": {
                    "testAssignmentAbsenceCarryover": {
                        "sourceDate": source_date,
                        "assignedTests": [
                            {"id": definition["id"], "label": label, "status": "assigned"}
                        ],
                    }
                }
            },
            target_date: {
                "1": {
                    "testAssignmentAbsenceSourceDate": source_date,
                    "assignedTests": [{"id": definition["id"], "label": label}],
                }
            },
        }
        common = {
            "date_str": target_date,
            "ordered_student_ids": ["1"],
            "students": [{"id": "1", "name": "학생", "curriculum": "공수1"}],
            "progress": {target_date: {"1": {"tests": {label: "assigned"}}}},
            "tests_config": config,
            "mapping_bundle": bundle,
            "catalog_rows": rows,
            "log_history": log_history,
            "exported_assignment_keys": set(),
        }

        with self.assertRaises(NoQuickPrinterAssignments) as raised:
            build_quick_printer_export(**common)
        self.assertEqual(raised.exception.code, "no_new_assignments_after_carryover_exclusion")
        self.assertEqual(raised.exception.issues[0]["studentCount"], 1)
        self.assertEqual(raised.exception.issues[0]["assignmentCount"], 1)

        preview = build_quick_printer_export(**common, allow_empty=True)
        self.assertEqual(preview["rowCount"], 0)
        self.assertNotIn("csv", preview)
        self.assertEqual(preview["historyItems"], [])

        reprint = build_quick_printer_export(
            **common,
            include_previously_exported_carryovers=True,
        )
        self.assertEqual(reprint["rowCount"], 1)

    def test_multihop_absence_chain_resolves_the_original_assignment_date(self):
        config, definitions, _, _ = synthetic_resources()
        definition = definitions[0]
        label = definition["label"]
        history = {
            "2026-08-27": {
                "1": {
                    "testAssignmentAbsenceCarryover": {
                        "sourceDate": "2026-08-27",
                        "assignedTests": [
                            {"id": definition["id"], "label": label, "status": "assigned"}
                        ],
                    }
                }
            },
            "2026-08-28": {
                "1": {
                    "testAssignmentAbsenceSourceDate": "2026-08-27",
                    "testAssignmentAbsenceCarryover": {
                        "sourceDate": "2026-08-28",
                        "assignedTests": [
                            {"id": definition["id"], "label": label, "status": "assigned"}
                        ],
                    },
                    "assignedTests": [{"id": definition["id"], "label": label}],
                }
            },
            "2026-08-29": {
                "1": {
                    "testAssignmentAbsenceSourceDate": "2026-08-28",
                    "assignedTests": [{"id": definition["id"], "label": label}],
                }
            },
        }
        self.assertEqual(
            resolve_absence_carryover_origin_date(
                log_history=history,
                date_str="2026-08-29",
                sid="1",
                definition=definition,
            ),
            "2026-08-27",
        )

    def test_history_repository_is_persistent_atomic_and_concurrency_safe(self):
        item = {
            "studentId": "001",
            "testId": "unit-a",
            "materialId": "QT-UNIT-AAAAAAAAAAAAAAAA",
            "assignmentDate": "2026-08-28",
            "exportDate": "2026-08-29",
        }
        with tempfile.TemporaryDirectory(prefix="quick-printer-history-") as temp_dir:
            db_path = Path(temp_dir) / "app.sqlite"
            first = QuickPrinterExportHistoryRepository(
                db_path=db_path,
                now_iso=lambda: "2026-08-29T12:00:00+09:00",
            )
            self.assertEqual(first.record_generated([item, deepcopy(item)]), 1)
            expected_key = quick_printer_history_key("1", "unit-a", item["materialId"], "2026-08-28")
            restarted = QuickPrinterExportHistoryRepository(db_path=db_path)
            self.assertEqual(restarted.keys_for_students(["1"]), {expected_key})

            def record_again(_index: int) -> int:
                return QuickPrinterExportHistoryRepository(db_path=db_path).record_generated([item])

            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(list(executor.map(record_again, range(2))), [1, 1])
            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "SELECT COUNT(*), export_count FROM quick_printer_export_history"
                ).fetchone()
            self.assertEqual(row, (1, 3))

            rollback_db = Path(temp_dir) / "rollback.sqlite"
            rollback_repo = QuickPrinterExportHistoryRepository(db_path=rollback_db)
            self.assertEqual(rollback_repo.keys_for_students(["1"]), set())
            with closing(sqlite3.connect(rollback_db)) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_second_quick_printer_history "
                    "BEFORE INSERT ON quick_printer_export_history "
                    "WHEN NEW.test_id='unit-b' BEGIN SELECT RAISE(ABORT, 'synthetic'); END;"
                )
            failing_items = [item, {**item, "testId": "unit-b", "materialId": "QT-UNIT-BBBBBBBBBBBBBBBB"}]
            with self.assertRaises(sqlite3.IntegrityError):
                rollback_repo.record_generated(failing_items)
            with closing(sqlite3.connect(rollback_db)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM quick_printer_export_history").fetchone()[0]
            self.assertEqual(count, 0)

    def test_log_repository_export_history_keeps_only_required_absence_provenance(self):
        source_date = "2026-08-28"
        target_date = "2026-08-29"
        source_entry = {
            "notes": "브라우저로 보낼 필요 없는 본문",
            "testAssignmentAbsenceCarryover": {
                "sourceDate": source_date,
                "assignedTests": [{"id": "unit-a", "label": "시험 A"}],
            },
            "testAssignmentAbsenceSourceDate": "2026-08-27",
        }
        target_entry = {
            "notes": "현재 날짜는 full projection",
            "testAssignmentAbsenceSourceDate": source_date,
            "assignedTests": [{"id": "unit-a", "label": "시험 A"}],
        }
        with tempfile.TemporaryDirectory(prefix="quick-printer-log-history-") as temp_dir:
            temp = Path(temp_dir)
            logs_path = temp / "logs.json"
            logs_path.write_text(
                json.dumps(
                    {
                        source_date: {"1": source_entry},
                        target_date: {"1": target_entry},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            repository = LogRepository(logs_path=logs_path, db_path=str(temp / "app.sqlite"))
            projected = repository.read_export_history({"1": target_date})

        self.assertEqual(
            projected[source_date]["1"]["testAssignmentAbsenceCarryover"],
            source_entry["testAssignmentAbsenceCarryover"],
        )
        self.assertEqual(
            projected[source_date]["1"]["testAssignmentAbsenceSourceDate"],
            "2026-08-27",
        )
        self.assertNotIn("notes", projected[source_date]["1"])
        self.assertEqual(projected[target_date]["1"]["notes"], target_entry["notes"])

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
            logs_path = temp / "logs.json"
            db_path = temp / "app.sqlite"
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
            logs_path.write_text("{}", encoding="utf-8")
            with catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\r\n")
                writer.writeheader()
                writer.writerows(rows)
            bundle["catalog"]["sha256"] = file_sha256(catalog_path)
            mapping_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

            app = Flask(__name__)
            app.register_blueprint(route_module.bp_api_tests)
            log_repository = LogRepository(logs_path=logs_path, db_path=str(db_path))
            patches = (
                patch.object(route_module, "TESTS_CFG_PATH", config_path),
                patch.object(route_module, "STU_PATH", students_path),
                patch.object(route_module, "PRG_PATH", progress_path),
                patch.object(route_module, "QUICK_PRINTER_CATALOG_PATH", catalog_path),
                patch.object(route_module, "QUICK_PRINTER_MAPPING_PATH", mapping_path),
                patch.object(route_module, "get_log_repository", return_value=log_repository),
                patch.dict(os.environ, {"DB_PATH": str(db_path)}, clear=False),
            )
            for active_patch in patches:
                active_patch.start()
            try:
                reset_progress_cache()
                client = app.test_client()
                invalid_reprint = client.post(
                    "/api/tests/quick-printer-export",
                    json={
                        "date": "2026-08-28",
                        "studentIds": ["1"],
                        "includePreviouslyExportedCarryovers": "true",
                    },
                )
                self.assertEqual(invalid_reprint.status_code, 400)
                self.assertEqual(invalid_reprint.get_json()["code"], "invalid_reprint_option")

                preview = client.post(
                    "/api/tests/quick-printer-export/preview",
                    json={"date": "2026-08-28", "studentIds": ["1"]},
                )
                self.assertEqual(preview.status_code, 200)
                preview_payload = preview.get_json()
                self.assertTrue(preview_payload["ok"])
                self.assertEqual(preview_payload["rowCount"], 1)
                self.assertNotIn("csv", preview_payload)
                with closing(sqlite3.connect(db_path)) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM quick_printer_export_history").fetchone()[0],
                        0,
                    )

                class FailingHistoryRepository:
                    @staticmethod
                    def keys_for_students(_student_ids):
                        return set()

                    @staticmethod
                    def record_generated(_items):
                        raise sqlite3.OperationalError("synthetic history failure")

                with patch.object(
                    route_module,
                    "QuickPrinterExportHistoryRepository",
                    return_value=FailingHistoryRepository(),
                ):
                    failed_history = client.post(
                        "/api/tests/quick-printer-export",
                        json={"date": "2026-08-28", "studentIds": ["1"]},
                    )
                self.assertEqual(failed_history.status_code, 503)
                self.assertNotIn("csv", failed_history.get_json())
                with closing(sqlite3.connect(db_path)) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM quick_printer_export_history").fetchone()[0],
                        0,
                    )

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
                self.assertNotIn("historyItems", success_payload)
                with closing(sqlite3.connect(db_path)) as connection:
                    stored = connection.execute(
                        "SELECT student_id, test_id, assignment_date, export_count "
                        "FROM quick_printer_export_history"
                    ).fetchall()
                self.assertEqual(stored, [("1", "unit-a", "2026-08-28", 1)])

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
                with closing(sqlite3.connect(db_path)) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM quick_printer_export_history").fetchone()[0],
                        1,
                    )
            finally:
                for active_patch in reversed(patches):
                    active_patch.stop()
                reset_progress_cache()


if __name__ == "__main__":
    unittest.main(verbosity=2)
