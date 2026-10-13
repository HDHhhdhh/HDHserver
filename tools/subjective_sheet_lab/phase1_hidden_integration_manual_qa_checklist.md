# Phase 1 Hidden OCR Integration Manual QA Checklist

Use this checklist only for the current hidden Phase 1 mock review state.

Hard rules:

- Do not modify operating code.
- Do not call Gemini/API.
- Do not call `/api/submit-test`.
- Do not press the real final submit button during this QA pass.
- Keep this QA limited to the existing hidden `?ocr=1` mock review surface and the default flag-off surface.

Current verified state:

- `?ocr=1` hidden integration exists in `static/js/student.js`.
- Flag off hides OCR UI.
- Flag on shows OCR mock review.
- Confirmed review fills `#tsAnswersText`.
- Student still submits manually with the existing submit button.
- Rollback patch exists: `tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch`.
- Benchmark gate allows feature-flag integration and keeps production default `NO_GO`.
- Current Phase 1 allowlisted test is `t_unit_daesu_01_lv3_r1`.
- Answer-mode guidance exists for the allowlisted test:
  - `choice_number`: q001, q003, q005, q009, q013, q014, q017, q019
  - `answer_value`: q002, q004, q006, q007, q008, q010, q011, q012, q015, q016, q018, q020

## 0. Answer-Mode Guidance QA

Use this section before exercising the hidden OCR mock flow for the allowed test.

- [ ] For allowed test `t_unit_daesu_01_lv3_r1`, answer-mode guidance is known.
- [ ] OCR mock `answersText` uses the expected writing convention from `tools/subjective_sheet_lab/t_unit_daesu_01_lv3_r1_answer_mode_table.md`.
- [ ] Selection-number items produce numbers only: q001, q003, q005, q009, q013, q014, q017, q019.
- [ ] Answer-value items produce final values only: q002, q004, q006, q007, q008, q010, q011, q012, q015, q016, q018, q020.

Pass criteria: mock OCR output for the allowlisted test follows the documented answer-mode table before it is copied into `#tsAnswersText`.

## 1. Flag-Off Manual QA

Open the normal student page without `?ocr=1`.

- [ ] Student page loads without new console errors.
- [ ] Existing test submit modal opens normally.
- [ ] Existing manual fields are present: `#tsType`, `#tsTestId`, `#tsRound`, `#tsAnswersText`, `#tsMemo`.
- [ ] Existing final submit button label remains `제출`.
- [ ] OCR button `답안지 사진으로 입력` is not visible.
- [ ] `#tsOcrReviewOpen` is absent from the DOM.
- [ ] `#tsOcrReviewPanel` is absent from the DOM.
- [ ] `window.__OCR_PHASE1_TEST_HOOK__` is absent.
- [ ] Manual typing into `#tsAnswersText` still works.
- [ ] DevTools Network shows no OCR route call.
- [ ] DevTools Network shows no Gemini/provider call.
- [ ] DevTools Network shows no `/api/submit-test` call.

Pass criteria: OCR is fully hidden and the existing manual modal behavior is unchanged up to, but not including, final submit.

## 2. Flag-On Manual QA

Open the student page with `?ocr=1`.

- [ ] Student page loads without new console errors.
- [ ] Existing test submit modal opens normally.
- [ ] Existing manual fields remain present.
- [ ] Existing final submit button label remains `제출`.
- [ ] OCR button `답안지 사진으로 입력` is visible.
- [ ] Clicking `답안지 사진으로 입력` opens the Phase 1 mock review panel.
- [ ] Summary pills are visible for safe, review, retake, pending retake, and teacher-check states.
- [ ] Review-required cards render.
- [ ] Candidate selection changes the current answer.
- [ ] Direct input/keypad editing changes the current answer.
- [ ] `확정` resolves a review-required item.
- [ ] Safe-auto-grade details are not disruptive if opened.
- [ ] `확인한 답안으로 답칸 채우기` fills `#tsAnswersText` only after required review items are resolved.
- [ ] Student still must press the existing final submit button manually.
- [ ] DevTools Network shows no OCR route call.
- [ ] DevTools Network shows no Gemini/provider call.
- [ ] DevTools Network shows no `/api/submit-test` call during review and fill.

Pass criteria: OCR mock review is visible only with `?ocr=1`, fills the existing textarea after review, and does not submit anything automatically.

## 3. Mobile QA

Run with a phone-size viewport, for example 390 x 844.

- [ ] Test submit modal fits the viewport.
- [ ] No horizontal page or modal scrolling is introduced.
- [ ] Type/test/round controls stack cleanly.
- [ ] OCR button remains tappable.
- [ ] Review cards fit within the modal.
- [ ] Candidate buttons wrap cleanly.
- [ ] Keypad buttons wrap cleanly and remain tappable.
- [ ] Status text is readable and not clipped.
- [ ] `#tsAnswersText` remains editable after OCR fill.
- [ ] Existing `제출` button remains reachable by scrolling.

Pass criteria: a student can complete the mock review and fill flow on a phone-size viewport without layout breakage.

## 4. Unresolved Status Blocking QA

Confirm incomplete OCR review states cannot fill `#tsAnswersText`.

- [ ] Open `?ocr=1`.
- [ ] Open the test submit modal.
- [ ] Click `답안지 사진으로 입력`.
- [ ] Before confirming review-required items, click `확인한 답안으로 답칸 채우기`.
- [ ] Status message identifies the unresolved question/status.
- [ ] `#tsAnswersText` is not replaced by incomplete converted output.
- [ ] Resolve one review-required item.
- [ ] Click `확인한 답안으로 답칸 채우기` while another review-required item remains unresolved.
- [ ] Conversion remains blocked.
- [ ] Resolve all review-required items.
- [ ] Conversion succeeds only after all blocking statuses are resolved.

