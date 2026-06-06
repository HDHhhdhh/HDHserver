# ROUTES KNOWLEDGE BASE

## Overview
Flask blueprints live here. Routes are the boundary between static frontends, runtime JSON/SQLite, and core merge rules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Student/log/progress/bootstrap APIs | `api_basic.py` | Broadest surface; handles logs, progress, updates, assignments, bootstrap, and migrations. |
| Attendance/contact/absence/today APIs | `api_attend.py` | Date-scoped row actions and absence carryover. |
| Watch callbacks | `api_watch.py` | Student playback writes watch state and automatic progress. |
| Test catalog/records/stats | `api_tests.py` | Test config, submissions, and answer metadata. |
| Kollus callbacks | `api_kollus.py` | Delegates watch persistence to `api_watch.py`. |
| Admin chatbot API | `api_admin_chat.py` | User-facing knowledge backed by `core/admin_chat.py`. |
| Page routes | `pages.py` | Serves static HTML shells directly, not templates. |

## Conventions
- Class log reads/writes go through `get_log_repository()` / `LogRepository`.
- Use `core.log_rules.merge_log_entry_safe` and `log_entry_conflicts_with_base` for merge/conflict behavior.
- Use `core.progress_rules` for watch/progress transitions.
- Preserve endpoint URLs, payload keys, response shapes, and cache behavior unless a dedicated migration is part of the task.
- `GET /api/logs`, `GET /api/logs/entry`, `GET /api/updates`, and today's student bootstrap can touch runtime state; treat "read-only" smoke checks carefully.
- Student bootstrap returns `assignedTests` as a top-level array. `progress[date][sid].tests` is authoritative; log `assignedTests` is metadata/fallback.

## Runtime Data
- Runtime files are real local data: `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `watch.json`, `tests.json`, `tests-config.json`, `app.sqlite`, and related sidecars.
- Before migrations, repair jobs, or bulk rewrites, run `python scripts/backup_runtime_data.py`.
- Prefer PATCH-style route updates over full-map replacement.

## Anti-Patterns
- Do not open-code SQLite plus `logs.json` merge behavior in route handlers.
- Do not let automatic watch progress overwrite manual white, skip, or explicit clear markers.
- Do not resurrect stale cleared test assignments from log metadata.
- Do not expose Drive answer links when network gating says to strip or restrict them.
