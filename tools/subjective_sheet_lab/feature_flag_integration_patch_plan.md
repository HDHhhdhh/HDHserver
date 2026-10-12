# Subjective OCR/Vision Feature-Flag Integration Patch Plan

Status: plan only. Do not implement from this document until a separate integration task starts.

## Executive Decision

Use hidden/internal integration only.

- Default student page: unchanged.
- Hidden activation: `?ocr=1`.
- Internal JS flag name for the future patch: `window.__SUBJECTIVE_VISION_REVIEW_ENABLED__`.
- Existing direct answer textarea `#tsAnswersText`: preserved.
- Existing final submit endpoint `POST /api/submit-test`: preserved as the only final student-record save path.
- OCR/Vision processing endpoints: review payload only, never final submit.
- Production default: no-go.
- Feature-flag integration: go with conditions, based on `C:\server-ocr\gemini_outputs\ocr_benchmark_gate_report.md`.

## Read-Only Evidence Used

Real student flow:

- `static/student.html`
- `static/js/student.js`
- Dynamic test submit modal in `static/js/student.js` around `ensureModal()`
- Existing modal controls: `#tsType`, `#tsTestId`, `#tsRound`, `#tsAnswersText`, `#tsSubmit`
- Existing final submit call: `fetch('/api/submit-test', ...)`
- Existing experimental flag: `window.__OCR_TEST_SHEET_ENABLED__ = new URLSearchParams(location.search).get("ocr") === "1"`

Lab flow:

- `tools/subjective_sheet_lab/review_ui_mock.html`
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
- `tools/subjective_sheet_lab/ocr_review_schema.py`
- `tools/subjective_sheet_lab/ocr_answers_text_bridge.py`
- `tools/subjective_sheet_lab/final_review_payload_bridge.py`
- `tools/subjective_sheet_lab/final_review_payload_bridge_report.md`
- `tools/subjective_sheet_lab/phase1_internal_route_adapter_report.md`
- `C:\server-ocr\gemini_outputs\ocr_benchmark_gate_report.md`

## Non-Negotiable Scope

Future patch must not:

- Remove direct answer input.
- Remove or rewrite the current test submit modal.
- Change `/api/submit-test` request or response behavior.
- Call `/api/submit-test` from OCR/Vision endpoints.
- Save to `tests.json`, logs, SQLite, DB, or runtime data from OCR/Vision endpoints.
- Expose `expected`, `canonical_answer`, or `accepted_answers` to student UI, browser DOM, browser console, or student-facing JSON.
- Add OCR/Vision UI to `/tests` or admin test management pages.
- Enable the flow without the hidden feature flag.

## Feature Flag

### Activation

Use `?ocr=1` for the first hidden student-page integration because it already exists in `student.js` and is familiar from the lab work.

Future patch should create a more specific internal flag variable:

```js
window.__SUBJECTIVE_VISION_REVIEW_ENABLED__ =
  new URLSearchParams(location.search).get("ocr") === "1";
```

The old `window.__OCR_TEST_SHEET_ENABLED__` can remain as a compatibility alias during the patch, but the new review UI should check the more specific flag.

### Default

Default is off.

- `/student/<sid>`: no OCR/Vision UI.
- `/student/<sid>?ocr=1`: hidden/internal UI visible.

### Optional Internal Allowlist

If the next patch needs stricter safety, add an additional local allowlist check before rendering the button:

- `sid` must be a test student, or
- `window.__STUDENT_ACCESS__.testSubmissionBlocked === true` for fake/test pages, or
- a local non-committed config enables the feature.

Do not require this for the first plan unless the integration owner asks for it.

## Student Page UI Insertion Point

The current submit modal is created dynamically in `static/js/student.js` inside `ensureModal()`.

Insert the hidden photo entry point inside the existing modal, after the existing answer textarea block and before the memo block:

