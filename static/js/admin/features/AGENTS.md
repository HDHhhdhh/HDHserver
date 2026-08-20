# ADMIN FEATURES KNOWLEDGE BASE

## Overview
Feature modules own most admin behavior and the riskiest date-scoped UI flows. Keep edits narrow.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Today list state | `today.state.js` | Attendance/contact/arrive-time caches, saved order, schedule helpers. |
| Today/done rendering | `today.render.js` | Row DOM, `tr[data-sid][data-date]`, row actions, absence/contact/homework patches. |
| Today orchestration | `today.js` | Fetching, sorting, search, auto-refresh, stale-done warning. |
| Log/homework/progress modal | `logModal.js` | `/api/logs`, `/api/progress`, homework table, manual progress states. |
| Video assignment modal | `videoModal.js` | Updates/progress/watch integration and manual/auto assignment. |
| Test assignment modal | `testModal.js` | Assigned tests, status changes, log/progress patching. |
| Calendar/absence/makeup | `calendar.js`, `makeupPending.js`, `absentRecovery.js` | Absence, makeup, carryover, manual absence selection. |
| Toolbar date modals | `extraModal.js`, `absentRegister.js` | Must freeze their opening date before any later save. |
| Assistant notes | `hoverTooltip.js`, `assistantStudentNotes.js` | Student-scoped mount/load/save flow; not date-scoped or exportable. |
| Exports/tooltips | `exportLogs.js`, `hoverTooltip.js` | Reporting and auxiliary UI. |
| Event helpers | `timeGraph.js`, `uiEnhance.js`, `attendanceLedgerLink.js` | Consume render/refresh events; some initialize transitively. |

## Conventions
- Prefer row `data-date` for supplement/absence/contact/homework/log/video/test actions.
- Freeze a modal's target date when it opens; never call live `getAdminDate()` again to decide where its save lands.
- Manual white/skip/none progress must survive automatic watch progress.
- Empty save values must not erase meaningful server data unless an explicit clear/delete field is sent.
- `logModal.js` owns the shared unified launcher for the fixed student tooltip plus log, video-assignment, and test-assignment modals. Its `all-students-readonly` log access locks notes/homework, suppresses log/done writes, and allows only right-click skip changes in the progress grid.
- At `600px` and below, `videoModal.js` keeps those four unified surfaces reachable through the shared mobile tab switcher; do not restore off-screen fixed columns.
- Merge log modal saves with the latest server entry and preserve unknown fields.
- Keep homework book/current/next and notes readable; never display `???`/`????`.
- For direct `fetch()` calls kept for patch endpoints, preserve `credentials`, cache behavior, and payload keys.
- `today.js` owns rendering and stale-request suppression; it emits `today:rendered`. Mutations coordinate through `admin:refresh` and `attendance:updated`.
- `today.state.js` is the merge-safe client patch boundary. Preserve `__clear`, server-entry preference, unknown fields, and `done` behavior.
- Assistant-note mounts use a per-mount token to suppress stale responses. Keep authors/content student-scoped and out of CSV/print, class-log notes, and browser storage.
- `testModal.js` initializes through `logModal.js`; `attendanceLedgerLink.js` initializes through `uiEnhance.js`; `materials.js` is dormant/commented. Preserve topology before pruning imports.
- After changes here, reload `/admin` and verify the affected modal/table.
## Test Assignment Modal Guardrails

