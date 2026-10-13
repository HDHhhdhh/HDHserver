# Lowest-Risk Phase 1 OCR/Vision Integration Plan

Status: plan only. No operating app code should be changed from this document.

## Decision

Actual code change is not approved yet. The only safe next step is Stage 0 read-only audit and Stage 1 feature-off regression proof.

The first implementation change, when explicitly approved later, should be a no-op feature flag probe that produces identical DOM and identical submit behavior when the flag is off.

## Constraints

Do not:

- modify `app.py`
- modify `routes/**`
- modify `static/**`
- modify `data/**`
- modify DB files or runtime data
- modify the student page or existing submit flow
- call Gemini/API
- call `/api/submit-test`
- expose API keys, `.env`, answer keys, or provider payloads

## Current Real Flow Audit

Read-only files inspected:

- `static/student.html`
- `static/js/student.js`

Current static shell:

- `static/student.html` loads `/js/student.js`.
- `#openTestSubmit` exists in the hero area and is hidden until JS enables it.
- `#assignedTestsPanel` and `#assignedTestList` exist for today-test cards.
- The test submit modal is not static HTML; it is dynamically inserted by `student.js`.

Current modal creation:

- `student.js` creates `#testSubmitModal` inside `ensureModal()`.
- Existing core controls:
  - `#tsType`
  - `#tsTestId`
  - `#tsRound`
  - `#tsAnswersText`
  - `#tsMemo`
  - `#tsSubmit`
- Current exact future insertion point is inside `ensureModal()`, immediately after the answer textarea block containing `#tsAnswersText`, `#tsInfo`, and `#tsAnswerLinkArea`, before the memo block.

Current submit path:

- Submit listener is attached to `#tsSubmit`.
- It reads `#tsType`, `#tsTestId`, `#tsRound`, `#tsAnswersText`, and `#tsMemo`.
- Primary save call is `POST /api/submit-test` with `{ sid, testId, round, answersText, memo }`.
- Fallback legacy paths also exist after primary submit failure; the OCR/Vision plan must not touch any of those paths in early phases.

Current experimental OCR surface:

- `student.js` already has `window.__OCR_TEST_SHEET_ENABLED__ = new URLSearchParams(location.search).get("ocr") === "1"`.
- Current flagged code can render OCR-related UI when `?ocr=1`.
- For lowest-risk Phase 1, treat this as existing experimental surface to audit, not as production-ready integration.

## Current Lab Evidence

Read-only lab evidence:

- `C:\server-ocr\gemini_outputs\ocr_benchmark_gate_report.md`
- `tools/subjective_sheet_lab/review_ui_mock.html`
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
- `tools/subjective_sheet_lab/final_review_payload_bridge.py`
- `tools/subjective_sheet_lab/final_review_payload_bridge_report.md`
- `tools/subjective_sheet_lab/validate_ocr_review_contract.py`
- `tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py`
- `tools/subjective_sheet_lab/verify_final_review_payload_bridge.py`

Lab status:

- same-contact strategy remains preferred.
- Benchmark gate says feature-flag integration is allowed only with conditions.
- Production default remains no-go.
- Final review payload to `answersText` bridge is validated.
- Review UI mock is validated.
- Contract and negative tests are validated.
- `wrong_safe_auto_grade` stayed `0` in evaluated cases.
- More independent handwriting cases with human transcription are still required before production default.

## Stage 0: Read-Only Audit

Goal: prove the exact current behavior before any code changes.

Allowed work:

- Inspect `static/student.html`.
- Inspect `static/js/student.js`.
- Inspect lab docs and validation reports.
- Capture current DOM snapshots and screenshots if browser tooling is available.
- Record current network behavior without clicking final submit.

Required outputs:

- Exact modal insertion point for future OCR button.
- Exact submit handler location and payload shape.
- Current feature flag surface, including any existing `?ocr=1` behavior.
- Current default-off behavior.

Acceptance:

- No files modified.
- No `/api/submit-test` call.
- No Gemini/API call.
- Current default student page behavior documented.

## Stage 1: No-Op Feature Flag Probe

Goal: add or verify feature detection with zero visible or behavioral effect when off.

Lowest-risk option:

- If the current `window.__OCR_TEST_SHEET_ENABLED__` flag is already present, do not add another flag yet.
- First perform a verification-only probe that compares default URL behavior against a baseline.

If a code change is later required, it must be limited to:

