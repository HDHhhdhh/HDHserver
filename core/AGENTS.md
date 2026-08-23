# CORE KNOWLEDGE BASE

## Overview
Shared backend helpers live here. Keep pure merge rules, persistence wrappers, path constants, network gating, and storage locks distinct.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Log merge/conflict rules | `log_rules.py` | Pure functions only. No Flask, SQLite, JSON file reads, or runtime-data repair. |
| Progress/watch merge rules | `progress_rules.py` | Manual white/skip/none states stay authoritative over automatic watch updates. |
| Video review projection | `video_review_rules.py` | Pure strict-before-date resolver; progress presence and manual overrides outrank watch fallback. |
| Video catalog correction | `video_catalog_correction.py` | Pure draft validation, impact counts, and simultaneous MID remap across updates/progress/watch values. |
| Log persistence | `log_repository.py` | SQLite plus `logs.json` dual-read/dual-write contract. |
| Assistant notes | `assistant_student_notes.py` | Student-scoped SQLite repository; separate from class logs despite sharing `app.sqlite`. |
| Runtime paths | `paths.py` | Canonical JSON/SQLite path constants. |
| JSON storage/locks | `storage.py` | Atomic replace, mirror/snapshot copies, and interprocess locks. |
| Network gating | `network_access.py` | Answer-link and academy-network visibility behavior. |
| Ghost student guards | `ghost_student.py` | Blocks writes for synthetic/placeholder students. |
| Non-student OCR cache | `non_student_ocr_cache.py` | Internal captured-cache adapter only; it is not connected to student test submission. |
| Legacy SQLite reader | `logs_sqlite.py` | No indexed consumers; do not revive it as a `LogRepository` bypass. |

## Conventions
- Keep `log_rules.py`, `progress_rules.py`, `video_review_rules.py`, and `video_catalog_correction.py` deterministic and side-effect free.
- Video catalog correction must preserve unknown keys and manual progress ownership, support simultaneous MID swaps, reject stale drafts/duplicate identities, and refuse deletion while any assignment/progress/watch reference remains.
- `resolve_video_review_states_before_date()` may project `done` or `interrupted` history, but route/UI policy decides which projected states are eligible. The current student chooser and self-study assignment accept only `done`.
- Review resolution is strictly before its cutoff: a progress key on a date suppresses same-date watch fallback, and `__manualProgressMids` keeps a later watch-only completion from resurrecting manual white/skip.
- Class-log routes use `routes.api_basic.get_log_repository()` so route-side placeholder repair remains injected while core merge rules stay pure.
- Preserve unknown keys in log/progress records unless a route explicitly clears them.
- Keep Korean text as UTF-8. Do not replace unreadable legacy text with `????`.
- Importing `paths.py` creates `files/` and every missing canonical JSON store. Avoid import probes when filesystem purity matters.
- `TODAY_ORDER_PATH` is exclusively `DATA_DIR/today_order.json` (default `data/today_order.json`). Never recreate the retired root sibling.
- `save_atomic()` does not lock the read-modify-write cycle; hold the target `file_lock()` across load, merge, and save. Mirror/snapshot failure must not invalidate a successful primary replace.
- Repository connections enable WAL and ensure schema. Log reads and assistant-note lists can therefore create sidecars or migrate/backfill rows.
- Keep assistant notes out of class-log notes, counseling data, CSV/print exports, and browser storage. Tests inject a temporary `db_path`.

## Anti-Patterns
- Do not move homework placeholder repair into `log_rules.py`; it can depend on student/book runtime data.
- Do not collapse watch/progress auto-status rules into log rules.
- Do not make `video_review_rules.py` read the video catalog or infer current curriculum; catalog scoping and response sanitization belong at the route boundary.
- Do not bypass `LogRepository` for class-log writes.
- Do not use `logs_sqlite.py` for new reads or writes.
- Do not merge the assistant-note repository with `LogRepository` merely because both resolve to `app.sqlite`.
- Do not add broad data cleanup inside pure helpers.

## Verification
- Exercise pure rules without importing Flask or runtime paths.
- Cover invalid dates/SIDs, numeric SID aliases, same-date progress-versus-watch precedence, later manual clears, malformed values, and input immutability when changing video review rules.
- Exercise storage and repositories with temporary JSON/SQLite paths; assert partial-store/conflict behavior, not only the happy path.
- Importing `app`, `core.paths`, or a repository against defaults is a runtime-affecting check.
