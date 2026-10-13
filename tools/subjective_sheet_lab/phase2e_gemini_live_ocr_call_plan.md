# Phase 2E Gemini-Live OCR Call Design Plan

Date: 2026-06-29 KST.

Scope: design-only report for adding live Gemini OCR safely after the current Phase 2D cached recognized/review-payload baseline. This task does not implement code, does not call Gemini/API, does not call `/api/submit-test`, does not click `#tsSubmit`, does not enable production default, and does not change environment variables.

## 1. Current Phase 2D Baseline

Authoritative current baseline: Phase 2D cached review-payload route-backed baseline.

Observed Phase 2D properties from the existing lab reports and verifier:

- The OCR review route remains disabled by default unless `OCR_PHASE2_REVIEW_ROUTE_ENABLED` is explicitly enabled.
- Phase 2C crop/contact generation runs before any Phase 2D cache lookup.
- Phase 2D is separately gated by `OCR_PHASE2D_CACHED_REVIEW_ENABLED`.
- Phase 2D reads local cached `review_payload` or local cached `recognized.json`.
- Recognized-only cache is converted into 20 `review_required` items.
- Phase 2D does not call Gemini/API.
- Phase 2D does not call `/api/submit-test`.
- Phase 2D does not use the old `/api/ocr-test-sheet`.
- Phase 2D does not read answer keys or `tests-config.json`.
- Student-facing payloads reject answer-key fields and filesystem path leaks.
- Malformed, missing, forbidden, or path-leaking cache falls back to the existing mock payload.
- Production default remains `NO-GO`.

Phase 2E must preserve all of those defaults and only add live provider calls behind additional explicit gates.

## 2. Proposed Phase 2E Feature Flags

Existing gates to preserve:

- `OCR_PHASE2_REVIEW_ROUTE_ENABLED`
  - Enables the internal/lab OCR review route.
  - Default: unset/false.
- `OCR_PHASE2D_CACHED_REVIEW_ENABLED`
  - Enables local cached recognized/review-payload lookup.
  - Default: unset/false.

Proposed new Phase 2E gates:

- `OCR_PHASE2E_GEMINI_LIVE_ENABLED`
  - Enables live Gemini OCR code path after Phase 2C and Phase 2D cache lookup.
  - Default: unset/false.
- `OCR_PHASE2E_PROVIDER_CALLS_ALLOWED`
  - Separate hard provider-call authorization flag.
  - Default: unset/false.
  - Live provider calls require both this flag and `OCR_PHASE2E_GEMINI_LIVE_ENABLED`.
- `OCR_PHASE2E_CACHE_WRITE_ENABLED`
  - Allows storing newly generated `recognized.json` in the Phase 2E runtime cache.
  - Default: false until retention and cleanup policy is approved.
- `OCR_PHASE2E_LOCAL_ONLY`
  - Forces Phase 2E to use local cache/mock/fake-provider paths only and forbids real Gemini/API calls even if the live implementation code exists.
  - Default: true for development, CI, and manual QA unless an operator explicitly disables local-only mode for an authorized live-provider run.
  - This flag should be treated as a hard provider-call veto, not as a hint.
- `OCR_PHASE2E_CONTACT_SHEET_ENABLED`
  - Allows using Phase 2C contact sheets as the provider input package.
  - Default: true only in lab after validation; false should still allow crop-only mode if implemented.
- `OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST`
  - Hard cap, recommended default: `4`, one per q001-q005, q006-q010, q011-q015, q016-q020 contact sheet.
- `OCR_PHASE2E_ALLOWED_TEST_IDS`
  - Server-side allowlist, initially only `t_unit_daesu_01_lv3_r1`.
- `OCR_PHASE2E_ALLOWED_ROUNDS`
  - Server-side allowlist, initially only round `1`.

Do not use a single feature flag for both UI visibility and provider calling. Route availability, live OCR selection, and provider-call authorization must remain separate.

## 3. Provider-Call Gate Rules

Live Gemini calls are allowed only when all required gates pass:

1. Route gate: `OCR_PHASE2_REVIEW_ROUTE_ENABLED` is true.
2. Existing route guards pass: real sid, non-ghost sid, allowlisted test id, allowlisted round, valid uploaded image.
3. Phase 2C crop/contact pipeline succeeds.
4. Phase 2D cache lookup is enabled and attempted first when available.
5. No valid cached `review_payload` is available.
6. No valid cached `recognized.json` is available.
7. `OCR_PHASE2E_GEMINI_LIVE_ENABLED` is true.
8. `OCR_PHASE2E_PROVIDER_CALLS_ALLOWED` is true.
9. `OCR_PHASE2E_LOCAL_ONLY` is false for this explicitly authorized live run.
10. Request is lab/internal authorized, not production default.
11. Provider-call budget is available for this request/session.
12. No answer-key data is loaded into the provider prompt or provider adapter.

