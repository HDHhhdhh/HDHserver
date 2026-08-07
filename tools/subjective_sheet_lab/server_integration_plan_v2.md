# Subjective OCR/Vision Student Submission Integration Plan v2

This is a plan-only document. It does not implement the integration, does not call Gemini or any external API, and does not change the operating student page, routes, data, DB, or `/api/submit-test`.

## 0. Scope

### Goal

Move the lab Subjective OCR/Vision review flow toward the real student test submission flow in a controlled future migration, while preserving the current direct/manual submission path.

### Non-goals for this plan

- Do not modify `app.py`.
- Do not modify `routes/**`, `static/**`, templates, runtime data, DB files, or student records.
- Do not call Gemini or any external API.
- Do not change `/api/submit-test`.
- Do not expose expected answers, canonical answers, or accepted answers to students.

### Files inspected as read-only reference

Lab and evaluation flow:

- `tools/subjective_sheet_lab/review_ui_mock.html`
- `tools/subjective_sheet_lab/review_ui_mock_sample.json`
- `tools/subjective_sheet_lab/review_ui_mock_sample_person02.json`
- `tools/subjective_sheet_lab/review_ui_mock_sample_jamo.json`
- `tools/subjective_sheet_lab/evaluate_ocr_result.py`
- `tools/subjective_sheet_lab/review_policy_evaluator.py`
- `tools/subjective_sheet_lab/gemini_provider.py`
- `tools/subjective_sheet_lab/gemini_provider_dry_run.py`
- `tools/subjective_sheet_lab/verify_evaluate_ocr_policy.py`
- `tools/subjective_sheet_lab/verify_review_ui_mock_policy.py`

Real app flow, read-only:

- `static/student.html`
- `static/js/student.js`
- `routes/api_tests.py`
- `core/ocr_test_sheet.py` as the current experimental OCR adapter reference only

## 1. Current Lab Pipeline Summary

The current lab pipeline is already shaped like the desired future product flow, but it is intentionally isolated from the live student page.

### 1.1 Image upload

Lab inputs are currently prepared as cropped question images or contact sheets rather than a live full-sheet upload. The intended future flow starts with a full answer-sheet photo from the student device.

The lab artifacts represent the downstream stages:

1. Full answer sheet image, future integration input.
2. Marker detection and perspective correction, future server-side step.
3. Per-question crop extraction.
4. Crop enhancement.
5. Vision recognition.
6. Review policy evaluation.
7. Student review UI.
8. Final answer payload generation.

### 1.2 Marker, crop, and enhance

The lab has been using per-question crops and enhanced variants to evaluate OCR/Vision behavior. The future server pipeline should generate:

- `crop_original_path` or a short-lived image reference for each question.
- `crop_enhanced_path` or a short-lived image reference for each question.
- A processing summary that can distinguish whole-sheet failure from per-question failure.

Whole-sheet failures must not enter the review UI. They should return a "retake the whole sheet" result to the upload/capture screen.

### 1.3 Vision recognition

`gemini_provider.py` supports crop and contact-sheet recognition modes in the lab. The important product behavior to preserve later is the output shape, not the lab CLI itself:

- Question number.
- Recognized answer text.
- Warnings.
- Optional candidates.
- No automatic final submission.

The prompt policy currently emphasizes:

- No guessing.
- Use original crop as primary evidence.
- Use enhanced crop only as secondary evidence.
- Preserve math notation.
- Preserve Hangul jamo choices.
- Mark ambiguous answers for review instead of forcing an answer.

### 1.4 Answer key evaluation

`evaluate_ocr_result.py` compares recognized values to expected/canonical answers in the lab. In the real product this evaluation must happen server-side only. Student-facing JSON must not include:

- `expected`
- `canonical_answer`
- `accepted_answers`
- raw answer key rows

### 1.5 Status classification

The lab status policy is:

- `safe_auto_grade`: answer can be included in the final ordered answer set without student action.
- `review_required`: student must confirm or correct the recognized answer.
- `retake_required`: a specific question crop is unusable and needs a per-question retake.
- `retake_uploaded`: a retake image has been selected but has not been re-recognized yet.
- `data_check_required`: answer key, crop mapping, or source data looks inconsistent and requires admin/developer handling.

Accepted matches with blocking warnings must not become `safe_auto_grade`. They should stay reviewable.

### 1.6 Review UI

