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