```html
<textarea id="tsAnswersText"></textarea>
<div id="tsInfo"></div>
<div id="tsAnswerLinkArea"></div>

<!-- feature-flag only -->
<div id="tsVisionEntry">
  <button id="tsVisionStart" type="button">답안지 사진으로 입력</button>
</div>

<textarea id="tsMemo"></textarea>
```

Rules:

- Keep `#tsAnswersText` visible and editable.
- Do not replace the direct input label.
- Show `#tsVisionEntry` only when `window.__SUBJECTIVE_VISION_REVIEW_ENABLED__ === true`.
- Existing submit button remains `#tsSubmit`.
- The flagged path may change the submit button label to `확인 후 제출`, but it must not change submit semantics.

## Student Review UI Placement

Use a second dynamic modal or full-screen panel created by `student.js`, not static HTML churn in `static/student.html`.

Recommended IDs:

- `#subjectiveVisionModal`
- `#svUploadInput`
- `#svProcessSheet`
- `#svReviewRoot`
- `#svSafeDetails`
- `#svFinalPreview`
- `#svApplyToAnswersText`
- `#svClose`

The review modal should be opened from `[답안지 사진으로 입력]`, not from default page load.

## Future Internal Route Boundaries

Add a new backend blueprint later, not in this task.

Candidate file:

- `routes/api_subjective_vision.py`

Candidate core files:

- `core/subjective_sheet_pipeline.py`
- `core/subjective_review_policy.py`
- `core/subjective_review_contract.py`

### 1. Upload full sheet image

```http
POST /api/internal/subjective-vision/sheet
Content-Type: multipart/form-data
```

Fields:

- `sid`
- `testId`
- `round`
- `image`

Returns:

- `ok: true`
- `recognitionSessionId`
- student-safe review payload

Does not:

- Save records.
- Call `/api/submit-test`.
- Return answer-key-only fields.

### 2. Process OCR/Vision

This can be synchronous inside the upload endpoint at first. If slow or quota-limited, split later into:

```http
POST /api/internal/subjective-vision/sheet/process
GET /api/internal/subjective-vision/session/<session_id>
```

For the first hidden integration, prefer synchronous processing with clear timeout/failure JSON to reduce state surface.

### 3. Retake one question

```http
POST /api/internal/subjective-vision/retake
Content-Type: multipart/form-data
```

Fields:

- `recognitionSessionId`
- `sid`
- `testId`
- `round`
- `questionNo`
- `image`

Returns one updated student-safe item.

### 4. Validate final reviewed payload

```http
POST /api/internal/subjective-vision/finalize
Content-Type: application/json
```

Input:

- `recognitionSessionId`
- `sid`
- `testId`
- `round`
- final review payload items

Returns:

- `ok: true`
- `answersText`
- final review summary

Does not submit or save. The frontend still calls existing `/api/submit-test` only after the student confirms.

### 5. Existing final submit endpoint

Keep unchanged:

```http
POST /api/submit-test
```

The final call remains the existing student-confirmed submit path:

```json
{
  "sid": "...",
  "testId": "...",
  "round": 1,
  "answersText": "line 1\nline 2\n...",
  "memo": ""
}
```

## Data Flow

```text
student opens existing test submit modal
-> selects test through #tsType / #tsTestId / #tsRound
-> clicks [답안지 사진으로 입력]
-> uploads full sheet image
-> server marker detection / perspective correction / crop / enhance
-> Vision recognition
-> server-side review policy evaluation
-> student-safe review payload
-> student review modal
-> final review payload
-> final_review_payload_bridge-style validation
-> answersText
-> write answersText into #tsAnswersText
-> student checks or edits direct textarea if needed
-> student clicks existing #tsSubmit
-> existing POST /api/submit-test
```

## Review Status Blocking Rules

Final conversion to `answersText` must be blocked when any item has:

- `review_required`
- `retake_required`
- `retake_uploaded`
- `data_check_required`

Additional blockers:

- Missing question number.
- Duplicate question number.
- Question outside configured problem count.
- Empty final answer.
- Newline inside one final answer.
- Student-facing payload contains `expected`, `canonical_answer`, or `accepted_answers`.

