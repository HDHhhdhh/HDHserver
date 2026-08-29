from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from typing import Final, TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


# These fields are removed by ``strip_tests_config_answer_links`` for public
# clients.  A subsequent whole-config write must not erase the academy copy.
PRESERVED_TEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "answerKeys",
        "answer_keys",
        "answerKey",
        "answer_key",
        "answers",
        "answerModes",
        "answer_modes",
        "answerLinkStatus",
        "answer_link_status",
        "answerUrl",
        "answer_url",
        "solutionUrl",
        "solution_url",
        "answerFileId",
        "answer_file_id",
        "solutionFileId",
        "solution_file_id",
        "url",
        "link",
    }
)
SOURCE_FILE_FIELDS: Final[tuple[str, ...]] = ("sourceFiles", "source_files")
TEST_RECORD_CLEARABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {"term", "examTerm"}
)
VALID_ANSWER_MODES: Final[frozenset[str]] = frozenset(
    {"choice_number", "answer_value", "manual_review"}
)


class TestsConfigWriteConflict(ValueError):
    """Raised when a whole-config write silently drops existing test IDs."""

    def __init__(self, missing_test_ids: Iterable[str]) -> None:
        self.missing_test_ids = tuple(sorted({str(value) for value in missing_test_ids}))
        super().__init__(
            f"tests-config write omitted {len(self.missing_test_ids)} existing test(s)"
        )


def tests_config_revision(config: JsonObject) -> str:
    """Return a stable revision token for optimistic whole-config writes."""

    encoded = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _test_id(test: JsonObject) -> str:
    raw_id = test.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, (str, int)):
        return ""
    return str(raw_id).strip()


def _validate_config_shape(config: JsonObject, label: str) -> None:
    categories = config.get("categories")
    if not isinstance(categories, dict):
        raise ValueError(f"{label}.categories must be an object")
    for category_key, category in categories.items():
        if not isinstance(category_key, str) or not isinstance(category, dict):
            raise ValueError(f"{label}.categories contains an invalid category")
        tests = category.get("tests")
        if tests is not None and not isinstance(tests, list):
            raise ValueError(f"{label}.categories[{category_key!r}].tests must be an array")


def _test_records(config: JsonObject) -> dict[str, JsonObject]:
    records: dict[str, JsonObject] = {}
    categories = config.get("categories")
    if not isinstance(categories, dict):
        return records
    for category in categories.values():
        if not isinstance(category, dict):
            continue
        tests = category.get("tests")
        if not isinstance(tests, list):
            continue
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_id = _test_id(test)
            if test_id:
                records[test_id] = test
    return records


def _merge_preserved_fields(current: JsonObject, incoming: JsonObject) -> None:
    for key in PRESERVED_TEST_FIELDS:
        if key not in incoming and key in current:
            incoming[key] = deepcopy(current[key])

    for source_key in SOURCE_FILE_FIELDS:
        current_source = current.get(source_key)
        incoming_source = incoming.get(source_key)
        if not isinstance(current_source, dict):
            continue
        if source_key not in incoming:
            incoming[source_key] = deepcopy(current_source)
        elif isinstance(incoming_source, dict):
            merged_source = deepcopy(current_source)
            merged_source.update(deepcopy(incoming_source))
            incoming[source_key] = merged_source


def _round_values(value: JsonValue | None, round_key: str) -> list[JsonValue] | None:
    if isinstance(value, dict):
        value = value.get(round_key)
    if isinstance(value, list):
        return value
    return None


def validate_test_answer_mode_consistency(test: JsonObject) -> None:
    """Reject explicit answer-mode data that contradicts its answer key.

    This is a consistency gate, not a classifier: it never derives a mode from
    an answer value. Tests without explicit modes remain valid for legacy and
    non-UNIT catalog entries.
    """

    raw_modes = test.get("answerModes")
    if raw_modes is None:
        raw_modes = test.get("answer_modes")
    if raw_modes is None:
        return

    try:
        problems = int(test.get("problems") or 0)
    except (TypeError, ValueError):
        raise ValueError("test problems must be an integer") from None
    if problems <= 0:
        raise ValueError("test problems must be positive when answer modes are present")

    default_round = str(test.get("round") or "1").strip() or "1"
    mode_rows = raw_modes if isinstance(raw_modes, dict) else {default_round: raw_modes}
    for raw_round, raw_mode_values in mode_rows.items():
        round_key = str(raw_round or "").strip()
        if not round_key or not isinstance(raw_mode_values, list) or len(raw_mode_values) != problems:
            raise ValueError("answerModes must contain one mode per problem")
        modes = [str(value or "").strip() for value in raw_mode_values]
        if any(mode not in VALID_ANSWER_MODES for mode in modes):
            raise ValueError("answerModes contains an unsupported or unverified mode")

        answers = _round_values(test.get("answerKeys"), round_key)
        if answers is None:
            answers = _round_values(test.get("answer_keys"), round_key)
        if answers is None and round_key == default_round:
            for field in ("answerKey", "answer_key", "answers"):
                answers = _round_values(test.get(field), round_key)
                if answers is not None:
                    break
        if answers is None or len(answers) != problems:
            raise ValueError("answerModes requires a same-length answer key for its round")

        for question_no, (raw_answer, mode) in enumerate(zip(answers, modes), start=1):
            answer = str(raw_answer or "").strip()
            if mode == "choice_number" and answer not in {"1", "2", "3", "4", "5"}:
                raise ValueError(
                    f"choice_number answer must be 1..5 at question {question_no}"
                )
            if mode == "answer_value" and not answer:
                raise ValueError(f"answer_value requires an answer at question {question_no}")


