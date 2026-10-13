# Teacher-Supervised OCR Pilot Intake Checklist

## Scope

- Test: `t_unit_daesu_01_lv3_r1`, round `1`.
- Entry: hidden `?ocr=1` only.
- Mode: local-only candidate, teacher confirmation, direct-input fallback, no submit.
- This checklist applies first to the teacher-authored dry-run and then to each real student case.

## Operator Intake

- [ ] Assign a unique anonymous case ID. Keep the name/SID mapping outside shared reports.
- [ ] Confirm the participant can access the target test and round.
- [ ] Confirm a teacher is present for the complete run.
- [ ] Confirm the answer sheet is newly written and photographed for this case.
- [ ] Confirm no old fixture, cache, benchmark, or another participant image is selected.
- [ ] Confirm manual entry and retake are available if OCR is unclear.

## Isolated Run Preflight

- [ ] Create a fresh copied app/runtime and isolated OCR artifact/cache root.
- [ ] Use a new Chrome profile and result folder.
- [ ] Disable Flask debug reloader.
- [ ] Capture original protected runtime and shared OCR-root hashes before the run.
- [ ] Verify provider and external OCR budgets are `0`.
- [ ] Verify `/api/submit-test` and final submit are blocked for this run.
- [ ] Verify production default remains `NO-GO`.

## Teacher-Supervised Flow

1. Open the hidden target page and confirm test ID and round.
2. Upload the newly captured answer sheet.
3. Run local-only candidate/review once at most.
4. Confirm there are exactly 20 review items or record a safe fail-closed result.
5. Treat every candidate as a candidate, never as an answer-key result.
6. Confirm or correct candidates with the teacher.
7. Use direct input for missing candidates.
8. Leave unclear, erased, overwritten, or multiple-answer items blank.
9. Verify `#tsAnswersText` has exactly 20 editable lines.
10. Do not submit.

## Record Per Case

| Field | Record |
| --- | --- |
| Anonymous case ID | |
| Candidate count | |
| Correct candidate count | |
| Corrected candidate count | |
| Direct-input count | |
| Blank count | |
| Unresolved count | |
| Filled/blank line count | |
| Processing duration | |
| Manual fallback used | yes/no |
| UI friction | |
| Stale or other-case answer shown | yes/no |
| OCR review HTTP result | |
| Provider/submit/final-submit counts | |
| Original-runtime/shared-OCR drift | |

## Stop Conditions

Stop immediately and record `BLOCKED` or `FAIL` if provider activity, submit activity, final-submit activity, original-runtime drift, shared OCR-root drift, a stale/other-case answer, answer-key/grading/path leak, or a production-default change is observed.

## Claim Boundary

The teacher-authored dry-run is not real-student pilot evidence. A real-student pilot is not production-default evidence.
