# Server Rules Index

**감사 기준:** 2026-08-28, `codex/apple-clean-redesign` @ `dee7220`

**범위:** 학생 App/PWA 개발을 제외한 `C:/server` 운영 규칙. 학생 시험 OCR 제출은 `RULE-STUDENT-OCR-001`로 포함한다.

이 문서는 규칙 본문을 다시 설명하지 않는다. 각 규칙의 의미, 구현 위치,
결정 기록, 검증 위치를 연결하는 **정본 소유권 색인**이다.

## 판정 원칙

- **실제 동작**은 현재 코드와 런타임을 읽기 전용으로 검증해 판정한다.
- **의도된 규칙**은 최신 명시적 사용자 결정 → [로직 결정 원장](LOGIC_DECISION_LEDGER.md)
  → [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) 순으로 판정한다.
- 실제 동작과 의도된 규칙이 다르면 어느 한쪽으로 조용히 덮지 않고
  **구현 드리프트**로 기록한다.
- [코드·데이터 흐름 지도](CODE_FLOW_MAP.md)는 “어디서 구현되는가”만,
  루트와 하위 `AGENTS.md`는 “어떻게 안전하게 바꾸는가”만 소유한다.
- 과거 스냅샷과 회고는 현재 규칙의 근거가 아니다. 필요한 결정의
  provenance만 로직 결정 원장으로 옮긴다.

## 규칙 소유권