`review_ui_mock.html` provides a standalone student-style review interface:

- Summary cards.
- Review-required cards with candidates, keypad, current answer, and confirm action.
- Retake-required cards with per-question retake image upload.
- Retake-uploaded cards that require re-recognition before final payload creation.
- Safe-auto-grade answers collapsed by default.
- Developer/debug area separated from student-facing UI.

Student-facing UI must not show expected/canonical/accepted answers or raw payloads.

### 1.7 Final payload

The lab final payload is item-based:

```json
{
  "test_id": "mock_test",
  "round": "2",
  "answers": [
    {
      "question_no": 1,
      "final_answer": "2",
      "source": "safe_auto_grade"
    },
    {
      "question_no": 4,
      "final_answer": "0.5",
      "source": "student_selected_candidate"
    }
  ]
}
```

The future app adapter must convert this item payload into the existing ordered `answersText` format before using the current final submission path.

## 2. Current Real Student Submission Flow

### 2.1 Entry points

`static/student.html` contains:

- `#assignedTestsPanel`
- `#assignedTestList`
- `#openTestSubmit`

`static/js/student.js` renders assigned test cards in `renderAssignedTests()`. By default, assigned test clicks open the existing submit modal or an answer link depending on access rules. When the current experimental `?ocr=1` flag is enabled, assigned test clicks are intercepted and routed to `window.ocrTestSheetStartCapture(test)`.

### 2.2 Test type, test, and round selection

The existing submit modal is created in `static/js/student.js` by `ensureModal()` inside the test submission module. It contains:

- `#tsType`: test type/category selector.
- `#tsTestId`: selected test selector.
- `#tsRound`: round selector.
- `#tsInfo`: test metadata and submission result area.

The modal loads test definitions through `GET /api/tests-config` and normalizes configured tests in frontend helpers such as `loadTestsConfig()`, `normalizeCfg()`, `findTestById()`, and related list helpers.

### 2.3 Current answer input

Manual/direct answer input happens in:

- `#tsAnswersText`

The field accepts compact answer text such as line-separated or specification-style answers, and the server later parses it using existing backend grading helpers.

### 2.4 Current final submission

The existing submit button handler posts to:

```http
POST /api/submit-test
Content-Type: application/json
```

Primary modern payload:

```json
{
  "sid": "student_id",
  "testId": "test_id",
  "round": 1,
  "answersText": "1/2\n-3\nsqrt(3)",
  "memo": ""
}
```

`routes/api_tests.py` handles `/api/submit-test`. When `answersText` is present, it:

1. Loads the test definition from `tests-config.json`.
2. Resolves the answer key for the selected round.
3. Parses `answersText`.
4. Grades the answers.
5. Saves a test record through the existing logs/tests storage path.
6. Returns:

```json
{
  "ok": true,
  "score": "18/20",
  "wrong": [3, 7],
  "pct": 90
}
```

### 2.5 Existing experimental OCR helper

The current app already has a guarded experimental OCR helper:

- Frontend flag: `window.__OCR_TEST_SHEET_ENABLED__ = new URLSearchParams(location.search).get("ocr") === "1"`
- Frontend upload control in the existing modal only when `?ocr=1`.
- Backend route: `POST /api/ocr-test-sheet`

Current behavior is answer-text assistance only. It fills `#tsAnswersText` and does not directly call `/api/submit-test`.

For the future Vision review integration, this route should be treated as an experimental predecessor. The new review flow should not silently expand this old route into production behavior without a feature flag and separate contract review.

### 2.6 What must not change

Until the final rollout phase:

- Do not remove or replace `#tsAnswersText`.
- Do not remove the existing submit modal.
- Do not change `/api/submit-test` request/response shape.
- Do not auto-submit after OCR/Vision recognition.
- Do not change existing `/api/tests-config` behavior.
- Do not change current assigned-test rendering for users without the feature flag.

## 3. Proposed Future Integration Architecture

### 3.1 High-level architecture

Add a photo-based recognition path beside the existing manual submission path.

```text
Student selected test
  -> choose manual submit OR photo recognition
  -> upload/capture full sheet
  -> server detects markers, crops, enhances
  -> Vision recognition
  -> server evaluates against answer key
  -> server returns student-safe review payload
  -> student reviews only needed items
  -> frontend builds ordered final answers
  -> existing /api/submit-test receives answersText after student confirmation
```

