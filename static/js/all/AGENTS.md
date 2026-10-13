# ALL-PAGE JS KNOWLEDGE BASE

## Overview
The all-students page is a standalone static frontend with its own core wrapper and feature modules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Entry point | `main.js` | Calls `loadAll()`, renders, then mounts features. |
| API wrapper | `core/api.js` | Same-origin/no-store wrapper around `../../shared/api.js`. |
| Shared state | `core/state.js` | Students, videos, progress, calendar, and linked homework-book runtime maps. |
| Table controller | `features/table.js` | Roster DOM, inline edits, search, and the lazy unified student-popup launcher. |
| Add/delete/clone | `features/addStudent.js`, `deleteButtons.js`, `cloneButtons.js` | Mutating student actions. |
| Roster export | `features/chatRosterExport.js` | Chat/export helper. |

## Conventions
- Keep `core/api.js` behavior aligned with `static/js/shared/api.js`.
- Keep `credentials: 'same-origin'` and `cache: 'no-store'` defaults unless the endpoint requires otherwise.
- Render changes usually belong in `features/table.js`, not `main.js`.
- `core/state.js` lazy-loads progress once per SID and merges date/SID entries. Do not mark failed loads as cached or replace the map.
- Field edits preserve unknown student keys through `/api/update`; clone intentionally copies identity fields and clears curriculum/schedule fields.
- The former student `subBook*` inputs are retired. The table reads `/api/homework-books`, derived from each student's latest registered `homeworkTable[].book`.
- The row counseling button reuses the admin log modal in `all-students-readonly` mode: class-log notes/homework are read-only, the separate assistant-note thread supports list/create only, and progress accepts right-click skip edits only.
- Direct fetch remains in add/clone/delete/progress compatibility paths; do not mass-convert without preserving fallbacks and payloads.

## Anti-Patterns
- Do not share admin selected-date assumptions with the all-students page.
- Do not bypass the all-page API wrapper for new JSON helpers.
- Do not remove DOM hooks from `static/all.html` without updating `main.js` and features.

## Verification
- Load `/students`, confirm initial students/videos/calendar state, then exercise lazy progress for more than one SID.
- After mutations, verify DOM, `state.students`, compatibility globals, counts, and roster export agree without a reload.
- Use mocked or disposable data paths for add/clone/delete checks; the live roster is operational data.
