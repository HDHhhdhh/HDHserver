from __future__ import annotations

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


class TestsConfigWriteConflict(ValueError):
    """Raised when a whole-config write silently drops existing test IDs."""

    def __init__(self, missing_test_ids: Iterable[str]) -> None:
        self.missing_test_ids = tuple(sorted({str(value) for value in missing_test_ids}))
        super().__init__(
            f"tests-config write omitted {len(self.missing_test_ids)} existing test(s)"
        )


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
        current_test = current_records.get(test_id)
        if current_test is not None:
            _merge_preserved_fields(current_test, incoming_test)
    return merged