The OCR/Vision processing endpoint must never call `/api/submit-test` by itself.

### 3.2 Entry point

Future student UI should add a feature-flagged photo entry point:

- Either inside the existing test submit modal next to the manual answer textarea.
- Or as a separate "photo answer sheet" flow launched from assigned test cards.

Manual/direct submission must remain visible and usable as fallback.

### 3.3 Full sheet before review UI

The future server flow should process the full answer sheet before opening the review UI:

1. Validate image size and type.
2. Detect answer sheet markers.
3. Perform perspective correction.
4. Crop per-question answer areas.
5. Generate enhanced crops.
6. Run Vision recognition.
7. Compare to answer key server-side.
8. Return a student-safe review payload.

If marker detection, perspective correction, or whole-sheet crop generation fails, return a whole-sheet retake response and do not enter the review UI.

### 3.4 Review UI filtering

The student review UI should focus on action:

- `review_required`: show as editable confirmation cards.
- `retake_required`: show retake cards.
- `retake_uploaded`: show re-recognition pending state.
- `data_check_required`: show a blocked/admin-needed card without answer editing.
- `safe_auto_grade`: collapse by default and show recognized answer only, not expected answer.

### 3.5 Final submission compatibility

The final reviewed answers must be converted into the existing ordered `answersText` string. After all blocking statuses are resolved, the frontend can call the existing `/api/submit-test` exactly as it does today:

```json
{
  "sid": "...",
  "testId": "...",
  "round": 1,
  "answersText": "ordered answers here",
  "memo": "optional note"
}
```

This preserves the current backend grading and storage path.

## 4. Proposed API Boundaries

These are future API boundaries. Do not implement them as part of this plan.

### 4.1 Existing endpoints to remain unchanged

```http
GET /api/tests-config
POST /api/submit-test
```

`POST /api/submit-test` remains the only final save/grade endpoint for student test records during the planned migration.

The current experimental endpoint may remain during transition:

```http
POST /api/ocr-test-sheet
```

However, the future review flow should have an explicit new contract instead of overloading the old answer-text helper.

### 4.2 Future endpoint: process full answer sheet

Candidate:

```http
POST /api/subjective-vision/sheets
Content-Type: multipart/form-data
```

Fields:

- `sid`
- `testId`
- `round`
- `image`
- optional `clientCaptureMeta`

Behavior:

- Validate only.
- Process OCR/Vision and answer-key evaluation.
- Return review payload.
- Do not save student test records.
- Do not call `/api/submit-test`.

### 4.3 Future endpoint: upload/re-recognize one retake item

Candidate:

```http
POST /api/subjective-vision/items/<question_no>/retake
Content-Type: multipart/form-data
```

Fields:

- `sid`
- `testId`
- `round`
- `questionNo`
- `image`
- optional `recognitionSessionId`

Behavior:

- Recognize one question image only.
- Return one updated item.
- Do not submit final answers.

### 4.4 Future endpoint: validate final reviewed payload

Candidate:

```http
POST /api/subjective-vision/review/validate
Content-Type: application/json
```

Behavior:

- Validate that all required items are resolved.
- Build ordered `answersText`.
- Return `answersText` and a validation summary.
- Do not save test records.

This endpoint is optional. The mapping can also be done client-side if the payload is simple and fully student-safe, but server-side validation is safer for rollout.

### 4.5 Final save endpoint

Use existing:

```http
POST /api/submit-test
```

Only after the student confirms the reviewed answers. The OCR/Vision endpoints must never call it directly.

## 5. Data Contracts

### 5.1 OCR processing request

Multipart request:

```text
sid: string
testId: string
round: "1" | "2" | "3"
image: jpg/png/webp file
clientCaptureMeta: optional JSON string
```

Server validation:

- Student exists and is allowed to submit.
- Test exists in `/api/tests-config`.
- Round is valid.
- File type and size are allowed.
- Answer key exists server-side.

### 5.2 Review payload response

Student-safe response:

