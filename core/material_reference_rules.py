from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any


LOCAL_FILE_PREFIX = "/files/"
DIRECTORY_TOKEN_PREFIX = "DIR:"


def normalize_relative_file_path(value: Any) -> str:
    """Return a slash-normalized safe relative path without resolving the filesystem."""
    text = str(value or "").strip().replace("\\", "/").lstrip("/")
    parts: list[str] = []
    for part in text.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("parent path segments are not allowed")
        parts.append(part)
    return "/".join(parts)


def path_is_same_or_descendant(path: Any, prefix: Any) -> bool:
    candidate = normalize_relative_file_path(path)
    parent = normalize_relative_file_path(prefix)
    return bool(parent) and (candidate == parent or candidate.startswith(parent + "/"))


def _validated_store(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} store must be an object")
    return copy.deepcopy(value)


def _normalized_replacements(
    replacements: Iterable[tuple[Any, Any]],
) -> list[tuple[str, str]]:
    normalized: dict[str, str] = {}
    for old_value, new_value in replacements:
        old_path = normalize_relative_file_path(old_value)
        new_path = normalize_relative_file_path(new_value)
        if not old_path or not new_path:
            raise ValueError("replacement paths must be non-empty")
        previous = normalized.get(old_path)
        if previous is not None and previous != new_path:
            raise ValueError(f"conflicting replacement for {old_path}")
        normalized[old_path] = new_path
    if not normalized:
        raise ValueError("at least one replacement is required")
    return sorted(normalized.items(), key=lambda item: len(item[0]), reverse=True)


def _normalized_prefixes(prefixes: Iterable[Any]) -> list[str]:
    normalized: set[str] = set()
    for value in prefixes:
        path = normalize_relative_file_path(value)
        if path:
            normalized.add(path)
    if not normalized:
        raise ValueError("at least one path prefix is required")
    return sorted(normalized, key=len, reverse=True)


def _rewrite_relative_path(path: str, replacements: list[tuple[str, str]]) -> str:
    for old_path, new_path in replacements:
        if not path_is_same_or_descendant(path, old_path):
            continue
        suffix = path[len(old_path):]
        return new_path + suffix
    return path


def _matches_any_prefix(path: str, prefixes: list[str]) -> bool:
    return any(path_is_same_or_descendant(path, prefix) for prefix in prefixes)