If any gate fails, the route must not call Gemini. It should return the existing safe cached/mock review-payload fallback, or a safe review-route error if the image/crop pipeline itself failed.

## 4. When Gemini May Be Called

Gemini may be called only for live OCR recognition of the prepared Phase 2C image artifacts:

- after valid uploaded full sheet intake,
- after Phase 2C produced 20 crops,
- after contact sheets are generated and verified when contact mode is enabled,
- after cache lookup misses or cache is disabled,
- after explicit Phase 2E provider-call flags are enabled,
- after `OCR_PHASE2E_LOCAL_ONLY` is explicitly false for the live-provider run,
- for an allowlisted test/round,
- in an internal/lab flow,
- with a bounded call count,
- with a prompt that requests transcription only.

The provider may receive:

- crop images,
- enhanced crops,
- contact sheets,
- row/question labels,
- transcription instructions.

The provider must not receive answer keys, grading outcomes, previous scores, `tests-config.json`, student records, or submit payloads.

## 5. When Gemini Must Not Be Called

Gemini must not be called when:

- production default is active or flags are unset,
- `OCR_PHASE2E_LOCAL_ONLY` is true,
- the request is not allowlisted,
- sid is missing or ghost/blocked,
- upload is missing, invalid, oversized, or unsafe,
- Phase 2C crop/contact pipeline fails,
- a valid cached `review_payload` is available,
- a valid cached `recognized.json` is available and cache reuse is allowed,
- provider-call budget is exhausted,
- rate-limit cooldown is active,
- the request would require answer-key access,
- the route is handling `/api/submit-test`,
- the browser opens review UI without an explicit OCR action,
- a student clicks final submit,
- environment variables are missing or invalid.

No Gemini/API call should ever be made from browser JavaScript.

## 6. Required Input Artifacts

Phase 2E should require these artifacts before live provider execution:

1. Uploaded full sheet
   - Accepted only through the already gated OCR review route.
   - Stored in a route-runtime/lab directory, not app `static`, DB, student records, or progress/log/test runtime data.

2. Phase 2C crops
   - Exactly `q001.png` through `q020.png`.
   - Each crop must be verified before provider call.
   - Missing or duplicate crops stop live provider execution.

3. Contact sheets
   - Four groups: q001-q005, q006-q010, q011-q015, q016-q020.
   - Contact sheets should include original primary and enhanced secondary views.
   - Contact sheets should be verified for dimensions and prompt/source safety before use.

Debug sheets are optional internal evidence and must not be returned in the student response.

## 7. Prompt And Source Strategy

Recognition prompt strategy:

- Original crop is the primary evidence.
- Source priority should be documented as: original crop primary, enhanced/contact secondary if available.
- Enhanced crop/contact view is secondary evidence.
- If original and enhanced disagree, return `?`.
- If handwriting is crossed out, overwritten, ambiguous, or incomplete, return `?`.
- Do not solve, correct, infer, normalize, or grade.
- Preserve visible math symbols and answer text only.
- Preserve Korean choice markers if visible.
- Do not infer an answer from the answer key.
- Do not include explanations in the provider output.
- Return JSON only.

Source package strategy:

1. Preferred live mode: one contact sheet per five questions.
2. Fallback live mode: one crop group per call if contact sheet generation is unavailable.
3. Internal experiment mode only: include full-color/raw crop plus enhanced crop for ambiguous handwriting analysis.

The provider prompt must never include:

- expected answer,
- canonical answer,
- accepted answers,
- score,
- correctness,
- previous grading result,
- `tests-config.json`,
- `/api/submit-test` payload,
- filesystem paths.

## 8. Output Contract

Internal `recognized.json` contract:

```json
{
  "items": [
    {
      "question": 1,
      "recognized": "..."
    }
  ]
}
```

Allowed internal optional fields, if added later:

- `warnings`
- `candidates`
- `provider_model`
- `provider_call_id`
- `source_group`
- `created_at`

Student-facing `review_payload` contract:

```json
{
  "source": "phase2e_gemini_live",
  "test_id": "t_unit_daesu_01_lv3_r1",
  "round": "1",
  "problem_count": 20,
  "items": [
    {
      "question_no": 1,
      "status": "review_required",
      "recognized": "...",
      "warnings": [],
      "candidates": [],
      "final_answer": null,
      "source": null
    }
  ]
}
```

Phase 2E live-recognized output should default to `review_required` for every recognized item. It should not create `safe_auto_grade` because live OCR recognition does not read answer keys and must not grade.

Student response must not contain:

