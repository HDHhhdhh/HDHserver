# FRONTEND JS KNOWLEDGE BASE

## Overview
Browser behavior is split between admin modules, all-page modules, shared helpers, and large standalone student/test scripts.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Shared fetch helpers | `shared/api.js` | `fetchJson`, `fetchJsonOr`, `sendJson`, `ensureOk`, `ApiError`. |
| Shared search/calendar/self-study helpers | `shared/` | Reusable UI/data helpers. |
| Admin entry | `admin/main.js` | Admin bootstrap and feature initialization. |
| Student page | `student.js` | Monolithic bootstrap, assigned/review video playlist, Kollus playback, watch sync, announcements, tests, answer links. |
| Video catalog page | `video-manage.js`, `shared/videoIds.js`, `shared/videoCatalogIdentity.js` | Normal full-map save plus an offline correction draft mode for protected MID changes/removals. |
| Test management page | `tests.js` | Admin test catalog editing and CSV import UI. |
| Calendar/files pages | `school-cal.js`, `file-manage.js` | Standalone full-map editors with their own compatibility contracts. |
| All-students page | `all/main.js` | All-page bootstrap. |
| Demo sandbox | `admin/demo/` | Pre-entrypoint synthetic API, session store, navigation guard, and help tutorial. |
| Answer-link map | `test_answer_link_map.json` | Sole tracked canonical explanation map. The retired `.js` wrapper and URL must stay absent/404. |

## Conventions
- When adding or touching JSON request wrappers, prefer `shared/api.js` or page-specific wrappers over fresh ad hoc fetch helpers.
- Preserve endpoint URLs, payload keys, credentials/cache options, and existing response shapes.
- `todayLocalKey()` means real local date. Admin selected-date behavior belongs in `static/js/admin/core/adminDate.js`.
- Student bootstrap `assignedTests` stays a top-level array and its server-projected `answerUrl`/`answerRestricted` fields are authoritative. Student test cards are read-only answer links; do not add submit, grading, OCR capture, or client-side answer-map fallback hooks.
- Student bootstrap is also the sole authority for `reviewVideos` membership. Normalize only deduplicated `reviewStatus: "done"` rows, preserve chapter order, and never infer candidates from `/api/videos`, progress/watch, or localStorage. If bootstrap fails, surface the load error and stop instead of reconstructing partial state from legacy endpoints.
- The “영상 등록” button only appends checked authorized MIDs to the visible playlist and `student:review-playlist:<sid>:<date>`. It performs no fetch and must prune stored MIDs against each fresh bootstrap. Checkbox/title clicks select only; playback starts from the main playlist row.
- Assigned and registered-review rows share `play(mid)`, `/api/get-url`, the Kollus bridge, local resume state, and `/api/watch`. Outside the academy, keep review rows title-only and non-actionable; do not issue get-url or watch requests.
- The current web student uses `/api/watch`. Do not introduce `/api/watch-status` calls here; that older endpoint remains temporarily only for the separately developed student app until its migration and merge.
- A server-authoritative bootstrap may intentionally reintroduce a manually reopened assigned video. Clear only that visible assigned MID's stale local completed cache; never apply this repair to unrelated review/history rows.
- Watch `updatedAt` is epoch milliseconds. Never apply bitwise integer coercion such as `| 0` to timestamps; add a regression assertion whenever watch snapshot serialization changes.
- File-manager assignment changes must fetch `X-Material-State-Revision` immediately before editing and POST the whole map with `If-Match`; show a reload/retry message on 409 and a read-only recovery message on 503. Keep the temporary no-header compatibility path until the already-running old backend is normally restarted.
- The retired `ensureTodayAssignmentIfMissing()`/last-assignment writer must not be restored in `student.js`; server snapshots and bootstrap own automatic assignment.
- Answer precedence is assignment/config direct URL, `sourceFiles.solutionFileId`, then canonical JSON map. Academy-network gating strips/blocks every layer.
- `video-manage.js` may add rows and edit metadata or a signed URL that resolves to the same MID. If an existing ID is removed or its MID changes in normal mode, restore the last saved catalog and show the persistent protection warning; the server 409 remains authoritative.
- Correction mode starts from a clone of the last saved catalog, disables normal save, suppresses auto-save POSTs, and may only download the versioned draft. Cancel restores the saved clone. Never add a browser apply endpoint or persist the draft in localStorage.
- `tests.js` POSTs the whole test config. Never save a network-stripped GET representation or drop source metadata, unknown fields, or answer rounds.
- Do not introduce mojibake or placeholder `????` text.

## Anti-Patterns
- Do not let student `todayLocalKey()` semantics leak into admin selected-date flows.
- Do not hand-edit generated link maps when a script should regenerate them.
- Do not make broad changes to `student.js` without testing the student page surface.
- Do not replace shared helper behavior with one-off fetch wrappers.
- Do not reintroduce the retired seven-endpoint bootstrap fallback. A failed `/api/student/bootstrap` request must not render a partial page without assigned tests or authoritative review membership.
- Do not persist student review registration through `/api/updates/self-study` or invent review/training-pack update endpoints.
- Keep completed rows from today's named `source: "auto"` assignment in the current playlist with the blue completion badge, including after the class log is archived; do not duplicate them in the review chooser. Historical completed assignments may move to review, while a manually reopened green assignment must clear stale local completion and remain in today's playlist.

## Video Verification

- Run `node --check static/js/student.js`, `node scripts/verify_student_previous_video_review.js`, and `node scripts/verify_student_material_access_scope.js` after student video/review/access changes.
- For catalog edits run `node --check static/js/video-manage.js`, `node scripts/verify_video_manage_ids.mjs`, `python scripts/verify_video_mid_change_guard.py`, and `python scripts/verify_video_catalog_correction.py`.
- Browser QA must cover one current assignment, one completed review registration, academy-network restriction, first-video autoplay/active state, playlist switch, and visible progress updates without console errors.
