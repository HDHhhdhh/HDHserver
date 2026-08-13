# ALL-PAGE FEATURES KNOWLEDGE BASE

## Overview
All-students feature modules render the roster, inline-edit student fields, mutate students, export/chat roster views, and show progress summaries.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Main table and inline edits | `table.js` | Roster DOM, field edits, search, linked homework books, and the `.miniProgBtn` unified student-popup launcher. |
| Add student bar | `addStudent.js` | Builds `/api/add-student` payload from the new-student form. |
| Clone student | `cloneButtons.js` | Copies identity fields only, clears curriculum/schedule/book fields. |
| Delete student | `deleteButtons.js` | DELETE endpoint first, then legacy fallback; removes the row locally after success. |
| Legacy progress modal | `progressModal.js` | Listens for dormant `.showProg`; current UI uses the mini editor inside `table.js`. |
| Roster export/chat | `chatRosterExport.js` | Builds exportable roster context. |
| Search/sort/tooltips/stats | `sortHelpers.js`, `hoverTooltip.js`, `yoilStats.js` | Table support behavior. |

## Conventions
- Keep all-page behavior separate from admin selected-date flows.
- Use all-page `core/api.js` for new JSON helpers unless an existing endpoint fallback requires direct `fetch()`.
- Preserve unknown student fields for field-scoped edits. Clone deliberately clears curriculum, schedule, and book fields.
- Row identity should come from `data-id`, `data-sid`, or `/student/<sid>` links before falling back to display text.
- Table search should keep `shared/search.js` Korean initials and keyboard-layout behavior.
- The `.miniProgBtn` uses the admin unified launcher to open the fixed student tooltip plus log, video-assignment, and test-assignment modals together, with the row's real local date and `all-students-readonly` log access.
- Keep the admin popup module graph behind the first `.miniProgBtn` interaction. Do not statically import `studentRecordPopup.js` from `all/main.js` or mount admin modal DOM during roster startup.
- On mobile, the shared `영상 / 상담 / 테스트 / 학생정보` switcher must keep all four surfaces reachable without horizontal clipping.
- In that mode notes/homework must never be patched; only right-click progress changes may reach `/api/progress/patch`.
- Delete uses `DELETE /api/students/:sid` then a legacy POST fallback; the live Flask app currently has no fallback route.

## Anti-Patterns
- Do not make delete/clone/add actions rewrite the full students list.
- Do not share admin `state` or `getAdminDate()` assumptions here.
- Do not remove DOM hooks from `static/all.html` without updating `main.js` and the affected feature modules.
- Do not drop the legacy delete fallback without confirming demo/external compatibility, even though the live Flask app lacks that route.
- Do not let a successful delete leave `state.students` stale when counts or roster export refresh; export reads `state.students`, not only `window.students` or the DOM.

## Verification
- After table changes, load `/students` and verify roster rows, search, and inline edits.
- After add/clone/delete changes, use a safe test path or mocked API before touching real student data.
- After unified-popup changes, verify all four admin surfaces open, real-local-date semantics hold, notes/homework stay read-only, left-click progress stays blocked, and right-click-only progress saves.
- After delete/export changes, verify the same-page CSV and counts no longer include a deleted student.