```js
const SUBJECTIVE_OCR_PHASE1_ENABLED =
  new URLSearchParams(location.search).get("ocr") === "1";
```

Rules:

- No OCR button in Stage 1.
- No mock UI in Stage 1.
- No backend route in Stage 1.
- No DOM change when the flag is off.
- No change to existing submit handler.
- No change to `#tsAnswersText`.

Feature-off proof:

- Default URL DOM does not contain OCR/Vision button.
- Default URL `#testSubmitModal` structure matches baseline.
- Existing submit button still reads `#tsAnswersText` and posts through existing handler only.

Acceptance:

- `?ocr=1` may set a local variable only.
- Feature off is DOM-identical to current behavior.
- Feature off submit behavior is identical to current behavior.

## Stage 2: Hidden OCR Button With Mock Only

Goal: test review UI mechanics without OCR provider, backend route, or save path.

Allowed future change:

- Add `[답안지 사진으로 입력]` button only when `?ocr=1`.
- Button opens a mock review flow using local mock payload only.
- Mock final review payload can be converted to ordered `answersText`.
- Conversion only fills `#tsAnswersText`.
- Student still presses existing `#tsSubmit` manually.

Required UI rule:

- Direct input textarea remains visible.
- No tab switch replaces direct input.
- OCR button appears after `#tsAnswersText` area and before memo.
- `safe_auto_grade` items are collapsed.
- `review_required` uses candidate selection.
- `retake_required` uses retake mock state.
- `data_check_required` blocks conversion.

Forbidden:

- No Gemini/API call.
- No new backend call.
- No `/api/submit-test` call from OCR code.
- No direct save.
- No answer-key fields in student UI.

Acceptance:

- Feature off remains identical.
- Feature on shows only mock OCR button.
- Mock flow cannot save.
- Final mock flow fills `#tsAnswersText`.
- Existing submit handler remains the only final submit mechanism.

## Stage 3: Internal Route Only

Goal: add hidden/internal OCR endpoint that returns review payload only.

Allowed future backend files:

- New `routes/api_subjective_vision.py`
- New `core/subjective_sheet_pipeline.py`
- New `core/subjective_review_contract.py`
- New or lab-derived `core/subjective_review_policy.py`

Route candidates:

```http
POST /api/internal/subjective-vision/sheet
POST /api/internal/subjective-vision/retake
POST /api/internal/subjective-vision/finalize
```

Rules:

- Route is disabled unless internal feature flag is enabled.
- Route returns student-safe review payload only.
- Route never calls `/api/submit-test`.
- Route never writes DB/runtime data/student records.
- Finalize route returns `answersText` only; it does not submit.

Acceptance:

- Disabled route returns `feature_disabled`.
- Missing image returns safe JSON error.
- Invalid payload returns safe JSON error.
- Student-safe payload excludes `expected`, `canonical_answer`, and `accepted_answers`.

## Stage 4: Limited Internal Account Test

Goal: run end-to-end internal testing without production exposure.

Requirements:

- Test accounts only.
- `?ocr=1` required.
- Internal allowlist recommended.
- Logging/reporting only.
- No broad student rollout.
- Rollback by disabling feature flag.

Allowed:

- Process real test images for allowlisted fake/internal accounts.
- Fill `#tsAnswersText`.
- Let tester manually press existing submit only when explicitly testing fake-account submission.

Forbidden:

- Enable for all students.
- Hide manual input.
- Auto-submit.
- Treat `data_check_required` as student-editable.
- Record provider secrets, raw prompts, or answer keys in browser-visible output.

Acceptance:

- Mobile capture smoke passes.
- Feature off regression passes.
- No-answer-key leak checks pass.
- Submit payload compatibility passes.
- Rollback drill passes.

## Files That May Be Modified Later

Only after explicit implementation approval:

- `static/js/student.js`
- `static/css/student.css` only if dynamic styles are insufficient
- New `routes/api_subjective_vision.py`
- New `core/subjective_sheet_pipeline.py`
- New `core/subjective_review_contract.py`
- New or adapted `core/subjective_review_policy.py`
- `app.py` only if blueprint registration cannot be done elsewhere

## Files That Must Not Be Modified

For Phase 1:

- `routes/api_tests.py`
- existing `/api/submit-test` implementation
- `tests.json`
- `tests-config.json`
- `students.json`
- `logs.json`
- `app.sqlite`
- `data/**`
- `/tests` management page files
- admin test management flow

