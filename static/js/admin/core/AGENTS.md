# ADMIN CORE JS KNOWLEDGE BASE

## Overview
Admin core modules own the selected date, bootstrap state, shared API wrapper, theme setup, view mode, and small DOM utilities used by feature modules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Selected admin date | `adminDate.js` | `getAdminDate()`, `setAdminDate()`, session storage, `admin:date-change`, date bar UI. |
| Admin API wrapper | `api.js` | Re-exports shared fetch helpers as `api.get`, `api.getStrict`, `api.getOr`, `api.post`. |
| Bootstrap state | `state.js` | Loads students/videos/materials/updates/logs/progress/calendar/tests and exposes compatibility globals. |
| Theme setup | `darkmode.js` | Dark-mode bootstrap for the admin shell. |
| View mode | `viewMode.js` | Admin display-mode state and DOM hooks. |
| Utilities | `utils.js` | Small DOM/toast/date helpers shared by admin features. |

## Conventions
- Admin operating-date behavior uses `getAdminDate()`; real local date belongs only where explicitly intended.
- `setAdminDate()` should keep the `YYYY-MM-DD` guard and broadcast `admin:date-change` unless `silent` is requested.
- Bootstrap loads a real-local-today baseline before selected-date initialization. Treat it as initial compatibility state; each selected-date feature hydrates its active date.
- Date-scoped refreshes merge into `state` without normalizing or replacing unrelated runtime records.
- Keep compatibility globals in sync while legacy feature modules still read `window.logs`, `window.progressData`, `window.students`, or similar names.
- New admin JSON helpers should pass through `api.js` so shared error and fallback behavior stays consistent.
- `utils.js` installs global rejection/error handlers on import and still exposes legacy direct-fetch helpers. Do not assume `api.js` is the only request or side-effect path.
- Date-bar style changes must stay scoped to `#adminDateMount`.

## Anti-Patterns
- Do not move feature-specific row actions into core.
- Do not use `todayLocalKey()` as a substitute for selected admin date in feature flows.
- Do not replace whole runtime maps from core after a row-scoped refresh.
- Do not remove compatibility globals until every dependent feature module is migrated.

## Verification
- After selected-date changes, reload `/admin` and confirm the date bar updates plus `admin:date-change` listeners refresh.
- After `state.js` changes, verify bootstrap loads logs and progress for the intended date scope.
- After API wrapper changes, run syntax checks for the edited wrapper and one affected feature module.