- `expected`,
- `canonical_answer`,
- `accepted_answers`,
- `correct`,
- `incorrect`,
- `score`,
- `wrong`,
- `pct`,
- raw provider response,
- API key markers,
- local filesystem paths,
- no filesystem paths of any kind,
- crop/contact/debug image paths,
- runtime cache paths.

## 9. Cache Strategy

Lookup order should remain cache-first:

1. Valid cached `review_payload`
2. Valid cached `recognized.json`
3. Live Gemini OCR only if all Phase 2E gates pass
4. Safe fallback to mock/cached baseline if live call is unavailable

Cache keys should include:

- test id,
- round,
- normalized image hash,
- crop pipeline version,
- contact-sheet generation version,
- provider model,
- prompt version,
- source package mode.

Repeated provider calls should be avoided by:

- writing a successful `recognized.json` only to a controlled Phase 2E lab/cache folder when cache write is enabled,
- storing partial provider results separately from complete recognized output,
- requiring an explicit force-refresh lab flag for re-running live OCR,
- using idempotency metadata to prevent duplicate calls on browser retry.

Cached recognized output must still be sanitized into a student-safe `review_payload`; cache status fields must not be trusted to grade.
recognized-only output must remain `review_required` unless a separate, non-provider, non-answer-key validation policy is explicitly designed and approved.

## 10. Quota And Rate-Limit Handling

429 handling:

- Treat as provider unavailable.
- Do not retry immediately in a loop.
- Record a server-side quota event without API key or raw sensitive data.
- Return a safe fallback review payload if available.
- If no safe fallback exists, return a safe OCR-unavailable response that keeps manual input available.
- Do not expose provider quota details to the student response.

Retry policy:

- 429: no same-request retry.
- 503 or transient network timeout: at most one bounded retry per contact sheet with short backoff.
- JSON parse/model-format error: no blind retry unless explicitly configured for lab debugging.
- Retry count must respect `OCR_PHASE2E_MAX_PROVIDER_CALLS_PER_REQUEST`.

Partial result policy:

- Partial provider output must not be silently treated as complete.
- If fewer than 20 questions are recognized, build a complete review payload only by filling missing rows as `review_required` with `recognized: "?"`.
- Mark missing rows internally as provider-missing.
- Prefer returning cached/mock payload over live partial output if the partial result is structurally unsafe.
- Never submit partial results.

Fallback policy:

- Valid cached review payload: return it.
- Valid cached recognized JSON: convert it to 20 `review_required` items.
- Live provider unavailable: fallback to existing mock/cached route response.
- cache fallback must be preferred over any new provider call whenever a valid cache artifact exists.
- App manual answer input remains writable.

## 11. Failure Modes

Expected failure modes:

- route disabled,
- provider disabled,
- live flag disabled,
- provider-call authorization missing,
- invalid/missing image,
- Phase 2C crop failure,
- contact sheet generation failure,
- provider API key missing,
- provider 429 quota/rate-limit,
- provider 503 or timeout,
- provider invalid JSON,
- provider returns duplicate/missing questions,
- provider returns unsafe text or unexpected fields,
- cache write failure,
- path leakage in generated payload,
- answer-key field leakage in generated payload,
- browser retry causes duplicate OCR request,
- student navigates away during OCR,
- OCR returns ambiguous/crossed-out answers as `?`,
- OCR misreads high-confidence digits, as seen in person_03 q003/q018.

Every failure must preserve:

- no auto-submit,
- no grading,
- no student record write,
- no answer-key leakage,
- manual input fallback.

## 12. Safety Rules

Non-negotiable safety rules:

- Do not auto-submit.
- Do not call `/api/submit-test` from OCR routes.
- Keep `/api/submit-test` unchanged.
- Do not click or trigger `#tsSubmit`.
- Do not grade in OCR recognition.
- Do not read answer keys in the provider adapter.
- Do not put answer-key fields in student-facing JSON.
- Do not put filesystem paths in student-facing JSON.
- Do not expose API keys or `.env` contents.
- Do not make browser-side Gemini/API calls.
- Do not enable production default.
- Keep production default `NO-GO`.
- Keep direct/manual answer entry available when OCR fails.
- Treat live OCR output as review assistance, not final grading.

## 13. Validation Plan

Pre-implementation validation requirements:

- Re-run existing Phase 2D verifier and keep it green.
- Confirm disabled-default behavior makes zero provider calls.
- Confirm Phase 2D cache hit prevents Phase 2E live call.
- Confirm missing/malformed/forbidden cache falls back safely.

Implementation validation requirements, once implementation is authorized:

- Unit test feature-flag truth table:
  - no route flag -> no provider call,
  - route only -> no provider call,
  - route + Phase 2E live only -> no provider call,
  - route + Phase 2E live + provider-call flag -> provider call eligible only after cache miss.
