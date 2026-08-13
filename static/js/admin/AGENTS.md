# ADMIN JS KNOWLEDGE BASE

## Overview
The admin frontend starts at `main.js`, loads core state/date helpers, then mounts feature modules under `features/`.

## Structure
```
static/js/admin/
|-- main.js
|-- core/
|   |-- adminDate.js
|   |-- api.js
|   |-- state.js
|   `-- utils.js
|-- features/
`-- demo/              # pre-entrypoint synthetic API and tutorial sandbox
```

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Bootstrap | `main.js` | Initializes core and feature modules after `bootstrap()`. |
| Selected date | `core/adminDate.js` | Source of truth for `getAdminDate()` and `admin:date-change`. |
| Shared admin data | `core/state.js` | Loads students/videos/logs/progress and compatibility globals. |
| Admin API wrapper | `core/api.js` | Re-exports shared JSON helpers as `api.get`, `api.getOr`, `api.post`. |
| Feature modules | `features/` | Today list, log modal, video modal, calendar, tests, and exports. |
| Demo bootstrap | `demo/bootstrap.js` | Loaded before normal page modules on demo-capable shells. |

## Conventions
- Use `getAdminDate()` for admin operating-date behavior.
- Use row or cell `data-date` first for row actions; use `getAdminDate()` only as fallback.
- Core bootstrap intentionally loads a real-local-today baseline before the date bar starts; selected-date features must hydrate their own date instead of trusting that baseline.
- Keep `state` updates date/sid scoped. Do not replace whole runtime maps from the frontend.
- Use `core/api.js` / `shared/api.js` for new JSON wrapper code.
- Keep compatibility globals only when legacy modules still require them.
- After admin frontend changes, verify `/admin` reloads and the target table/modal renders.

## Anti-Patterns
- Do not use `todayLocalKey()` for selected admin date behavior.
- Do not drop `data-date` from today/done rows or calendar day cells.
- Do not make feature modules depend on a stale cached date after a modal opens.
- Do not let demo API requests fall through to the live server; follow `demo/AGENTS.md` for sandbox changes.