For Stage 0 and this planning task:

- all operating app files must remain untouched.

## Feature Flag Behavior

Feature off:

- No user-visible OCR/Vision UI.
- No new DOM nodes for OCR/Vision in the modal.
- No event listeners that change submit behavior.
- No backend OCR route calls.
- Existing direct answer submission works exactly as before.

Feature on:

- Hidden/internal OCR button may appear in Stage 2+.
- OCR flow may fill `#tsAnswersText`.
- Existing submit button remains the only final save action.
- Failures fall back to direct input.

## Failure Fallback Messages

Use short student-facing messages:

- 429 quota/rate limit: `사진 인식 요청이 많습니다. 직접 입력으로 제출해 주세요.`
- 503 provider unavailable: `사진 인식 서버가 일시적으로 불안정합니다. 직접 입력으로 제출해 주세요.`
- marker failure: `답안지 전체와 네 모서리 마커가 보이게 다시 촬영해 주세요.`
- crop failure: `일부 답안칸을 읽지 못했습니다. 직접 입력으로 제출해 주세요.`
- invalid payload: `인식 결과를 확인할 수 없습니다. 직접 입력으로 제출해 주세요.`
- contract validation failure: `인식 결과 검증에 실패했습니다. 직접 입력으로 제출해 주세요.`

All failures:

- must not clear `#tsAnswersText` if the student already typed answers.
- must not call `/api/submit-test`.
- must not save records.

## Rollback Plan

Rollback method: feature flag off.

Expected rollback result:

- OCR/Vision button hidden.
- Mock/internal route inaccessible or returns `feature_disabled`.
- Existing manual submit modal still opens.
- Existing `#tsAnswersText` remains editable.
- Existing `/api/submit-test` behavior unchanged.
- No DB migration or data repair required.

## Validation Commands

Preflight before any future code change:

```powershell
python tools\subjective_sheet_lab\verify_ocr_benchmark_gate.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
git status --short
```

After Stage 1 or Stage 2 frontend-only change:

```powershell
node --check static\js\student.js
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
```

After Stage 3 backend route change:

```powershell
python -m py_compile app.py routes\api_subjective_vision.py core\subjective_sheet_pipeline.py core\subjective_review_contract.py core\subjective_review_policy.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
```

## No-Answer-Key-Leak Checks

Check all student-facing responses, DOM, console output, generated reports, and saved session artifacts for:

- `expected`
- `canonical_answer`
- `accepted_answers`
- `GEMINI_API_KEY`
- `AIza`
- `x-goog-api-key`
- raw provider response
- raw answer key rows

Failure means stop immediately and do not proceed to the next stage.

## Feature-Off Regression Checks

Feature off must match current behavior:

- Default student URL has no OCR/Vision button.
- `#openTestSubmit` still opens the existing submit modal.
- `#tsType`, `#tsTestId`, `#tsRound`, `#tsAnswersText` exist after modal open.
- Typing in `#tsAnswersText` works.
- Existing `#tsSubmit` handler is unchanged.
- No OCR/Vision network request occurs.
- No console error is introduced.

## Mobile Smoke Check

On flagged URL only:

- Android Chrome: file picker/camera opens for photo input when present.
- iOS Safari if supported: file picker/camera opens for photo input when present.
- Modal stays usable on narrow viewport.
- Student can close OCR review and return to direct input.
- Failure messages fit without blocking the submit modal.

## Submit Payload Compatibility Check

For any final reviewed payload:

- Convert to newline-separated `answersText`.
- Fill only `#tsAnswersText`.
- Do not mutate `sid`, `testId`, `round`, or `memo`.
- Existing submit payload remains:

```json
{
  "sid": "student_id",
  "testId": "test_id",
  "round": 1,
  "answersText": "ordered answers",
  "memo": ""
}
```

OCR/Vision code must not call this endpoint. Only the existing `#tsSubmit` handler may call it.

## Recommended First Implementation Step

Stage 0 read-only audit plus Stage 1 feature-off regression harness.

Do not add the OCR button until the audit proves feature-off DOM and submit behavior can be compared reliably.

## Go/No-Go For Actual Code Change

Go only for Stage 0 read-only audit now.

No-go for app code change until:

- current experimental `?ocr=1` surface is audited,
- feature-off baseline is captured,
- owner confirms whether to keep, remove, or supersede the existing experimental OCR code,
- validation commands pass.
