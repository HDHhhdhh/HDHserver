# ADMIN DEMO JS KNOWLEDGE BASE

## Overview
This directory virtualizes admin-family pages for `/demo/rh3123*`. It is a security boundary: synthetic reads/writes stay in session storage and must never reach live APIs or external navigation.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Pre-entrypoint guard | `bootstrap.js` | Activates exact demo paths, installs fetch/navigation/window guards, reset controls, and fallback responses. |
| Primary synthetic API | `fetch.js` | Emulates supported endpoints and mutations; unsupported API requests return synthetic errors. |
| Session store | `store.js` | `academy.adminDemo.v1`, schema validation, clone/load/save/reset helpers. |
| Initial fixtures | `data.js` | Fixed synthetic time, students, logs, progress, tests, announcements, and calendar data. |
| Tutorial controller | `tutorial.js` | Idempotent feature-help mounting and popover/center orchestration. |
| Tutorial metadata | `tutorial.features.js`, `tutorial.targets.js` | Page routing, selectors, target ranking, and feature descriptions. |
| Tutorial UI/state | `tutorial.render.js`, `tutorial.styles.js`, `tutorial.state.js` | DOM, injected styles, and a separate session key. |

## Conventions
- Five shells load `bootstrap.js` before their normal entrypoint: admin, all-students, tests, video manager, and school calendar.
- Production paths must remain untouched; activation uses normalized exact demo paths.
- Same-origin `/api/*` requests and retired `/arrive-time*` aliases never fall through to original `fetch`. The retired aliases are rejection guards only and must return synthetic unsupported responses.
- Keep `fetch.js` primary responses and `bootstrap.js` fallback responses compatible for endpoint shape, disabled behavior, and mutations.
- Mutations stay in `sessionStorage`. Schema mismatch or non-demo student IDs reset the store.
- Today order supports GET/PATCH/DELETE only; do not emulate the retired whole-map POST.
- `/api/updates` is GET-only; assignment mutations use `/api/updates/patch` or `/api/updates/self-study`, and the retired base POST must return a synthetic unsupported response.
- Extra attendance supports only `/api/extra-attend`; obsolete `/api/extra`, `/api/extra_attend`, and `/api/extra-attend/all` requests must return synthetic unsupported responses.
- Keep fixed synthetic time/schema changes synchronized across `data.js`, `store.js`, and request handlers.
- New demo pages require coordinated changes to `DEMO_PATHS`, `DEMO_ROUTE_MAP`, `routes/pages.py`, shell script order, and tutorial page resolution.
- Navigation and `window.open` remain sandboxed; production aliases remap to demo routes and external/unknown targets block.
- Preserve readable Korean strings and tutorial selectors tied to live shell DOM hooks.

## Anti-Patterns
- Do not allow unsupported API requests to reach the live backend.
- Do not read or write root runtime JSON, SQLite, local downloads, or browser storage outside the demo session keys.
- Do not move demo bootstrap after a page entrypoint; live fetches can begin during module initialization.
- Do not add an endpoint to only one of the primary/fallback routers when both can serve that page flow.
- Do not reuse production student IDs or current wall-clock data in fixtures.

## Verification
- Run `node --check` on all edited demo modules.
- Load the corresponding `/demo/rh3123*` page, verify reset/session persistence, and confirm network activity contains no live API mutation.
- Verify production `/admin` and sibling non-demo pages still use the original fetch/navigation paths.
