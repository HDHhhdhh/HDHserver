# OCR Training Pack Manual QA Checklist

Date: 2026-07-05 KST

Purpose: fixed manual QA checklist for the four non-frequent Training Pack tests.

## Safety

- Gemini/API calls: 0 unless a separate live-call approval is present.
- `/api/submit-test` calls: 0 unless a separate local submit approval is present.
- `#tsSubmit` clicks: 0 unless a separate manual submit approval is present.
- Production default remains NO-GO.
- Do not edit `tests-config.json`, answer keys, runtime JSON, DB, or student records from this checklist.

## Fixed Training Pack Set

| testId | Round | Expected problem count | Latest provider-free route result |
| --- | ---: | ---: | --- |
| `t_training_pack_mijeok1_non_frequent_r1` | 1 | 20 | HTTP 200, 20 items, live_call_not_authorized |
| `t_training_pack_mijeok1_non_frequent_r2` | 2 | 20 | HTTP 200, 20 items, live_call_not_authorized |
| `t_training_pack_gongsu2_non_frequent_r1` | 1 | 20 | HTTP 200, 20 items, live_call_not_authorized |
| `t_training_pack_gongsu2_non_frequent_r2` | 2 | 20 | HTTP 200, 20 items, live_call_not_authorized |

## Per-Test Manual Steps

1. Open `/student/<sid>?ocr=1`.
2. Open the test submit modal.
3. Select `TRAINING_PACK`.
4. Select the target curriculum and round.
5. Confirm only round 1 and round 2 are offered for the target Training Pack.
6. Confirm round 3 is not offered.
7. Upload the answer-sheet image.
8. Confirm OCR route returns 20 review items.
9. Confirm provider-disabled/cache-miss state uses safe student copy and makes no live call.
10. Confirm cache-hit state shows the review screen, if cache exists.
11. Confirm only non-safe questions require confirmation.
12. Confirm successful fill writes exactly 20 non-empty lines to `#tsAnswersText`.
13. Do not submit unless a separate submit approval is present.

## Existing Provider-Free Checks

Already passed in the latest report:

```text
node scripts/verify_student_training_pack_round_filter.js
python scripts/verify_submit_test_assignment_round_matching.py
```

## Record Each Run In

Use `tools/subjective_sheet_lab/ocr_manual_qa_result_template.md`.
