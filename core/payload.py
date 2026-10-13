from __future__ import annotations

import math
import re


class PayloadError(ValueError):
    pass


def expect_dict(value) -> dict:
    if not isinstance(value, dict):
        raise PayloadError("body must be a JSON object")
    return value


def student_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError("name must be a nonempty string")
    if not re.sub(r"[^0-9A-Za-z가-힣]", "", value):
        raise PayloadError("name must contain a supported SID character")
    return value


def _scalar(value) -> bool:
    return value is None or isinstance(value, (str, bool, int)) or (
        isinstance(value, float) and math.isfinite(value)
    )


def _json_value(value, depth=0) -> bool:
    if _scalar(value):
        return True
    if depth >= 8:
        return False
    if isinstance(value, list):
        return all(_json_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_value(item, depth + 1) for key, item in value.items())
    return False


def student_update(body) -> tuple[str, str, object]:
    body = expect_dict(body)
    sid, field = body.get("id"), body.get("field")
    if not isinstance(sid, (str, int)) or isinstance(sid, bool) or not str(sid).strip():
        raise PayloadError("id must identify a student")
    if not isinstance(field, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", field) is None:
        raise PayloadError("field must be an identifier of at most 40 characters")
    if "value" not in body:
        raise PayloadError("value is required")
    value = body["value"]
    valid = _scalar(value) or (isinstance(value, list) and all(_scalar(item) for item in value))
    if isinstance(value, dict) and field == "selfStudyDays":
        valid = all(key in {"day1", "day2", "day3", "day4", "day5"} and _scalar(item) for key, item in value.items())
    elif isinstance(value, dict) and field == "testLevelDefaults":
        # The editor preserves other categories and unknown legacy metadata.
        valid = _json_value(value)
    if not valid:
        raise PayloadError("value has an unsupported shape for this field")
    return str(sid), field, value
