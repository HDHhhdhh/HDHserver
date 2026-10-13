from __future__ import annotations

import re


_SUPPORTED_CATEGORIES = {"UNIT", "REVIEW", "SCHOOL_PAST", "ILSAN_PAST"}


def _normalize_round(value) -> str:
    match = re.search(r"\d+", str(value or "1").strip())
    return match.group(0) if match else "1"


def _drive_url(file_id) -> str:
    value = str(file_id or "").strip()
    return f"https://drive.google.com/file/d/{value}/view?usp=drivesdk" if value else ""


def _entry_url(entry) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("answerUrl", "answer_url", "solutionUrl", "solution_url", "url", "link"):
            value = str(entry.get(key) or "").strip()
            if value:
                return value
    return ""


def _direct_url(item: dict) -> str:
    direct = _entry_url(item)
    if direct:
        return direct
    source_files = item.get("sourceFiles") or item.get("source_files")
    return _entry_url(source_files) if isinstance(source_files, dict) else ""


def _category_key(item: dict) -> str:
    source = " ".join(
        str(item.get(key) or "")
        for key in ("category", "categoryKey", "categoryLabel", "label", "type")
    )
    upper = source.upper()
    compact = re.sub(r"\s+", "", source)
    if re.search(r"\bUNIT\b", upper) or "\ub2e8\uc6d0\ud3c9\uac00" in source or "\ub2e8\uc6d0" in source:
        return "UNIT"
    if "REVIEW" in upper or "\ubcf5\uc2b5" in compact:
        return "REVIEW"
    if (
        "SCHOOL_PAST" in upper
        or "SCHOOL" in upper
        or "\ud559\uad70\uc9c0" in compact
        or "\ud559\uad50\ubcc4" in compact
    ):
        return "SCHOOL_PAST"
    if "ILSAN_PAST" in upper or "ILSAN" in upper or "\uc77c\uc0b0" in compact:
        return "ILSAN_PAST"
    return ""


def _difficulty(category_key: str, value) -> str:
    text = str(value or "").strip()
    if category_key == "ILSAN_PAST":
        if "\uadf8\ub798\ud504" in text:
            return "\uadf8\ub798\ud504 \ud3ec\ud568"
        if text in {"\uc911\uc0c1", "\uc0c1"}:
            return text
        if text == "\uc911" or "\uc911" in text:
            return "\uc911\uc0c1"
    return text


def _config_url(test: dict) -> str:
    if not isinstance(test, dict):
        return ""
    direct = _entry_url(test)
    if direct:
        return direct
    source_files = test.get("sourceFiles") or test.get("source_files")
    if isinstance(source_files, dict):
        direct = _entry_url(source_files)
        if direct:
            return direct
        for key in ("solutionFileId", "solution_file_id", "answerFileId", "answer_file_id"):
            url = _drive_url(source_files.get(key))
            if url:
                return url
    for key in ("solutionFileId", "solution_file_id", "answerFileId", "answer_file_id"):
        url = _drive_url(test.get(key))
        if url:
            return url
    return ""


def _candidate_ids(item: dict) -> list[str]:
    candidates: list[str] = []
    for key in ("id", "testId", "sourceId", "source_id"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        candidates.append(raw)
        stripped = re.sub(r"_r[123]$", "", raw)
        if stripped != raw:
            candidates.append(stripped)
    return list(dict.fromkeys(candidates))


def _configured_test(item: dict, config: dict) -> dict:
    category_key = _category_key(item)
    category = (config.get("categories") or {}).get(category_key)
    tests = category.get("tests") if isinstance(category, dict) else []
    if not isinstance(tests, list):
        return {}

    ids = set(_candidate_ids(item))
    if ids:
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_ids = {
                str(test.get("id") or "").strip(),
                str(test.get("sourceId") or test.get("source_id") or "").strip(),
            }
            if ids.intersection(value for value in test_ids if value):
                return test

    item_name = str(item.get("name") or item.get("testName") or "").strip()
    item_label = str(item.get("label") or "").strip()
    item_round = _normalize_round(item.get("round"))
    item_curriculum = str(item.get("curriculum") or "").strip()
    item_difficulty = _difficulty(category_key, item.get("difficulty"))
    item_term = str(item.get("term") or "").strip()
    for test in tests:
        if not isinstance(test, dict):
            continue
        test_name = str(test.get("name") or "").strip()
        name_ok = item_name == test_name if item_name else bool(test_name and test_name in item_label)
        if not name_ok:
            continue
        if item_round and _normalize_round(test.get("round")) != item_round:
            continue
        if item_curriculum and str(test.get("curriculum") or "").strip() != item_curriculum:
            continue
        if item_difficulty and _difficulty(category_key, test.get("difficulty")) != item_difficulty:
            continue
        if item_term and str(test.get("term") or "").strip() != item_term:
            continue
        return test
    return {}


def resolve_test_assignment_answer_url(
    item: dict,
    *,
    tests_config: dict | None = None,
    answer_link_map: dict | None = None,
) -> str:
    """Resolve the established assignment -> config -> generated-map precedence."""
    if not isinstance(item, dict) or _category_key(item) not in _SUPPORTED_CATEGORIES:
        return ""

    direct = _direct_url(item)
    if direct:
        return direct

    config = tests_config if isinstance(tests_config, dict) else {}
    configured = _configured_test(item, config)
    configured_url = _config_url(configured)
    if configured_url:
        return configured_url

    link_map = answer_link_map if isinstance(answer_link_map, dict) else {}
    round_key = _normalize_round(item.get("round"))
    for candidate in (item, configured):
        for test_id in _candidate_ids(candidate):
            rounds = link_map.get(test_id)
            if isinstance(rounds, dict):
                url = _entry_url(rounds.get(round_key))
                if url:
                    return url
            url = _entry_url(rounds)
            if url:
                return url
    return ""