def validate_tests_config_answer_modes(config: JsonObject) -> None:
    for test in _test_records(config).values():
        validate_test_answer_mode_consistency(test)


def validate_new_test_answer_modes(test: JsonObject) -> None:
    raw_modes = test.get("answerModes")
    if raw_modes is None:
        raw_modes = test.get("answer_modes")
    if raw_modes is None:
        raise ValueError("new test requires explicit answerModes")
    validate_test_answer_mode_consistency(test)


def merge_tests_config_for_write(
    current: JsonObject,
    incoming: JsonObject,
    removed_test_ids: Iterable[str] = (),
) -> JsonObject:
    """Validate and merge a whole tests-config write.

    Existing test IDs are append/update-safe by default.  A caller must list
    IDs in ``removed_test_ids`` to intentionally delete them.  Answer keys and
    Drive solution metadata omitted by a network-stripped payload are restored
    from the current server copy while explicit incoming values remain intact.
    """

    _validate_config_shape(current, "current")
    _validate_config_shape(incoming, "incoming")

    current_records = _test_records(current)
    incoming_records = _test_records(incoming)
    allowed_removals = {str(value).strip() for value in removed_test_ids if str(value).strip()}
    missing_test_ids = set(current_records) - set(incoming_records) - allowed_removals
    if missing_test_ids:
        raise TestsConfigWriteConflict(missing_test_ids)

    merged = deepcopy(incoming)
    for test_id, incoming_test in _test_records(merged).items():
        if test_id not in current_records:
            validate_new_test_answer_modes(incoming_test)
    for test_id, incoming_test in _test_records(merged).items():
        current_test = current_records.get(test_id)
        if current_test is not None:
            _merge_preserved_fields(current_test, incoming_test)
    validate_tests_config_answer_modes(merged)
    return merged


def patch_test_config_record(
    current: JsonObject,
    target_category_key: str,
    incoming_test: JsonObject,
    *,
    category_label: str = "",
    clear_fields: Iterable[str] = (),
) -> tuple[JsonObject, JsonObject]:
    """Merge one test definition without transferring the whole catalog.

    The caller still owns optimistic revision checking and persistence.  The
    existing record supplies unknown fields, while explicitly provided test
    fields replace their current values.  Moving a test between categories
    preserves its identity and appends it to the destination category.
    """

    _validate_config_shape(current, "current")
    category_key = str(target_category_key or "").strip()
    if not category_key or not isinstance(incoming_test, dict):
        raise ValueError("invalid test patch")

    test_id = _test_id(incoming_test)
    if not test_id:
        raise ValueError("test patch requires an id")

    normalized_clear_fields: list[str] = []
    for raw_field in clear_fields:
        if not isinstance(raw_field, str):
            raise ValueError("test patch clear fields must be strings")
        field = raw_field.strip()
        if field not in TEST_RECORD_CLEARABLE_FIELDS:
            raise ValueError("test patch contains an unsupported clear field")
        if field not in normalized_clear_fields:
            normalized_clear_fields.append(field)

    matches: list[tuple[str, int, JsonObject]] = []
    categories = current.get("categories")
    assert isinstance(categories, dict)
    for source_key, raw_category in categories.items():
        if not isinstance(source_key, str) or not isinstance(raw_category, dict):
            continue
        tests = raw_category.get("tests")
        if not isinstance(tests, list):
            continue
        for index, raw_test in enumerate(tests):
            if isinstance(raw_test, dict) and _test_id(raw_test) == test_id:
                matches.append((source_key, index, raw_test))

    if len(matches) > 1:
        raise ValueError("test patch id is ambiguous")

    merged_test: JsonObject
    if matches:
        _source_key, _source_index, current_test = matches[0]
        merged_test = deepcopy(current_test)
        incoming_copy = deepcopy(incoming_test)
        for source_field in SOURCE_FILE_FIELDS:
            current_source = current_test.get(source_field)
            incoming_source = incoming_copy.get(source_field)
            if isinstance(current_source, dict) and isinstance(incoming_source, dict):
                merged_source = deepcopy(current_source)
                merged_source.update(incoming_source)
                incoming_copy[source_field] = merged_source
        merged_test.update(incoming_copy)
    else:
        merged_test = deepcopy(incoming_test)
        validate_new_test_answer_modes(merged_test)

    for field in normalized_clear_fields:
        merged_test.pop(field, None)
    validate_test_answer_mode_consistency(merged_test)

    merged = deepcopy(current)
    merged_categories = merged.get("categories")
    assert isinstance(merged_categories, dict)

    if matches:
        source_key, source_index, _current_test = matches[0]
        source_category = merged_categories.get(source_key)
        if not isinstance(source_category, dict):
            raise ValueError("invalid source category")
        source_tests = source_category.get("tests")
        if not isinstance(source_tests, list):
            raise ValueError("invalid source test list")
        if source_key == category_key:
            source_tests[source_index] = merged_test
            return merged, deepcopy(merged_test)
        source_tests.pop(source_index)

    target_category = merged_categories.get(category_key)
    if target_category is None:
        target_category = {
            "label": str(category_label or category_key).strip() or category_key,
            "tests": [],
        }
        merged_categories[category_key] = target_category
    if not isinstance(target_category, dict):
        raise ValueError("invalid target category")
    target_tests = target_category.get("tests")
    if target_tests is None:
        target_tests = []
        target_category["tests"] = target_tests
    if not isinstance(target_tests, list):
        raise ValueError("invalid target test list")
    if category_label and not str(target_category.get("label") or "").strip():
        target_category["label"] = str(category_label).strip()
    target_tests.append(merged_test)
    return merged, deepcopy(merged_test)