| ID | 규칙군 | 의미 정본 | 구현·데이터 흐름 | 결정·미완료 | 대표 검증 |
|---|---|---|---|---|---|
| <a id="rule-auth-001"></a>`RULE-AUTH-001` | 인증·네트워크·쓰기 경계 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §3 | [코드 흐름 지도](CODE_FLOW_MAP.md) §2·§4, `app.py`, `core/network_access.py` | [결정 원장](LOGIC_DECISION_LEDGER.md) D-01 | `verify_auth_secret_safety.py`, `verify_academy_proxy_network_access.py` |
| <a id="rule-identity-001"></a>`RULE-IDENTITY-001` | 사람·과목별 SID·학생 명단 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §5 | `core/person_identity.py`, `core/person_identity_store.py`, `core/student_auto_assignment_rules.py`, `routes/api_students.py`, `app.py` | 구현 드리프트 없음 | `verify_person_identity.py`, `verify_person_identity_routes.py` |
| <a id="rule-white-review-001"></a>`RULE-WHITE-REVIEW-001` | 백지리뷰 검사 대기 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §6 | [코드 흐름 지도](CODE_FLOW_MAP.md) §4·§5.1, `routes/api_students.py`, `static/js/admin/features/today.render.js` | [결정 원장](LOGIC_DECISION_LEDGER.md) D-11: SID 영속 상태, 날짜·하원·기록정리 독립 | `verify_person_identity_routes.py`, `verify_admin_white_review_pending.mjs`, Chrome 8004 |
| <a id="rule-date-001"></a>`RULE-DATE-001` | 선택 날짜·실제 오늘·SID | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §5·§6 | [코드 흐름 지도](CODE_FLOW_MAP.md) §4·§5.1, `core/date_rules.py`, date-indexed route/store 경계, `static/js/admin/core/adminDate.js` | 결정 원장의 날짜 병존 계약; D-04 whole-map absence 예외 | `verify_admin_date_session_storage.mjs`, `verify_local_date_contracts.js`, `verify_progress_routes.py`, `verify_log_routes.py`, `verify_updates_routes.py`, `verify_video_progress_matrix.py` |
| <a id="rule-attend-001"></a>`RULE-ATTEND-001` | 출결·결석·보강·오늘 순서 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §7·§15 | [코드 흐름 지도](CODE_FLOW_MAP.md) §4·§5, `routes/api_schedule_overrides.py`, absence core/route 경계 | 결정 원장 L-11·L-14·D-04·D-08; 새 결석만 날짜 배정 삭제 예외, weekend strict 400/403/404 gate, 오늘 extra post-commit 동일 재시도 | `verify_schedule_override_routes.py`, `verify_absence_transaction.py`, `verify_absence_makeup_matrix.py` |
| <a id="rule-log-001"></a>`RULE-LOG-001` | 수업 로그·숙제·기록 정리 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §8 | `core/log_rules.py`, `core/log_repository.py`, `routes/log_repository_provider.py`, `routes/api_logs.py` | SQLite 우선·JSON 결손 보충·signature 안정 cache와 방어 복사·D-08 | `verify_log_routes.py`, `verify_record_cleanup_test_status.mjs`, 기본 safety suite |
| <a id="rule-video-001"></a>`RULE-VIDEO-001` | 영상 카탈로그·배정 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §9 | [코드 흐름 지도](CODE_FLOW_MAP.md) §5.2·§5.3, `core/absence_transaction.py`, `core/student_schedule_rules.py`, `core/student_video_projection.py`, `core/student_video_assignment_rules.py`, `core/update_assignment_rules.py`, `core/update_assignment_store.py`, `routes/student_auto_assignment_service.py`, `routes/api_videos.py`, `routes/api_updates.py`, `routes/api_student_bootstrap.py`, `routes/student_bootstrap_projection.py`, `static/js/student/bootstrapState.js`, `static/js/student/watchState.js`, `static/js/student/playback.js`, `static/js/student/reviewPlaylist.js`, 배정·시청 core/route 경계 | 결정 원장 L-05~L-09·L-13~L-15·D-08; 기본 배정 상한 6, 완료 후 고정 snapshot, 새 결석 삭제 예외와 stale 재생성 차단, 복습 등록 후 1회 reload, 손상 store fail-closed, PATCH boolean 삭제·잠금 후 최종 source 검증 | `verify_student_auto_assignment_service.py`, `verify_absence_transaction.py`, `verify_student_video_assignment_rules.py`, `verify_video_mid_change_guard.py`, `verify_updates_routes.py`, `verify_student_bootstrap_routes.py`, `verify_student_bootstrap_state.mjs`, `verify_student_watch_autosave.mjs`, `verify_student_playback.mjs`, `verify_student_review_playlist.mjs`, 영상 배정·MID 교정 검증군 |
| <a id="rule-progress-001"></a>`RULE-PROGRESS-001` | 시청·진도·복습 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §10 | `routes/api_progress.py`, `core/progress_rules.py`, `core/progress_store.py`, `core/watch_progress_writer.py`, `static/js/student/watchState.js`, `static/js/student/playback.js`, `static/js/student/reviewPlaylist.js`, `static/js/student.js` | 수동 상태 우선 병존 계약·D-08 | `verify_progress_routes.py`, `verify_video_progress_matrix.py`, `verify_student_watch_timestamp.mjs`, `verify_student_watch_autosave.mjs`, `verify_student_playback.mjs`, `verify_student_review_playlist.mjs` |
| <a id="rule-test-001"></a>`RULE-TEST-001` | 시험 카탈로그·배정·답지·기록 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §11 | `core/test_config_safety.py`, `routes/api_tests.py`, `static/js/admin/features/logModal.js`, `static/js/admin/features/testModal.js`, `static/js/tests/catalogState.js`, `static/js/tests/catalogEditorState.js`, `static/js/tests/catalogStatisticsState.js`, `static/js/tests.js`, `static/css/tests.css`, `static/js/student/testPresentation.js`, `static/js/student.js` | 개별 PATCH / 전체·삭제 POST; 통합 학생 팝업은 결석 이월보다 사용자가 직접 저장한 테스트 상태를 마지막 권위로 적용; 관리자 catalog/editor/statistics state·test-page cascade·학생 read-only presentation 분리; compact는 단일 답안, UI는 구분자 형식만 안내·D-08 | `student_mobile_app_checks/homework-admin.mjs`, test-modal assignment source/behavior, `verify_test_catalog_state.mjs`, `verify_test_catalog_editor_state.mjs`, `verify_test_catalog_statistics_state.mjs`, `verify_tests_stylesheet_extraction.mjs`, `verify_test_catalog_search_and_sort.mjs`, mobile touch, admin record-detail UI/backend, `verify_test_answer_modes.py`, `verify_tests_config_write_safety.py`, 학생 presentation/answer/access 회귀 |
| <a id="rule-student-ocr-001"></a>`RULE-STUDENT-OCR-001` | 학생 시험 촬영·OCR·채점·보류 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §21 | `core/student_test_ocr_*`, `routes/api_student_test_ocr.py`, `static/js/student-test-*`, 관리자 OCR review 모듈 | [결정 원장](LOGIC_DECISION_LEDGER.md) L-04·D-09: 작업 트리 구현, 품질 gate·운영 rollout 대기 | `verify_student_test_ocr_*`, frontend/admin 전용 검증 |
| <a id="rule-note-001"></a>`RULE-NOTE-001` | 조교 메모·운영 노트·학생 로그 분리 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §12 | [코드 흐름 지도](CODE_FLOW_MAP.md) §4·§6 | 저장소 간 격리 | notes 검증군 |
| <a id="rule-material-001"></a>`RULE-MATERIAL-001` | 자료·파일·배정 참조 무결성 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §13 | `core/material_state.py`, `core/material_reference_rules.py`, `routes/api_materials.py`, `routes/material_state_provider.py`, `routes/api_fs.py` | 결정 원장 D-06A·D-07·D-08 | `verify_material_routes.py`, `verify_file_reference_routes.py` |
| <a id="rule-calendar-001"></a>`RULE-CALENDAR-001` | 학교 일정 저장 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §13 | `core/school_calendar_store.py`, `routes/api_school_calendar.py`, `static/js/shared/schoolCalendarSaveQueue.js`, `static/js/school-calendar/state.js`, `static/js/school-calendar/persistence.js`, `static/js/school-cal.js` | 결정 원장 D-06B·D-08: 작업 트리 적용, 격리 두 브라우저 증거 완료, 운영 rollout 대기 | `verify_school_calendar_revision.py`, `verify_school_calendar_state.mjs`, `verify_school_calendar_save_queue.mjs`, demo contract |
| <a id="rule-announce-001"></a>`RULE-ANNOUNCE-001` | 공지·설문·공개 이미지 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §13 | `core/announcement_image_access.py`, 공지/file route, `static/js/student/announcementState.js`, `static/js/student.js` | 공개 이미지 3중 gate; 학생 상태와 DOM/transport 분리·D-08 | `verify_announcement_image_access.py`, `verify_student_announcement_state.mjs`, student-mobile board/notifications |
| <a id="rule-data-001"></a>`RULE-DATA-001` | 운영 데이터·원본·백업 경계 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §14 | `core/paths.py`와 각 repository | migration 전 백업 | backup·temp fixture 검증 |
| <a id="rule-demo-001"></a>`RULE-DEMO-001` | 데모 무실서버 쓰기 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §3·§4 | `static/js/admin/demo/` | live write 금지 | demo contract 검증군 |
| <a id="rule-ops-001"></a>`RULE-OPS-001` | 운영 서버·격리 서버·배포 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §18 | [격리 서버 runbook](isolated-design-server.md), runner scripts | D-10: 8003 보호·8004 loopback 격리, 운영 관리자 Chrome 지원, 2026-08-29 native Kollus 실기동 증거 제외 | runtime server guard, Chrome 운영판, 학생 DOM/API·watch 계약 검증 |
| <a id="rule-verify-001"></a>`RULE-VERIFY-001` | 변경·검증 절차 | [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md) §17·§20 | 루트·하위 `AGENTS.md`, `scripts/AGENTS.md` | D-08·D-10: 독립 oracle + 실제 표면 + 무쓰기/hash 불변; 승인된 실기동 제외를 통과로 오기하지 않음 | 기본 safety suite, `verify_admin_latency_contracts.mjs`, 대상별 검증 |

## 문서 역할

- [기능·로직 기준서](PROJECT_FUNCTIONS_AND_LOGIC.md): 현재 의미·원본·우선순위·상태 전이
- [코드·데이터 흐름 지도](CODE_FLOW_MAP.md): 화면·API·순수 규칙·저장소 연결
- [로직 결정 원장](LOGIC_DECISION_LEDGER.md): 사용자 결정·충돌 판정·미완료 상태
- [문서 안내](README.md): 읽는 순서와 갱신 규칙
- [역사 자료](history/README.md): 당시 기록 보존; 현재 규칙으로 재사용 금지

## 범위 밖

학생 App/PWA 자체 개발 규칙은 이번 색인에 통합하지 않았다. 학생 시험 OCR 제출은 D-09 결정과 전용 검증을 거쳐 `RULE-STUDENT-OCR-001`로 편입했다. 비학생 OCR 연구 cache는 학생 제출과 계속 분리한다.
