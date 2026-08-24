# ROUTES KNOWLEDGE BASE

## Overview
Flask blueprints live here. Routes are the boundary between static frontends, runtime JSON/SQLite, and core merge rules.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Student/log/progress/bootstrap APIs | `api_basic.py` | Broadest surface; handles logs, progress, updates, automatic/self-study video assignments, review projection, bootstrap, and protected video identity changes. |
| Attendance/contact/absence/today APIs | `api_attend.py` | Date-scoped row actions; new absence cleanup delegates through `absence_assignment_cleanup.py`. |
| Watch writes | `api_watch.py` | Browser playback writes monotonic watch state and automatic progress without refilling assignment snapshots. |
| Test catalog/records | `api_tests.py` | Catalog management, GET-only historical `tests.json` records, stats, and legacy-log fallback. Student submission/OCR routes are retired. |
| Kollus playback/callbacks | `api_kollus.py` | Academy-only `/api/get-url` plus LMS callback delegation to `core.watch_progress_writer`. |
| Announcements/surveys | `api_announcements.py` | Announcement images, replies, acknowledgements, surveys, and statuses. |
| Auth/files/makeup | `api_auth.py`, `api_fs.py`, `api_makeup_carryover.py` | Specialized persistence; makeup sheet sync shares the public absence cleanup adapter. |
| Assistant notes API | `api_assistant_notes.py` | Admin-referer-gated, student-scoped SQLite CRUD; never student/export facing. |
| Today order metadata | `api_todaymeta.py` | Live `/api/today_order` uses `data/today_order.json`; retired `/api/_legacy/*` routes and whole-map `POST /api/today_order` must not be restored. |
| Page routes | `pages.py` | Serves static HTML shells directly, not templates. |

## Conventions
- Every new blueprint must be explicitly imported and registered in `app.py`.
- Normal JSON mutation is canonical `core.paths` path + target `file_lock()` + load/merge/`save_atomic()`; atomic replace alone is not RMW locking.
- Class log reads/writes go through `get_log_repository()` / `LogRepository`.
- Use `core.log_rules.merge_log_entry_safe` and `log_entry_conflicts_with_base` for merge/conflict behavior.
- Use `core.progress_rules` for watch/progress transitions, `core.watch_progress_writer` for browser/Kollus writes, `core.progress_store` for strict progress caching/locking/saves, and `core.progress_notifications` for milestone hooks. `api_watch` and `api_kollus` must not import each other, and `api_watch` must not import helpers from `api_basic`.
- Attendance, makeup sheet sync, and the offline sync script must use `routes.absence_assignment_cleanup.absence_write_scope` plus `commit_new_absences_locked`; never import cleanup helpers from another blueprint. Preserve date/SID scope, carryover-before-clear ordering, the 8-second update/progress locks, normal response/revision shapes, startup recovery, and post-commit-only schedule notifications.
- Arrival-time routes use `/api/arrive-time` and `/api/arrive-time/patch` only. The retired prefixless `/arrive-time*` aliases must stay unavailable.
- `/api/attendance` and `/api/contact` are GET-only. Writes must use their single-student `/patch` endpoints; retired bulk POST handlers must stay unavailable.
- Extra attendance uses only `/api/extra-attend` with GET/PATCH. The old `/api/extra`, `/api/extra_attend`, and `/api/extra-attend/all` names never existed on the live server and must not be revived.
- Bare `GET /api/updates` is a legacy mutating read only for the real current KST date: it may create today's missing assignment or rebase today's stale curriculum MIDs. `GET /api/updates?readOnly=1`, historical/future loads, and future schedule events must remain storage-only. Student bootstrap may auto-assign only for a non-public request for real today; public or non-today bootstrap reads storage without creating an assignment.
- `/api/updates` is GET-only. Assignment writes must use `/api/updates/patch` or the validated `/api/updates/self-study` flow; the retired multi-date/student base POST must stay unavailable.
- Automatic video targets are scheduled or extra-attendance students who are not absent/done, plus the separate self-study mode. The configured count is 1-6 (default 3, A:Ble default 1); adjacent active class slots double the date-specific effective count after weekend overrides and slot absences. Initial candidates stay inside the exact current curriculum/sub-curriculum and exclude finished `done`/`skip` history.
- Preserve assignment source semantics: automatic snapshots may exist only for today or past dates and are immutable after creation except for an explicit current-day curriculum rebase. Never create, resize, or retain a future named `source: "auto"` snapshot. Progress/watch, schedule, absence, consecutive-slot, and count writes must never advance, shrink, remove, or refill an existing auto snapshot. Count writes persist only the student setting used by the next real-date initialization; explicit future `manual`, `selfStudy`, and unknown legacy entries remain protected.
- Bootstrap `videos` contains unfinished assigned catalog rows plus completed rows from today's named `source: "auto"` snapshot; retained completed rows carry `todayAutoAssignmentStatus: "done"`. Historical, skipped, and self-study completions stay out of that playlist. `reviewVideos` contains sanitized, current-curriculum, `done` rows through the requested date, excluding every still-visible assignment; it never exposes raw progress/watch/event-date data. Absent, archived, ghost, course-blocked, or malformed flows return an empty review array.
- `POST /api/updates/self-study` revalidates self-study/absence/archive state and only accepts current-curriculum videos completed strictly before the target date. It is not the student review button's persistence endpoint.
- `POST /api/videos` is a locked full-catalog save in normal mode. It must return 409 before writing when an existing stable row ID is removed or its URL-derived MID changes. Same-MID signed URL/metadata edits and new rows are allowed. Do not add a body/query bypass; correction drafts stay browser-local and live apply is an offline maintenance script with Waitress stopped and a verified backup.
- `/api/get-url` must validate academy access, session SID, known SID, and known MID. Browser watch writes share those academy/SID/ghost gates. Configure `KOLLUS_CALLBACK_SECRET` for exposed LMS callbacks; callbacks cannot use the browser's academy-only gate because Kollus must reach them.
- Keep `/api/watch-status` only as a temporary compatibility endpoint for the student app being developed on another computer. The current web student must use `/api/watch`; do not add new `/api/watch-status` consumers, and remove it only after the external app migrates and is merged.
- Preserve endpoint URLs, payload keys, response shapes, and cache behavior unless a dedicated migration is part of the task.
- /api/students, /api/materials, and base /api/logs are GET-only. Keep student mutations on the locked add/field-update/delete routes and class-log mutations on /api/logs/patch or /api/logs/patch-batch; do not restore whole-collection POST handlers.
- /api/fs/page-folders GET/POST is retired. Do not restore the HTTP surface; preserve PAGE_FOLDERS_PATH and existing local data unless a separate internal-store retirement is explicitly approved.
- File rename/move/delete/upload use the file-tree lock first, then material_state locks. Korean safe names must remain valid; prefix rewrites are path-segment aware across materials, assignment URL/relative/DIR tokens, and pageFolders. Delete stages content before commit, and a pre-journal failure restores the filesystem.
- `/api/mat-assign` GET carries the whole material-state revision and POST requires `If-Match`; a stale writer returns 409 without mutation. Student bootstrap and `/api/materials` read the same coordinated snapshot. Recovery-required material/file writes return 503 while unrelated routes remain available.
- External administrator API Basic auth must preserve each student/integration route's existing gate and status contract. In particular, `/api/get-url` remains academy/SID/MID gated and Kollus callbacks remain callback-secret gated.
- `GET /api/logs`, `GET /api/logs/entry`, `GET /api/updates`, and today's student bootstrap can touch runtime state; treat "read-only" smoke checks carefully.
- Assistant-note GET/list can enable WAL, create/migrate schema, and backfill `updated_by`; exclude it from filesystem-pure smoke checks.
- Student bootstrap returns `assignedTests` as a top-level array. `progress[date][sid].tests` is authoritative; log `assignedTests` is metadata/fallback.
- Student test submission and student OCR review routes are not registered. `/api/tests` is GET-only; keep assignment, answer-link, catalog, stats, and historical-record reads independent of submission.
- No known private cross-blueprint import remains. Public `get_log_repository()` consumers remain compatibility wiring; `api_fs` must use `core.announcement_image_access`, and `api_tests` must use `core.storage.file_lock` plus `core.test_answer_links`. Do not reintroduce the former watch/Kollus, makeup/attendance, test lock/answer-link, or file/announcement private seams.
- `/api/tests-config` POST replaces the whole config and requires the revision returned in the preceding GET's `X-Tests-Config-Revision` header. Reject stale or missing revisions before merging. Never POST a network-stripped GET representation or drop `sourceFiles`, source ids, unknown fields, or answer rounds.