```json
{
  "ok": true,
  "recognitionSessionId": "opaque-session-id",
  "sid": "student_id",
  "testId": "test_id",
  "testName": "Unit Test",
  "round": 1,
  "problems": 20,
  "summary": {
    "safe_auto_grade": 17,
    "review_required": 2,
    "retake_required": 1,
    "data_check_required": 0
  },
  "items": [
    {
      "question_no": 1,
      "status": "safe_auto_grade",
      "recognized": "1/2",
      "final_answer": "1/2",
      "source": "safe_auto_grade",
      "warnings": [],
      "student_messages": [],
      "candidates": [],
      "crop_original_url": "/future/signed/or/session/image/ref",
      "crop_enhanced_url": "/future/signed/or/session/image/ref"
    }
  ],
  "warnings": []
}
```

Must not include in student response:

- `expected`
- `canonical_answer`
- `accepted_answers`
- raw answer key rows
- raw Gemini payload
- API key or provider request metadata

Admin-only debug records may contain those fields, but only behind an admin-only route or local report.

### 5.3 Per-question item status contract

Common item fields:

```json
{
  "question_no": 4,
  "status": "review_required",
  "recognized": "0,5",
  "final_answer": null,
  "source": null,
  "warnings": ["symbol_confusion"],
  "student_messages": [
    "The math symbol may need confirmation."
  ],
  "review_reasons": ["symbol_confusion"],
  "candidates": ["0.5", "0,5"],
  "crop_original_url": "...",
  "crop_enhanced_url": "..."
}
```

Status meanings:

- `safe_auto_grade`: no student action required; included in final answers.
- `review_required`: student must select a candidate or edit with keypad/input.
- `retake_required`: student should recapture this question only.
- `retake_uploaded`: retake image attached but not recognized; blocks final submit.
- `data_check_required`: expected key/crop mapping/source consistency issue; blocks student final submit and requires admin/developer handling.
- `student_selected_candidate`: student confirmed by candidate.
- `student_direct_input`: student typed or keypad-corrected answer.
- `safe_auto_grade_after_retake`: retake recognition became safe.
- `student_selected_candidate_after_retake`: student chose candidate after retake recognition.
- `student_direct_input_after_retake`: student corrected answer after retake recognition.

### 5.4 Retake upload result

Before recognition:

```json
{
  "ok": true,
  "question_no": 6,
  "status": "retake_uploaded",
  "retake_image_attached": true,
  "message": "Retake image uploaded. Re-recognition is required."
}
```

After re-recognition:

```json
{
  "ok": true,
  "question_no": 6,
  "status": "review_required",
  "recognized": "n,r",
  "warnings": ["jamo_choice_confusion"],
  "candidates": ["ㄴ,ㄹ", "n,r", "4,2"],
  "student_messages": [
    "The answer shape may be confused with numbers or letters."
  ]
}
```

### 5.5 Final reviewed answer payload

Client-side review result:

```json
{
  "sid": "student_id",
  "testId": "test_id",
  "round": 1,
  "recognitionSessionId": "opaque-session-id",
  "answers": [
    {
      "question_no": 1,
      "final_answer": "1/2",
      "source": "safe_auto_grade"
    },
    {
      "question_no": 4,
      "final_answer": "0.5",
      "source": "student_selected_candidate"
    },
    {
      "question_no": 6,
      "final_answer": "ㄴ,ㄹ",
      "source": "student_direct_input_after_retake",
      "retake_image_attached": true
    }
  ]
}
```

Blocking conditions:

- Any unresolved `review_required`.
- Any `retake_required`.
- Any `retake_uploaded`.
- Any `data_check_required`.
- Missing question numbers.
- Duplicate question numbers.
- Item count not equal to configured problem count.

### 5.6 Mapping to existing submit structure

After validation, build ordered `answersText`:

```text
1/2
-3
sqrt(3)
0.5
...
```

Then call existing final submission:

```json
{
  "sid": "student_id",
  "testId": "test_id",
  "round": 1,
  "answersText": "1/2\n-3\nsqrt(3)\n0.5",
  "memo": "submitted from reviewed photo flow"
}
```

The server-side `/api/submit-test` grading and storage behavior remains authoritative.

## 6. UI Integration Plan

### 6.1 Where the review UI appears

Future UI should be introduced behind a feature flag first:

- Option A: open a full-screen review modal after photo processing from the existing test submit modal.
- Option B: open a separate photo review route/page for internal testing, then return to the existing modal for final submit.

Option A is likely better for student continuity. Option B is safer for Phase 1 internal testing.

### 6.2 Mapping from lab mock to student page

Lab mock section:

