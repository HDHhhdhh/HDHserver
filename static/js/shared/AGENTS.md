# SHARED JS KNOWLEDGE BASE

## Overview
Cross-page browser helpers live here. Admin, all-students, student, and utility pages import these modules, so behavior changes can fan out quickly.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Fetch and JSON helpers | `api.js` | `ApiError`, `ensureOk`, `fetchJson*`, `sendJson`, `JSON_HEADERS`. |
| Search normalization | `search.js` | Hangul initials, Dubeolsik keyboard variants, whitespace-as-AND matching. |
| School calendar normalization | `schoolCalendar.js` | V1/V2 calendar payloads, grade/phase flattening, nonblank merge behavior. |
| School calendar save queue | `schoolCalendarSaveQueue.js` | Serialized whole-document writes, revision chaining, conflict blocking, and flush keepalive. |
| Self-study day helpers | `selfStudy.js` | `selfStudyDays`, `day1`-`day5`, weekday/date matching. |
| Test-record data | `testRecordData.js` | Cached `/api/tests` flattening and `/api/tests-records` detail loads. |
| Test-record UI | `testRecordDetails.js` | Cross-page detail controls; currently hard-disabled by its feature flag. |

## Conventions
- Keep helpers framework-free ES modules.
- Preserve exported names; page modules import them directly.
- `fetchJson` parses JSON without checking HTTP status; `fetchJsonChecked` calls `ensureOk`. `fetchJsonOr` falls back only on fetch/parse exceptions, not valid JSON from a non-2xx response.
- `sendJson` defaults only the method, JSON headers, and body. Callers own credentials/cache options.
- Search helpers must keep Korean initials, composed Hangul, Latin keyboard variants, and multi-term AND behavior aligned.
- Calendar helpers should merge only nonblank override values so common school schedule fields survive sparse grade entries.
- Calendar save jobs must capture an immutable JSON snapshot before enqueueing, keep at most one request active, and pass the latest valid 64-hex revision as `If-Match`. A 409/428 blocks queued followers until `school-calendar/persistence.js` performs a fresh GET and calls `setRevision`; network failures remain retryable.
- Self-study helpers support both `selfStudyDays` and legacy `dayNSelfStudy` fields.
- `testRecordData.js` caches promises; keep cache invalidation and privacy-filtered response shapes explicit. Do not enable the detail UI flag without all-page/admin/student verification.

## Anti-Patterns
- Do not add page-specific DOM or state dependencies here.
- Do not replace Korean search normalization with plain lowercase matching.
- Do not assume `fetchJson` rejects non-2xx responses; callers needing that contract must use the checked helper.
- Do not make calendar normalization drop unknown payload fields unless every caller is updated.
- Do not retry a calendar conflict without a new authoritative GET, and do not compute test expectations with the queue's own private revision state.

## Verification
- For `api.js`, check at least one admin/all caller that exercises the helper path you touched.
- For `search.js`, verify a Korean initial search and a Latin keyboard-layout search.
- For calendar/self-study changes, verify both admin today rows and all-students table consumers when applicable.
