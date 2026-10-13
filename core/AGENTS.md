# CORE KNOWLEDGE BASE

## Overview
Shared backend helpers live here. Keep pure merge rules, persistence wrappers, path constants, network gating, and storage locks distinct.
Business meaning is owned by [the Server Rules Index](../docs/SERVER_RULES_INDEX.md);
this file owns core-module edit and verification constraints.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Person identity rules | `person_identity.py` | Pure validation and add/clone/profile-update/retirement transforms for stable people and subject/SID rows. |
| Person identity persistence | `person_identity_store.py` | Strict two-store load, deterministic locks, journaled commit/rollback/recovery, and fail-closed configured-state detection. |
| Student auto-assignment settings | `student_auto_assignment_rules.py` | Pure A:Ble detection, default/count coercion, and configured-count interpretation shared by roster writes and automatic assignment. |
| Student schedule rules | `student_schedule_rules.py` | Pure date, regular/weekend slot, slot-absence, consecutive-count, self-study, log-entry, and daily-absence interpretation. |
| Student schedule projection | `student_schedule_projection.py` | Pure public schedule rows plus exact-date effective attendance roster IDs for regular, extra, active makeup, and absence precedence. |
| Student video projection | `student_video_projection.py` | Pure curriculum scoping, completion/blocking state, response filtering, and sanitized review projection. |
| Video provider rules | `video_sources.py` | Pure YouTube URL/row identity, embed URL and narrow cleanup patch; approved provider/overlay exceptions are canonical in [§9](../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#youtube-gichul-overlay). |
| Isolated video QA | `isolated_kollus_qa.py` | Default-OFF, exact-pair manager/process/loopback validation; scope is [D-18](../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#관리형-8004-영상-전용-qa-예외-d-18). Never grant overall academy access. |
| Student video assignment transforms | `student_video_assignment_rules.py` | Pure self-study prior-video selection and metadata-preserving auto append/rebase transforms. |
| Update assignment rules | `update_assignment_rules.py` | Pure SID alias, video-list normalization, merge/source, and self-study boundary vocabulary. |
| Update assignment persistence | `update_assignment_store.py` | Strict object reads, atomic saves, typed failures, and canonical interprocess lock parameters for `updates.json`; callers retain path ownership. |
| Canonical date keys | `date_rules.py` | Pure real-calendar validation for exact `YYYY-MM-DD` keys shared by date-indexed HTTP/store boundaries. |
| Log merge/conflict rules | `log_rules.py` | Pure functions only. No Flask, SQLite, JSON file reads, or runtime-data repair. |
| Progress/watch merge rules | `progress_rules.py` | Manual white/skip/none states stay authoritative over automatic watch updates. |
| Progress JSON persistence | `progress_store.py` | Strict object reads, process-local signature cache, compact atomic saves, and the canonical progress file lock. |
| Progress milestone bridge | `progress_notifications.py` | Best-effort, default-off notification snapshots and commits around successful progress writes. |
| Watch/progress writer | `watch_progress_writer.py` | Path-injected monotonic watch persistence and automatic progress writes shared by browser and Kollus routes. |
| Watch storage reads | `watch_store.py` | Strict root/target-branch validation with typed failure; missing storage alone is empty. |
| Absence assignment cleanup | `absence_assignment_cleanup.py` | Pure/date-SID-scoped projections plus the legacy independently committed compatibility writer. |
| Absence transaction | `absence_transaction.py` | Path-injected narrow before-images, sensitive no-mirror journal, all-store rollback/recovery, and same-context reentrant consistency barrier. |
| Material reference rules | `material_reference_rules.py` | Pure segment-aware rename/move/delete transforms across material metadata, assignment tokens, and page-folder values. |
| Material state persistence | `material_state.py` | File-tree then deterministic three-store locks, versioned undo/forward recovery, coherent reads, and last-good fallback. |
| File/material transaction plan | `file_material_transaction.py` | Path-injected filesystem intent, private staging, identity validation, and prepared rollback/committing roll-forward. |
| Makeup payload rules | `makeup_payload_rules.py` | Pure legacy-compatible schedule/manual projections, student IDs, and revision; routes retain transport and persistence. |
| Administrator authentication cache | `admin_auth_cache.py` | Process-local bounded successful verdicts, framed secret HMAC keys, configuration generations, absolute 5-second TTL, and bounded in-flight sharing. |
| School calendar persistence | `school_calendar_store.py` | Strict object reads, canonical SHA-256 revision, file-locked compare-and-replace, and unreadable-store failure. |
| Video review projection | `video_review_rules.py` | Pure strict-before-date resolver; progress presence and manual overrides outrank watch fallback. |
| Video catalog correction | `video_catalog_correction.py` | Pure draft validation, impact counts, and simultaneous MID remap across updates/progress/watch values. |
| Log persistence | `log_repository.py` | SQLite plus signature-stable, defensively copied `logs.json` dual-read/dual-write contract. |
| Assistant notes | `assistant_student_notes.py` | Student-scoped SQLite repository; separate from class logs despite sharing `app.sqlite`. |
| Runtime paths | `paths.py` | Canonical JSON/SQLite path constants. |
| Runtime server guard | `runtime_server_guard.py` | Refuses a second Waitress/Flask network server against the live repository runtime while production port 8003 is listening. A marker-verified copied code root is allowed; test-client imports remain allowed. |
| JSON storage/locks | `storage.py` | Atomic replace, mirror/snapshot copies, active-token-protected interprocess locks, and ownerless local-orphan recovery. |
| Request/read consistency | `request_consistency.py`, `read_cohort.py` | Pure absence HTTP classification and process-local read cohorts holding the unchanged cross-process file lease; only explicitly storage-only requests may share. |
| Network gating | `network_access.py` | Answer-link and academy-network visibility behavior. |
| Test answer-link resolution | `test_answer_links.py` | Pure assignment -> config -> generated-map precedence shared by bootstrap and test-record routes. |
| Test record/statistics projection | `test_record_projection.py`, `test_statistics_projection.py` | Pure historical normalization/detail/statistics; routes retain storage order, date policy, clock, authorization and response transport. |
| Student assigned-test projection | `student_test_projection.py` | Pure progress-authoritative presentation and injected answer resolution; api_basic retains loader/cache order and compatibility aliases. |
| Quick-printer CSV/history | `quick_printer_export.py`, `quick_printer_export_history.py` | Current-subject green-assignment projection plus exact absence provenance and a separate SQLite per-assignment generated-export history. |
| Student test OCR | `student_test_ocr_rules.py`, `student_test_ocr_repository.py`, `student_test_ocr_service.py`, engine/job/assets/config helpers | Default-off, migration-explicit UNIT capture, OCR, grading, retention, and review boundary. |
| UNIT solution crop | `student_test_solution_crop.py` | Optional read-only crop from the official first-page answer table; Drive source remains the fallback. |
| Announcement image access | `announcement_image_access.py` | Pure path/membership/visibility rules plus a path-injected locked store reader for public student files. |
| Ghost student guards | `ghost_student.py` | Blocks writes for synthetic/placeholder students. |
| Non-student OCR cache | `non_student_ocr_cache.py` | Internal captured-cache adapter only; it is not connected to student test submission. |
| Legacy SQLite reader | `logs_sqlite.py` | No indexed consumers; do not revive it as a `LogRepository` bypass. |

## Conventions
- Keep `person_identity.py`, `student_auto_assignment_rules.py`, `student_schedule_rules.py`, `student_video_projection.py`, `student_video_assignment_rules.py`, `update_assignment_rules.py`, `log_rules.py`, `progress_rules.py`, `video_review_rules.py`, and `video_catalog_correction.py` deterministic and side-effect free. `student_auto_assignment_rules.py` owns the approved 1-6 count clamp; values above 6 are interpreted as 6 without mutating the input student row.
- [`RULE-IDENTITY-001`](../docs/SERVER_RULES_INDEX.md#rule-identity-001) owns identity semantics. `persons.json` holds stable people/shared profile fields and `students.json` holds subject/SID rows. Add and clone have different person-link meanings; `id` and `personId` are immutable.
- Once `identity_is_configured()` is true, person and student stores must load and mutate through `person_identity_store.py`. Missing, unreadable, invalid, or recovery-required partial state must fail closed; never silently fall back to legacy roster-only writes or create an empty `persons.json`.
- Identity mutations must use the journaled two-store boundary and preserve unknown fields. Recovery completes or rolls back before another mutation; shared profile changes fan out only through the canonical transform, while SID-specific fields remain on the selected student row.
- Routes must use `watch_progress_writer.py` for browser/Kollus watch and automatic-progress writes, `progress_store.py` for progress file caching/locking, and `progress_notifications.py` for milestone hooks. Do not reintroduce cross-blueprint private writer imports or `api_watch` imports from `routes.api_basic`.
- Newly registered absence assignments must plan with `absence_assignment_cleanup.py` and commit through `absence_transaction.py` using explicit paths and a repository factory. Keep both Flask independent and date/SID scoped; preserve carryover read before mutation, narrow date snapshots, the 8-second updates/progress locks, exact dual-log row restoration, rollback-first recovery, and a no-mirror transient journal. Related automatic writers acquire the coordinator before reading authoritative absence state and before the updates lock. Reentrancy applies only to the same coordinator in the same execution context; never turn it into a process-wide bypass.
- Date-indexed progress/watch projection must ignore records after the assignment target date. Curriculum rebase preserves every assigned MID still in the current course, including completed/blocked MIDs, and replaces only stale slots up to the existing snapshot size when candidates exist. Future named `source:auto` cleanup belongs to `update_assignment_rules.py`; preserve future manual, self-study, legacy-array, and unknown-source entries.
- General date-indexed HTTP and repository boundaries use `date_rules.py` for exact real-calendar `YYYY-MM-DD` keys. Reject shape-valid impossible dates before locks, repositories, assignment hooks, or persistence. D-04's approved whole-map `/api/absent` 500/no-write limitation is the explicit exception and stays in `core.absent` until the user changes that decision.
- [`RULE-VIDEO-001`](../docs/SERVER_RULES_INDEX.md#rule-video-001) owns the `updates.json` failure contract. Read and save it through `update_assignment_store.py`: absence alone projects `{}`, but unreadable or non-object content raises a typed store failure and must never be replaced with an empty assignment map.
- Video catalog correction must preserve unknown keys and manual progress ownership, support simultaneous MID swaps, reject stale drafts/duplicate identities, and refuse deletion while any assignment/progress/watch reference remains.
- Material reference transforms must be pure, input-immutable, segment-aware, and preserve unknown fields/tokens. File routes must commit materials, assignments, and pageFolders through material_state.py while holding its locks; save_atomic alone is insufficient.
- `material_state.py` owns file-tree before three-store locks; do not nest another file-tree lease around it. Strict reads, revisions, last-good fallback, and version 1 metadata recovery remain supported. Version 2 file intent rolls prepared work back without rewriting primary JSON bytes; committing work rolls all three stores forward. Ambiguous paths, replaced files, unreadable journals, or failed recovery block mutations. Staging stays under the root's ignored `instance/` namespace.
- `school_calendar_store.py` owns the calendar revision and locked compare-and-replace. Missing files project `{}`, but unreadable/non-object stores fail closed; routes and tests must not duplicate its write path or derive expected test revisions with this production helper.
- `resolve_video_review_states_before_date()` may project `done` or `interrupted` history, but route/UI policy decides which projected states are eligible. The current student chooser and self-study assignment accept only `done`.
- Review resolution is strictly before its cutoff: a progress key on a date suppresses same-date watch fallback, and `__manualProgressMids` keeps a later watch-only completion from resurrecting manual white/skip.
- Class-log routes use `routes.log_repository_provider.get_log_repository()` so route-side placeholder repair remains injected while core merge rules stay pure. `routes.api_basic.get_log_repository` is a compatibility re-export, not the canonical owner.
- Preserve unknown keys in log/progress records unless a route explicitly clears them.
- Student OCR workers receive answer modes but never answer keys. Choice keeps one pooled model. Subjective jobs also receive one catalog-derived formula profile: `공통수학1·2` use `m3_h1`, while `대수·미적분1·확통·기하·미적분2` use `m3_h1_h2_h3`; student grade is never an input. Persist the profile in the job payload, require the same profile for recapture/retake, and fail closed on unknown curricula or catalog drift. The round-scoped context, strict legacy digest, async recapture, resident worker, and lease/grading recovery contracts are owned by [canonical §21](../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약). All student images expire after seven days, and optional official solution crops must stay administrator-only and path-contained under the configured PDF cache.
- Keep Korean text as UTF-8. Do not replace unreadable legacy text with `????`.
- OCR maintenance is model-independent and separately default-OFF. Keep its existing-schema/startup guard, single-file retention transaction, read-only administrator inspection and lifecycle limits under [canonical §21](../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#21-학생-시험-ocr-제출과-카탈로그-유형-계약); never run it against live data merely to verify source changes.
- `paths.py` only declares paths. `app.create_app()` initializes missing legacy defaults after its server guard and runs recovery; importing `app` or repositories against default paths can still write runtime. Do not create a configured missing person identity store.
- While production port 8003 is listening, `create_app()` must reject non-production Waitress/Flask server commands before recovery or other startup writes. Only a code-root-matching `ACADEMY_ISOLATED_SERVER_ROOT` plus `.academy-isolated-server.json` marker may allow the managed copied server; pure/test-client imports stay permitted.
- `TODAY_ORDER_PATH` is exclusively `DATA_DIR/today_order.json` (default `data/today_order.json`). Never recreate the retired root sibling.
- `save_atomic()` does not lock the read-modify-write cycle; hold the target `file_lock()` across load, merge, and save. Mirror/snapshot failure must not invalidate a successful primary replace.
- The admin latency/cache contract is canonical in [PROJECT_FUNCTIONS_AND_LOGIC §6·§8](../docs/PROJECT_FUNCTIONS_AND_LOGIC.md#admin-latency-contract). `logs.json` cache entries require a stable before/after file signature, a 16-path cap, and defensive copies at every public read boundary. Never break a live same-process token or another live process's lock; only a same-process lock file with no registered owner may use the short orphan grace.
- Repository connections enable WAL and ensure schema. Log reads and assistant-note lists can therefore create sidecars or migrate/backfill rows.
- Keep assistant notes out of class-log notes, counseling data, CSV/print exports, and browser storage. Tests inject a temporary `db_path`.
- Quick-printer history is not a class-log field. Keep it in its separate SQLite repository with `(student_id, test_id, material_id, assignment_date)` uniqueness, `BEGIN IMMEDIATE` upserts, exact-boolean reprint policy at the route, and temp-only restart/concurrency/rollback verification. Exact absence provenance plus an originally `assigned` carryover is sufficient for default exclusion even when the successful CSV predates history tracking; generated-export history remains the audit record, not an exclusion prerequisite.

## Anti-Patterns
- Do not move homework placeholder repair into `log_rules.py`; it can depend on student/book runtime data.
- Do not collapse watch/progress auto-status rules into log rules.
- Do not make `video_review_rules.py` read the video catalog or infer current curriculum; catalog scoping and response sanitization belong in `student_video_projection.py`, while runtime file loads and writes remain outside both modules.
- Do not bypass `LogRepository` for class-log writes.
- Follow `RULE-LOG-001` for complete snapshots. Keep the internal row marker out of public entry/map/export projections, hydrate unknown legacy fields before sealing a row, and prove clear/reload/restart after a JSON mirror failure. Absence raw snapshots must preserve the marker byte-for-byte for rollback.
- Do not use `logs_sqlite.py` for new reads or writes.
- Do not merge the assistant-note repository with `LogRepository` merely because both resolve to `app.sqlite`.
- Do not add broad data cleanup inside pure helpers. The absence cleanup service is an explicit path-injected mutation boundary and must never widen beyond the supplied date/SID pairs.

## Verification
- Exercise pure rules without importing Flask or runtime paths.
- Makeup normalization preserves explicit `scheduledMakeup:null` deletion tombstones for absence and manual rows; a missing camelCase key may take a null legacy alias. Keep missing-key note fallback distinct. Run `verify_makeup_payload_rules.py` for the literal temp HTTP → actual browser projection roundtrip and unchanged legacy-body oracle.
- For identity changes, cover new-person add, same-person clone, shared-profile propagation, SID-specific isolation, immutable `id`/`personId`, configured partial-store failure, injected failure after each store write, rollback, restart recovery, and unrelated-person preservation using temporary paths.
- Cover invalid dates/SIDs, numeric SID aliases, same-date progress-versus-watch precedence, later manual clears, malformed values, and input immutability when changing video review rules.
- Date-key verification must include a valid leap day, an invalid non-leap day, an impossible day such as `2026-02-30`, compact/basic ISO input, and timestamp input, plus actual route/store no-write evidence.
- Exercise storage, the path-injected watch/progress writer, absence planning/coordinator services, and repositories with temporary JSON/SQLite paths. Inject failures after updates, progress, logs, absence, carryover, and before the commit marker; assert every store rolls back, crash journals recover, failed rollback stays fail-closed/retryable, and unrelated dates/SIDs and manual states survive. A deterministic two-thread negative control must reproduce stale automatic reassignment without the barrier and prove it is absent with coordinator → absence read → updates lock ordering.
