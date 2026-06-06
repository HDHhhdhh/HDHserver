from __future__ import annotations

GHOST_STUDENT_ID = "ghost-outside-test"
GHOST_STUDENT_WRITE_ERROR = "ghost_student_read_only"


def is_ghost_student_sid(sid) -> bool:
    return str(sid or "").strip() == GHOST_STUDENT_ID


def mapping_contains_ghost_student_sid(value) -> bool:
    if not isinstance(value, dict):
        return False
    for key, nested in value.items():
        if is_ghost_student_sid(key):
            return True
        if isinstance(nested, dict) and mapping_contains_ghost_student_sid(nested):
            return True
    return False
