from __future__ import annotations

from flask import current_app, jsonify, make_response

from core.material_state import (
    load_material_state,
    load_material_state_last_good,
    material_state_revision,
)


def load_material_state_for_read(
    materials_path,
    assignments_path,
    page_folders_path,
) -> tuple[dict, dict, dict, bool]:
    """Load one coherent snapshot while keeping unrelated server surfaces available."""
    try:
        materials, assignments, page_folders = load_material_state(
            materials_path,
            assignments_path,
            page_folders_path,
        )
    except Exception as primary_error:
        try:
            materials, assignments, page_folders = load_material_state_last_good(materials_path)
        except Exception:
            current_app.logger.error(
                "Material state read degraded without a last-good snapshot: %s",
                primary_error,
            )
            return {}, {}, {}, True
        current_app.logger.warning(
            "Material state read is using the last-good snapshot: %s",
            primary_error,
        )
        return materials, assignments, page_folders, True
    return materials, assignments, page_folders, False


def material_state_json_response(
    value: dict,
    materials: dict,
    assignments: dict,
    page_folders: dict,
    *,
    degraded: bool,
):
    response = make_response(jsonify(value))
    response.headers["X-Material-State-Revision"] = material_state_revision(
        materials,
        assignments,
        page_folders,
    )
    if degraded:
        response.headers["X-Material-State-Degraded"] = "1"
    return response


__all__ = ("load_material_state_for_read", "material_state_json_response")
