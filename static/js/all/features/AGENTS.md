# ALL-PAGE FEATURES KNOWLEDGE BASE

## Overview
All-students feature modules render the roster, inline-edit student fields, mutate students, export/chat roster views, and show progress summaries.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Main table and inline edits | `table.js` | Renders roster rows, school/grade/day/time/doc edits, curriculum stats, search keys. |
| Add student bar | `addStudent.js` | Builds `/api/add-student` payload from the new-student form. |
| Clone student | `cloneButtons.js` | Copies identity fields only, clears curriculum/schedule/book fields. |
| Delete student | `deleteButtons.js` | DELETE endpoint first, then legacy fallback; removes the row locally after success. |
| Progress modal | `progressModal.js` | Shows accumulated progress through real today and saves to `/api/progress/patch`. |
| Roster export/chat | `chatRosterExport.js` | Builds exportable roster context. |
| Search/sort/tooltips/stats | `sortHelpers.js`, `hoverTooltip.js`, `yoilStats.js` | Table support behavior. |

## Conventions
- Keep all-page behavior separate from admin selected-date flows.
- Use all-page `core/api.js` for new JSON helpers unless an existing endpoint fallback requires direct `fetch()`.
- Preserve unknown student fields when mutating one field or cloning a student.
- Row identity should come from `data-id`, `data-sid`, or `/student/<sid>` links before falling back to display text.
- Table search should keep `shared/search.js` Korean initials and keyboard-layout behavior.
- Progress modal currently uses the real local date; do not switch it to admin selected date.

## Anti-Patterns
- Do not make delete/clone/add actions rewrite the full students list.
- Do not share admin `state` or `getAdminDate()` assumptions here.
- Do not remove DOM hooks from `static/all.html` without updating `main.js` and the affected feature modules.
- Do not drop the legacy delete fallback unless the backend route compatibility is removed deliberately.

## Verification
- After table changes, load `/students` or `/all` and verify roster rows, search, and inline edits.
- After add/clone/delete changes, use a safe test path or mocked API before touching real student data.
- After progress modal changes, verify save payload date semantics and visible cell states.
