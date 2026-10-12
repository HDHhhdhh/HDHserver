# Student Page Teacher-Supervised OCR Checklist

Generated: 2026-07-10 03:30:00 +09:00
Classification: PLANNING_ONLY_TEACHER_SUPERVISED_CHECKLIST

## Purpose

This checklist defines how a teacher should supervise OCR answer-entry assistance on the student page during July/August limited use. It is not a production default approval and does not authorize submit/final submit.

## Scope

- Student count starts at exactly one named student.
- Test scope starts at `t_unit_daesu_01_lv3_r1` / round `1`.
- OCR remains allowlist/flag gated.
- OCR helps fill the answer text area after review; it does not grade.
- Manual input fallback remains available at all times.

## Pre-Run Checks

- Confirm the student id and intended test/round.
- Confirm OCR is allowed only for the intended test/round.
- Confirm production default remains NO-GO.
- Confirm provider/Gemini/API budget is 0 unless a separate live run is approved.
- Confirm `/api/submit-test` will not be called.
- Confirm `#tsSubmit` / final submit will not be clicked.
- Confirm no answer key, expected answer, canonical answer, accepted answer, or grading field is needed.
- Confirm the teacher can use manual input if OCR blocks or fails.

## Student Answer-Sheet Instructions

- Write one final answer per problem.
- For choice questions, write the choice number only.
- For answer-value questions, write the final answer only.
- If an answer is erased, crossed out, overwritten, or unclear, rewrite it cleanly.
- If multiple answers remain visible, expect review or retake handling.
- Do not rely on OCR to decide between old and new overwritten answers.

## OCR Use Steps

1. Open the student page under the approved hidden/allowlist path.
2. Open the test-submit modal for the intended test/round.
3. Confirm manual answer input remains editable.
4. Upload the answer-sheet image.
5. Trigger OCR review.
6. Confirm `/api/ocr-test-sheet-review` count and status.
7. Confirm review UI has 20 items or records a safe block.
8. Confirm each `review_required` item only if the visible final answer is reasonable.
9. Use retake/manual input if final answer is unclear.
10. Fill answers only if 20 safe non-empty final answers are available.
11. Verify `#tsAnswersText` has exactly 20 non-empty editable lines after fill.
12. Do not click `#tsSubmit` or final submit unless a separate certification/run explicitly approves it.

## Stop Conditions

Stop immediately if any of these occurs:

- Gemini/API/provider call occurs without explicit live budget.
- `/api/submit-test` is called.
- `#tsSubmit` or final submit is clicked.
- OCR appears for a non-allowlisted test.
- Production default changes unexpectedly.
- Answer-key, grading, or filesystem path leak appears in student-facing UI or payload.
- The selected test/round is not `t_unit_daesu_01_lv3_r1` / round `1` for the current July baseline.
- `#tsAnswersText` has fewer or more than 20 lines after fill.
- Runtime/data/config writes occur outside an approved run.

## Fallback

- If OCR fails, use manual input.
- If OCR blocks because review/retake is required, do not force fill.
- If the image is unclear, retake the photo.
- If only a subset of answers is reliable, use manual input for the rest.

## Evidence To Record

- Student id.
- Test id and round.
- Entry path.
- `/api/ocr-test-sheet-review` count and HTTP status.
- Legacy `/api/ocr-test-sheet` count.
- Gemini/API/provider count.
- `/api/submit-test` count.
- `#tsSubmit` / final submit count.
- Review item count.
- Status counts: `safe_auto_grade`, `review_required`, `retake_required`, `data_check_required`.
- `#tsAnswersText` line count.
- Leak scan result.
- Production default state.
- Manual fallback needed yes/no.

## Decision

- `GO_FILL_ONLY`: review UI completed and `#tsAnswersText` has 20 non-empty editable lines; submit still not authorized.
- `PASS_SAFE_BLOCK`: OCR safely blocked fill due to unresolved review/retake state; manual fallback remains available.
- `BLOCKED`: environment, runtime, route, or access gate prevents safe QA.
- `FAIL`: provider call, submit call, final-submit click, production default change, leak, wrong test/round, or unsafe fill occurs.
