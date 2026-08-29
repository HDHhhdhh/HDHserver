from __future__ import annotations


AUTO_VIDEO_ASSIGN_FIELD = "autoVideoAssignCount"
DEFAULT_AUTO_VIDEO_ASSIGN_COUNT = 3
ABLE_AUTO_VIDEO_ASSIGN_COUNT = 1
ABLE_CURRICULUM_KEY = "a:ble"
MIN_AUTO_VIDEO_ASSIGN_COUNT = 1
MAX_AUTO_VIDEO_ASSIGN_COUNT = 6


def coerce_auto_video_assign_count(
    value,
    default: int = DEFAULT_AUTO_VIDEO_ASSIGN_COUNT,
) -> int:
    try:
        count = int(round(float(value)))
    except Exception:
        count = default
    return max(MIN_AUTO_VIDEO_ASSIGN_COUNT, min(MAX_AUTO_VIDEO_ASSIGN_COUNT, count))


def is_able_curriculum_value(value) -> bool:
    return str(value or "").strip().casefold() == ABLE_CURRICULUM_KEY


def student_uses_able_curriculum(student: dict) -> bool:
    if not isinstance(student, dict):
        return False
    return is_able_curriculum_value(student.get("curriculum")) or is_able_curriculum_value(
        student.get("subCurriculum")
    )


def apply_able_auto_video_assign_default(student: dict) -> None:
    if student_uses_able_curriculum(student):
        student[AUTO_VIDEO_ASSIGN_FIELD] = ABLE_AUTO_VIDEO_ASSIGN_COUNT


def student_auto_video_assign_count(student: dict) -> int:
    if not isinstance(student, dict):
        return DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
    default = (
        ABLE_AUTO_VIDEO_ASSIGN_COUNT
        if student_uses_able_curriculum(student)
        else DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
    )
    return coerce_auto_video_assign_count(
        student.get(AUTO_VIDEO_ASSIGN_FIELD),
        default=default,
    )


__all__ = (
    "ABLE_AUTO_VIDEO_ASSIGN_COUNT",
    "AUTO_VIDEO_ASSIGN_FIELD",
    "DEFAULT_AUTO_VIDEO_ASSIGN_COUNT",
    "MAX_AUTO_VIDEO_ASSIGN_COUNT",
    "MIN_AUTO_VIDEO_ASSIGN_COUNT",
    "apply_able_auto_video_assign_default",
    "coerce_auto_video_assign_count",
    "is_able_curriculum_value",
    "student_auto_video_assign_count",
    "student_uses_able_curriculum",
)
