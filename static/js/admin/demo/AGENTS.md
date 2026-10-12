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
| Quick-printer sandbox | `quickPrinterContract.js` | Synthetic preview/export, automatic exclusion counts, the omitted-API reprint default, and session-only export receipts; the popup initial selection follows canonical §11. |
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
- Makeup sheet config GET/POST stays inside demo session storage, and demo sheet sync returns a synthetic no-op receipt; neither may reach the live API.
- School-calendar GET returns the same opaque 64-hex revision header as the live contract. POST requires matching `If-Match`, returns 428/409 without changing session state when missing/stale, and keeps primary `fetch.js` plus bootstrap fallback behavior aligned.
- `/api/updates` is GET-only; assignment mutations use `/api/updates/patch` or `/api/updates/self-study`, and the retired base POST must return a synthetic unsupported response.
- Extra attendance supports only `/api/extra-attend`; obsolete `/api/extra`, `/api/extra_attend`, and `/api/extra-attend/all` requests must return synthetic unsupported responses.
- `/api/delete-student` and `/api/material-upload` are retired and stay unsupported. Demo deletion uses canonical `DELETE /api/students/:sid`; material state uses `/api/materials`.
- Keep fixed synthetic time/schema changes synchronized across `data.js`, `store.js`, and request handlers.
- Quick-printer preview/export must be handled in both primary and fallback routers. Preview and zero-row failure write no session receipt; a successful synthetic CSV may append only to `quickPrinterExports` in the demo session store and must never call the live route or a print device.
- Missing-leave summaries in both demo routers must intersect arrival traces with the exact-date effective regular/extra/active-makeup roster. Keep a moved-makeup negative fixture so stale arrival residue cannot reintroduce the warning.
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
