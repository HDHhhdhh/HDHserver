# Subjective OCR/Vision Feature-Flag Integration Checklist

Use this checklist when the hidden/internal integration patch is actually started. This file is a plan artifact only.

## A. Pre-Patch Scope Check

- [ ] Work is explicitly approved as hidden/internal integration.
- [ ] Default student page must stay unchanged.
- [ ] No Gemini/API call is needed for the patch itself.
- [ ] No `/api/submit-test` call is made by the patch work.
- [ ] Current dirty worktree is recorded before edits.
- [ ] Runtime data files are out of scope.
- [ ] `/tests` management page is out of scope.

## B. Feature Flag Gate

- [ ] Flag activation is `?ocr=1`.
- [ ] Future JS flag is `window.__SUBJECTIVE_VISION_REVIEW_ENABLED__`.
- [ ] Default flag state is false.
- [ ] `/student/<sid>` shows no `[답안지 사진으로 입력]` button.
- [ ] `/student/<sid>?ocr=1` shows the hidden/internal button.
- [ ] Existing manual submit button remains visible.
- [ ] Existing `#tsAnswersText` remains visible and editable.

## C. UI Insertion Gate

- [ ] Button is inserted in the existing test submit modal.
- [ ] Button text is `[답안지 사진으로 입력]`.
- [ ] Button appears after the answer textarea area and before memo.
- [ ] Direct answer textarea is not moved into a secondary tab.
- [ ] No “직접 입력 / 사진 인식” chooser replaces the current UI.
- [ ] OCR/Vision review modal is created dynamically or isolated from static shell churn.
- [ ] Safe-auto-grade items are collapsed by default.
- [ ] Review-required cards show candidates.
- [ ] Retake-required cards show retake only.
- [ ] Data-check-required cards are not student-editable.
- [ ] Student UI excludes developer debug JSON.

## D. Backend Boundary Gate

- [ ] New OCR/Vision route namespace is internal/hidden.
- [ ] Full sheet upload route returns a student-safe review payload only.
- [ ] Per-question retake route returns one updated student-safe item only.
- [ ] Optional finalize route returns `answersText` only.
- [ ] OCR/Vision routes never call `/api/submit-test`.
- [ ] OCR/Vision routes never write `tests.json`, logs, DB, or runtime student records.
- [ ] `/api/tests-config` remains unchanged.
- [ ] `/api/submit-test` remains unchanged.

## E. Review Payload Contract Gate

- [ ] Payload has exactly configured problem count items.
- [ ] Question numbers are continuous and unique.
- [ ] `safe_auto_grade` has a final answer and source.
- [ ] `review_required` has no final answer until resolved.
- [ ] `retake_required` has no final answer.
- [ ] `retake_uploaded` blocks final conversion.
- [ ] `data_check_required` blocks final conversion.
- [ ] Accepted match with blocking warnings does not become `safe_auto_grade`.
- [ ] Student-facing payload contains no `expected`.
- [ ] Student-facing payload contains no `canonical_answer`.
- [ ] Student-facing payload contains no `accepted_answers`.
- [ ] Student-facing payload contains no raw provider response.
- [ ] Student-facing payload contains no API key or env value.

## F. Final Conversion Gate

- [ ] `review_required` unresolved blocks conversion.
- [ ] `retake_required` blocks conversion.
- [ ] `retake_uploaded` blocks conversion.
- [ ] `data_check_required` blocks conversion.
- [ ] Missing question blocks conversion.
- [ ] Duplicate question blocks conversion.
- [ ] Empty final answer blocks conversion.
- [ ] Newline inside one answer blocks conversion.
- [ ] Final conversion emits ordered newline-separated `answersText`.
- [ ] Final conversion writes only into `#tsAnswersText`.
- [ ] Student still must click existing `#tsSubmit`.

## G. Failure Handling Gate

