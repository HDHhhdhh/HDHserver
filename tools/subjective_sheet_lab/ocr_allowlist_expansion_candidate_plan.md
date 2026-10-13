# OCR Allowlist Expansion Candidate Plan

Date: 2026-07-03

## Scope

This is a provider-free lab planning report for expanding hidden OCR QA beyond the current baseline.

- Current OCR baseline remains `t_unit_daesu_01_lv3_r1` / round `1`.
- OCR UI remains hidden behind `?ocr=1`.
- Production default remains `NO-GO`.
- No live allowlist change is made by this report.
- No answer key values are included in provider input or student-facing output by this report.

## Inputs Inspected

- `C:\server\tests-config.json` read-only
- `C:\server\tools\subjective_sheet_lab\next_ocr_allowlist_candidate_answer_mode_audit.md`
- `C:\server\tools\subjective_sheet_lab\t_unit_daesu_02_lv3_r1_answer_mode_table.md`
- `C:\server\tools\subjective_sheet_lab\tests_config_answer_pattern_audit.md`
- Local round-1 solution PDF existence under `C:\server\.codex_drive_download\unit_answer_pdfs\...`

## Candidate Decision

| priority | testId | label | status | reason |
|---:|---|---|---|---|
| 1 | `t_unit_daesu_02_lv3_r1` | 지수2 Lv.3 / 1회차 | Ready for next lab integration task | Same subject/level as current baseline, local PDF exists, answer-mode table already exists, 20-question shape confirmed. |
| 2 | `t_unit_daesu_01_lv3_r2` | 지수1 Lv.3 / 2회차 | Audit next | Same source family as current baseline and low shape risk, but needs round-2 answer-mode confirmation before OCR allowlist use. |
| 3 | `t_unit_daesu_03_lv3_r1` | 로그1 Lv.3 / 1회차 | Audit next | Same 대수 Lv.3 sequence and local PDF exists, but negative/fraction values increase OCR ambiguity and answer-mode table is not confirmed yet. |
| defer | `t_unit_daesu_04_lv3_r1` | 로그2 Lv.3 / 1회차 | Stress candidate later | Decimal and larger-number values make it useful for stress QA, but not a first expansion target. |
| defer | `t_unit_gongsu1_01_lv3_r1` | 다항식의 연산1 Lv.3 / 1회차 | Cross-subject later | Useful after 대수 path is stable; defer because it switches subject family. |

## Shape Evidence

All candidate rows below have 20 configured answers and a local round-1 source PDF where applicable. Counts are shape-only checks, not a substitute for answer-mode classification.

| testId | sourceId | configured count | single digit 1-5 count | integer count | fraction count | decimal count | negative count | local PDF |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `t_unit_daesu_01_lv3_r2` | `t_unit_daesu_01_lv3` | 20 | 13 | 20 | 0 | 0 | 0 | yes |
| `t_unit_daesu_02_lv3_r1` | `t_unit_daesu_02_lv3` | 20 | 9 | 19 | 1 | 0 | 0 | yes |
| `t_unit_daesu_03_lv3_r1` | `t_unit_daesu_03_lv3` | 20 | 15 | 19 | 1 | 0 | 1 | yes |
| `t_unit_daesu_04_lv3_r1` | `t_unit_daesu_04_lv3` | 20 | 12 | 18 | 0 | 2 | 0 | yes |
| `t_unit_gongsu1_01_lv3_r1` | `t_unit_gongsu1_01_lv3` | 20 | 14 | 19 | 1 | 0 | 2 | yes |

Important rule: single-digit answer shape does not prove `choice_number`. For example, existing audits already show single-digit `answer_value` items. Each candidate still needs source/PDF-based answer-mode confirmation.

## Ready Candidate Requirements

`t_unit_daesu_02_lv3_r1` can be the first expansion target only after a separate implementation task does all of the following:

1. Add runtime answer-mode support for this testId without changing production default.
2. Keep OCR eligibility scoped to the explicit allowlist.
3. Reuse the documented modes:
   - `choice_number`: q003, q006, q007, q009, q010, q011, q015, q020
   - `answer_value`: q001, q002, q004, q005, q008, q012, q013, q014, q016, q017, q018, q019
4. Run provider-free route/client contract checks.
5. Run one hidden `?ocr=1` manual QA pass without `/api/submit-test` auto-call.
6. Only then perform a separately authorized live provider QA if needed.

## Next Audit Requirements

Before `t_unit_daesu_01_lv3_r2` or `t_unit_daesu_03_lv3_r1` can be allowlisted:

1. Create a per-question answer-mode table from local source/PDF evidence.
2. Mark every question as `choice_number`, `answer_value`, or `unclear`.
3. Confirm no `unclear` item is silently auto-filled.
4. Add provider-free regression fixtures for invalid choice values and ambiguous answer-value values.
5. Confirm student-facing JSON/UI contains no answer-key, grading, or filesystem path leak.

## Recommended Execution Order

1. Implement multi-test answer-mode lookup using `t_unit_daesu_02_lv3_r1` only.
2. Add a provider-free verifier that rejects unsupported/unknown testIds and checks `t_unit_daesu_02_lv3_r1` mode behavior.
3. Run hidden OCR UI cache replay for `t_unit_daesu_02_lv3_r1`.
4. Build answer-mode tables for `t_unit_daesu_01_lv3_r2` and `t_unit_daesu_03_lv3_r1`.
5. Decide whether the second expansion should be same-source round expansion (`지수1 2회차`) or next-unit expansion (`로그1 1회차`).

## Safety Confirmation

- Gemini/API call count: 0
- `/api/submit-test` call count: 0
- `#tsSubmit` click count: 0
- Production default changed: no
- Live OCR allowlist changed: no
- `tests-config.json` changed: no
- Answer keys changed: no
- Runtime JSON / DB / student records changed: no
- Existing benchmark recognized/cache files overwritten: no
- Student-facing answer-key/grading/path leak introduced: no

## Result

Recommended next concrete task: promote `t_unit_daesu_02_lv3_r1` to a lab-only hidden OCR allowlist candidate in a separate implementation task, guarded by provider-free verification and without enabling production default.