## Runtime Data
- Runtime files are real local data: `students.json`, `videos.json`, `updates.json`, `progress.json`, `logs.json`, `watch.json`, `tests.json`, `tests-config.json`, `app.sqlite`, and related sidecars.
- Before migrations, repair jobs, or bulk rewrites, run `python scripts/backup_runtime_data.py`.
- Prefer PATCH-style route updates over full-map replacement.
- Watch and ordinary log flows retain their documented independent-store fallback behavior. Newly registered absence cleanup is the exception: updates, progress, dual class logs, absence, and optional makeup carryover use a rollback-first journal transaction. Verify other dates/SIDs survive, `assigned` becomes `interrupted`, carryover is collected before mutation, every injected failure restores all stores, and recovery-required state returns 503/fails startup rather than accepting another related write.

## Anti-Patterns
- Do not open-code SQLite plus `logs.json` merge behavior in route handlers.
- Do not let automatic watch progress overwrite manual white, skip, or explicit clear markers.
- Do not treat `interrupted` as eligible student review membership merely because the pure resolver can project it; current chooser/self-study policy is done-only.
- Do not add `/api/updates/review` or `/api/updates/training-pack` calls: no such video-assignment routes exist. Student review registration is local-only.
- Do not make admin modal hydration call the mutating `/api/updates` GET.
- Do not resurrect stale cleared test assignments from log metadata.
- Do not expose Drive answer links when network gating says to strip or restrict them.
- Do not reconnect the separate non-student OCR cache/lab to student routes, test history, progress, or logs. A future student submission flow must be rebuilt and reviewed as a new feature.
- Do not expose assistant notes through student bootstrap, test records, CSV/print exports, or browser storage.
- Do not copy legacy `api_todaymeta.py` or `api_auth.py` open-coded JSON patterns into new routes.

## Video Verification

- Run the default server units covering progress rules, review-state projection, assignment snapshots/hooks, completion reconciliation, self-study assignment, bootstrap projection, and watch routes.
- Verify a manual white/skip survives watch writes and reload, a completed auto video leaves today's snapshot byte-for-byte stable, non-today loads and future schedule events create no automatic snapshot, count writes persist only the setting, today's initial snapshot doubles for adjacent active slots, a slot absence removes that multiplier, and an absent/archived student receives no review choices.
- Run `python scripts/verify_video_mid_change_guard.py` for catalog identity work. It must use a temporary `videos.json` and prove same-MID edits/new rows succeed while existing MID changes, removals, and invalid duplicate IDs leave the file unchanged.
