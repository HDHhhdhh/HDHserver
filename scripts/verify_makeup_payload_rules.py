from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from typing import Any, Dict
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ROUTE = ROOT / "routes" / "api_makeup_carryover.py"
RULES = ROOT / "core" / "makeup_payload_rules.py"
RENAMES = {
    "_norm_date": "normalize_makeup_date",
    "_norm_sid": "normalize_makeup_sid",
    "_norm_slot_list": "normalize_makeup_slots",
    "_normalize_schedule": "normalize_makeup_schedule",
    "_normalize_manual": "normalize_manual_makeups",
    "_normalize_payload": "normalize_makeup_payload",
    "_makeup_student_ids": "makeup_student_ids",
    "_makeup_revision": "makeup_revision",
}
# Captured from the dirty, approved source before extraction, not from HEAD.
BEFORE_HASHES = {
    "_norm_date": "78c5bde68fa84e8e650dd99e1d38225c2e7e7adcbf81e660af84db7c9fa8f851",
    "_norm_sid": "928d4a40ff516ee13469003c115eb6600aed0b3eaa5c12d131a2ff728d13ea10",
    "_norm_slot_list": "ba550be5411c02f237bbd5ac509375addfb93a00c1593d3aa319e997018153ae",
    "_normalize_schedule": "0f4945afe42d64c05c875ef7f11113bd35aa2eeda217b6a17c34ace37a0b061a",
    "_normalize_manual": "cbce336a98e0d01f817f892e79a21ec7c6ba4bf32f0876b1721ff531119f2aa8",
    "_normalize_payload": "bc9d0da0dd7503338ff24f077a18bcbe10baac693830243c764209fbfbe30fb5",
    "_makeup_student_ids": "9426235ec57f4b660ed8645154976a5cbd98684f84a71261638c8de42fc646ca",
    "_makeup_revision": "0aaaad3099109c29cd3ce2cce5807aec9e94226ee93df6f604d50b1715bd0a0c",
}
checks = 0


