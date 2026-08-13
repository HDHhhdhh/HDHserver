# ROUTES KNOWLEDGE BASE

## Overview
Flask blueprints live here. Routes are the boundary between static frontends, runtime JSON/SQLite, and core merge rules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Student/log/progress/bootstrap APIs | `api_basic.py` | Broadest surface; handles logs, progress, updates, assignments, bootstrap, and migrations. |
| Attendance/contact/absence/today APIs | `api_attend.py` | Date-scoped row actions and absence carryover. |
| Watch callbacks | `api_watch.py` | Student playback writes watch state and automatic progress. |
| Test/OCR/catalog/records | `api_tests.py` | Grading, OCR review, submissions, full config replacement, durable `tests.json`, and legacy-log fallback. |
| Kollus callbacks | `api_kollus.py` | Delegates watch persistence to `api_watch.py`. |
| Announcements/surveys | `api_announcements.py` | Announcement images, replies, acknowledgements, surveys, and statuses. |
| Auth/files/makeup | `api_auth.py`, `api_fs.py`, `api_makeup_carryover.py` | Specialized persistence and mutation boundaries. |
| Assistant notes API | `api_assistant_notes.py` | Admin-referer-gated, student-scoped SQLite CRUD; never student/export facing. |
| Legacy today metadata | `api_todaymeta.py` | Live `/api/today_order` uses `data/today_order.json`, not root `today_order.json`. |
| Page routes | `pages.py` | Serves static HTML shells directly, not templates. |

## Conventions
- Every new blueprint must be explicitly imported and registered in `app.py`.
- Normal JSON mutation is canonical `core.paths` path + target `file_lock()` + load/merge/`save_atomic()`; atomic replace alone is not RMW locking.
- Class log reads/writes go through `get_log_repository()` / `LogRepository`.
- Use `core.log_rules.merge_log_entry_safe` and `log_entry_conflicts_with_base` for merge/conflict behavior.
- Use `core.progress_rules` for watch/progress transitions.
- Preserve endpoint URLs, payload keys, response shapes, and cache behavior unless a dedicated migration is part of the task.
- `GET /api/logs`, `GET /api/logs/entry`, `GET /api/updates`, and today's student bootstrap can touch runtime state; treat "read-only" smoke checks carefully.
- Assistant-note GET/list can enable WAL, create/migrate schema, and backfill `updated_by`; exclude it from filesystem-pure smoke checks.
- Student bootstrap returns `assignedTests` as a top-level array. `progress[date][sid].tests` is authoritative; log `assignedTests` is metadata/fallback.
- Manual test submission reconciles an active progress assignment to done; OCR review does not unless that transition is explicitly authorized.
- Existing private cross-blueprint seams are deliberate cycle-avoidance: tests/watch/attendance import from `api_basic`, and Kollus imports watch writers. Verify every consumer before renaming or moving those helpers.
- `/api/tests-config` POST replaces the whole config. Never POST a network-stripped GET representation or drop `sourceFiles`, source ids, unknown fields, or answer rounds.

## Runtime Data
- Runtime files are real local data: `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `watch.json`, `tests.json`, `tests-config.json`, `app.sqlite`, and related sidecars.
- Before migrations, repair jobs, or bulk rewrites, run `python scripts/backup_runtime_data.py`.
- Prefer PATCH-style route updates over full-map replacement.
- Watch, absence, test-submit, and log flows span multiple independently committed stores; preserve documented partial-success/fallback responses.

## Anti-Patterns
- Do not open-code SQLite plus `logs.json` merge behavior in route handlers.
- Do not let automatic watch progress overwrite manual white, skip, or explicit clear markers.
- Do not resurrect stale cleared test assignments from log metadata.
- Do not expose Drive answer links when network gating says to strip or restrict them.
- Do not fabricate OCR recognition/review payloads when cache, authorized provider, and local OCR are unavailable; fail closed without answer-key or filesystem-path leakage.
- Do not expose assistant notes through student bootstrap, test records, CSV/print exports, or browser storage.
- Do not copy legacy `api_todaymeta.py` or `api_auth.py` open-coded JSON patterns into new routes.