Statuses that must block conversion:

- `review_required`
- `retake_required`
- `retake_uploaded`
- `data_check_required`
- invalid payload shape
- duplicate, missing, or out-of-range question number
- answer containing an embedded newline

Pass criteria: no unresolved or invalid OCR state reaches `#tsAnswersText` as final converted output.

## 5. `answersText` 20-Line Verification

After successful mock review conversion:

- [ ] Copy the value of `#tsAnswersText`.
- [ ] Confirm exactly 20 non-empty lines.
- [ ] Confirm line 1 maps to question 1, line 2 to question 2, through line 20 to question 20.
- [ ] Confirm every answer is a single line.
- [ ] Confirm no answer contains embedded newline characters.
- [ ] Confirm OCR output does not use concatenated digit format.
- [ ] Confirm concatenated multi-digit examples such as `126442` are not used for answers intended as `12`, `64`, `42`.
- [ ] Confirm multi-character answers remain intact as one complete line each.
- [ ] Confirm editing `#tsAnswersText` after fill still works.
- [ ] Do not press the final submit button.

Pass criteria: `#tsAnswersText` contains 20 ordered newline-separated answers and remains a manual textarea for the existing submit path.

## 6. No Answer-Key Leak Check

Student-facing UI must not show:

- `expected`
- `canonical_answer`
- `accepted_answers`
- answer-key values
- correct/incorrect labels
- raw answer-key payload fields

Manual UI checks:

- [ ] Open `?ocr=1`.
- [ ] Open the OCR mock review panel.
- [ ] Inspect review cards.
- [ ] Inspect safe-auto-grade details.
- [ ] Inspect status text.
- [ ] Confirm no answer-key-only fields or correct-answer labels appear.

Source scan:

```bash
rg -n "expected|canonical_answer|accepted_answers" static/js/student.js tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch
```

Pass criteria: matches are limited to the explicit answer-key leak guard, and no answer-key fields appear in student-facing UI.

## 7. No Automatic Submit Check

During this QA pass:

- [ ] Do not click the existing `제출` button.
- [ ] Keep DevTools Network open.
- [ ] Filter for `submit-test`.
- [ ] Open the OCR mock review.
- [ ] Resolve review-required items.
- [ ] Fill `#tsAnswersText`.
- [ ] Confirm zero `/api/submit-test` requests occurred.
- [ ] Confirm no DB/data writes are triggered by OCR review or fill.
- [ ] Confirm the only way to submit remains the existing manual `제출` button.

Pass criteria: OCR review and fill never submit automatically.

## 8. Rollback Check

Rollback artifact:

```text
tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch
```

Dry-run reverse check:

```bash
git apply --reverse --check tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch
```

Rollback command if needed:

```bash
git apply -R tools/subjective_sheet_lab/phase1_hidden_integration_patch.patch
```

Checklist:

- [ ] Reverse patch check succeeds.
- [ ] Rollback patch affects only `static/js/student.js`.
- [ ] No backend rollback is needed.
- [ ] No route rollback is needed.
- [ ] No data/DB rollback is needed.
- [ ] After rollback, flag-off behavior is identical to the pre-OCR path.

Pass criteria: Phase 1 hidden OCR integration can be removed by reversing the patch without backend, route, data, or DB changes.

## 9. Criteria For Moving From Mock Review To Internal OCR Route

Move from mock review to an internal OCR route only when all of these are true:

- [ ] Sections 1 through 8 pass.
- [ ] Benchmark gate still allows feature-flag integration.
- [ ] Production default remains `NO_GO`.
- [ ] Internal route contract returns the same review payload shape already validated by the mock flow.
- [ ] Internal route does not call `/api/submit-test`.
- [ ] Internal route never returns `expected`, `canonical_answer`, or `accepted_answers` to student-facing payloads.
- [ ] Internal route fails closed into `review_required`, `data_check_required`, or manual fallback.
- [ ] Provider/API key handling is documented and keeps secrets server-side only.
- [ ] Quota and timeout behavior are defined before any real OCR provider call is wired.
- [ ] Manual fallback to `#tsAnswersText` remains available.
- [ ] Rollback remains one step and default-off.

Pass criteria: the internal route can replace only the mock payload source, not the review contract, textarea conversion, manual submit path, or default-off rollout posture.

## 10. Criteria For Stopping Rollout

Stop rollout immediately if any of these occur:

- [ ] OCR UI appears without `?ocr=1`.
- [ ] OCR review or fill calls `/api/submit-test`.
- [ ] OCR review or fill submits records automatically.
- [ ] Gemini/provider/API call occurs during mock-only QA.
- [ ] Student-facing UI exposes answer-key fields or correct-answer labels.
- [ ] `#tsAnswersText` has fewer or more than 20 lines after conversion.
- [ ] Question order in `#tsAnswersText` is not 1 through 20.
- [ ] Unresolved statuses can be converted into final answers.
- [ ] Mobile layout prevents review, fill, or manual fallback.
- [ ] Existing manual entry or existing final submit path is degraded.
- [ ] Rollback patch no longer applies cleanly.
- [ ] Benchmark gate changes to block feature-flag integration.
- [ ] Production default is proposed before production blockers are cleared.

Stop action:

- Keep OCR hidden/default-off.
- Do not proceed to internal route integration.
- Do not proceed to broader rollout.
- Record the failing item, smallest suspected fix, and required re-test section.
