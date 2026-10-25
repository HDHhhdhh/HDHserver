from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, g, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_student_bootstrap  # noqa: E402
from core.student_schedule_rules import student_is_self_study_on_date  # noqa: E402
from routes.student_bootstrap_projection import (  # noqa: E402
    StudentBootstrapProjectionDependencies,
)


HISTORICAL_DATE = "2026-05-31"
TODAY = "2026-06-01"
SID = "sid-a"
GHOST_SID = "ghost-outside-test"


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(path: Path) -> tuple[bytes, str]:
    content = path.read_bytes()
    return content, hashlib.sha256(content).hexdigest()


def _assert_all_unchanged(
    before: dict[Path, tuple[bytes, str]],
    label: str,
) -> None:
    for path, expected in before.items():
        actual = _fingerprint(path)
        assert actual[0] == expected[0], f"{label} changed {path.name} bytes"
        assert actual[1] == expected[1], f"{label} changed {path.name} SHA-256"


def main() -> int:
    previous_watch_path = api_student_bootstrap.WATCH_PATH
    previous_load = api_student_bootstrap.load
    previous_academy_allowed = api_student_bootstrap.academy_network_allowed
    previous_ip_allowed = api_student_bootstrap.ip_allowed
    try:
        with tempfile.TemporaryDirectory(
            prefix="verify-student-bootstrap-routes-"
        ) as raw_root:
            root = Path(raw_root)
            paths = {
                name: root / f"{name}.json"
                for name in (
                    "students",
                    "videos",
                    "updates",
                    "watch",
                    "progress",
                    "absent",
                    "materials",
                    "assigns",
                    "logs",
                )
            }
            fixtures = {
                "students": [
                    {
                        "id": SID,
                        "name": "가학생",
                        "curriculum": "ALG",
                        "subCurriculum": "BASE",
                        "day1": "월 13:00",
                    }
                ],
                "videos": [
                    {
                        "mid": "mid-a",
                        "title": "배정 영상",
                        "chapter": "1",
                        "curriculum": "ALG",
                        "subCurriculum": "BASE",
                        "url": "https://video.example/mid-a",
                    },
                    {
                        "mid": "mid-review",
                        "title": "복습 영상",
                        "chapter": "2",
                        "curriculum": "ALG",
                        "subCurriculum": "BASE",
                        "url": "https://video.example/mid-review",
                    },
                ],
                "updates": {
                    HISTORICAL_DATE: {
                        SID: {
                            "videos": ["mid-a"],
                            "source": "auto",
                            "unknown": {"keep": True},
                        }
                    },
                    TODAY: {
                        SID: {"videos": ["mid-a"], "source": "auto"}
                    },
                },
                "watch": {
                    "2026-05-20": {
                        SID: {
                            "mid-a": {
                                "last": 10,
                                "dur": 100,
                                "updatedAt": 10,
                            }
                        }
                    },
                    "2026-05-30": {
                        SID: {
                            "mid-a": {
                                "last": 95,
                                "dur": 100,
                                "updatedAt": 20,
                            }
                        }
                    },
                },
                "progress": {},
                "absent": {"by_date": {}, "by_student": {}},
                "materials": {
                    "mat-a": {
                        "id": "mat-a",
                        "title": "자료 A",
                        "url": "/files/material-a.pdf",
                    }
                },
                "assigns": {
                    SID: {
                        "materials": ["mat-a"],
                        "unknown": {"keep": True},
                    }
                },
                "logs": {
                    HISTORICAL_DATE: {
                        SID: {
                            "homeworkTable": [
                                {"book": "교재A", "this": "1-3"}
                            ]
                        }
                    },
                    TODAY: {SID: {}},
                },
            }
            for name, value in fixtures.items():
                _write_json(paths[name], value)

            calls: dict[str, object] = {
                "loads": [],
                "auto": [],
                "log_reads": 0,
                "review": 0,
            }
            policy = {"inside": True, "registered": True}

            def file_load(path: Path):
                calls["loads"].append(Path(path).name)
                return deepcopy(_read_json(Path(path)))

            class FixtureLogRepository:
                def read_entry(self, date: str, sid: str):
                    calls["log_reads"] += 1
                    logs = _read_json(paths["logs"])
                    return SimpleNamespace(
                        entry=deepcopy((logs.get(date) or {}).get(sid) or {})
                    )

                def read_json_map(self):
                    return deepcopy(_read_json(paths["logs"]))

            def restrict_videos(items: list[dict], academy_allowed: bool):
                result = deepcopy(items)
                if academy_allowed:
                    return result
                for item in result:
                    item.pop("url", None)
                    item["playbackRestricted"] = True
                return result

            def review_projection(
                _student,
                _videos,
                _progress,
                _watch,
                _date,
                _assigned,
                academy_allowed,
            ):
                calls["review"] += 1
                item = {
                    "mid": "mid-review",
                    "title": "복습 영상",
                    "chapter": "2",
                    "reviewStatus": "done",
                }
                if not academy_allowed:
                    item["playbackRestricted"] = True
                return [item]

            def restrict_tests(items: list[dict], academy_allowed: bool):
                result = deepcopy(items)
                if academy_allowed:
                    return result
                for item in result:
                    item.pop("answerUrl", None)
                    item["answerRestricted"] = True
                return result

            def load_updates_with_auto_assign(**kwargs):
                calls["auto"].append(deepcopy(kwargs))
                return file_load(paths["updates"])

            dependencies = StudentBootstrapProjectionDependencies(
                students_path=paths["students"],
                videos_path=paths["videos"],
                updates_path=paths["updates"],
                watch_path=paths["watch"],
                load=file_load,
                load_absent=lambda: file_load(paths["absent"]),
                load_progress=lambda: file_load(paths["progress"]),
                load_material_state=lambda: (
                    file_load(paths["materials"]),
                    file_load(paths["assigns"]),
                    {},
                    False,
                ),
                get_log_repository=lambda: FixtureLogRepository(),
                homework_books_from_log=lambda entry: [
                    row["book"]
                    for row in (entry or {}).get("homeworkTable", [])
                    if row.get("book")
                ],
                student_is_registered=lambda *_args, **_kwargs: bool(
                    policy["registered"]
                ),
                student_is_self_study=lambda logs, date, sid, _student, **_kwargs: bool(
                    ((logs.get(date) or {}).get(sid) or {}).get("selfStudy")
                ),
                student_absent=lambda absent, date, sid: sid
                in ((absent.get("by_date") or {}).get(date) or []),
                active_alias_sid=lambda *_args, **_kwargs: "",
                dashboard_enabled=lambda: False,
                dashboard_projection=lambda **_kwargs: {},
                build_latest_status=lambda _progress: {},
                student_completion_videos=lambda _student, _videos: [],
                course_videos_completed=lambda *_args: False,
                load_updates_with_auto_assign=load_updates_with_auto_assign,
                build_auto_blocked=lambda _progress, _watch: {},
                blocked_mids=lambda _blocked, _sid: set(),
                eligible_review_mids=lambda *_args: {"mid-review"},
                filter_self_study_assignment=lambda assignment, _eligible: deepcopy(
                    assignment
                ),
                filter_auto_assignment=lambda assignment, _student, _videos: deepcopy(
                    assignment
                ),
                review_states_through_date=lambda *_args: {},
                student_primary_video_mids=lambda _student, _videos: {"mid-a"},
                academy_restricted_videos=restrict_videos,
                review_video_projection=review_projection,
                assigned_material_list=lambda assignment: list(
                    (assignment or {}).get("materials") or []
                ),
                filter_materials=lambda catalog, assigned: {
                    key: deepcopy(catalog[key])
                    for key in assigned
                    if key in catalog
                },
                assigned_tests=lambda *_args: [
                    {
                        "id": "test-a",
                        "label": "시험 A",
                        "status": "assigned",
                        "answerUrl": "https://answer.example/test-a",
                    }
                ],
                filter_tests_for_curriculum=lambda items, _student: deepcopy(
                    items
                ),
                academy_restricted_tests=restrict_tests,
                today_iso=lambda: TODAY,
                dashboard_course_block_message="수업일이 아닙니다.",
            )

            api_student_bootstrap.WATCH_PATH = paths["watch"]
            api_student_bootstrap.load = file_load
            api_student_bootstrap.academy_network_allowed = lambda: bool(
                policy["inside"]
            )
            api_student_bootstrap.ip_allowed = lambda value: (
                value == "192.168.0.20"
            )

            app = Flask("verify-student-bootstrap-routes")

            @app.before_request
            def install_public_fixture_context():
                if request.headers.get("X-Public") != "1":
                    return None
                g.student_app_public_request = True
                g.student_app_client_ip = request.headers.get("X-Client-IP", "")
                if request.headers.get("X-Session") == "valid":
                    g.student_app_active_sid = SID

            api_student_bootstrap.configure_student_bootstrap_projection(
                app,
                dependencies,
            )
            app.register_blueprint(
                api_student_bootstrap.bp_api_student_bootstrap
            )
            client = app.test_client()

            route_rows = [
                (
                    rule.rule,
                    rule.endpoint,
                    sorted(rule.methods - {"HEAD", "OPTIONS"}),
                )
                for rule in app.url_map.iter_rules()
                if rule.rule == "/api/student/bootstrap"
            ]
            assert route_rows == [
                (
                    "/api/student/bootstrap",
                    "api_student_bootstrap.api_student_bootstrap",
                    ["GET"],
                )
            ]

            before = {
                path: _fingerprint(path)
                for path in paths.values()
            }

            no_session_reads = len(calls["loads"])
            response = client.get(
                f"/api/student/bootstrap?date={HISTORICAL_DATE}",
                headers={"X-Public": "1"},
            )
            assert response.status_code == 401
            assert response.get_json() == {
                "ok": False,
                "code": "unauthenticated",
            }
            assert len(calls["loads"]) == no_session_reads

            response = client.get(
                f"/api/student/bootstrap?date={HISTORICAL_DATE}"
            )
            assert response.status_code == 400
            assert response.get_json() == {
                "ok": False,
                "error": "missing sid",
            }

            response = client.get(
                f"/api/student/bootstrap?sid={SID}&date=not-a-date"
            )
            assert response.status_code == 400
            assert response.get_json() == {
                "ok": False,
                "error": "bad date",
            }

            response = client.get(
                f"/api/student/bootstrap?sid=missing&date={HISTORICAL_DATE}"
            )
            assert response.status_code == 404
            assert response.get_json() == {
                "ok": False,
                "error": "student not found",
            }

            response = client.post(
                f"/api/student/bootstrap?sid={SID}&date={HISTORICAL_DATE}"
            )
            assert response.status_code == 405
            _assert_all_unchanged(before, "bootstrap failure cases")

            ghost_read_count = len(calls["loads"])
            ghost_log_reads = calls["log_reads"]
            response = client.get(
                f"/api/student/bootstrap?sid={GHOST_SID}&date={HISTORICAL_DATE}"
            )
            ghost = response.get_json()
            assert response.status_code == 200
            assert ghost == {
                "ok": True,
                "date": HISTORICAL_DATE,
                "students": [
                    {
                        "id": GHOST_SID,
                        "name": "외부접속 테스트",
                        "curriculum": "고스트",
                        "subCurriculum": "외부접속",
                        "level": "중",
                        "school": "",
                        "grade": "",
                        "ghostStudent": True,
                    }
                ],
                "student": {
                    "id": GHOST_SID,
                    "name": "외부접속 테스트",
                    "curriculum": "고스트",
                    "subCurriculum": "외부접속",
                    "level": "중",
                    "school": "",
                    "grade": "",
                    "ghostStudent": True,
                },
                "videos": [
                    {
                        "mid": "ghost-outside-video",
                        "id": "ghost-outside-video",
                        "title": "외부접속 테스트 영상",
                        "chapter": "TEST",
                        "curriculum": "고스트",
                        "subCurriculum": "외부접속",
                        "isExtraAssignment": False,
                        "playbackRestricted": True,
                    }
                ],
                "reviewVideos": [],
                "updates": {
                    HISTORICAL_DATE: {
                        GHOST_SID: ["ghost-outside-video"]
                    }
                },
                "materials": {},
                "assigns": {GHOST_SID: []},
                "absent": {
                    "by_date": {HISTORICAL_DATE: []},
                    "by_student": {},
                },
                "logs": {
                    HISTORICAL_DATE: {
                        GHOST_SID: {
                            "homeworkTable": [
                                {
                                    "book": "고스트 숙제 교재",
                                    "this": "",
                                    "next": "",
                                    "comment": "",
                                }
                            ]
                        }
                    }
                },
                "assignedTests": [
                    {
                        "id": "ghost-outside-answer-test",
                        "testId": "ghost-outside-answer-test",
                        "name": "외부접속 테스트 답지",
                        "label": "외부접속 테스트 답지",
                        "categoryKey": "UNIT",
                        "categoryLabel": "단원평가",
                        "curriculum": "고스트",
                        "round": "1",
                        "status": "assigned",
                        "statusLabel": "배정",
                        "answerRestricted": True,
                    }
                ],
                "homeworkBooks": ["고스트 숙제 교재"],
                "courseVideosCompleted": False,
                "academyAccessAllowed": False,
                "outsideAcademyBlocked": True,
                "networkBlocked": True,
                "academyOnlyMessage": "영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.",
                "ghostStudent": True,
            }
            assert len(calls["loads"]) == ghost_read_count
            assert calls["log_reads"] == ghost_log_reads
            assert calls["auto"] == []

            policy["inside"] = True
            response = client.get(
                f"/api/student/bootstrap?sid={SID}&date={HISTORICAL_DATE}"
            )
            payload = response.get_json()
            assert response.status_code == 200
            assert "no-store" in str(response.headers.get("Cache-Control") or "")
            assert payload == {
                "ok": True,
                "date": HISTORICAL_DATE,
                "students": [fixtures["students"][0]],
                "student": fixtures["students"][0],
                "videos": [
                    {
                        **fixtures["videos"][0],
                        "isExtraAssignment": False,
                    }
                ],
                "reviewVideos": [
                    {
                        "mid": "mid-review",
                        "title": "복습 영상",
                        "chapter": "2",
                        "reviewStatus": "done",
                    }
                ],
                "updates": {
                    HISTORICAL_DATE: {
                        SID: {
                            "videos": ["mid-a"],
                            "source": "auto",
                            "unknown": {"keep": True},
                        }
                    }
                },
                "materials": fixtures["materials"],
                "assigns": {SID: fixtures["assigns"][SID]},
                "absent": {
                    "by_date": {HISTORICAL_DATE: []},
                    "by_student": {},
                },
                "logs": {
                    HISTORICAL_DATE: {
                        SID: fixtures["logs"][HISTORICAL_DATE][SID]
                    }
                },
                "assignedTests": [
                    {
                        "id": "test-a",
                        "label": "시험 A",
                        "status": "assigned",
                        "answerUrl": "https://answer.example/test-a",
                    }
                ],
                "homeworkBooks": ["교재A"],
                "selfStudy": False,
                "courseVideosCompleted": False,
                "academyAccessAllowed": True,
                "outsideAcademyBlocked": False,
                "networkBlocked": False,
                "academyOnlyMessage": "영상 재생과 테스트 답지는 학원 Wi-Fi에서만 볼 수 있습니다.",
            }
            assert calls["auto"] == []
            _assert_all_unchanged(before, "historical bootstrap")

            response = client.get(
                f"/api/student/bootstrap?sid=forged&date={TODAY}",
                headers={
                    "X-Public": "1",
                    "X-Session": "valid",
                    "X-Client-IP": "203.0.113.10",
                },
            )
            public_payload = response.get_json()
            assert response.status_code == 200
            assert public_payload["student"]["id"] == SID
            assert public_payload["academyAccessAllowed"] is False
            assert public_payload["outsideAcademyBlocked"] is True
            assert public_payload["networkBlocked"] is True
            assert public_payload["videos"] == [
                {
                    "mid": "mid-a",
                    "title": "배정 영상",
                    "chapter": "1",
                    "curriculum": "ALG",
                    "subCurriculum": "BASE",
                    "isExtraAssignment": False,
                    "playbackRestricted": True,
                }
            ]
            assert public_payload["reviewVideos"] == [
                {
                    "mid": "mid-review",
                    "title": "복습 영상",
                    "chapter": "2",
                    "reviewStatus": "done",
                    "playbackRestricted": True,
                }
            ]
            assert public_payload["materials"] == {
                "mat-a": {"id": "mat-a", "title": "자료 A"}
            }
            assert public_payload["assignedTests"] == [
                {
                    "id": "test-a",
                    "label": "시험 A",
                    "status": "assigned",
                }
            ]
            assert public_payload["watch"] == {
                "ok": True,
                "sid": SID,
                "date": "",
                "watch": {
                    "mid-a": {
                        "last": 95,
                        "dur": 100,
                        "completed": True,
                        "updatedAt": 20,
                    }
                },
            }
            assert calls["auto"] == []
            _assert_all_unchanged(before, "public today bootstrap")

            auto_before = len(calls["auto"])
            response = client.get(
                f"/api/student/bootstrap?sid={SID}&date={TODAY}"
            )
            assert response.status_code == 200
            assert len(calls["auto"]) == auto_before + 1
            auto_call = calls["auto"][-1]
            assert auto_call["date_key"] == TODAY
            assert auto_call["students"] == fixtures["students"]
            assert auto_call["videos"] == fixtures["videos"]
            assert auto_call["logs"] == {TODAY: {}}
            _assert_all_unchanged(before, "injected today bootstrap")

            policy["registered"] = False
            response = client.get(
                f"/api/student/bootstrap?sid={SID}&date={HISTORICAL_DATE}"
            )
            blocked = response.get_json()
            assert response.status_code == 200
            assert blocked["courseBlocked"] is True
            assert blocked["videos"] == []
            assert blocked["reviewVideos"] == []
            assert blocked["updates"] == {HISTORICAL_DATE: {SID: []}}
            assert blocked["assignedTests"] == []
            assert blocked["homeworkBooks"] == []
            assert blocked["blockMessage"] == "수업일이 아닙니다."
            _assert_all_unchanged(before, "course-blocked bootstrap")

            makeup_path = root / "makeup.json"
            makeup_student = {**fixtures["students"][0], "day1": "일1", "selfStudyDays": {"day1": True}}
            _write_json(paths["students"], [makeup_student])
            policy["registered"] = True
            api_student_bootstrap.configure_student_bootstrap_projection(app, replace(
                dependencies, makeup_path=makeup_path, student_is_self_study=student_is_self_study_on_date,
            ))
            for status, slots, expected in (("scheduled", [1], False), ("cancelled", [1], True),
                                           ("completed", [1], True), ("scheduled", [2], True)):
                _write_json(makeup_path, {"by_absence": {"2026-05-24": {SID: {"scheduledMakeup": {
                    "studentId": SID, "makeupDate": HISTORICAL_DATE, "makeupTimes": slots, "status": status,
                }}}}})
                snapshots = {path: _fingerprint(path) for path in [*paths.values(), makeup_path]}
                response = client.get(f"/api/student/bootstrap?sid={SID}&date={HISTORICAL_DATE}")
                assert response.status_code == 200 and response.get_json()["selfStudy"] is expected
                _assert_all_unchanged(snapshots, "makeup self-study bootstrap")

            print(
                "student bootstrap route checks passed: "
                "literal projections, public/session gates, auto-init boundary, "
                "and byte/hash invariance"
            )
            return 0
    finally:
        api_student_bootstrap.WATCH_PATH = previous_watch_path
        api_student_bootstrap.load = previous_load
        api_student_bootstrap.academy_network_allowed = previous_academy_allowed
        api_student_bootstrap.ip_allowed = previous_ip_allowed


if __name__ == "__main__":
    raise SystemExit(main())