- `testModal.js`의 `레벨 설정` 버튼과 Lv.3~Lv.6 선택 패널은 학생별 UNIT 기본값 편집기다. `testLevelDefaults.UNIT[normalizeSubject(subject)]`만 `/api/update`로 저장하고 현재 테스트 상태, 테스트 관리 공통 규칙, 다른 과목 기본값을 바꾸지 않는다.
- 일반 난이도 셀렉트는 학생별 기본값으로 축소하지 않는다. UNIT 탭에서는 항상 Lv.3~Lv.6 전체를 선택할 수 있어야 한다.
- 팝업 최초 과목은 `activeStudent.curriculum`의 정규화값이다. 최근 보기, 최근 배정 이력, 기본값 어느 것도 이 과목을 덮어쓰면 안 된다.
- 현재 커리큘럼과 같은 과목 안에서만 유효한 학생별 최근 보기 → 최근 배정 이력 → 학생별/관리 기본값 순으로 분류·난이도·고사·회차를 복원한다. 다른 과목 최근 보기·이력은 무시하고 수동 교차 과목 보기는 다음 오픈의 시작값으로 저장하지 않는다.
- 필수 회귀 사례는 `미적분2` 학생에게 유효한 `대수` 최근 보기와 더 최신 `대수` 배정 이력이 함께 있어도 최초 과목이 `미적분2`이고, 같은 과목 이력만 선택되는 경우다.
- 최근 보기 저장은 UI 편의 상태일 뿐 배정 원본이 아니다. `progress[date][sid].tests`와 로그 배정 메타데이터의 권위를 대체하거나 서버 런타임 데이터에 새 필드를 쓰지 않는다.
- Ctrl/Cmd+클릭의 `선택` 상태와 방향키 순환(`none → interrupted → assigned → done → skip → none`)을 테스트 상태 클릭/드래그와 분리해 유지한다.
- 버튼 DOM, 단일 필드 저장, 전체 난이도 노출, 최근 보기/배정 폴백, 다중 선택 단축키를 바꿀 때는 `run_admin_test_modal_assignment_source_checks`와 `run_admin_test_modal_assignment_behavior_checks`를 함께 확장하고 실행한다.


## Record Cleanup Guardrails

- Record cleanup means finalizing an active done row; it is not an alias for `하원` or `숙검하원`.
- Individual cleanup uses the row's frozen `data-date` and sid. Bulk cleanup uses the selected date and invokes the same helper once per target.
- Both paths must call `completeAssignedTestsForRecordCleanup()`; do not duplicate status transitions in click handlers.
- A nonempty `state.logs` or `state.progress` entry is still only a cache. Cleanup must issue `no-store` reads for the latest log and, unless absent, the exact date/sid progress entry.
- Latest-read HTTP errors, malformed/missing entries, a remotely undone row, or an already archived row fail closed. Do not patch progress or archive from cached fallback data.
- Latest progress is authoritative: only `assigned` becomes `done`. Preserve `done`, `interrupted`, `skip`, and an existing explicit blank key. Use log assignment metadata only when the progress key is absent.
- Save order is latest reads → progress patch → one log patch containing test metadata and `archived: true`. A read/progress failure must leave the row unarchived; a later log failure must remain retryable.
- Keep `completeAssignedTestsForRecordCleanup()` out of leave, homework-leave, and undo blocks.
- Any change to test status normalization, assignment metadata, progress/log fetches, cleanup buttons, or archive order must extend and run `scripts/verify_record_cleanup_test_status.mjs`. The default safety suite must continue invoking it.
- The current cross-store flow is not atomic. If concurrent assignment during cleanup becomes an observed issue, move the transition to a server-side date/sid endpoint with locking or version checks.

## Anti-Patterns
- Do not overwrite all of `state.logs`, `state.progress`, attendance, contact, or arrive-time maps for a single row action.
- Do not let a live date change alter a modal save target opened from a different row date.
- Do not bypass 409/base-entry conflict handling in log saves.
- Do not assume a row belongs to the real local today.

## Verification
- For log-affecting work, open a known student/date with Korean notes, homework rows, and progress; verify no `???` text.
- Toggle one green progress cell to white, save, reload, and confirm it remains white after automatic watch updates.
- Change the date bar while a modal is open and confirm the save still targets the row/cell date captured at open.
- For assistant notes, verify student isolation, stale-mount suppression, author display, blank-note behavior, and absence from exports/browser storage.