Allowed final statuses/sources:

- `safe_auto_grade`
- `student_selected_candidate`
- `student_selected_candidate_after_retake`
- `safe_auto_grade_after_retake`

Lab/debug-only sources:

- `student_direct_input`
- `student_direct_input_after_retake`

For the student-facing first integration, prefer candidate selection and retake. Keep free-form direct input available only through the existing `#tsAnswersText` manual fallback, not inside the review cards.

## Student UI Policy

Show:

- Test name and round.
- Original crop image.
- Enhanced crop image.
- Recognized answer.
- Candidate buttons.
- Retake button.
- Review reason in student-friendly text.
- Collapsed safe-auto-grade list.

Do not show:

- `expected`
- `canonical_answer`
- `accepted_answers`
- raw answer-key rows
- raw provider payload
- API key, env values, request headers
- admin-only debug JSON

`data_check_required` is not student-editable. Show a blocked message and instruct fallback to direct input or teacher/admin review based on product policy. Do not convert it into a student-selected final answer.

## Failure Handling

All failures fall back to existing direct input. No failure may submit or save.

### Gemini 429

- Stop the OCR/Vision attempt.
- Show: `현재 사진 인식 요청이 많습니다. 직접 입력으로 제출해 주세요.`
- Keep modal open.
- Leave `#tsAnswersText` unchanged.

### Gemini 503

- Stop the OCR/Vision attempt.
- Show: `사진 인식 서버가 일시적으로 불안정합니다. 직접 입력으로 제출해 주세요.`
- No retry loop in the student page.

### Marker failure

- Do not open item review.
- Ask for whole-sheet retake.
- Explain: A4 전체와 네 모서리 마커가 보여야 함.

### Crop failure

- If whole-sheet crop mapping fails globally: whole-sheet retake.
- If one question crop fails: item status `retake_required`.

### Invalid payload

- Do not render review cards.
- Show direct-input fallback.
- Log sanitized error only.

### Contract validation failure

- Do not convert to `answersText`.
- Do not call `/api/submit-test`.
- Show direct-input fallback.
- Preserve sanitized diagnostic for admin/developer only.

## Rollback Plan

Rollback is feature flag off.

- Remove `?ocr=1` from URL or disable flag check.
- OCR/Vision button disappears.
- Existing direct `#tsAnswersText` remains.
- Existing `#tsSubmit` remains.
- No DB schema change to roll back.
- No `/api/submit-test` change to roll back.
- No runtime data migration.

If any backend OCR/Vision route is unstable, disable only the feature flag or return `feature_disabled`; do not touch the manual submit path.

## Exact Future Implementation Steps

### Step 1. Add backend student-safe contract adapter

Files to modify later:

- New `routes/api_subjective_vision.py`
- New `core/subjective_review_contract.py`
- New or adapted `core/subjective_review_policy.py`

Files not to touch:

- `routes/api_tests.py` except blueprint registration review if unavoidable.
- `/api/submit-test` implementation.
- Runtime data files.

Acceptance:

- Disabled by default.
- Returns `feature_disabled` when not enabled.
- Returns student-safe review payload when enabled with local/mock image.
- Never writes records.
- Never calls `/api/submit-test`.

### Step 2. Add app blueprint registration only after route tests pass

Files to modify later:

- `app.py` only if the existing blueprint registration pattern requires it.

Alternative:

- Register from an existing route registration module if present.

Acceptance:

- `GET /api/tests-config` unchanged.
- `POST /api/submit-test` unchanged.
- New route is inaccessible or disabled unless internal flag is on.

### Step 3. Add hidden student-page entry point

Files to modify later:

- `static/js/student.js`
- `static/css/student.css` only if dynamic injected styles are not enough.

Do:

- Add `[답안지 사진으로 입력]` inside current submit modal after `#tsAnswersText`.
- Render only under `?ocr=1`.
- Keep current manual input and submit behavior unchanged.

Do not:

- Intercept default assigned-test click.
- Remove current `openTestSubmit`.
- Auto-submit.