def _local_file_url_parts(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith(LOCAL_FILE_PREFIX):
        return None
    remainder = value[len(LOCAL_FILE_PREFIX):]
    tail_index = len(remainder)
    for delimiter in ("?", "#"):
        index = remainder.find(delimiter)
        if index >= 0:
            tail_index = min(tail_index, index)
    relative = normalize_relative_file_path(remainder[:tail_index])
    if not relative:
        return None
    return relative, remainder[tail_index:]


def _rewrite_assignment_token(
    token: Any,
    replacements: list[tuple[str, str]],
    material_ids: set[str],
) -> Any:
    if not isinstance(token, str) or token in material_ids:
        return token

    if token.startswith(DIRECTORY_TOKEN_PREFIX):
        relative = normalize_relative_file_path(token[len(DIRECTORY_TOKEN_PREFIX):])
        rewritten = _rewrite_relative_path(relative, replacements)
        return DIRECTORY_TOKEN_PREFIX + rewritten if rewritten != relative else token

    local_url = _local_file_url_parts(token)
    if local_url is not None:
        relative, tail = local_url
        rewritten = _rewrite_relative_path(relative, replacements)
        return LOCAL_FILE_PREFIX + rewritten + tail if rewritten != relative else token

    relative = normalize_relative_file_path(token)
    rewritten = _rewrite_relative_path(relative, replacements)
    return rewritten if rewritten != relative else token


def _assignment_token_is_removed(
    token: Any,
    prefixes: list[str],
    removed_material_ids: set[str],
    all_material_ids: set[str],
) -> bool:
    token_id = str(token)
    if token_id in removed_material_ids:
        return True
    if not isinstance(token, str) or token in all_material_ids:
        return False

    if token.startswith(DIRECTORY_TOKEN_PREFIX):
        relative = normalize_relative_file_path(token[len(DIRECTORY_TOKEN_PREFIX):])
        return _matches_any_prefix(relative, prefixes)

    local_url = _local_file_url_parts(token)
    if local_url is not None:
        return _matches_any_prefix(local_url[0], prefixes)

    relative = normalize_relative_file_path(token)
    return _matches_any_prefix(relative, prefixes)


def rewrite_material_file_references(
    materials: Any,
    assignments: Any,
    page_folders: Any,
    replacements: Iterable[tuple[Any, Any]],
) -> tuple[dict, dict, dict]:
    """Return transformed copies for renamed or moved file-tree prefixes."""
    normalized = _normalized_replacements(replacements)
    next_materials = _validated_store(materials, "materials")
    next_assignments = _validated_store(assignments, "assignments")
    next_page_folders = _validated_store(page_folders, "pageFolders")
    material_ids = {str(material_id) for material_id in next_materials}

    for material_id, metadata in list(next_materials.items()):
        if not isinstance(metadata, dict):
            continue
        local_url = _local_file_url_parts(metadata.get("url"))
        if local_url is None:
            continue
        relative, tail = local_url
        rewritten = _rewrite_relative_path(relative, normalized)
        if rewritten != relative:
            metadata["url"] = LOCAL_FILE_PREFIX + rewritten + tail
            next_materials[material_id] = metadata

    for sid, tokens in list(next_assignments.items()):
        if not isinstance(tokens, list):
            continue
        next_assignments[sid] = [
            _rewrite_assignment_token(token, normalized, material_ids)
            for token in tokens
        ]

    for page, relative_value in list(next_page_folders.items()):
        if not isinstance(relative_value, str):
            continue
        relative = normalize_relative_file_path(relative_value)
        rewritten = _rewrite_relative_path(relative, normalized)
        if rewritten != relative:
            next_page_folders[page] = rewritten

    return next_materials, next_assignments, next_page_folders


def remove_material_file_references(
    materials: Any,
    assignments: Any,
    page_folders: Any,
    deleted_prefixes: Iterable[Any],
) -> tuple[dict, dict, dict]:
    """Return copies with references inside deleted file-tree prefixes removed."""
    prefixes = _normalized_prefixes(deleted_prefixes)
    next_materials = _validated_store(materials, "materials")
    next_assignments = _validated_store(assignments, "assignments")
    next_page_folders = _validated_store(page_folders, "pageFolders")
    all_material_ids = {str(material_id) for material_id in next_materials}
    removed_material_ids: set[str] = set()

    for material_id, metadata in list(next_materials.items()):
        if not isinstance(metadata, dict):
            continue
        local_url = _local_file_url_parts(metadata.get("url"))
        if local_url is None or not _matches_any_prefix(local_url[0], prefixes):
            continue
        removed_material_ids.add(str(material_id))
        next_materials.pop(material_id, None)

    for sid, tokens in list(next_assignments.items()):
        if not isinstance(tokens, list):
            continue
        next_assignments[sid] = [
            token
            for token in tokens
            if not _assignment_token_is_removed(
                token,
                prefixes,
                removed_material_ids,
                all_material_ids,
            )
        ]

    for page, relative_value in list(next_page_folders.items()):
        if not isinstance(relative_value, str):
            continue
        relative = normalize_relative_file_path(relative_value)
        if _matches_any_prefix(relative, prefixes):
            next_page_folders[page] = ""

    return next_materials, next_assignments, next_page_folders


__all__ = [
    "normalize_relative_file_path",
    "path_is_same_or_descendant",
    "remove_material_file_references",
    "rewrite_material_file_references",
]