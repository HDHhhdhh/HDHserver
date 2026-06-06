# ALL-PAGE JS KNOWLEDGE BASE

## Overview
The all-students page is a standalone static frontend with its own core wrapper and feature modules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Entry point | `main.js` | Calls `loadAll()`, renders, then mounts features. |
| API wrapper | `core/api.js` | Same-origin/no-store wrapper around `../shared/api.js`. |
| Shared state | `core/state.js` | Students, videos, progress, calendar, runtime maps. |
| Table renderer | `features/table.js` | Main roster/table UI and sorting/search display. |
| Add/delete/clone | `features/addStudent.js`, `deleteButtons.js`, `cloneButtons.js` | Mutating student actions. |
| Roster export | `features/chatRosterExport.js` | Chat/export helper. |

## Conventions
- Keep `core/api.js` behavior aligned with `static/js/shared/api.js`.
- Keep `credentials: 'same-origin'` and `cache: 'no-store'` defaults unless the endpoint requires otherwise.
- Render changes usually belong in `features/table.js`, not `main.js`.
- Mutating student actions must preserve unknown student fields and avoid normalizing unrelated data.

## Anti-Patterns
- Do not share admin selected-date assumptions with the all-students page.
- Do not bypass the all-page API wrapper for new JSON helpers.
- Do not remove DOM hooks from `static/all.html` without updating `main.js` and features.