- Header and summary cards -> student photo review modal header.
- `review_required` cards -> editable confirmation cards.
- `retake_required` cards -> per-question retake cards.
- `retake_uploaded` cards -> re-recognition pending cards.
- `safe_auto_grade` details -> collapsed "recognized answers" section.
- Developer tools/debug -> excluded from student UI; admin-only debug route or local report only.

### 6.3 Student-facing fields

Allowed:

- Question number.
- Original crop image.
- Enhanced crop image, labeled as clearer view.
- Recognized answer.
- Student-friendly warning messages.
- Candidate buttons.
- Per-question keypad/direct input.
- Retake button.
- Current final answer.

Forbidden:

- `expected`
- `canonical_answer`
- `accepted_answers`
- answer key rows
- raw warning strings
- raw provider payload
- raw developer status values
- correctness result before final submission

### 6.4 Data check handling

`data_check_required` is not student-editable.

Student-facing behavior:

- Explain that this item needs teacher/admin review.
- Do not show the answer key.
- Block final photo-flow submit.
- Offer manual fallback only if product policy allows it, clearly separated from the photo-reviewed payload.

Admin/developer behavior:

- Show expected/canonical/accepted answers only in an admin-only debug/report surface.
- Record crop path, contact sheet path, recognized value, and mismatch reason.

### 6.5 Retake behavior

Whole-sheet retake:

- Used for marker detection failure, perspective correction failure, or full crop failure.
- The review UI should not open.
- The upload/capture screen should ask the student to photograph the whole sheet again.

Per-question retake:

- Used when the whole sheet succeeded but one answer crop is blurred, cut off, or unreadable.
- The review UI remains open.
- The student uploads/captures only the specific question answer.
- State moves from `retake_required` to `retake_uploaded`.
- Re-recognition must run before final payload creation.

### 6.6 Accepted match with warnings

If an answer matches but has a blocking warning, do not mark it as `safe_auto_grade`.

Examples that should remain reviewable:

- `digit_confusion_0_6`
- `variable_confusion_x_n`
- `jamo_choice_confusion`
- `equation_part_missing`
- `symbol_confusion`
- original/enhanced disagreement

## 7. Safety and Rollback Plan

### 7.1 Feature flag

Roll out through a disabled-by-default flag:

- Internal route first.
- Then `?visionReview=1` or equivalent hidden flag.
- Then limited student account allowlist.
- Then controlled production rollout.

Default student pages must behave exactly as they do today.

### 7.2 Fail closed

If any processing step fails:

- Do not submit.
- Do not save a test record.
- Show retry/manual fallback.
- Preserve the existing manual `#tsAnswersText` path.

### 7.3 Final submit guards

Do not allow final photo-flow submit when:

- `review_required` is unresolved.
- `retake_required` is unresolved.
- `retake_uploaded` has not been re-recognized.
- `data_check_required` exists.
- Final ordered answers are missing, duplicated, or not equal to configured problem count.

### 7.4 Rollback

Rollback should be possible by disabling the feature flag. Because `/api/submit-test` and the manual modal stay unchanged, the old path remains available.

Rollback must not require data migration if OCR/Vision sessions are stored as temporary/session-only artifacts.

## 8. Migration Phases

### Phase 0: Lab-only complete

Status: current stage.

- Keep `tools/subjective_sheet_lab` isolated.
- Continue using mock review UI and local reports.
- No operating app changes.

Exit criteria:

- Review UI payload rules are stable.
- Warning policy is documented.
- Final payload mapping is deterministic.

### Phase 1: Internal route only

Future work:

- Add a non-student-facing internal route or CLI wrapper for full-sheet processing.
- Use a test account or local image only.
- Do not link from the real student page.
- Do not call `/api/submit-test`.

Exit criteria:

- Full-sheet failure vs per-question failure is distinguishable.
- Review payload contains no student-facing answer key leak.

### Phase 2: Hidden feature flag on student page

Future work:

- Add hidden flag such as `?visionReview=1`.
- Add photo-recognition entry point without removing manual submit.
- Reuse current test/testId/round selection.
- Keep existing submit modal available.

Exit criteria:

- Default URL has no new OCR/Vision UI.
- Flagged URL can process test images and review payloads.
- No final submit happens until student confirmation.

### Phase 3: Limited test account use

Future work:

- Enable for allowlisted student IDs or fake/test students.
- Log processing errors separately from student records.
- Do not enable broad real student rollout.

Exit criteria:

- Mobile camera capture works.
- Retake flow works.
- Manual fallback is clear.
- No expected answer leak in browser DOM, network response, or console logs.

### Phase 4: Real student rollout

Future work:

- Gradual enablement.
- Monitor unresolved review, retake, data-check, and fallback rates.
- Keep manual path visible.

Exit criteria:

- Stable final answer payloads.
- Low data-check rate.
- Teacher/admin support path exists.

### Phase 5: Monitoring and rollback

Future work:

- Dashboard or report for:
  - total recognitions
  - review_required count
  - retake_required count
  - data_check_required count
  - final submit success/failure
  - manual fallback usage
- One-switch disable.
- Preserve existing `/api/submit-test` path.

## 9. Future File-Level Integration Points

Do not implement these in this plan. This list is for later execution.

### Candidate backend files

- New: `routes/api_subjective_vision.py`
  - Full-sheet upload endpoint.
  - Per-question retake endpoint.
  - Optional final review validation endpoint.
- New: `core/subjective_sheet_pipeline.py`
  - Marker/crop/enhance orchestration.
  - Provider adapter boundary.
- New or adapted: `core/subjective_review_policy.py`
  - Status classification shared by API and reports.
- Existing, unchanged until final phase: `routes/api_tests.py`
  - Keep `/api/submit-test` stable.
  - Existing `/api/ocr-test-sheet` remains experimental unless explicitly migrated.

### Candidate frontend files

- Existing future edit: `static/js/student.js`
  - Feature-flagged photo entry point.
  - Review modal state manager.
  - Final payload to `answersText` mapper.
- Existing future edit: `static/css/student.css`
  - Review modal/card/keypad/retake styles.
- Existing future reference: `static/student.html`
  - Prefer dynamic modal injection to avoid static shell churn.

### Lab files to keep as source references

- `tools/subjective_sheet_lab/review_ui_mock.html`
- `tools/subjective_sheet_lab/evaluate_ocr_result.py`
- `tools/subjective_sheet_lab/review_policy_evaluator.py`
- `tools/subjective_sheet_lab/gemini_provider.py`

## 10. Validation Checklist

Plan-only validation:

- [ ] No operating code changed.
- [ ] No Gemini/API call made.
- [ ] No `/api/submit-test` call made.
- [ ] No runtime data changed.
- [ ] No API key or `.env` value printed.

Future integration validation:

- [ ] Default student URL shows no photo-recognition UI.
- [ ] Feature-flag URL shows photo-recognition entry point.
- [ ] Manual/direct submission remains available.
- [ ] `/api/submit-test` unchanged until final rollout phase.
- [ ] OCR/Vision endpoints never call `/api/submit-test`.
- [ ] Student network responses do not include expected/canonical/accepted answers.
- [ ] Browser DOM does not include expected/canonical/accepted answers.
- [ ] Final payload has exactly the configured problem count.
- [ ] Question numbers are continuous and unique.
- [ ] `safe_auto_grade`, `review_required`, `retake_required`, and `data_check_required` counts match payload items.
- [ ] Accepted match with warnings is routed to review, not safe auto grade.
- [ ] `review_required` cannot submit until confirmed.
- [ ] `retake_uploaded` cannot submit until re-recognized.
- [ ] `data_check_required` blocks student final submit.
- [ ] Mobile camera capture works.
- [ ] Per-question retake works.
- [ ] Whole-sheet retake does not enter review UI.
- [ ] API key is server-only and never logged.
- [ ] Rollback by feature flag restores current behavior.

## 11. Key Risks

- Expected answer leak in student JSON, DOM, console, or screenshots.
- OCR/Vision endpoint accidentally saving records or calling `/api/submit-test`.
- Retake-uploaded treated as final.
- Accepted match with warnings incorrectly safe-auto-graded.
- Data-check cases pushed to students instead of admin/developer review.
- Feature flag accidentally enabled for all students.
- Mobile camera behavior differing across browsers.
- Contact sheet/crop mapping drift causing false OCR blame.

## 12. Recommended Next Work Item

Before touching the real student page, create a Phase 1 internal-only full-sheet API contract test using synthetic/local images and a fake/test student. The test should assert:

- No save occurs.
- No `/api/submit-test` call occurs.
- Student-safe review payload excludes answer keys.
- Blocking statuses prevent final payload mapping.
- Manual fallback remains independent.
