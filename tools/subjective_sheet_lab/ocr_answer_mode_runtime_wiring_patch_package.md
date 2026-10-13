# OCR Answer Mode Runtime Wiring Patch Package

Date: 2026-07-06 KST

Status: not applied. User approval is required before editing runtime/preflight files.

## Purpose

This package turns the draft answer-mode classification for Mijeok1 and Training Pack tests into a reviewable runtime/preflight patch. It is an artifact only; it does not change current behavior.

## Proposed Patch

See:

- `tools/subjective_sheet_lab/ocr_answer_mode_runtime_wiring_proposed.patch`

The patch proposes changes to:

- `tools/subjective_sheet_lab/ocr_answer_mode_policy.py`
- `static/js/student.js`
- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`

## Runtime Mapping Proposed

Mijeok1 function limit Lv.3 round 1:

- `t_unit_mijeok1_01_lv3_r1`
- `choice_number`: 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20
- `answer_value`: 7, 15, 19

Training Pack non-frequent tests:

- `t_training_pack_mijeok1_non_frequent_r1`: all 20 questions `choice_number`
- `t_training_pack_mijeok1_non_frequent_r2`: all 20 questions `choice_number`
- `t_training_pack_gongsu2_non_frequent_r1`: all 20 questions `choice_number`
- `t_training_pack_gongsu2_non_frequent_r2`: all 20 questions `choice_number`

## Preflight Addition Proposed

Add this check after `ocr_answer_mode_coverage`:

```python
CheckSpec("ocr_draft_answer_mode_combined_policy", (py, "tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py"), LAB / "verify_ocr_draft_answer_mode_combined_policy.py"),
```

## Required Approval Text

Before applying the patch, request explicit approval similar to:

> Mijeok1 and Training Pack OCR answer-mode runtime wiring is approved. Modify only `tools/subjective_sheet_lab/ocr_answer_mode_policy.py`, `static/js/student.js`, and `tools/subjective_sheet_lab/run_phase1_preflight_checks.py` for the mapping/preflight addition. Gemini/API calls are forbidden. `/api/submit-test` calls are forbidden. `#tsSubmit` clicks are forbidden. Production default remains NO-GO. Do not modify tests-config, answer keys, DB, runtime JSON, student records, or benchmark recognized/cache artifacts.

## Verification After Approval

Run:

```bash
node --check static/js/student.js
python -m py_compile tools/subjective_sheet_lab/ocr_answer_mode_policy.py tools/subjective_sheet_lab/run_phase1_preflight_checks.py tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py
python tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py
python tools/subjective_sheet_lab/run_phase1_preflight_checks.py
git diff --check
```

## Safety Notes

- No answer keys are used in the proposed mapping.
- No provider/API calls are part of this patch.
- No `/api/submit-test` call or `#tsSubmit` click is part of this patch.
- No filesystem paths are added to student-facing JSON/UI.
- Production default remains NO-GO.