- Unit test provider adapter rejects answer-key fields.
- Unit test recognized parser rejects duplicate/missing question rows unless filling missing rows as `?` in a clearly marked review-required payload.
- Unit test student-facing payload scanner rejects path leaks and forbidden fields.
- Route verifier with mocked provider:
  - success with 20 recognized rows,
  - 429 fallback,
  - timeout fallback,
  - malformed provider JSON fallback,
  - partial provider result,
  - cache-hit no-call path,
  - cache-miss live-call path.
- Contract validators:
  - `validate_ocr_review_contract.py`
  - `verify_ocr_review_contract_negative.py`
  - `verify_final_review_payload_bridge.py`
- Browser/preflight:
  - OCR review route call count expected,
  - `/api/submit-test` calls remain 0,
  - Gemini/API calls remain 0 unless mocked provider path is explicitly enabled in a controlled verifier,
  - `#tsAnswersText` remains 20 lines after student review/finalization,
  - manual input remains writable.

No validation should require a real provider call until provider-call authorization is explicitly granted.

## 14. Manual QA Plan

Manual QA should run in stages:

1. Disabled default
   - Open test UI with OCR hidden/disabled.
   - Confirm no provider call.
   - Confirm no `/api/submit-test`.

2. Route enabled, Phase 2D cache enabled
   - Upload full sheet.
   - Confirm Phase 2C crop/contact path runs.
   - Confirm cached review payload or cached recognized payload is used.
   - Confirm no provider call.

3. Phase 2E mocked provider
   - Use a local fake provider response, not Gemini/API.
   - Confirm success, partial, malformed, timeout, and 429 branches.
   - Confirm student-facing JSON has no paths or answer-key fields.

4. Phase 2E live provider, only after explicit authorization
   - Use a lab-only case.
   - Keep `#tsSubmit` untouched.
   - Inspect returned review payload.
   - Confirm all live recognized rows are review-required or safe unresolved statuses, not auto-graded.
   - Confirm cache write behavior and repeated-open cache reuse.

5. Review/finalization UI
   - Student reviews/edits OCR suggestions.
   - `answersText` becomes exactly 20 lines.
   - Final submit remains the existing manual submit path and is not invoked during OCR QA.

## 15. Rollback Plan

Immediate rollback:

- Unset `OCR_PHASE2E_GEMINI_LIVE_ENABLED`.
- Unset `OCR_PHASE2E_PROVIDER_CALLS_ALLOWED`.
- Leave `OCR_PHASE2_REVIEW_ROUTE_ENABLED` and Phase 2D flags unchanged only if cached baseline is still desired.

Code rollback, if implementation later exists:

- Bypass the Phase 2E provider adapter branch.
- Keep Phase 2D cached fallback intact.
- Keep Phase 2C crop/contact pipeline intact if still needed.
- Do not touch `/api/submit-test`.
- Do not touch answer keys, DB, `tests-config.json`, student records, or production defaults.

Artifact rollback:

- Remove only Phase 2E runtime/lab cache folders created during QA.
- Preserve benchmark evidence unless intentionally replacing a lab run with a new named variant.
- Do not delete operating app runtime data.

## 16. GO/NO-GO Gates Before Implementation

GO for implementation only when all are true:

- Explicit authorization exists for live provider-call implementation work.
- Explicit authorization exists for any real Gemini/API call.
- Feature-flag design is accepted.
- Provider-call gate is separate from route/UI gate.
- Phase 2D cached baseline remains green.
- No production-default enablement is requested.
- Retention/cleanup policy for uploaded images, crops, contact sheets, and provider outputs is accepted.
- Quota/rate-limit behavior is accepted.
- Student-facing output contract is accepted.
- Answer-key exclusion is accepted.
- Manual QA runbook is accepted.

NO-GO if any are true:

- provider-call authorization is absent,
- production default would be enabled,
- `/api/submit-test` would be changed or called by OCR,
- answer keys would be sent to Gemini,
- student-facing response would include paths or answer-key fields,
- live OCR would create `safe_auto_grade` by reading expected answers,
- cache-hit path would still call Gemini,
- quota/rate-limit failures would retry unboundedly,
- manual input fallback is unavailable.

Current recommendation: GO for design-only Phase 2E planning; NO-GO for implementation and real provider calls until separately authorized.

## 17. Explicit No-Change Statement

This task created only this design report:

```text
C:\server\tools\subjective_sheet_lab\phase2e_gemini_live_ocr_call_plan.md
```

This task made no code changes and no operating app data changes. It did not modify `app.py`, `routes`, `static`, `data`, DB, `tests-config`, answer keys, student records, progress/logs/tests runtime data, or `static/js/student.js`.

This task did not call Gemini/API, did not call `/api/submit-test`, did not click `#tsSubmit`, did not enable production default, and did not change environment variables.
