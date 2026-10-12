# OCR Answer Mode Runtime Wiring Plan

Date: 2026-07-06 KST

## Scope

- Purpose: improve OCR accuracy/safety by wiring reviewed answer-mode tables for Mijeok1 and Training Pack targets.
- Status: plan only. No runtime wiring was performed in this step.
- Gemini/API calls: 0
- external OCR API calls: 0
- `/api/submit-test` calls: 0
- `#tsSubmit` clicks: 0
- production default: `NO-GO`
- answer-key/grading/path leak: 0

## Current Evidence

- Combined verifier: `tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py`
- Combined report: `tools/subjective_sheet_lab/ocr_draft_answer_mode_combined_policy.md`
- Draft targets fully classified: 5 / 5
- Runtime-ready draft count: 0
- Mijeok1 missing-mode runtime gap: 17 choice-number questions
- Training Pack missing-mode runtime gap: 80 choice-number questions

## Runtime Files Requiring Explicit Approval

These files are not changed by this plan. They require explicit approval before editing.

- `tools/subjective_sheet_lab/ocr_answer_mode_policy.py`
- `static/js/student.js`
- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`

## Server Lab Policy Wiring

Target file:

- `tools/subjective_sheet_lab/ocr_answer_mode_policy.py`

Insertion point:

- `ANSWER_MODE_BY_TEST_ID`

Add these mode-only entries:

```python
"t_unit_mijeok1_01_lv3_r1": {
    "choice_number": frozenset((1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20)),
    "answer_value": frozenset((7, 15, 19)),
},
"t_training_pack_mijeok1_non_frequent_r1": {
    "choice_number": frozenset(range(1, 21)),
    "answer_value": frozenset(),
},
"t_training_pack_mijeok1_non_frequent_r2": {
    "choice_number": frozenset(range(1, 21)),
    "answer_value": frozenset(),
},
"t_training_pack_gongsu2_non_frequent_r1": {
    "choice_number": frozenset(range(1, 21)),
    "answer_value": frozenset(),
},
"t_training_pack_gongsu2_non_frequent_r2": {
    "choice_number": frozenset(range(1, 21)),
    "answer_value": frozenset(),
},
```

Expected effect:

- Non-1~5 values such as `12`, `x=2`, `3sqrt(2)`, `1,3`, `1/2,9/2`, `?`, `n`, and `unknown` are blocked from safe auto-fill on choice-number questions.
- Mijeok1 answer-value questions q007, q015, q019 keep numeric/fraction final answers fillable.

## Hidden OCR UI Wiring

Target file:

- `static/js/student.js`

Insertion point:

- `OCR_PHASE1_ANSWER_MODE_BY_TEST_ID`

Add matching mode-only entries:

```javascript
t_unit_mijeok1_01_lv3_r1: {
  choice_number: new Set([1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20]),
  answer_value: new Set([7, 15, 19]),
},
t_training_pack_mijeok1_non_frequent_r1: {
  choice_number: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
  answer_value: new Set([]),
},
t_training_pack_mijeok1_non_frequent_r2: {
  choice_number: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
  answer_value: new Set([]),
},
t_training_pack_gongsu2_non_frequent_r1: {
  choice_number: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
  answer_value: new Set([]),
},
t_training_pack_gongsu2_non_frequent_r2: {
  choice_number: new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]),
  answer_value: new Set([]),
},
```

Expected UI behavior after wiring:

- Confirmation cards for choice-number questions should prefill only `1` through `5`.
- Invalid recognized values should leave the confirm input blank and keep review-required behavior.
- Mijeok1 answer-value q007, q015, q019 should allow simple numeric/fraction values.

## Preflight Inclusion Plan

Target file:

- `tools/subjective_sheet_lab/run_phase1_preflight_checks.py`

Insertion point:

- `check_specs()` near existing `ocr_answer_mode_coverage`

Add after `ocr_answer_mode_coverage`:

```python
CheckSpec(
    "ocr_draft_answer_mode_combined_policy",
    (py, "tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py"),
    LAB / "verify_ocr_draft_answer_mode_combined_policy.py",
),
```

Important:

- This preflight change requires explicit approval because `run_phase1_preflight_checks.py` is forbidden by OCR lab default rules.
- The verifier is provider-free and records runtime wiring status as `not_wired`.

## Approval Text Needed

For preflight inclusion only:

```text
run_phase1_preflight_checks.py에 verify_ocr_draft_answer_mode_combined_policy.py를 추가하는 것을 승인한다.
Gemini/API 호출 금지, /api/submit-test 호출 금지, #tsSubmit 클릭 금지, 운영 데이터/DB/tests-config 수정 금지.
변경은 preflight 체크 목록 추가에만 한정한다.
```

For runtime answer-mode wiring:

```text
미적분1 함수의 극한1 Lv.3 1회차와 트레이닝팩 미적분1/공수2 비빈출 1회차/2회차의 OCR answer-mode table을 hidden OCR UI와 lab server policy에 연결하는 것을 승인한다.
Gemini/API 호출 금지, /api/submit-test 호출 금지, #tsSubmit 클릭 금지, tests-config/answer keys/DB/runtime JSON/student records 수정 금지.
변경은 tools/subjective_sheet_lab/ocr_answer_mode_policy.py와 static/js/student.js의 answer-mode mapping 추가에만 한정한다.
```

## Required Verification After Approval

Provider-free commands:

```bash
python -m py_compile tools/subjective_sheet_lab/ocr_answer_mode_policy.py
python -m py_compile tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py
python tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py
python tools/subjective_sheet_lab/verify_ocr_answer_mode_coverage.py
node --check static/js/student.js
python tools/subjective_sheet_lab/run_phase1_preflight_checks.py
git diff --check
```

Expected after runtime wiring:

- `verify_ocr_answer_mode_coverage.py` should no longer report `t_unit_mijeok1_01_lv3_r1` as missing from the explicit client allowlist.
- Mijeok1 choice-number invalid samples should route to review-required behavior.
- Training Pack choice-number invalid samples should route to review-required behavior.
- `/api/submit-test` call count remains 0.
- Gemini/API call count remains 0.
- production default remains `NO-GO`.

## Remaining Blocker

- Runtime/preflight edits are approval-gated. Until approval is given, the correct state is provider-free evidence only, not runtime behavior change.
