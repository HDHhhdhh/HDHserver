from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_materials  # noqa: E402


def _revision(materials: dict, assignments: dict, page_folders: dict) -> str:
    payload = {
        "materials": materials,
        "assignments": assignments,
        "pageFolders": page_folders,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _primary_fingerprints(paths: tuple[Path, ...]) -> dict[str, tuple[int, str]]:
    return {
        path.name: (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in paths
    }


def _assert_primary_unchanged(
    paths: tuple[Path, ...],
    before: dict[str, tuple[int, str]],
    label: str,
) -> None:
    assert _primary_fingerprints(paths) == before, f"{label} changed a primary material store"


def main() -> int:
    route_source = (ROOT / "routes" / "api_materials.py").read_text("utf-8")
    provider_source = (ROOT / "routes" / "material_state_provider.py").read_text("utf-8")
    basic_source = (ROOT / "routes" / "api_basic.py").read_text("utf-8")
    app_source = (ROOT / "app.py").read_text("utf-8")

    assert '@bp_api_materials.route("/api/mat-assign", methods=["GET", "POST"])' in route_source
    assert '@bp_api_materials.get("/api/materials")' in route_source
    assert '"/api/mat-assign"' not in basic_source
    assert '"/api/materials"' not in basic_source
    assert "def load_material_state_for_read(" in provider_source
    assert "from routes.api_materials import bp_api_materials" in app_source
    assert "app.register_blueprint(bp_api_materials)" in app_source

    with tempfile.TemporaryDirectory(prefix="verify-material-routes-") as tmp:
        root = Path(tmp)
        materials_path = root / "materials.json"
        assignments_path = root / "mat_assign.json"
        page_folders_path = root / "page_folders.json"
        primary_paths = (materials_path, assignments_path, page_folders_path)

        materials = {
            "m1": {
                "url": "/files/교재/m1.pdf",
                "relative": "교재/m1.pdf",
                "unknown": {"keep": True},
            }
        }
        assignments = {
            "s1": ["m1", "DIR:교재", {"unknown": "keep"}],
        }
        page_folders = {
            "materials": "교재",
            "unknown": {"keep": True},
        }
        for path, value in zip(primary_paths, (materials, assignments, page_folders)):
            path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")

        original_paths = (
            api_materials.MAT_PATH,
            api_materials.ASN_PATH,
            api_materials.PAGE_FOLDERS_PATH,
        )
        api_materials.MAT_PATH = materials_path
        api_materials.ASN_PATH = assignments_path
        api_materials.PAGE_FOLDERS_PATH = page_folders_path
        try:
            app = Flask("verify-material-routes")
            app.register_blueprint(api_materials.bp_api_materials)
            client = app.test_client()

            expected_revision = _revision(materials, assignments, page_folders)
            materials_response = client.get("/api/materials")
            assignments_response = client.get("/api/mat-assign")
            assert materials_response.status_code == 200
            assert materials_response.get_json() == materials
            assert materials_response.headers.get("X-Material-State-Revision") == expected_revision
            assert assignments_response.status_code == 200
            assert assignments_response.get_json() == assignments
            assert assignments_response.headers.get("X-Material-State-Revision") == expected_revision
            assert "X-Material-State-Degraded" not in materials_response.headers
            assert "X-Material-State-Degraded" not in assignments_response.headers

            before_failures = _primary_fingerprints(primary_paths)
            retired_material_post = client.post("/api/materials", json={"replace": True})
            invalid_body = client.post(
                "/api/mat-assign",
                json=[],
                headers={"If-Match": expected_revision},
            )
            missing_revision = client.post("/api/mat-assign", json={"s1": ["m1", "m2"]})
            stale_revision = client.post(
                "/api/mat-assign",
                json={"s1": ["stale"]},
                headers={"If-Match": "0" * 64},
            )
            assert retired_material_post.status_code == 405
            assert invalid_body.status_code == 400
            assert (invalid_body.get_json() or {}).get("code") == "invalid_material_assignments"
            assert missing_revision.status_code == 428
            assert (missing_revision.get_json() or {}).get("code") == "material_state_revision_required"
            assert stale_revision.status_code == 409
            assert (stale_revision.get_json() or {}).get("code") == "material_state_conflict"
            assert stale_revision.headers.get("X-Material-State-Revision") == expected_revision
            _assert_primary_unchanged(primary_paths, before_failures, "validated route failures")

            next_assignments = {
                "s1": ["m1", "m2", {"unknown": "keep"}],
                "s2": ["DIR:교재"],
            }
            expected_next_revision = _revision(materials, next_assignments, page_folders)
            saved = client.post(
                "/api/mat-assign",
                json=next_assignments,
                headers={"If-Match": f'W/"{expected_revision}"'},
            )
            assert saved.status_code == 204
            assert saved.headers.get("X-Material-State-Revision") == expected_next_revision
            assert json.loads(materials_path.read_text("utf-8")) == materials
            assert json.loads(assignments_path.read_text("utf-8")) == next_assignments
            assert json.loads(page_folders_path.read_text("utf-8")) == page_folders

            last_good_path = root / "instance" / "material_state_last_good.json"
            assert last_good_path.is_file()
            journal_path = root / "material_state_transaction.json"
            journal_path.write_text("{broken", "utf-8")
            before_degraded = _primary_fingerprints(primary_paths)

            degraded_materials = client.get("/api/materials")
            degraded_assignments = client.get("/api/mat-assign")
            assert degraded_materials.status_code == 200
            assert degraded_materials.get_json() == materials
            assert degraded_materials.headers.get("X-Material-State-Degraded") == "1"
            assert degraded_materials.headers.get("X-Material-State-Revision") == expected_next_revision
            assert degraded_assignments.status_code == 200
            assert degraded_assignments.get_json() == next_assignments
            assert degraded_assignments.headers.get("X-Material-State-Degraded") == "1"
            assert degraded_assignments.headers.get("X-Material-State-Revision") == expected_next_revision

            blocked_write = client.post(
                "/api/mat-assign",
                json={"s1": ["must-not-write"]},
                headers={"If-Match": expected_next_revision},
            )
            assert blocked_write.status_code == 503
            assert (blocked_write.get_json() or {}).get("code") == "material_state_unavailable"
            _assert_primary_unchanged(primary_paths, before_degraded, "degraded write")
        finally:
            (
                api_materials.MAT_PATH,
                api_materials.ASN_PATH,
                api_materials.PAGE_FOLDERS_PATH,
            ) = original_paths

    print(
        "material route checks passed: dedicated blueprint, independent revision oracle, "
        "coherent GETs, revisioned assignment save, degraded reads, and hash-identical failures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
