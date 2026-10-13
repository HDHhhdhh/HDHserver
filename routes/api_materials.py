from __future__ import annotations

from flask import Blueprint, current_app, jsonify, make_response, request

from core.material_state import (
    MaterialStateConflictError,
    MaterialStateRecoveryRequiredError,
    replace_material_state_component,
)
from core.paths import ASN_PATH, MAT_PATH, PAGE_FOLDERS_PATH
from routes.material_state_provider import (
    load_material_state_for_read,
    material_state_json_response,
)


bp_api_materials = Blueprint("api_materials", __name__)


def _normalize_material_state_revision(value: str | None) -> str:
    revision = str(value or "").strip()
    if revision.startswith("W/"):
        revision = revision[2:].strip()
    return revision.strip('"')


@bp_api_materials.route("/api/mat-assign", methods=["GET", "POST"])
def api_mat_assign():
    materials, assignments, page_folders, degraded = load_material_state_for_read(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )
    if request.method == "GET":
        return material_state_json_response(
            assignments,
            materials,
            assignments,
            page_folders,
            degraded=degraded,
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "code": "invalid_material_assignments"}), 400
    expected_revision = _normalize_material_state_revision(request.headers.get("If-Match"))
    if not expected_revision:
        return jsonify({"ok": False, "code": "material_state_revision_required"}), 428

    try:
        new_revision = replace_material_state_component(
            MAT_PATH,
            ASN_PATH,
            PAGE_FOLDERS_PATH,
            "assignments",
            body,
            expected_revision=expected_revision,
        )
    except MaterialStateConflictError as exc:
        response = make_response(
            jsonify({"ok": False, "code": "material_state_conflict"}),
            409,
        )
        response.headers["X-Material-State-Revision"] = exc.current_revision
        return response
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        current_app.logger.error("Material assignment write is unavailable: %s", exc)
        return jsonify({"ok": False, "code": "material_state_unavailable"}), 503
    except ValueError:
        return jsonify({"ok": False, "code": "invalid_material_assignments"}), 400
    except Exception:
        current_app.logger.exception("Material assignment write failed")
        return jsonify({"ok": False, "code": "material_state_unavailable"}), 503

    response = make_response("", 204)
    response.headers["X-Material-State-Revision"] = new_revision
    return response


@bp_api_materials.get("/api/materials")
def api_materials():
    materials, assignments, page_folders, degraded = load_material_state_for_read(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )
    return material_state_json_response(
        materials,
        materials,
        assignments,
        page_folders,
        degraded=degraded,
    )


__all__ = ("bp_api_materials",)