def same(actual: Any, expected: Any, label: str) -> None:
    global checks
    assert actual == expected, f"{label}: {actual!r} != {expected!r}"
    checks += 1


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_rules(before: bool, baseline_source: Path | None = None) -> dict[str, Any]:
    input_source = baseline_source or ROUTE
    if baseline_source is not None:
        same(hashlib.sha256(input_source.read_bytes()).hexdigest(), "f898c29493a2da39e8e64d423836242572a3c0e53901b16d6f7eabd489f5b23d", "captured route baseline bytes")
    tree = ast.parse((input_source if before else RULES).read_text(encoding="utf-8"))
    reverse = {new: old for old, new in RENAMES.items()}

    class OriginalNames(ast.NodeTransformer):
        def visit_Name(self, node):
            node.id = reverse.get(node.id, node.id)
            return node

        def visit_FunctionDef(self, node):
            node.name = reverse.get(node.name, node.name)
            return self.generic_visit(node)

    functions = []
    tombstone_branch = ast.dump(ast.parse(
        'if row.get("scheduledMakeup", row.get("scheduled_makeup", False)) is None:\n'
        '    normalized_row["scheduledMakeup"] = None\n'
    ).body[0], include_attributes=False)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in (RENAMES if before else reverse):
            original = copy.deepcopy(node) if before else OriginalNames().visit(copy.deepcopy(node))
            if not before and original.name in {"_normalize_manual", "_normalize_payload"}:
                removed = 0
                for parent in ast.walk(original):
                    body = getattr(parent, "body", None)
                    if isinstance(body, list):
                        kept = [child for child in body if ast.dump(child, include_attributes=False) != tombstone_branch]
                        removed += len(body) - len(kept)
                        parent.body = kept
                same(removed, 1, "only approved null-preservation branch excluded from frozen legacy body")
            actual = hashlib.sha256(ast.dump(original, include_attributes=False).encode("utf-8")).hexdigest()
            same(actual, BEFORE_HASHES[original.name], f"pre-extraction body {original.name}")
            functions.append(node)
    same(len(functions), 8, "all eight extracted bodies are present")
    if before:
        namespace = {"dt": dt, "hashlib": hashlib, "json": json, "Any": Any, "Dict": Dict}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROUTE), "exec"), namespace)
        return {new: namespace[old] for old, new in RENAMES.items()}
    allowed = {"__future__", "datetime", "hashlib", "json", "typing"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            same(set(alias.name for alias in node.names) <= allowed, True, "stdlib-only pure imports")
        elif isinstance(node, ast.ImportFrom):
            same(node.module in allowed, True, "no Flask/paths/storage/notification imports")
    import core.makeup_payload_rules as module
    same("app" in sys.modules or "core.paths" in sys.modules, False, "pure import has no runtime owner")
    return {name: getattr(module, name) for name in RENAMES.values()}


def payload_oracle(rules: dict[str, Any]) -> None:
    norm_date = rules["normalize_makeup_date"]
    for value, expected in [
        ("2024-02-29", "2024-02-29"), ("2026-02-29", ""), ("2026-02-30", ""),
        (" 2026-10-01T09:00:00 ", "2026-10-01"), ("20261001", "20261001"),
        ("2026-W40-4", "2026-W40-4"), ("2026-10-01 09:00:00", ""), (None, ""),
    ]:
        same(norm_date(value), expected, "existing date coercion")
    same(rules["normalize_makeup_slots"]([" 2 ", 1, 2, 3, "토2", True, 1.0, None]), [1, 2], "server integer slots stay 1/2")
    same(rules["normalize_makeup_slots"]("1,2"), [], "server does not parse a slot label")
    same(rules["normalize_makeup_sid"](0), "", "zero SID legacy falsy coercion")
    same(rules["normalize_makeup_sid"](7), "7", "numeric SID coercion")
    normalize = rules["normalize_makeup_payload"]
    fixture = {
        "unknownRoot": {"keepInput": True},
        "by_absence": {
            "2026-10-01": {
                " sid-a|2 ": {
                    "state": " OPEN ", "updatedAt": " touched ", "note": " 교재 ", "unknownRow": [1],
                    "scheduled_makeup": {
                        "student_id": " sid-b ", "makeup_date": "2026-10-04T10:00:00",
                        "makeup_times": [3, 2, 1, 2], "status": "scheduled", "created_by": " planner ",
                        "created_at": " born ", "updated_at": " changed ", "owned_extra": "false",
                        "owned_slots": [2, 3], "unknownSchedule": True,
                    },
                },
                "self": {"state": "self-study", "note": "교재실"},
                "completed|1": {"state": "carried", "scheduledMakeup": {"status": "completed"}},
                "legacy": True, "removed": False, "null": None,
            },
            "2026-02-30": {"invalid": True}, "invalid": {"bad": True},
        },
        "manual": {"2026-10-02": {
            " date-only ": {"sid": "sid-a", "slotless": True, "slot": 2, "state": " open ", "course": " 교재실 "},
            "default": {"sid": "sid-c", "slots": [], "slot": 2, "note": " 교재 "},
            "retired": {"sid": "sid-d", "state": "carried", "scheduledMakeup": {"status": "cancelled", "ownedSlots": [2], "ownedExtra": False}},
            "missing": {"slots": [1]}, "disabled": False,
        }},
    }
    expected = {
        "by_absence": {"2026-10-01": {
            "sid-a|2": {"state": "open", "updatedAt": "touched", "note": "교재", "scheduledMakeup": {
                "originalAbsenceId": "absence|2026-10-01|sid-a|2", "studentId": "sid-b", "makeupDate": "2026-10-04",
                "makeupTimes": [1, 2], "status": "scheduled", "createdAt": "born", "updatedAt": "changed",
                "createdBy": "planner", "ownedExtra": True, "ownedSlots": [2],
            }},
            "self": {"state": "self-study", "updatedAt": "", "note": "교재실"},
            "completed|1": {"state": "carried", "updatedAt": "", "note": "", "scheduledMakeup": {
                "originalAbsenceId": "absence|2026-10-01|completed|1", "studentId": "completed", "makeupDate": "",
                "makeupTimes": [1], "status": "completed", "createdAt": "", "updatedAt": "", "ownedExtra": False,
            }},
            "legacy": {"state": "carried", "updatedAt": "", "note": ""},
        }},
        "manual": {"2026-10-02": {
            "date-only": {"sid": "sid-a", "slots": [], "dateOnly": True, "state": "open", "createdAt": "", "updatedAt": "", "note": "", "course": "교재실"},
            "default": {"sid": "sid-c", "slots": [1], "dateOnly": False, "state": "", "createdAt": "", "updatedAt": "", "note": "교재", "course": ""},
            "retired": {"sid": "sid-d", "slots": [1], "dateOnly": False, "state": "carried", "createdAt": "", "updatedAt": "", "note": "", "course": "", "scheduledMakeup": {
                "originalAbsenceId": "manual|2026-10-02|retired", "studentId": "sid-d", "makeupDate": "", "makeupTimes": [2],
                "status": "cancelled", "createdAt": "", "updatedAt": "", "ownedExtra": False, "ownedSlots": [2],
            }},
        }},
    }
    before = digest(fixture)
    same(normalize(fixture), expected, "literal absence/manual/schedule payload")
    same(digest(fixture), before, "unknown input fields and source fixture remain unchanged")
    same(normalize(expected), expected, "normalization idempotence")
    same(rules["makeup_student_ids"](fixture), {"sid-a", "sid-b", "sid-c", "sid-d", "self", "completed", "legacy"}, "notification fanout follows SID rows and explicit linked SID")
    revision = hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    same(rules["makeup_revision"](fixture), revision, "revision from independent literal document")
    same(normalize({"2026-10-01": {"s": True}}), {"by_absence": {"2026-10-01": {"s": {"state": "carried", "updatedAt": "", "note": ""}}}, "manual": {}}, "legacy top-level absence map")
    for raw in [None, [], 3, "bad", {"by_absence": [], "manual": []}]:
        same(normalize(raw), {"by_absence": {}, "manual": {}}, "malformed projection remains legacy-compatible")
    schedule = rules["normalize_makeup_schedule"]
    same(schedule({"status": "scheduled"}, fallback_original_absence_id="absence|d|s", fallback_student_id="s"), None, "active schedule needs its date")
    same(schedule({"originalAbsenceId": "raw", "studentId": "s", "status": "cancelled", "ownedExtra": False}), {
        "originalAbsenceId": "raw", "studentId": "s", "makeupDate": "", "makeupTimes": [1], "status": "cancelled", "createdAt": "", "updatedAt": "", "ownedExtra": False,
    }, "cancelled metadata keeps detached ownership without inferring slots")


def tombstone_oracle(rules: dict[str, Any]) -> None:
    normalize = rules["normalize_makeup_payload"]
    schedule = {"makeupDate": "2026-10-04", "makeupTimes": [2]}
    for fields, expected in [
        ({}, False), ({"scheduledMakeup": None}, True), ({"scheduled_makeup": None}, True),
        ({"scheduledMakeup": None, "scheduled_makeup": schedule}, True),
        ({"scheduledMakeup": schedule, "scheduled_makeup": None}, False),
        ({"scheduledMakeup": False}, False), ({"scheduledMakeup": {}}, False),
        ({"scheduledMakeup": "invalid"}, False),
    ]:
        raw = {"by_absence": {"2026-10-01": {"s|2": {"state": "carried", **fields}}},
               "manual": {"2026-10-01": {"m": {"sid": "s", **fields}}}}
        before = digest(raw)
        result = normalize(raw)
        for row in [result["by_absence"]["2026-10-01"]["s|2"], result["manual"]["2026-10-01"]["m"]]:
            same("scheduledMakeup" in row and row["scheduledMakeup"] is None, expected, "literal tombstone/alias/missing/invalid distinction")
        same(normalize(result), result, "tombstone normalization is idempotent")
        same(digest(raw), before, "tombstone input immutable")
    missing = {"by_absence": {"2026-10-01": {"s": {"state": "carried"}}}, "manual": {}}
    deleted = copy.deepcopy(missing)
    deleted["by_absence"]["2026-10-01"]["s"]["scheduledMakeup"] = None
    same(rules["makeup_revision"](missing) != rules["makeup_revision"](deleted), True, "missing schedule and explicit deletion have distinct revisions")


def route_oracle(route_source: Path = ROUTE, *, tombstones: bool = True) -> None:
    from flask import Flask
    import core.storage as storage

    with tempfile.TemporaryDirectory(prefix="verify-makeup-payload-") as directory:
        base = Path(directory).resolve()
        paths = types.ModuleType("core.paths")
        paths.__file__ = str(base / "core" / "paths.py")
        hooks = types.ModuleType("core.student_notification_hooks")
        notifications = []
        hooks.enqueue_current_schedule_changes = lambda sids: notifications.append((set(sids), json.loads((base / "makeup_carryover.json").read_text("utf-8"))))
        with patch.dict(os.environ, {"DATA_DIR": str(base / "data"), "DATA_MIRROR_DIR": str(base / "mirror")}):
            exec(compile((ROOT / "core" / "paths.py").read_text("utf-8"), paths.__file__, "exec"), paths.__dict__)
            for value in vars(paths).values():
                if isinstance(value, Path):
                    same(value.resolve().is_relative_to(base), True, "injected path is inside OS temp")
            with patch.dict(sys.modules, {"core.paths": paths, "core.student_notification_hooks": hooks}):
                spec = importlib.util.spec_from_file_location("makeup_payload_fixture_route", route_source)
                route = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(route)
                same("app" in sys.modules, False, "dedicated route has no app import")
                carryover = route.MAKEUP_CARRYOVER_PATH
                same(carryover.resolve().is_relative_to(base), True, "carryover path injected before import")
                initial = {"by_absence": {"2026-10-01": {"s": {"state": "self-study", "updatedAt": "", "note": "교재실"}}}, "manual": {}}
                carryover.write_text(json.dumps(initial, ensure_ascii=False), "utf-8")
                io_paths = []

                def checked_load(path):
                    same(Path(path).resolve().is_relative_to(base), True, "route load temp-only")
                    io_paths.append(("load", Path(path)))
                    return storage.load(path)

                def checked_save(path, payload):
                    same(Path(path).resolve().is_relative_to(base), True, "route save temp-only")
                    io_paths.append(("save", Path(path)))
                    storage.save_atomic(path, payload)

                route.load = checked_load
                route.save_atomic = checked_save
                app = Flask("makeup-payload-oracle")
                app.register_blueprint(route.bp_api_makeup_carryover)
                client = app.test_client()
                revision = hashlib.sha256(json.dumps(initial, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

                def fingerprint():
                    return {str(p.relative_to(base)): (p.stat().st_mtime_ns, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in base.rglob("*") if p.is_file()}

                untouched = fingerprint()
                current = client.get("/api/makeup-carryover")
                same(current.status_code, 200, "GET status")
                same(current.get_json(), initial, "GET literal payload")
                same(current.headers.get("X-Makeup-Carryover-Revision"), revision, "GET independent revision")
                same(current.headers.get("ETag"), f'"{revision}"', "GET ETag")
                same(current.headers.get("Cache-Control"), "no-store", "GET cache behavior")
                same(fingerprint(), untouched, "GET bytes/mtime/SHA invariant")
                for body, headers, code, error in [
                    ([], {}, 400, None), (initial, {}, 428, "makeup_revision_required"),
                    (initial, {"If-Match": "stale"}, 409, "makeup_revision_conflict"),
                ]:
                    response = client.post("/api/makeup-carryover", json=body, headers=headers)
                    same(response.status_code, code, "invalid/revision failure status")
                    if error:
                        same(response.get_json(), {"ok": False, "error": error}, "revision failure body")
                        same(response.headers.get("X-Makeup-Carryover-Revision"), revision, "revision failure retains current revision")
                    same(fingerprint(), untouched, "failed request bytes/mtime/SHA invariant")
                    same(notifications, [], "failed request has no notification")
                requested = copy.deepcopy(initial)
                requested["by_absence"]["2026-10-01"]["s"]["state"] = "open"
                requested["manual"] = {"2026-10-02": {"m": {"sid": "s-peer", "slots": [], "dateOnly": True, "state": "open", "createdAt": "", "updatedAt": "", "note": "교재", "course": "교재실"}}}
                expected = copy.deepcopy(requested)
                expected["by_absence"]["2026-10-01"]["s"]["state"] = "self-study"
                accepted = client.post("/api/makeup-carryover", json=requested, headers={"If-Match": f'"{revision}"'})
                same(accepted.status_code, 200, "revisioned save status")
                same(accepted.get_json(), expected, "old-client open cannot reopen self-study; manual is independent")
                same(json.loads(carryover.read_text("utf-8")), expected, "actual atomic temp persistence")
                same(notifications, [({"s", "s-peer"}, expected)], "old/new SID hook observed after persisted commit")
                committed = fingerprint()
                stale = client.post("/api/makeup-carryover", json=initial, headers={"If-Match": revision})
                same(stale.status_code, 409, "stale request cannot remove newer manual row")
                same(fingerprint(), committed, "stale save preserves main/mirror/sidecar fingerprints")
                same(len(notifications), 1, "stale save never adds a hook")
                if tombstones:
                    note = "예정 정규수업 결석: 2026-09-25 2타임 / 직보 추가등원 예약으로 1회 차감: 2026-09-27 2타임 교재실 (s). 실제 이행 완료 표시는 아님. [approved-fixture-20260923]"
                    requested = copy.deepcopy(expected)
                    requested["by_absence"]["2026-09-25"] = {
                        "s|2": {"state": "carried", "scheduledMakeup": None, "note": note},
                        "alias|2": {"state": "carried", "scheduled_makeup": None, "note": note.replace("(s)", "(alias)")},
                        "legacy|2": {"state": "carried", "note": note.replace("(s)", "(legacy)")},
                    }
                    requested["manual"]["2026-10-02"]["m"]["scheduledMakeup"] = None
                    expected = copy.deepcopy(requested)
                    expected["by_absence"]["2026-09-25"]["alias|2"]["scheduledMakeup"] = expected["by_absence"]["2026-09-25"]["alias|2"].pop("scheduled_makeup")
                    for row in expected["by_absence"]["2026-09-25"].values():
                        row["updatedAt"] = ""
                    revision = client.get("/api/makeup-carryover").headers["X-Makeup-Carryover-Revision"]
                    saved = client.post("/api/makeup-carryover", json=requested, headers={"If-Match": revision})
                    same(saved.status_code, 200, "null deletion revisioned POST")
                    same(saved.get_json(), expected, "POST literal null payload including untouched rows")
                    same(json.loads(carryover.read_text("utf-8")), expected, "actual store retains null")
                    committed = fingerprint()
                    reloaded = client.get("/api/makeup-carryover")
                    same(reloaded.get_json(), expected, "GET roundtrip retains null")
                    same(fingerprint(), committed, "roundtrip GET has no store writes")
                    revision = hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                    same(reloaded.headers["X-Makeup-Carryover-Revision"], revision, "independent null-aware revision")
                    stale = client.post("/api/makeup-carryover", json=initial, headers={"If-Match": saved.headers["X-Makeup-Carryover-Revision"] + "-stale"})
                    same(stale.status_code, 409, "stale client cannot erase tombstones")
                    same(fingerprint(), committed, "stale tombstone save is byte/mtime/SHA invariant")
                    same(len(notifications), 2, "GET/stale tombstone save adds no notification")
                    fixture = base / "http-roundtrip.json"
                    fixture.write_text(json.dumps(reloaded.get_json(), ensure_ascii=False), "utf-8")
                    result = subprocess.run(["node", str(ROOT / "scripts/verify_makeup_projection_oracle.mjs"), "--roundtrip", str(fixture)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                    same(result.returncode, 0, "actual browser projection of HTTP roundtrip: " + result.stderr)
                    print(result.stdout.strip(), flush=True)
                same(all(p.is_relative_to(base) for _, p in io_paths), True, "all observed route I/O stays temporary")


def related_gates() -> None:
    import importlib
    import re
    import runpy

    with tempfile.TemporaryDirectory(prefix="verify-makeup-related-isolation-") as directory:
        base = Path(directory).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        paths = types.ModuleType("core.paths")
        paths.__file__ = str(base / "core" / "paths.py")
        hooks = types.ModuleType("core.student_notification_hooks")
        hooks.enqueue_current_schedule_changes = lambda *args, **kwargs: 0
        hooks.enqueue_progress_milestones = lambda *args, **kwargs: 0
        hooks.runtime_repository = lambda: None
        tree = ast.parse((ROOT / "core" / "student_notification_hooks.py").read_text("utf-8"))
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "student_schedule_changed_sids")
        namespace = {"json": json, "re": re}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<notification-pure-helper>", "exec"), namespace)
        hooks.student_schedule_changed_sids = namespace["student_schedule_changed_sids"]
        with patch.dict(os.environ, {"DATA_DIR": str(base / "data"), "DATA_MIRROR_DIR": str(base / "mirror")}):
            exec(compile((ROOT / "core" / "paths.py").read_text("utf-8"), paths.__file__, "exec"), paths.__dict__)
            assert all(value.resolve().is_relative_to(base) for value in vars(paths).values() if isinstance(value, Path))
            with patch.dict(sys.modules, {"core.paths": paths, "core.student_notification_hooks": hooks}):
                import core.storage as storage

                def guarded(operation):
                    def run(path, *args, **kwargs):
                        assert Path(path).resolve().is_relative_to(temp_root), f"non-temp runtime I/O: {path}"
                        return operation(path, *args, **kwargs)
                    return run

                with patch.object(storage, "load", guarded(storage.load)), patch.object(storage, "save_atomic", guarded(storage.save_atomic)), patch.object(storage, "file_lock", guarded(storage.file_lock)):
                    for relative in [
                        "scripts/verify_makeup_schedule_links.py",
                        "scripts/verify_makeup_sheet_route_safety.py",
                        "scripts/verify_makeup_sheet_additive_sync.py",
                    ]:
                        print("isolated related gate:", relative, flush=True)
                        try:
                            runpy.run_path(str(ROOT / relative), run_name="__main__")
                        except SystemExit as exc:
                            if exc.code not in (None, 0):
                                raise
                    matrix = importlib.import_module("scripts.verify_absence_makeup_matrix")
                    # The legacy offline fixture uses ROOT for ZIP member paths.
                    # Inject both owners so its files and backup stay in OS temp.
                    with patch.object(matrix, "ROOT", base), patch.object(matrix.offline_sync, "ROOT", base):
                        same(matrix.main(), 0, "full focused absence/makeup matrix")
                    same("app" in sys.modules, False, "related gates never import app")
                    print("all makeup related gates passed with OS-temp paths, guarded storage and notification stubs", flush=True)



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-extraction", action="store_true", help="Run the same literal oracle against pre-extraction source AST.")
    parser.add_argument("--related-gates", action="store_true", help="Run existing focused gates with OS-temp path and hook injection.")
    parser.add_argument("--baseline-source", type=Path, help="Replay the captured pre-extraction route with --before-extraction.")
    args = parser.parse_args()
    if args.baseline_source is not None and (not args.before_extraction or args.related_gates):
        parser.error("--baseline-source requires --before-extraction and excludes --related-gates")
    if args.related_gates:
        related_gates()
        return
    rules = load_rules(args.before_extraction, args.baseline_source)
    payload_oracle(rules)
    if not args.before_extraction:
        tombstone_oracle(rules)
    route_oracle(args.baseline_source or ROUTE, tombstones=not args.before_extraction)
    print(f"makeup payload {'before' if args.before_extraction else 'after'} extraction: {checks} assertions passed; runtime paths and hooks injected")


if __name__ == "__main__":
    main()
