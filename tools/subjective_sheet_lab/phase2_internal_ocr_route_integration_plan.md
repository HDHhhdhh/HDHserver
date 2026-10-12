# Phase 2 Internal OCR Route Integration Plan

Status: plan only. This document does not implement the route, does not call Gemini/API, does not call `/api/submit-test`, and does not modify operating code, runtime data, `tests-config.json`, or answer keys.

## 1. Current Phase 1 Baseline

Evidence reviewed:

- `static/js/student.js`
- `routes/api_tests.py`
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
- `tools/subjective_sheet_lab/phase1_hidden_integration_manual_qa_checklist.md`
- `tools/subjective_sheet_lab/phase1_manual_qa_result_report.md`
- `tools/subjective_sheet_lab/phase1_internal_route_adapter_report.md`
- `tools/subjective_sheet_lab/phase1_internal_contract_report.md`
- `tools/subjective_sheet_lab/final_review_payload_bridge_report.md`
- `tools/subjective_sheet_lab/pre_integration_100_percent_readiness_report.md`
- `tools/subjective_sheet_lab/ocr_benchmark_gate.py`

Current baseline:

- Phase 1 hidden mock QA passed after accidental submit cleanup.
- OCR UI is enabled only when `window.__OCR_TEST_SHEET_ENABLED__` is true, which currently means URL query `?ocr=1`.
- OCR is additionally allowlisted by `OCR_PHASE1_ALLOWED_TEST_IDS`, currently only `t_unit_daesu_01_lv3_r1`.
- The test submit modal is created dynamically in `static/js/student.js` inside `ensureModal()`.
- Existing modal controls remain:
  - `#tsType`
  - `#tsTestId`
  - `#tsRound`
  - `#tsAnswersText`
  - `#tsMemo`
  - `#tsSubmit`
- Phase 1 mock review payload is created by `ocrReviewCreateMockPayload()`.
- Student-facing payload validation rejects answer-key-only fields:
  - `expected`
  - `canonical_answer`
  - `accepted_answers`
- `ocrReviewConvertToAnswersText()` converts only fully resolved review payloads into exactly 20 newline-separated answers.
- Clicking `확인한 답안으로 답칸 채우기` fills only `#tsAnswersText`.
- Final save still happens only when the student clicks `#tsSubmit`.
- `#tsSubmit` currently posts to `/api/submit-test` with `{ sid, testId, round, answersText, memo }`.
- Production default remains `NO_GO`.

Phase 2 must replace only the Phase 1 mock review payload source. It must not change the final submit path.

## 2. Proposed Phase 2 Route Name And Payload Contract

Recommended future route:

```http
POST /api/internal/ocr-test-sheet-review
```

Recommended location:

- Add to the existing `routes/api_tests.py` blueprint in a later implementation phase.
- Rationale: avoids modifying `app.py` for a new blueprint during Phase 2.
- Do not touch `/api/submit-test`.

Request shape:

```http
POST /api/internal/ocr-test-sheet-review
Content-Type: multipart/form-data
```

Fields:

| Field | Required | Rule |
|---|---:|---|
| `sid` | yes | Existing student id. Reject ghost student ids. |
| `testId` | yes | Must be in the Phase 2 OCR allowlist. |
| `round` | yes | `1`, `2`, or `3`; Phase 2 allowlist initially permits only round `1` for `t_unit_daesu_01_lv3_r1`. |
| `image` | Phase 2B+ | Full answer-sheet photo. Phase 2A may omit it because the route is a stub returning mock payload. |
| `clientMode` | optional | `student_hidden_flag`; diagnostic only, never trusted for authorization. |

Success response:

```json
{
  "ok": true,
  "review_payload": {
    "source": "phase2_internal_mock",
    "test_id": "t_unit_daesu_01_lv3_r1",
    "round": "1",
    "problem_count": 20,
    "items": [
      {
        "question_no": 1,
        "status": "safe_auto_grade",
        "recognized": "5",
        "warnings": [],
        "candidates": [],
        "final_answer": "5",
        "source": "safe_auto_grade"
      }
    ]
  },
  "warnings": []
}
```

Failure response:

```json
{
  "ok": false,
  "errorCode": "provider_disabled",
  "message": "OCR provider is disabled.",
  "warnings": []
}
```

Contract rules:

- `review_payload` must match `tools/subjective_sheet_lab/ocr_review_payload_contract.md`.
- `review_payload.items` must contain exactly one item for each question `1..20`.
- Student-facing response must never include `expected`, `canonical_answer`, `accepted_answers`, raw answer-key rows, raw provider payloads, API keys, or `.env` values.
- The route must return review payload only. It must not produce a saved test record.
- The route must not call `/api/submit-test`.
- The route must not write `tests.json`, `logs.json`, SQLite, `progress.json`, `data/**`, or student records.

## 3. Student-Side Flow

Future Phase 2 frontend change should be minimal:

1. Keep existing modal and manual textarea visible.
2. Keep OCR entry hidden unless:
   - URL has `?ocr=1`.
   - selected/current `testId` is allowlisted.
   - test round is allowlisted.
3. Replace `ocrReviewOpenMockFlow()` payload creation with a small provider function:

```text
ocrReviewOpenFlow()
  -> if providerMode is "mock": use existing ocrReviewCreateMockPayload()
  -> if providerMode is "internal-route": upload image to /api/internal/ocr-test-sheet-review
  -> normalize data.review_payload with ocrReviewNormalizePayload()
  -> render the same review panel
```

4. Keep `ocrReviewNormalizePayload()`, `ocrReviewBlockingItems()`, and `ocrReviewConvertToAnswersText()` as the final frontend gate.
5. `확인한 답안으로 답칸 채우기` continues to set `#tsAnswersText` only.
6. Student still decides whether to edit `#tsAnswersText`.
7. Student still submits only by clicking the existing `#tsSubmit`.

Do not:

- Hide or remove `#tsAnswersText`.
- Auto-click or programmatically call `#tsSubmit`.
- Fetch `/api/submit-test` from OCR code.
- Show answer-key details in the OCR review panel.

## 4. Server-Side Flow

Future route flow:

1. Parse multipart form.
2. Validate feature flags:
   - global route flag
   - student hidden flag mode if needed
   - test allowlist
   - round allowlist
   - provider mode
3. Validate student id:
   - `sid` required
   - reject ghost/test-protected ids using existing student-id guard pattern
4. Validate selected test:
   - `testId` required
   - must be `t_unit_daesu_01_lv3_r1` for Phase 2
   - test definition must exist
   - problem count must be 20
   - answer-mode documentation must exist for the test
5. Validate upload:
   - `image` required in Phase 2B+
   - accepted MIME types: JPEG, PNG, WebP if supported
   - bounded file size
   - reject empty or corrupt image
6. Produce a review payload:
   - Phase 2A: existing mock payload
   - Phase 2B: accepts image but still returns mock payload
   - Phase 2C: local crop/enhance pipeline with cached review payload
   - Phase 2D: explicit lab/local Gemini provider
7. Run server-side student-safe leak scan before response.
8. Return `{ ok: true, review_payload, warnings }`.

The server route must fail closed. On any ambiguity, return an error or review payload with blocking statuses; never auto-submit.

## 5. Crop/Enhance/Contact-Sheet/Gemini Plug-In Point

Provider plug-in seam:

```text
route validation
  -> phase2_provider.recognize_sheet(image_bytes, sid, testId, round)
  -> crop/enhance/contact-sheet pipeline
  -> provider result
  -> evaluate/review policy
  -> student-safe review_payload
```

Planned provider layers:

- `core/subjective_ocr_phase2.py`: route-facing adapter, no Flask dependency.
- `core/subjective_review_contract.py`: operating copy of the reviewed lab contract, if/when promoted.
- `core/subjective_review_policy.py`: status classification, warning policy, answer-mode mismatch handling.
- `C:\server-ocr` lab/runtime scripts remain the OCR sandbox while Phase 2 is hidden.

Gemini provider plug-in:

- Do not wire Gemini in Phase 2A/B.
- Phase 2C should use cached/local review payloads only.
- Phase 2D may call Gemini only when an explicit local/lab provider flag is enabled.
- Provider output must be normalized into the same review payload schema before reaching the browser.

