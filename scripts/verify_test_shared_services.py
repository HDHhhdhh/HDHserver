from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.storage import InterProcessFileLock, save_atomic  # noqa: E402
from core.test_answer_links import resolve_test_assignment_answer_url  # noqa: E402
from routes import api_tests  # noqa: E402


def _resolver_fixture() -> tuple[dict, dict]:
    return (
        {
            "categories": {
                "REVIEW": {
                    "tests": [
                        {
                            "id": "review-direct",
                            "name": "Direct",
                            "round": "1",
                            "answerUrl": "https://config.example/should-not-win",
                        },
                        {
                            "id": "review-config",
                            "name": "Config",
                            "round": "1",
                            "sourceFiles": {"solutionFileId": "CONFIG_FILE_ID"},
                        },
                    ],
                },
                "ILSAN_PAST": {
                    "tests": [
                        {
                            "id": "ilsan-config",
                            "name": "Ilsan",
                            "round": "1",
                            "difficulty": "\uc0c1",
                            "answerUrl": "https://config.example/ilsan",
                        },
                    ],
                },
            },
        },
        {
            "review-direct": {"1": {"answerUrl": "https://map.example/should-not-win"}},
            "review-config": {"1": {"answerUrl": "https://map.example/should-not-win"}},
            "unit-map": {"2": {"answerUrl": "https://map.example/unit-round-2"}},
        },
    )


def _verify_resolver() -> None:
    config, link_map = _resolver_fixture()
    before = copy.deepcopy((config, link_map))

    assert resolve_test_assignment_answer_url(
        {
            "id": "review-direct",
            "category": "REVIEW",
            "round": "1",
            "answerUrl": "https://direct.example/assignment",
        },
        tests_config=config,
        answer_link_map=link_map,
    ) == "https://direct.example/assignment"

    assert resolve_test_assignment_answer_url(
        {"id": "review-config", "category": "REVIEW", "round": "1"},
        tests_config=config,
        answer_link_map=link_map,
    ) == "https://drive.google.com/file/d/CONFIG_FILE_ID/view?usp=drivesdk"

    assert resolve_test_assignment_answer_url(
        {"id": "unit-map_r2", "category": "UNIT", "round": "round 2"},
        tests_config=config,
        answer_link_map=link_map,
    ) == "https://map.example/unit-round-2"

    assert resolve_test_assignment_answer_url(
        {
            "category": "ILSAN_PAST",
            "name": "Ilsan",
            "round": "1",
            "difficulty": "\uc0c1",
        },
        tests_config=config,
        answer_link_map=link_map,
    ) == "https://config.example/ilsan"

    assert resolve_test_assignment_answer_url(
        {"category": "TRAINING_PACK", "answerUrl": "https://unsupported.example"},
        tests_config=config,
        answer_link_map=link_map,
    ) == ""
    assert (config, link_map) == before


def _verify_tests_config_lock() -> None:
    original_path = api_tests.TESTS_CFG_PATH
    try:
        with tempfile.TemporaryDirectory(prefix="test-shared-lock-") as temp_dir:
            config_path = Path(temp_dir) / "tests-config.json"
            config_path.write_text("{}", encoding="utf-8")
            api_tests.TESTS_CFG_PATH = config_path

            owner = api_tests._tests_config_lock()
            assert isinstance(owner, InterProcessFileLock)
            assert owner.lock_path == str(config_path) + ".lock"
            with owner:
                assert Path(owner.lock_path).is_file()
                contender = api_tests._tests_config_lock()
                contender.timeout_sec = 0.1
                try:
                    contender.acquire()
                except TimeoutError:
                    pass
                else:
                    contender.release()
                    raise AssertionError("tests-config lock allowed a competing writer")
            assert not Path(owner.lock_path).exists()
    finally:
        api_tests.TESTS_CFG_PATH = original_path


def _verify_admin_record_route() -> None:
    app = Flask("test-shared-services")
    app.register_blueprint(api_tests.bp_api_tests)
    original = {
        "TESTS_PATH": api_tests.TESTS_PATH,
        "LOGS_PATH": api_tests.LOGS_PATH,
        "STU_PATH": api_tests.STU_PATH,
        "TESTS_CFG_PATH": api_tests.TESTS_CFG_PATH,
        "TEST_ANSWER_LINK_MAP_PATH": api_tests.TEST_ANSWER_LINK_MAP_PATH,
        "academy_network_allowed": api_tests.academy_network_allowed,
        "_legacy_test_record_candidates": api_tests._legacy_test_record_candidates,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="test-shared-route-") as temp_dir:
            root = Path(temp_dir)
            api_tests.TESTS_PATH = root / "tests.json"
            api_tests.LOGS_PATH = root / "logs.json"
            api_tests.STU_PATH = root / "students.json"
            api_tests.TESTS_CFG_PATH = root / "tests-config.json"
            api_tests.TEST_ANSWER_LINK_MAP_PATH = root / "test_answer_link_map.json"
            api_tests._legacy_test_record_candidates = lambda: []
            for path, value in (
                (api_tests.TESTS_PATH, {}),
                (api_tests.LOGS_PATH, {}),
                (api_tests.STU_PATH, []),
                (
                    api_tests.TESTS_CFG_PATH,
                    {
                        "categories": {
                            "UNIT": {
                                "tests": [
                                    {
                                        "id": "route-unit",
                                        "sourceId": "route-source",
                                        "name": "Route Unit",
                                        "round": "2",
                                    }
                                ]
                            }
                        }
                    },
                ),
                (
                    api_tests.TEST_ANSWER_LINK_MAP_PATH,
                    {"route-source": {"2": {"answerUrl": "https://map.example/route"}}},
                ),
            ):
                save_atomic(path, value, mirror=False)

            api_tests.academy_network_allowed = lambda: True
            inside = app.test_client().get(
                "/api/tests-records?test_id=route-unit&recent_days=1"
            )
            assert inside.status_code == 200
            assert inside.get_json()["answerUrl"] == "https://map.example/route"

            api_tests.academy_network_allowed = lambda: False
            outside = app.test_client().get(
                "/api/tests-records?test_id=route-unit&recent_days=1"
            )
            assert outside.status_code == 200
            assert outside.get_json()["answerUrl"] == ""
    finally:
        for name, value in original.items():
            setattr(api_tests, name, value)


def _verify_source_boundary() -> None:
    source = (ROOT / "routes" / "api_tests.py").read_text(encoding="utf-8")
    assert "from routes.api_basic import _InterProcessFileLock" not in source
    assert "from routes.api_basic import _test_assignment_answer_url" not in source
    assert "from core.test_answer_links import resolve_test_assignment_answer_url" in source
    assert "file_lock(TESTS_CFG_PATH" in source


def main() -> int:
    _verify_resolver()
    _verify_tests_config_lock()
    _verify_admin_record_route()
    _verify_source_boundary()
    print("test shared-service checks passed: resolver, lock, route, private-import boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
