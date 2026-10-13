# OCR UNIT Representative Manual QA Checklist

Date: 2026-07-05 KST

Purpose: fixed provider-free/manual QA checklist for representative UNIT tests. Do not run all UNIT tests manually.

## Safety

- Gemini/API calls: 0 unless a separate live-call approval is present.
- `/api/submit-test` calls: 0 unless a separate local submit approval is present.
- `#tsSubmit` clicks: 0 unless a separate manual submit approval is present.
- Production default remains NO-GO.
- Do not edit `tests-config.json`, answer keys, runtime JSON, DB, or student records from this checklist.
- Do not expose answer keys, grading fields, API keys, `.env`, or filesystem paths in student-facing UI/JSON.

## Catalog Evidence

- UNIT route eligibility scan: 1173 eligible tests in the latest report.
- Read-only catalog probe found 1122 unique `t_unit_*` ids in `tests-config.json` without printing answer-key fields.
- `gongsu2` Lv.3 UNIT ids were not found by the current id-pattern probe; cover `gongsu2` through Training Pack QA for now.

## Fixed Representative UNIT Set

| Group | testId | Round | Reason |
| --- | --- | ---: | --- |
| known OCR baseline | `t_unit_daesu_01_lv3_r1` | 1 | current OCR allowlist baseline |
| known OCR baseline | `t_unit_daesu_02_lv3_r1` | 1 | second daesu Lv.3 sample |
| known OCR baseline | `t_unit_mijeok1_01_lv3_r1` | 1 | current mijeok1 QA path |
| round spread | `t_unit_daesu_01_lv3_r2` | 2 | same unit, round 2 |
| round spread | `t_unit_daesu_01_lv3_r3` | 3 | same unit, round 3 |
| curriculum spread | `t_unit_mijeok1_02_lv3_r1` | 1 | mijeok1 second unit |
| curriculum spread | `t_unit_mijeok1_05_lv3_r1` | 1 | mijeok1 mid-range unit |
| curriculum spread | `t_unit_mijeok1_10_lv3_r1` | 1 | mijeok1 later unit |
| id-shape spread | `t_unit_gongsu1_01_lv3_r1` | 1 | gongsu1 base pattern |
| id-shape spread | `t_unit_gongsu1_08_lv3_r2` | 2 | gongsu1 mid-range round 2 |
| id-shape spread | `t_unit_gongsu1_16_lv3_r3` | 3 | gongsu1 later round 3 |
| quality repeat | `t_unit_mijeok1_01_lv3_r1` | 1 | rerun same image/cache for stability |

## Per-Sample Manual Steps

1. Open `/student/<sid>?ocr=1`.
2. Open the test submit modal.
3. Select `UNIT` and the target `testId` / round.
4. Confirm OCR photo input is visible only with `?ocr=1`.
5. Upload the answer-sheet image.
6. Confirm `/api/ocr-test-sheet-review` returns 20 review items.
7. Confirm only non-safe questions appear as confirmation cards.
8. Confirm invalid recognized answers are blank in the confirmation input.
9. Confirm clear numeric recognized answers prefill when safe for student confirmation.
10. Confirm successful fill writes exactly 20 non-empty lines to `#tsAnswersText`.
11. Do not submit unless a separate submit approval is present.

## Record Each Run In

Use `tools/subjective_sheet_lab/ocr_manual_qa_result_template.md`.