## 6. Gemini Disabled Or Mocked By Default

Required flags:

```text
OCR_PHASE2_ROUTE_ENABLED=0
OCR_PHASE2_ALLOWED_TEST_IDS=t_unit_daesu_01_lv3_r1
OCR_PHASE2_ALLOWED_ROUNDS=t_unit_daesu_01_lv3_r1:1
OCR_PHASE2_PROVIDER=mock
OCR_PHASE2_ALLOW_GEMINI=0
OCR_PHASE2_WRITE_DEBUG_ARTIFACTS=0
```

Default behavior:

- Route disabled unless `OCR_PHASE2_ROUTE_ENABLED=1`.
- Provider defaults to `mock`.
- Gemini is disabled unless both:
  - `OCR_PHASE2_PROVIDER=gemini`
  - `OCR_PHASE2_ALLOW_GEMINI=1`
- Browser never receives API key, `.env` contents, or raw Gemini payload.
- If provider is disabled, return `provider_disabled` and leave manual input available.

## 7. Return Same Review Payload Schema As Phase 1 Mock

Phase 2 route must produce the same item semantics already consumed by the Phase 1 UI:

- `safe_auto_grade`
- `review_required`
- `retake_required`
- `retake_uploaded`
- `data_check_required`
- `confirmed`
- `student_selected_candidate`
- `student_direct_input`
- `safe_auto_grade_after_retake`
- `student_selected_candidate_after_retake`
- `student_direct_input_after_retake`

Important policy:

- Accepted match with warnings must not become `safe_auto_grade`.
- `data_check_required` is not student-editable.
- `retake_uploaded` is not final.
- `review_required`, `retake_required`, `retake_uploaded`, and `data_check_required` must block textarea fill.
- `choice_number` items for `t_unit_daesu_01_lv3_r1` must not auto-convert expressions into option numbers.
- `answer_value` items must not auto-simplify or rewrite math into a different expression.

## 8. Preserve `#tsAnswersText` 20-Line Output

Frontend rule:

- Only `ocrReviewConvertToAnswersText()` may transform a final review payload into textarea content.
- Output must be exactly 20 newline-separated lines.
- Sort by `question_no`.
- No question labels.
- No embedded newline inside an answer.
- No empty final answer.

Server rule:

- Route returns review payload, not final `answersText`, until frontend review is complete.
- Optional future server-side validator may accept a final review payload and return `answersText`, but it must not submit.

## 9. Preserve `/api/submit-test` As Only Final Submit Path

Hard boundary:

- OCR route never calls `/api/submit-test`.
- OCR route never writes a grade record.
- OCR route never writes logs/tests/progress/student data.
- OCR frontend never calls `/api/submit-test` except through the existing `#tsSubmit` click handler.
- Existing `#tsSubmit` remains the only final save action.

The only data handed from OCR review to submit flow is `#tsAnswersText`.

## 10. Required Feature Flags And Allowlist Checks

Frontend checks:

- URL flag: `?ocr=1`
- selected/current test id must be allowlisted
- selected/current round must be allowlisted
- OCR UI hidden/disabled when any check fails

Server checks:

- route flag enabled
- provider mode allowed
- `testId` allowlisted
- round allowlisted
- problem count is 20
- answer-mode table exists for test id
- image validation passes in image phases
- no answer-key-only fields in outbound student payload

Never rely on frontend flags alone.

## 11. Failure Modes