- [ ] Gemini 429 shows direct-input fallback and stops.
- [ ] Gemini 503 shows direct-input fallback and stops.
- [ ] No retry loop runs on 429 or 503.
- [ ] Marker failure asks for whole-sheet retake.
- [ ] Global crop failure asks for whole-sheet retake.
- [ ] One-question crop failure becomes `retake_required`.
- [ ] Invalid payload does not render review cards.
- [ ] Contract validation failure does not fill `#tsAnswersText`.
- [ ] Any failure leaves manual input usable.

## H. Files To Modify Later

- [ ] New `routes/api_subjective_vision.py`
- [ ] New `core/subjective_sheet_pipeline.py`
- [ ] New or adapted `core/subjective_review_policy.py`
- [ ] New `core/subjective_review_contract.py`
- [ ] `app.py` only if blueprint registration is required.
- [ ] `static/js/student.js`
- [ ] `static/css/student.css` only if required.

## I. Files Not To Touch

- [ ] `routes/api_tests.py` `/api/submit-test`
- [ ] `tests.json`
- [ ] `tests-config.json`
- [ ] `students.json`
- [ ] `logs.json`
- [ ] `app.sqlite`
- [ ] `data/**`
- [ ] `/tests` page upload UI
- [ ] Admin test management flow

## J. Pre-Patch Validation Commands

```powershell
python tools\subjective_sheet_lab\verify_ocr_benchmark_gate.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
git status --short
```

Expected:

- [ ] All lab validators exit `0`.
- [ ] `node --check` exits `0`.
- [ ] Existing dirty files are identified and not reverted.

## K. Post-Patch Validation Commands

```powershell
python -m py_compile app.py routes\api_subjective_vision.py core\subjective_sheet_pipeline.py core\subjective_review_policy.py core\subjective_review_contract.py
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
node --check static\js\student.js
```

Expected:

- [ ] Backend compile exits `0`.
- [ ] Lab contract validation exits `0`.
- [ ] Student JS syntax check exits `0`.

## L. Browser QA Gate

- [ ] Open default student URL.
- [ ] Confirm OCR/Vision button is absent.
- [ ] Open flagged student URL with `?ocr=1`.
- [ ] Confirm `[답안지 사진으로 입력]` button is present.
- [ ] Open existing submit modal manually.
- [ ] Confirm `#tsAnswersText` is still editable.
- [ ] Trigger OCR/Vision failure path.
- [ ] Confirm manual input remains usable.
- [ ] Load a mock/local review payload.
- [ ] Confirm unresolved review blocks conversion.
- [ ] Confirm retake_uploaded blocks conversion.
- [ ] Confirm data_check_required blocks conversion.
- [ ] Resolve review-required item by candidate selection.
- [ ] Convert final review payload to `answersText`.
- [ ] Confirm `#tsAnswersText` receives ordered answers.
- [ ] Do not click final submit during hidden-flow QA unless using a fake/test account and explicitly testing `/api/submit-test`.

## M. Rollback Gate

- [ ] Disable feature flag.
- [ ] Reload default student page.
- [ ] Confirm OCR/Vision button disappears.
- [ ] Confirm existing manual submit modal still opens.
- [ ] Confirm direct answer input still works.
- [ ] Confirm no DB or runtime data migration is needed.

## N. Stop Conditions

Stop the integration patch if any item is true:

- [ ] OCR/Vision endpoint calls `/api/submit-test`.
- [ ] OCR/Vision endpoint writes student records.
- [ ] Student-facing JSON contains answer-key-only fields.
- [ ] Browser DOM contains answer-key-only fields.
- [ ] API key or `.env` value appears in output.
- [ ] Default student page shows OCR/Vision UI.
- [ ] Manual `#tsAnswersText` path breaks.
- [ ] `retake_uploaded` can be converted to final answers.
- [ ] `data_check_required` can be student-edited into final answers.

## O. Release Gate

- [ ] Feature flag remains off by default.
- [ ] Rollback drill passes.
- [ ] Same-contact remains the selected strategy.
- [ ] `wrong_safe_auto_grade` remains `0` in current benchmark evidence.
- [ ] Additional independent handwriting cases with human transcription are still required before production default.
