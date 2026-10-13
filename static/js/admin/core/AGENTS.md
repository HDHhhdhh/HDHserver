# ADMIN CORE JS KNOWLEDGE BASE

## Overview
Admin core modules own the selected date, bootstrap state, shared API wrapper, theme setup, view mode, and small DOM utilities used by feature modules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Selected admin date | `adminDate.js` | `getAdminDate()`, `setAdminDate()`, session storage, `admin:date-change`, date bar UI. |
| Admin API wrapper | `api.js` | Re-exports shared fetch helpers as `api.get`, `api.getStrict`, `api.getOr`, `api.post`. |
| Save conflicts | `saveConflict.js` | Classifies retryable lock timeouts without blaming another user and keeps real revision conflicts fail-closed. |
| Bootstrap state | `state.js` | Loads first-render students/videos/updates/logs/absence/progress/calendar data and exposes compatibility globals; materials and test catalogs remain on-demand. |
| Theme setup | `darkmode.js` | Dark-mode bootstrap for the admin shell. |
| View mode | `viewMode.js` | Admin display-mode state and DOM hooks. |
| Utilities | `utils.js` | Small DOM/toast/date helpers shared by admin features. |

## Conventions
- Admin operating-date behavior uses `getAdminDate()`; real local date belongs only where explicitly intended.
- `setAdminDate()` should keep the `YYYY-MM-DD` guard and broadcast `admin:date-change` unless `silent` is requested.
- Bootstrap loads a real-local-today baseline before selected-date initialization. Keep popup-only materials/test catalogs out of this blocking path; each selected-date feature hydrates its active date.
- Date-scoped refreshes merge into `state` without normalizing or replacing unrelated runtime records.
- Keep compatibility globals in sync while legacy feature modules still read `window.logs`, `window.progressData`, `window.students`, or similar names.
- New admin JSON helpers should pass through `api.js` so shared error and fallback behavior stays consistent.
- `saveConflict.js` follows [the canonical admin save-conflict contract](../../../../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#admin-latency-contract): only an actual lock-timeout code/message is retryable. A bare `retryable:true` on a revision/base conflict is insufficient and must stay fail-closed.
- `utils.js` installs global rejection/error handlers on import and still exposes legacy direct-fetch helpers. Do not assume `api.js` is the only request or side-effect path.
- Date-bar style changes must stay scoped to `#adminDateMount`.

## Anti-Patterns
- Do not move feature-specific row actions into core.
- Do not use `todayLocalKey()` as a substitute for selected admin date in feature flows.
- Do not replace whole runtime maps from core after a row-scoped refresh.
- Do not remove compatibility globals until every dependent feature module is migrated.

- Bootstrap initializes real-today assignments through checked `api.postStrict`; selected-date reads use storage-only GET. Reject invalid critical root shapes before publishing state or mounting save controls.

## Verification
- After selected-date changes, reload `/admin` and confirm the date bar updates plus `admin:date-change` listeners refresh.
- After `state.js` changes, verify bootstrap loads logs and progress for the intended date scope.
- After API wrapper changes, run syntax checks for the edited wrapper and one affected feature module.