| Failure | Response | Student outcome |
|---|---|---|
| upload missing | `400 invalid_request` | Show message; manual textarea remains usable. |
| invalid image type/size | `400 invalid_image` | Show message; manual textarea remains usable. |
| corrupt image | `400 invalid_image` | Ask for another photo; manual textarea remains usable. |
| route disabled | `503 feature_disabled` | OCR hidden or error; manual textarea remains usable. |
| OCR provider disabled | `503 provider_disabled` | Show provider disabled; manual textarea remains usable. |
| marker detection failed | `ok:false`, `whole_sheet_retake_required` | Ask for full sheet recapture; do not show review payload. |
| crop/enhance failed for one item | item `retake_required` | Block OCR fill until resolved or manual fallback used. |
| unresolved `review_required` | frontend conversion error | Do not fill `#tsAnswersText` from incomplete payload. |
| `retake_required` | frontend conversion error | Require retake/manual fallback. |
| `retake_uploaded` | frontend conversion error | Require re-recognition before fill. |
| `data_check_required` | frontend conversion error | Block OCR finalization; use manual fallback or teacher handling. |
| answer-mode mismatch | item `data_check_required` or `review_required` | Do not auto-convert expression/choice formats. |
| answer-key leak detected | `500 contract_violation` | Do not render payload; keep manual fallback. |
| provider timeout/quota | `503 provider_unavailable` | Manual fallback; no retry loop in student UI. |

## 12. Security And Safety

Required safety rules:

- No answer-key leakage to student UI or route response.
- No auto-submit.
- No `/api/submit-test` call from OCR route or OCR frontend code.
- No API key exposure.
- No `.env` content exposure.
- No raw provider payload in browser.
- No student record write during OCR processing.
- No runtime data write during OCR processing.
- No debug artifacts unless explicitly enabled and stored outside operating data.
- Clean up temporary uploads immediately after processing.
- Keep file size and MIME limits strict.
- Keep production default `NO_GO`.

## 13. Minimal Implementation Phases

### A. Route Stub Returning Existing Mock Payload

Goal: prove route plumbing without image processing.

Future code scope:

- Add `POST /api/internal/ocr-test-sheet-review` under existing `routes/api_tests.py` blueprint.
- Add route tests/harness under `tools/subjective_sheet_lab`.
- Frontend may optionally call this route only under `?ocr=1` and allowlisted test.

Behavior:

- Requires route flag.
- Validates `sid`, `testId`, `round`.
- Rejects non-allowlisted test.
- Returns the same mock review payload currently created by `ocrReviewCreateMockPayload()`.
- No image required.
- No provider call.
- No data write.

GO gate:

- Disabled route returns `feature_disabled`.
- Enabled allowlisted request returns valid 20-item review payload.
- Leak scan passes.
- Browser flow still fills `#tsAnswersText`.
- `/api/submit-test` calls remain zero until `#tsSubmit`.

### B. Route Accepts Image But Still Returns Mock

Goal: prove upload handling without OCR provider risk.

Behavior:

- Requires `image`.
- Validates MIME and byte limit.
- Reads image bytes in memory or temporary storage with immediate cleanup.
- Ignores image content after validation.
- Returns same mock review payload.

GO gate:

- missing upload returns `invalid_request`.
- invalid image returns `invalid_image`.
- valid image returns same review payload.
- no debug file leak.
- no data write.

### C. Route Runs Local Crop Pipeline And Returns Cached Review Payload

Goal: prove real server-side image preprocessing while still avoiding live Gemini.

Behavior:

- Run local marker/crop/enhance pipeline.
- Produce crop/contact artifacts under `C:\server-ocr` only when debug artifact flag is on.
- Use cached recognized/review payload from lab fixtures.
- Return normalized student-safe review payload.

GO gate:

- whole-sheet failure returns whole-sheet retake.
- per-question crop failure becomes `retake_required`.
- cached review payload validates against `ocr_review_payload_contract.md`.
- no Gemini/API call.

### D. Route Optionally Calls Gemini Only In Lab/Local Explicit Flag

Goal: prove live provider path only after A-C pass.

Behavior:

- Gemini only if `OCR_PHASE2_PROVIDER=gemini` and `OCR_PHASE2_ALLOW_GEMINI=1`.
- Cache successful provider responses.
- 429 stops immediately and writes lab-only error report.
- Timeout returns provider unavailable.
- Provider output normalized into review payload before browser.

GO gate:

- explicit operator approval for live provider call.
- API key loaded server-side only.
- no key in logs, browser, reports, or generated payloads.
- no provider call in default/mock mode.

## 14. Validation Plan

Static/lab validation:

- `python -m py_compile routes/api_tests.py`
- `node --check static/js/student.js`
- `python tools/subjective_sheet_lab/validate_ocr_review_contract.py`
- `python tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py`
- `python tools/subjective_sheet_lab/verify_final_review_payload_bridge.py`
- `python tools/subjective_sheet_lab/run_phase1_preflight_checks.py`

