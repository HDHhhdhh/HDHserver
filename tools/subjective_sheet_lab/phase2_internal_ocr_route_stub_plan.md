# Phase 2 Internal OCR Route Stub Plan

Status: report only. This planning pass did not implement code, did not call Gemini/API, did not call `/api/submit-test`, did not click `#tsSubmit`, and did not modify operating data, answer keys, DB schema, student records, or `tests-config.json`.

## Evidence Inspected

- `static/js/student.js`
  - URL flag: `window.__OCR_TEST_SHEET_ENABLED__ = new URLSearchParams(location.search).get("ocr") === "1"`
  - allowlist: `OCR_PHASE1_ALLOWED_TEST_IDS`
  - assigned-test click interception for `?ocr=1` plus allowlisted tests
  - modal OCR entry markup, review payload normalization, mock payload creation, `answersText` bridge, and existing submit handler
- `routes/api_tests.py`
  - existing `/api/ocr-test-sheet` answersText helper route
  - existing `/api/submit-test` grading/save route
  - existing `/api/tests-config` route
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
  - review payload schema
  - final status set
  - blocked status set
  - answer-key leak rules
  - `answersText` bridge rules
- Existing Phase 2 integration plan:
  - `tools/subjective_sheet_lab/phase2_internal_ocr_route_integration_plan.md`

## Current Phase 1 OCR UI Integration

Phase 1 is a hidden mock flow inside the existing student test submission modal.

Current client facts:

- OCR UI is disabled by default.
- OCR UI becomes available only when the student page URL contains `?ocr=1`.
- OCR entry is additionally restricted by `OCR_PHASE1_ALLOWED_TEST_IDS`; current allowlist contains `t_unit_daesu_01_lv3_r1`.
- Assigned-test cards are only intercepted for OCR when both the URL flag and test allowlist pass.
- The existing test submission modal still owns:
  - `#tsType`
  - `#tsTestId`
  - `#tsRound`
  - `#tsAnswersText`
  - `#tsMemo`
  - `#tsSubmit`
- The mock review payload is currently created by `ocrReviewCreateMockPayload(test, round)` in `static/js/student.js`.
- `ocrReviewOpenMockFlow()` loads the mock payload into `ocrReviewPayload`, renders the review panel, and does not submit.
- `ocrReviewNormalizePayload()` rejects student-facing payloads containing answer-key-only fields:
  - `expected`
  - `canonical_answer`
  - `accepted_answers`
- `ocrReviewConvertToAnswersText()` is the final client-side bridge from a completed review payload into exactly 20 newline-separated answers.
- The existing submit handler is the only path that posts to `/api/submit-test`.

Current server facts:

- `/api/ocr-test-sheet` currently returns `{ ok, answersText, items, warnings }`; that route is not the review-payload contract and should not be reused as-is for Phase 2 review UI.
- `/api/submit-test` expects the real final submission payload:

```json
{
  "sid": "student id",
  "testId": "test id",
  "round": 1,
  "answersText": "20 newline-separated answers",
  "memo": ""
}
```

- `/api/submit-test` grades against `tests-config.json` answer keys and writes the saved record. Phase 2 OCR must not call it.

## Proposed Route Name

Use a new route:

```http
POST /api/ocr-test-sheet-review
```

Why this route name:

- It is distinct from existing `/api/ocr-test-sheet`, which returns `answersText` directly.
- It names the new contract: OCR result for student review, not final submission.
- It can live in the existing `routes/api_tests.py` blueprint later, avoiding `app.py` blueprint registration changes in the first implementation.

Do not implement this route during this planning pass.

## Request Contract

Recommended content type for all phases:

```http
Content-Type: multipart/form-data
```

Fields:

| Field | Required | Phase | Rule |
|---|---:|---|---|
| `sid` | yes | A+ | Existing student id. Reject empty and ghost student ids. |
| `testId` | yes | A+ | Must be allowlisted for Phase 2 OCR. Initial value: `t_unit_daesu_01_lv3_r1`. |
| `round` | yes | A+ | Must parse to an allowed round. Initial allowlist: round `1` for the allowed test. |
| `image` | no in A, yes in B+ | B+ | Full answer sheet image. A route stub accepts omission. |
| `clientMode` | optional | A+ | Diagnostic only, for example `ocr_hidden_flag`. Never trusted for authorization. |

Phase 2A route stub may accept either `multipart/form-data` or JSON for easier test-client smoke checks, but the browser integration should use `FormData` from the start so Phase 2B can add the image without changing the frontend contract.

## Response Contract

Success:

```json
{
  "ok": true,
  "review_payload": {
    "source": "phase2_route_stub_mock",
    "test_id": "t_unit_daesu_01_lv3_r1",
    "round": "1",
    "problem_count": 20,
    "items": [
      {
        "question_no": 1,
        "status": "safe_auto_grade",
        "recognized": "1",
        "warnings": [],
        "candidates": [],
        "final_answer": "1",
        "source": "safe_auto_grade"
      }
    ]
  },
  "warnings": []
}
```

Failure:

```json
{
  "ok": false,
  "errorCode": "feature_disabled",
  "message": "OCR review route is disabled.",
  "warnings": []
}
```

Response rules:

- `review_payload` must match the lab contract in `tools/subjective_sheet_lab/ocr_review_payload_contract.md`.
- `review_payload.problem_count` must be `20`.
- `review_payload.items` must include exactly one item per `question_no` from `1` through `20`.
- Student-facing response must not include:
  - `expected`
  - `canonical_answer`
  - `accepted_answers`
  - answer-key rows
  - raw provider response
  - API keys
  - `.env` values
- The route returns review data only. It does not grade and does not save.

## Proposed Files To Change Later

Phase 2A implementation scope, later only:

- `routes/api_tests.py`
  - Add `POST /api/ocr-test-sheet-review` stub under the existing tests blueprint.
  - Keep `/api/ocr-test-sheet`, `/api/submit-test`, and `/api/tests-config` behavior unchanged.
- `static/js/student.js`
  - Replace the mock payload source in `ocrReviewOpenMockFlow()` with a provider switch.
  - Preserve the existing `ocrReviewCreateMockPayload()` as local fallback/test hook.
  - Preserve `ocrReviewNormalizePayload()`, `ocrReviewConvertToAnswersText()`, and the existing `#tsSubmit` handler.
- `tools/subjective_sheet_lab/*`
  - Add or update route-stub harnesses and validation reports only.

Do not change later in Phase 2A:

- `app.py`
- `tests-config.json`
- answer keys
- DB schema
- `tests.json`
- `logs.json`
- `progress.json`
- `data/**`
- student records

## Client-Side Changes Needed Later

Minimal frontend change:

1. Keep `?ocr=1` as the only client-side feature flag.
2. Keep `OCR_PHASE1_ALLOWED_TEST_IDS` or rename to a Phase 2 allowlist only if the implementation also updates all test hooks and docs.
3. Add a small route-backed payload loader:

```text
ocrReviewFetchRoutePayload(test, round)
  -> build FormData(sid, testId, round, optional image later)
  -> POST /api/ocr-test-sheet-review
  -> require data.ok === true
  -> return data.review_payload
```

4. Change the OCR button flow from:

```text
ocrReviewOpenMockFlow()
  -> ocrReviewCreateMockPayload()
  -> ocrReviewRender()
```

to:

```text
ocrReviewOpenFlow()
  -> if route mode enabled, fetch /api/ocr-test-sheet-review
  -> else use ocrReviewCreateMockPayload()
  -> ocrReviewNormalizePayload()
  -> ocrReviewRender()
```

5. If the route fails:
   - clear the OCR review panel
   - show a small error message
   - keep `#tsAnswersText` editable
   - keep normal manual submission available
6. Do not auto-fill `#tsAnswersText` until the student explicitly applies the reviewed payload.
7. Do not auto-click `#tsSubmit`.
8. Do not call `/api/submit-test` anywhere in OCR code.