### Step 4. Add review modal state manager

Files to modify later:

- `static/js/student.js`

Use lab UI policy:

- summary
- review cards
- retake cards
- safe collapsed section
- no developer debug in student UI

Acceptance:

- Unresolved statuses block conversion.
- Final conversion writes `answersText` into `#tsAnswersText`.
- Student must still click `#tsSubmit`.

### Step 5. Wire final bridge

Files to modify later:

- Backend finalize endpoint or frontend mapper in `student.js`.

Preferred for hidden integration:

- Server-side finalize endpoint validates final review payload and returns `answersText`.
- Frontend writes returned `answersText` into `#tsAnswersText`.

Acceptance:

- `data_check_required` blocks.
- `retake_uploaded` blocks.
- payload leak scan passes.

### Step 6. Browser and API validation

Commands before patch:

```powershell
python tools\subjective_sheet_lab\verify_ocr_benchmark_gate.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
```

Commands after patch:

```powershell
python -m py_compile app.py routes\api_subjective_vision.py core\subjective_review_contract.py core\subjective_review_policy.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
```

Manual QA after patch:

- Default `/student/<sid>` has no OCR/Vision button.
- `/student/<sid>?ocr=1` shows `[답안지 사진으로 입력]`.
- Manual answer entry and submit modal still work.
- OCR/Vision failure leaves direct input usable.
- Final review conversion fills `#tsAnswersText`.
- `/api/submit-test` is called only by clicking existing `#tsSubmit`.

## Risks

- Existing experimental OCR helper under `?ocr=1` may conflict with the new review flow if not isolated or replaced carefully.
- Student-facing leak of answer-key fields would invalidate rollout.
- `data_check_required` can be misunderstood as OCR failure; UI must route it to admin/developer handling.
- Mobile capture behavior varies across Android Chrome and iOS Safari.
- Full-sheet marker/crop failure needs a separate whole-sheet retake path, not item review.
- Gemini quota failures require fail-closed behavior with no retry loop.
- Overloading `/api/ocr-test-sheet` could blur old answerText-only behavior and new review-payload behavior; prefer a new internal route namespace.

## Files Proposed To Modify Later

Backend:

- `routes/api_subjective_vision.py` new
- `core/subjective_sheet_pipeline.py` new
- `core/subjective_review_policy.py` new or lab-derived
- `core/subjective_review_contract.py` new
- `app.py` only for blueprint registration if required

Frontend:

- `static/js/student.js`
- `static/css/student.css` only if dynamic injected styles are insufficient

Reference only:

- `tools/subjective_sheet_lab/review_ui_mock.html`
- `tools/subjective_sheet_lab/ocr_review_payload_contract.md`
- `tools/subjective_sheet_lab/final_review_payload_bridge.py`
- `tools/subjective_sheet_lab/ocr_benchmark_gate.py`

Files not to touch:

- `routes/api_tests.py` `/api/submit-test`
- `tests.json`
- `tests-config.json`
- `students.json`
- `logs.json`
- `app.sqlite`
- `data/**`
- `/tests` page files

## Validation Plan For Future Patch

1. Static validation
   - Python compile for new backend files.
   - `node --check static/js/student.js`.
   - Lab contract validators pass.

2. API validation
   - Feature disabled returns `feature_disabled`.
   - Upload endpoint returns review payload only.
   - Finalize endpoint returns `answersText` only.
   - No OCR/Vision endpoint writes runtime data.

3. Leak validation
   - Search student-facing JSON, DOM, console logs, and reports for `expected`, `canonical_answer`, `accepted_answers`, API key markers, and raw provider payload.

4. Browser validation
   - Default URL no button.
   - Flagged URL button visible.
   - Failure fallback works.
   - Review blocks unresolved statuses.
   - Final conversion fills textarea.
   - Existing submit button remains the only final save action.

5. Rollback validation
   - Disable flag.
   - Reload student page.
   - Confirm UI returns to current direct-input-only behavior.
