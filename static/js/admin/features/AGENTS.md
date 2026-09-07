# ADMIN FEATURES KNOWLEDGE BASE

## Overview
Feature modules own most admin behavior and the riskiest date-scoped UI flows. Keep edits narrow.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Today list state | `today.state.js` | Attendance/contact/arrive-time caches, saved order, schedule helpers. |
| Today/done rendering | `today.render.js` | Row DOM, `tr[data-sid][data-date]`, row actions, absence/contact/homework patches. |
| Today orchestration | `today.js` | Fetching, sorting, search, auto-refresh, stale-done and missing-leave warnings. |
| Log/homework/progress modal | `logModal.js` | `/api/logs`, `/api/progress`, homework table, manual progress states. |
| Video assignment modal | `videoModal.js` | Updates/progress/watch integration and manual/auto assignment. |
| Test assignment modal | `testModal.js` | Assigned tests, status changes, log/progress patching. |
| Test assignment rules | `testAssignmentRules.js` | DOM/transport-free status cycles, normalization and catalog ordering; opening subject is injected. |
| Test assignment rules | `testAssignmentRules.js` | DOM/transport-free status cycles, subject/difficulty/key normalization and catalog ordering; opening subject is injected. |
| Calendar/absence/makeup | `calendar.js`, `makeupPending.js`, `absentRecovery.js` | Absence, makeup, carryover, manual absence selection. |
| Toolbar date modals | `extraModal.js`, `absentRegister.js` | Must freeze their opening date before any later save. |
| Assistant notes | `hoverTooltip.js`, `assistantStudentNotes.js` | Student-scoped mount/load/save flow; not date-scoped or exportable. |
| Student test OCR review | `studentTestOcrReview.js` | Selected-date pending list, paired protected crops, pending resolution, and incorrect-to-correct correction. |
| Exports/tooltips | `exportLogs.js`, `hoverTooltip.js` | Reporting and auxiliary UI. |
| Event helpers | `timeGraph.js`, `uiEnhance.js`, `attendanceLedgerLink.js` | Consume render/refresh events; some initialize transitively. |

