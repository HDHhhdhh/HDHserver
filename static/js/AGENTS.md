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
| Calendar/files pages | `school-cal.js`, `file-manage.js` | Standalone full-map editors with their own compatibility contracts. |
| All-students page | `all/main.js` | All-page bootstrap. |
| Demo sandbox | `admin/demo/` | Pre-entrypoint synthetic API, session store, navigation guard, and help tutorial. |
| Answer-link map | `test_answer_link_map.json` | Tracked canonical generated explanation map. The ignored `.js` sibling is legacy/unreferenced. |

## Conventions
- When adding or touching JSON request wrappers, prefer `shared/api.js` or page-specific wrappers over fresh ad hoc fetch helpers.
- Preserve endpoint URLs, payload keys, credentials/cache options, and existing response shapes.
- `todayLocalKey()` means real local date. Admin selected-date behavior belongs in `static/js/admin/core/adminDate.js`.
- Student bootstrap `assignedTests` stays a top-level array. Preserve every server access flag when projecting bootstrap data into `window.__ASSIGNED_TESTS__` and `window.__STUDENT_ACCESS__`.
- The public student-app installation guide starts hidden and opens only from its explicit header button. Preserve standalone/install-complete hiding, stale-prompt cleanup, background inertness, Escape/dismiss behavior, and focus restoration; do not turn it into an automatic shell gate.
- Answer precedence is assignment/config direct URL, `sourceFiles.solutionFileId`, then canonical JSON map. Academy-network gating strips/blocks every layer.
- `tests.js` POSTs the whole test config with the `X-Tests-Config-Revision` returned by the preceding GET. On a revision conflict, reload the server copy instead of rolling stale client state back over it. Never save a network-stripped GET representation or drop source metadata, unknown fields, or answer rounds.
- Do not introduce mojibake or placeholder `????` text.

## Anti-Patterns
- Do not let student `todayLocalKey()` semantics leak into admin selected-date flows.
- Do not hand-edit generated link maps when a script should regenerate them.
- Do not make broad changes to `student.js` without testing the student page surface.
- Do not replace shared helper behavior with one-off fetch wrappers.
- Do not treat bootstrap fallback as equivalent: its legacy multi-GET path supplies no assigned tests.
