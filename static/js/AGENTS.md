# FRONTEND JS KNOWLEDGE BASE

## Overview
Browser behavior is split between admin modules, all-page modules, shared helpers, and large standalone student/test scripts.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Shared fetch helpers | `shared/api.js` | `fetchJson`, `fetchJsonOr`, `sendJson`, `ensureOk`, `ApiError`. |
| Shared search/calendar/self-study helpers | `shared/` | Reusable UI/data helpers. |
| Admin entry | `admin/main.js` | Admin bootstrap and feature initialization. |
| Student page | `student.js` | Monolithic student bootstrap, watch sync, announcements, tests, answer links. |
| Test management page | `tests.js` | Admin test catalog editing and CSV import UI. |
| All-students page | `all/main.js` | All-page bootstrap. |
| Answer-link maps | `test_answer_link_map.json`, `test_answer_link_map.js` | Generated or derived test explanation links. |

## Conventions
- When adding or touching JSON request wrappers, prefer `shared/api.js` or page-specific wrappers over fresh ad hoc fetch helpers.
- Preserve endpoint URLs, payload keys, credentials/cache options, and existing response shapes.
- `todayLocalKey()` means real local date. Admin selected-date behavior belongs in `static/js/admin/core/adminDate.js`.
- Keep generated `test_answer_link_map*` files in sync with test catalog/import work.
- Student bootstrap `assignedTests` stays a top-level array; answer links can come from assignment item, test config, Drive file ids, or generated link map.
- Do not introduce mojibake or placeholder `????` text.

## Anti-Patterns
- Do not let student `todayLocalKey()` semantics leak into admin selected-date flows.
- Do not hand-edit generated link maps when a script should regenerate them.
- Do not make broad changes to `student.js` without testing the student page surface.
- Do not replace shared helper behavior with one-off fetch wrappers.