## Conventions
- Prefer row `data-date` for supplement/absence/contact/homework/log/video/test actions.
- Freeze a modal's target date when it opens; never call live `getAdminDate()` again to decide where its save lands.
- Test save commands freeze SID/date/payload before awaiting, deduplicate per open session, and show completion only after progress plus log success. Late responses must not reset a newly opened popup. Exercise delayed reads, duplicate clicks, partial failure and retry through the real module.
- Keep assignment normalization/catalog projection in `testAssignmentRules.js`; modal state, recent-view storage, DOM, requests and save ordering remain in `testModal.js`. `normalizeConfig` deliberately retains its legacy in-place repair contract. Preserve the pre-extraction hash and literal oracle in `verify_test_assignment_rules.mjs` alongside the actual modal behavior driver and browser QA.
- Keep assignment normalization/catalog projection in `testAssignmentRules.js`; modal state, recent-view storage, DOM, requests and save ordering remain in `testModal.js`. `normalizeConfig` deliberately retains its legacy in-place repair contract. Preserve the pre-extraction hash and literal oracle in `verify_test_assignment_rules.mjs` alongside the actual modal behavior driver and browser QA.
- Keep assignment normalization/catalog projection in `testAssignmentRules.js`; modal state, recent-view storage, DOM, requests and save ordering remain in `testModal.js`. `normalizeConfig` deliberately retains its legacy in-place repair contract. Preserve the pre-extraction hash and literal oracle in `verify_test_assignment_rules.mjs` alongside the actual modal behavior driver and browser QA.
- Manual white/skip/none progress must survive automatic watch progress.
- Empty save values must not erase meaningful server data unless an explicit clear/delete field is sent.
- `logModal.js` owns the shared unified launcher for the fixed student tooltip plus log, video-assignment, and test-assignment modals. Its `all-students-readonly` log access locks class-log notes/homework, suppresses log/done writes, allows only right-click skip changes in the progress grid, and leaves the separate assistant-note thread available for list/create only.
- At `600px` and below, `videoModal.js` keeps those four unified surfaces reachable through the shared mobile tab switcher; do not restore off-screen fixed columns.
- Merge log modal saves with the latest server entry and preserve unknown fields.
- Keep homework book/current/next and notes readable; never display `???`/`????`.
- For direct `fetch()` calls kept for patch endpoints, preserve `credentials`, cache behavior, and payload keys.
- Use only `/api/arrive-time` and `/api/arrive-time/patch`; never restore the retired prefixless aliases in admin code.
- Read attendance/contact from their base GET endpoints and write only through `/api/attendance/patch` and `/api/contact/patch`; never restore bulk base-URL POSTs.
- Use only `/api/extra-attend` for extra-attendance reads and PATCH writes. Do not retry the nonexistent `/api/extra`, `/api/extra_attend`, or `/api/extra-attend/all` aliases.
- `today.js` owns rendering and stale-request suppression; it emits `today:rendered`. Mutations coordinate through `admin:refresh` and `attendance:updated`.
- `today.state.js` is the merge-safe client patch boundary. Preserve `__clear`, server-entry preference, unknown fields, and `done` behavior.
- The today-table `백지` checkbox is the SID-level `students.json.whiteReviewPending` flag, not a selected-date log field. Render it between `진도` and `작업`, save only an exact boolean through `/api/update`, roll back on failure, and never clear it from leave, homework-leave, record cleanup, attendance, progress, or date changes. Keep `진도`/`백지` at 36px each, reduce only `작업` to 232px, and preserve the `보강`/`문서` widths and total table width.
- Assistant-note mounts use a per-mount token to suppress stale responses. Keep authors/content student-scoped and out of CSV/print, class-log notes, and browser storage.
- All-students note mounts carry `existingReadOnly` into the note renderer itself; disable existing-note actions even after the thread moves outside `#logModal`. Keep list/create enabled and retain server-side PATCH/DELETE rejection.
- `testModal.js` initializes through `logModal.js`; `attendanceLedgerLink.js` initializes through `uiEnhance.js`. The comment-only `materials.js` module was retired after consumer audit; do not restore it or `/api/material-upload`.
- `main.js` may dynamically initialize calendar, announcements, operation notes, student logs/accounts/focus, and OCR only after the first today render. Their exported `init*` functions must remain idempotent and must not depend on receiving the first `today:rendered` event.
- Popup prefetch/cache changes follow [the canonical admin latency contract](../../../../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#admin-latency-contract). Preserve date/SID/URL scope, failed-promise eviction, save-time invalidation, and authoritative-load edit locking together; do not add a cache when any one gate is absent.
- After changes here, reload `/admin` and verify the affected modal/table.
- `examAttendance.js` owns the read-only exam-attendance projection and short-lived four-endpoint loader; meaning stays in the canonical logic document §7. `hoverTooltip.js` updates only its count spans after hydration, with popup epoch guards and attendance/refresh invalidation. Keep the existing thread/modal DOM intact and run `verify_exam_attendance.mjs` plus the real tooltip driver.
- OCR review freezes the selected date at load, uses only administrator endpoints, never displays answer keys on a student surface, and permits only pending correct/incorrect resolution plus incorrect-to-correct correction. Prefer the official solution crop; show the expected value and Drive source only when that crop is unavailable.

## Export Guardrails

- `명단 내보내기` 영상 텍스트는 선택일 배정 snapshot 중 선택일 전에 이미 `done`이었고 선택일에 명시적으로 재개되지 않은 차시는 제외한다. 선택일 당일 처음 `done`이 된 차시와 선택일에 비완료 상태로 다시 연 차시는 오늘 콘텐츠이므로 유지하고, 같은 날 테스트도 배정되어 있으면 영상과 테스트를 모두 출력한다.
- `로그 내보내기` TXT와 CSV `progress` 열은 같은 비완료 변화 목록을 사용한다. 둘 다 `done`(파란색)을 제외하고 `interrupted` 같은 비완료 표시만 유지하되, CSV의 고정 14열 구조는 보존한다.
- 두 내보내기의 테스트 텍스트는 현재 커리큘럼의 `assigned`(초록색) 배정 이름만 한 줄에 하나씩 출력한다. `SCHOOL_PAST`는 `학군지(난이도) 회차 이름`, `ILSAN_PAST`는 `일산(난이도) 회차 이름`으로 표기하고, 점수·오답·메모 같은 채점 정보는 포함하지 않는다.
- 회귀 검증은 `python scripts/verify_refactor_safety.py --only-export-log-format`으로 실행하고, 실제 관리자 선택일에서 명단/로그 TXT를 각각 확인한다.
- 빠른 인쇄기 CSV는 선택 타임과 현재 과목의 초록 `assigned` 조건, 운영판 학생/카탈로그 순서, BOM·헤더·이스케이프·파일명을 유지한다. 팝업 preview는 정확한 결석 이월 후 재배정된 항목의 자동 제외 `명 · 건`을 표시하며 재인쇄 checkbox는 매번 기본 꺼짐이다. 과거 CSV 이력은 감사 기록이지 자동 제외의 필수 조건이 아니다. 0행 응답은 download helper에 전달하지 않고 이유를 표시한다. 회귀 검증은 `--only-quick-printer-export`와 관리형 8004 실제 modal로 수행한다.

## Video Assignment Guardrails

- `videoModal.js` freezes the row's `data-date` and SID at open. Hydrate assignments with `/api/updates?readOnly=1`, the student's full progress history with `/api/progress?sid=...`, and `/api/watch/latest?sid=...`; a date-only progress read is insufficient for automatic exclusions.
- Opening or refreshing the popup is read-only. The server may create an automatic snapshot only for the real current KST date; selecting or operating on a future date must never persist `source: "auto"`. Adjacent active slots double today's displayed/effective count after weekend overrides and slot absences. A count save persists only the student setting used at the next date-boundary creation; it must not read, create, resize, or render a future automatic snapshot. Ordinary schedule, consecutive-slot, and progress/watch changes must not re-pick or resize an existing automatic snapshot. The newly registered absence transaction is the explicit removal exception.
- Primary automatic rows are the student's exact current curriculum/sub-curriculum, chapter-sorted. Cross-curriculum rows belong only to the explicit manual-add section. Do not restore subject-only fallback for a nonblank unmatched sub-curriculum.
- Keep `source` semantics stable: untouched automatic snapshots stay `auto`; any changed/forced-empty selection becomes an explicit `manual` snapshot; `selfStudy` is server-owned. An empty automatic result removes the snapshot, while an explicit empty manual save remains a meaningful clear.
- Progress colors and assignment checkboxes are related but separate. Persist changed `done`/`interrupted`/`skip`/`none` states through `/api/progress/patch` and preserve manual ownership so watch automation cannot overwrite them.
- In `all-students-readonly` mode, save only permitted progress exclusions; do not mutate assignments or extra-video log notes.
- Ctrl/Cmd selection, Ctrl/Cmd+Shift visible-range addition, pointer drag, right-click exclusion, and arrow-key state cycling must remain separate interaction modes and reset their anchor when the rendered list/filter changes.
- Save order is latest extra-video log read → assignment patch → progress patch → read-only assignment refresh → merge-safe extra-video log patch. Treat later-step failure as a recoverable partial success; never replace full runtime maps.
- Run `python scripts/verify_refactor_safety.py --only-video-modal-assignment-policy` plus the default assignment/watch units, then reload `/admin` and verify the frozen-date modal and student playlist projection.

## Test Assignment Modal Guardrails

- `testModal.js`의 `레벨 설정` 버튼과 Lv.3~Lv.6 선택 패널은 학생별 UNIT 기본값 편집기다. `testLevelDefaults.UNIT[normalizeSubject(subject)]`만 `/api/update`로 저장하고 현재 테스트 상태, 테스트 관리 공통 규칙, 다른 과목 기본값을 바꾸지 않는다.
- 일반 난이도 셀렉트는 학생별 기본값으로 축소하지 않는다. UNIT 탭에서는 항상 Lv.3~Lv.6 전체를 선택할 수 있어야 한다.
- 팝업 과목은 `activeStudent.curriculum`의 정규화값 하나로 고정한다. 다른 과목 시험은 카탈로그에서 제외하고 과목 셀렉트도 잠근다. 최근 보기, 최근 배정 이력, 기본값 어느 것도 이 과목을 덮어쓰면 안 된다.
- 현재 커리큘럼과 같은 과목 안에서만 유효한 최근 배정 이력 → 학생별 최근 보기 → 학생별/관리 기본값 순으로 분류·난이도·고사·회차를 복원한다. 분류 탭을 바꾸면 그 분류의 최근 배정 난이도·고사·회차를 우선 복원한다.
- 필수 회귀 사례는 `미적분2` 학생에게 유효한 `대수` 최근 보기와 더 최신 `대수` 배정 이력이 함께 있어도 최초 과목이 `미적분2`이고, 같은 과목 이력만 선택되는 경우다.
- 최근 보기 저장은 UI 편의 상태일 뿐 배정 원본이 아니다. 최근 배정 판정은 `progress[date][sid].__testAssignmentChangeOrder`의 시험별 순번을 사용한다. 팝업의 전체-map PATCH는 실제 조작한 키만 `__testAssignmentTouchedKeys`로 보내며 이 힌트는 서버에 저장하지 않는다. 상태 변경과 기존 시험 재배정은 모두 다음 순번을 받고, 한 PATCH에서 여러 분류가 같은 순번을 받으면 `UNIT`를 우선한다.
- 최근 배정 시험이 있는 목록은 그 정확한 행을 스크롤 뷰포트 중앙에 둔다. 목록이 스크롤되지 않으면 위치를 바꾸지 않는다.
- Ctrl/Cmd+클릭의 `선택` 상태와 방향키 순환(`none → interrupted → assigned → done → skip → none`)을 테스트 상태 클릭/드래그와 분리해 유지한다.
- 학생별 통합 팝업의 `저장 후 닫기`는 영상 저장 → 숙제/로그 저장 → 결석 테스트 이월 재적용 → 테스트 배정 저장 순서다. 테스트 배정 저장이 마지막 권위여야 사용자가 지운 초록 배정을 앞 단계의 오래된 이월 snapshot이 되살리지 않는다. 테스트 변경이 없으면 기존 이월은 그대로 유지한다.
- 숙제/로그 저장은 영상 진도 셀이 모두 `done`/`skip`이어도 날짜별 영상 배정을 삭제하지 않는다. 통합 `저장 후 닫기` 뒤에도 같은 snapshot을 유지하며 당일 다음 영상을 자동 보충하지 않는다.
- 버튼 DOM, 단일 필드 저장, 전체 난이도 노출, 최근 보기/배정 폴백, 다중 선택 단축키를 바꿀 때는 `run_admin_test_modal_assignment_source_checks`와 `run_admin_test_modal_assignment_behavior_checks`를 함께 확장하고 실행한다.


## Record Cleanup Guardrails

- Record cleanup means finalizing an active done row; it is not an alias for `하원` or `숙검하원`.
- The missing-leave warning is a separate alert on the shared hero warning stack: it uses only the server summary of pre-today arrival records without `done:true` and loads in parallel with the unarchived-done summary after the first table render. By the approved 2026-09-05 B design, its visible text is only `하원 미완료`, with a small decorative `aria-hidden` red dot and no background, border, dates, counts, or action button. Keep the existing date eligibility and empty/error suppression. The stale-done warning retains `date · 기록 정리` and its decorative SVG icon; long dates truncate visually on one line while the full DOM text stays accessible. Each visible warning spans both quick-action columns, with missing-leave first when both are visible. Keep both rows above `.hero-actions` without an internal scrollbar and maintain readable light/dark contrast.
- Individual cleanup uses the row's frozen `data-date` and sid. Bulk cleanup uses every unique row currently rendered in `#doneWrap`, preloads latest logs/progress once per rendered date, preserves each row's frozen date and sid, and invokes the same helper once per target.
- Both paths must call `completeAssignedTestsForRecordCleanup()`; do not duplicate status transitions in click handlers.
- A nonempty `state.logs` or `state.progress` entry is still only a cache. Cleanup must issue `no-store` reads for the latest log and, unless absent, the exact date/sid progress entry.
- Latest-read HTTP errors, malformed/missing log entries, a remotely undone row, or an already archived row fail closed. A sid omitted from an otherwise valid exact date/sids progress response is authoritative empty progress, matching the single-sid endpoint. Do not patch progress or archive from cached fallback data.
- Latest progress is authoritative: only `assigned` becomes `done`. Preserve `done`, `interrupted`, `skip`, and an existing explicit blank key. Use log assignment metadata only when the progress key is absent.
- Save order is latest reads → progress patch → one log patch containing test metadata and `archived: true`. Bulk cleanup may combine the final per-row log patches into one `/api/logs/patch-batch` request only after every successful target's latest read/progress step. A read/progress failure must leave the row unarchived; a later log failure must remain retryable.
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