## Server-Side Changes Needed Later

Phase 2A route stub:

1. Parse `sid`, `testId`, and `round`.
2. Check server feature flag, default disabled.
3. Check OCR test allowlist and round allowlist.
4. Reject ghost student ids.
5. Return the same student-safe mock review payload shape currently produced by `ocrReviewCreateMockPayload()`.
6. Run a server-side answer-key leak scan before returning.
7. Return JSON only.

Recommended server flags:

```text
OCR_PHASE2_REVIEW_ROUTE_ENABLED=0
OCR_PHASE2_ALLOWED_TEST_IDS=t_unit_daesu_01_lv3_r1
OCR_PHASE2_ALLOWED_ROUNDS=t_unit_daesu_01_lv3_r1:1
OCR_PHASE2_REVIEW_PROVIDER=mock
OCR_PHASE2_ALLOW_GEMINI=0
```

Server route must not:

- call Gemini/API
- call `/api/submit-test`
- grade
- write runtime data
- expose answer keys
- trust `clientMode` as authorization

## Safety Checks

Client safety:

- OCR UI hidden unless `?ocr=1`.
- OCR flow blocked for non-allowlisted tests.
- Existing manual `#tsAnswersText` remains available.
- Existing submit button remains unchanged.
- `review_required`, `retake_required`, `retake_uploaded`, and `data_check_required` continue to block `answersText` fill.
- `ocrReviewFindForbiddenKeys()` continues to reject answer-key fields before render/fill.

Server safety:

- Route disabled by default.
- Route allowlist enforced server-side, independent of frontend.
- No grading in route.
- No writes in route.
- No `/api/submit-test` reference in route implementation.
- No provider calls in route stub.
- No answer-key-only fields in response.

Operational safety:

- Production default remains `NO-GO`.
- No OCR behavior for default student URLs.
- Manual direct-answer flow remains the fallback.
- Existing `/api/submit-test` remains the only final persistence path.

## Failure Modes

| Failure | Stub response | Client outcome |
|---|---|---|
| feature disabled | `503 feature_disabled` | Show OCR unavailable; manual input remains. |
| missing `sid` | `400 invalid_request` | Show error; manual input remains. |
| ghost student sid | `403 forbidden_student` | Show error; manual input remains. |
| missing `testId` | `400 invalid_request` | Show error; manual input remains. |
| non-allowlisted test | `403 test_not_allowlisted` | Disable OCR; manual input remains. |
| non-allowlisted round | `403 round_not_allowlisted` | Disable OCR; manual input remains. |
| missing image in Phase 2A | allowed | Stub still returns mock payload. |
| missing image in Phase 2B+ | `400 image_required` | Manual input remains. |
| invalid image in Phase 2B+ | `400 invalid_image` | Manual input remains. |
| answer-key leak detected | `500 contract_violation` | Do not render OCR payload; manual input remains. |
| unresolved review payload | `ok:true` with blocked statuses | Client blocks fill; manual input remains. |

## Future Phases

### A. Route Stub Returns Mock Payload

Purpose: prove route plumbing and review-payload contract without OCR/provider risk.

Behavior:

- Route can be enabled only by explicit server flag.
- Route accepts `sid`, `testId`, and `round`.
- Route validates allowlist.
- Route returns a fixed 20-item mock review payload.
- No image required.
- No Gemini/API call.
- No grading.
- No data write.

### B. Route Accepts Image But Still Returns Mock Payload

Purpose: prove upload handling without OCR/provider risk.

Behavior:

- Route requires `image`.
- Route validates file size and image MIME/type.
- Route does not persist the upload.
- Route still returns the same mock payload.
- No Gemini/API call.
- No grading.
- No data write.

### C. Route Runs Local Crop/Enhance Pipeline

Purpose: prove server-side answer-sheet preprocessing.

Behavior:

- Route accepts the image.
- Local pipeline finds markers, crops q001-q020, and creates enhanced crops/contact sheets.
- Debug artifacts stay in `C:\server-ocr` only under an explicit debug flag.
- Route still does not call Gemini.
- Route returns either a cached review payload or blocking statuses for crop failures.

### D. Route Returns Cached Gemini Review Payload

Purpose: prove the final review-payload bridge with realistic cached OCR output.

Behavior:

- No live Gemini call.
- Load a known cached `recognized.json` or normalized review payload for the allowlisted case.
- Return the same student-safe schema.
- Validate that data-check/review/retake statuses block `#tsAnswersText` fill.

### E. Route Calls Gemini Only Under Explicit Lab/Local Flag

Purpose: prove live provider integration after A-D pass.

Behavior:

- Requires explicit server-side provider flag.
- Requires explicit local/lab operator approval before testing.
- Uses server-side API key only.
- Caches results.
- Stops on quota/429 without retry loops.
- Normalizes provider output before response.
- Still does not call `/api/submit-test`.

## Validation Plan

Planning-pass validation:

- Confirm the report file exists.
- Confirm only lab documentation was added/modified by this planning task.
- Confirm no Gemini/API command was run.
- Confirm `/api/submit-test` was not called.
- Confirm operating files were inspected read-only.

Future Phase 2A implementation validation:

- `python -m py_compile routes/api_tests.py`
- `node --check static/js/student.js`
- Flask `test_client()`:
  - disabled route returns `feature_disabled`
  - enabled allowlisted request returns 20-item review payload
  - non-allowlisted test is rejected
  - non-allowlisted round is rejected
  - ghost student sid is rejected
- Lab validators:
  - `python tools/subjective_sheet_lab/validate_ocr_review_contract.py`
  - `python tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py`
  - `python tools/subjective_sheet_lab/verify_final_review_payload_bridge.py`
- Browser/manual QA:
  - default student URL shows no OCR UI
  - `?ocr=1` plus allowlisted test shows OCR entry
  - route-backed mock response renders the same review panel
  - unresolved review items block fill
  - completed review fills `#tsAnswersText` with exactly 20 lines
  - no `/api/submit-test` network request occurs until the user clicks existing submit

## Rollback Plan

Phase 2A rollback after future implementation:

1. Set `OCR_PHASE2_REVIEW_ROUTE_ENABLED=0`.
2. Revert only Phase 2 route/client patch if needed.
3. Leave `/api/submit-test` unchanged.
4. Leave `tests-config.json`, answer keys, DB, and student records untouched.
5. Keep manual `#tsAnswersText` submission available.

Because Phase 2A must not write data, normal rollback should require no data restoration.

## GO / NO-GO Gate For Actual Implementation

GO for implementing Phase 2A only if:

- Phase 1 hidden mock QA remains PASS.
- Default student page still hides OCR.
- Existing allowlist is preserved.
- Route is disabled by default.
- Route stub returns only student-safe review payload.
- Final submit remains existing `/api/submit-test`.
- Manual fallback remains available.

NO-GO if any of these are true:

- The plan requires enabling OCR by default.
- The plan requires calling Gemini/API in Phase 2A.
- The plan requires calling `/api/submit-test` from OCR code.
- The plan requires changing `tests-config.json`, answer keys, DB schema, or student records.
- The plan exposes `expected`, `canonical_answer`, or `accepted_answers` to the student UI.
- The plan bypasses `ocrReviewConvertToAnswersText()`.
- The plan allows unresolved review statuses to fill `#tsAnswersText`.

## Confirmation For This Planning Pass

This pass created this report only:

- `tools/subjective_sheet_lab/phase2_internal_ocr_route_stub_plan.md`

This pass did not:

- implement `/api/ocr-test-sheet-review`
- call Gemini/API
- call `/api/submit-test`
- click `#tsSubmit`
- modify operating student page behavior
- modify `app.py`
- modify `routes`
- modify `static`
- modify `data`
- modify DB schema
- modify student records
- modify `tests-config.json`
- modify answer keys