Future route-specific validation:

- disabled route smoke via Flask `test_client()`
- allowlisted mock success via Flask `test_client()`
- non-allowlisted rejection via Flask `test_client()`
- missing image failure for Phase 2B+
- invalid image failure for Phase 2B+
- answer-key leak scan on every success payload
- submit-call scan proving OCR route does not reference `/api/submit-test`
- runtime data diff check before/after route calls:
  - `tests.json`
  - `logs.json`
  - `progress.json`
  - `app.sqlite`

Browser validation:

- default URL: no OCR UI
- `?ocr=1` allowed test: OCR entry visible
- `?ocr=1` blocked test: OCR hidden/disabled
- route success renders same review panel
- unresolved statuses block fill
- final reviewed payload fills `#tsAnswersText` with exactly 20 lines
- DevTools Network shows no `/api/submit-test` during OCR upload/review/fill
- mobile viewport still usable

## 15. Rollback Plan

Immediate rollback:

- Set `OCR_PHASE2_ROUTE_ENABLED=0`.
- Set `OCR_PHASE2_PROVIDER=mock` or `disabled`.
- Keep `?ocr=1` hidden flag off for normal users.

Code rollback, if needed after implementation:

- Revert only Phase 2 route/frontend patch.
- Do not revert unrelated dirty files.
- Do not touch `tests-config.json`, answer keys, or runtime data.
- Existing `/api/submit-test` remains unchanged, so no grading rollback should be needed.

Data rollback:

- No OCR route should write data; expected rollback is none.
- If accidental manual submit occurs again, use the Phase 1 cleanup pattern: identify exact saved rows, back up touched files, remove only accidental rows.

## 16. GO / NO-GO Gates

### GO For Phase 2A

- Phase 1 hidden mock QA PASS.
- Accidental submit cleanup complete.
- Production default remains `NO_GO`.
- Route disabled by default.
- Route stub returns valid student-safe review payload.
- No `/api/submit-test` call.
- No data write.

### GO For Phase 2B

- Phase 2A PASS.
- Image upload validation works.
- Invalid/missing image failures are safe JSON.
- Valid image still returns mock payload.
- No provider call.

### GO For Phase 2C

- Phase 2B PASS.
- Local crop/enhance pipeline produces deterministic outputs.
- Whole-sheet and per-question failures map to correct statuses.
- Cached review payload validates.
- No Gemini/API call.

### GO For Phase 2D

- Phase 2C PASS.
- Explicit local/lab approval for provider call.
- API key is server-side only.
- Quota/timeout/error behavior tested.
- Provider response normalized to student-safe payload.
- No answer-key leak.

### NO-GO Conditions

Stop immediately if any of these occur:

- OCR UI appears without `?ocr=1`.
- Non-allowlisted tests can open OCR.
- OCR route calls `/api/submit-test`.
- OCR frontend calls `/api/submit-test` before `#tsSubmit`.
- OCR route writes `tests.json`, `logs.json`, SQLite, `progress.json`, `data/**`, or student records.
- Student-facing payload includes `expected`, `canonical_answer`, `accepted_answers`, answer keys, raw provider payload, API keys, or `.env` values.
- `#tsAnswersText` output is not exactly 20 ordered newline-separated answers.
- `review_required`, `retake_required`, `retake_uploaded`, or `data_check_required` can be submitted through OCR fill.
- `data_check_required` becomes student-editable.
- Gemini runs when provider mode is disabled/mock.
- Production default is proposed before independent handwriting and operator-review evidence are sufficient.

## Final Recommendation

Implement Phase 2 as a route-source swap, not as a new submission system:

```text
Phase 1 mock payload source
  -> Phase 2 internal review-payload route
  -> same review panel
  -> same answersText bridge
  -> same existing #tsSubmit
  -> same existing /api/submit-test
```

The smallest safe first implementation is Phase 2A: a default-disabled internal route that returns the existing mock review payload and proves the route contract without image processing, Gemini, or data writes.
