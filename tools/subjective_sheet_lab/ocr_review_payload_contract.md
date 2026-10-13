# OCR Review Payload Contract

This is the lab contract for the subjective answer-sheet OCR review flow. It is not an operating Flask API contract yet, and it must not call `/api/submit-test`.


## Current offline run contract (2026-10-09)

New lab UI/cache inputs use `ocr.review.run.v1` and `ocr.run.identity.v1`.
Identity binds photograph SHA-256, test, round, form, model, prompt version,
preprocessing version and exactly ordered questions 1–20.
Unversioned historical fixtures below remain pure-validator references only;
they are not accepted by the current UI or automatic cache reuse.

The current UI removes duplicate image-supported candidates and shows at most five.
The editor starts hidden when candidates exist. **No matching candidate** reveals
manual input; zero candidates also permits it. Manual confirmation records
`student_direct_input` and review history without replacing raw `recognized`.
Retake remains unresolved until a new recognition result. Unknown states, data
mismatch, pending provider work, demo and unresolved final answers cannot complete.
Answer-key fields are rejected before state/DOM/export. No server submit exists.

Final JSON retains the same versioned `items` contract. The existing strong
validator and answersText bridge require 20 unique final items, reject empty/?/
multiline final answers, and preserve commas and formulas as one question per line.
Transport attempts include retries; images sent and attempts are separate counts.
Cache checkpoints/raw are immutable run files. Existing legacy data is preserved.

Offline acceptance command (choose a fresh output folder inside the lab):

```powershell
& 'C:\server-ocr\.venv\Scripts\python.exe' -B 'C:\server\tools\subjective_sheet_lab\verify_bulk_ocr_offline.py' --out-root '<fresh lab run folder>'
```

This uses synthetic photos, network-denied fake transports and existing Chrome
file/data pages. It does not measure actual Gemini/model accuracy or authorize
production integration. Offline local-model weights remain separately unverified.

## Historical fixture reference


## Scope

- Applies to lab review payloads under `tools/subjective_sheet_lab`.
- Covers OCR review payload, final review payload, status enum, source enum, and `answersText` bridge.
- Student-facing payloads must not contain answer-key-only or grading fields: `expected`, `canonical_answer`, `accepted_answers`, `correct`, `incorrect`, `score`, `wrong`, or `pct`.
- The bridge converts only a completed final review payload into `answersText`; it does not submit or write student records.

## Review Payload

Top-level shape:

```json
{
  "source": "local_dry_run_review_payload",
  "test_id": "mock_subjective_test",
  "round": "2",
  "problem_count": 20,
  "items": []
}
```

Fields:

| Field | Type | Rule |
|---|---|---|
| `source` | string, optional | Producer label. Not used as item source. |
| `test_id` | string | Test identifier. |
| `round` | string | Test round. |
| `problem_count` | integer, optional | Must be 20. Defaults to 20 for legacy bridge fixtures. New payloads should include it. |
| `items` | array | Exactly one item per question, `1..20`. |

Item shape:

```json
{
  "question_no": 1,
  "status": "safe_auto_grade",
  "recognized": "5",
  "warnings": [],
  "candidates": [],
  "final_answer": "5",
  "source": "safe_auto_grade"
}
```

Item rules:

| Field | Type | Rule |
|---|---|---|
| `question_no` | positive integer | Unique, within `1..problem_count`. |
| `status` | status enum | See status enum below. |
| `recognized` | string | OCR/Vision recognized text. Empty string is allowed only before final bridge. |
| `warnings` | string array, optional | Ambiguity or routing warnings. Values must be single-line strings. |
| `candidates` | string array, optional | Student-review candidate answers. Values must be single-line strings. |
| `final_answer` | string or null | Required string for resolved final statuses; null for unresolved states. |
| `source` | source enum or null | Null for unresolved states; final source for resolved states. |
| `retake_image_attached` | boolean, optional | Required true for after-retake final statuses. |

## Erased/Overwritten Safety Warnings

These warning codes are student-facing review warnings, not grading fields:

- `erased_trace_detected`
- `crossed_out_answer`
- `overwritten_answer`
- `multiple_answer_candidates`
- `unclear_final_answer`

Policy:

- Any item with one of these warnings must not remain `safe_auto_grade` or `safe_auto_grade_after_retake`.
- If a final answer is still reviewable, downgrade the item to `review_required` with `source: null` and `final_answer: null`.
- If `unclear_final_answer` has no reliable recognized value, final answer, or candidate, downgrade the item to `retake_required`.
- Never infer the final answer from answer keys, expected values, canonical answers, accepted answers, or grading output.
- The student UI should show a clear warning such as `지운 흔적 또는 덧쓴 흔적이 있어 확인이 필요합니다.`

## Status Enum

| Status | Meaning | Bridge-final? |
|---|---|---|
| `safe_auto_grade` | Accepted without student action. | yes |
| `review_required` | Student/admin review needed before finalization. | no |
| `retake_required` | Crop/image is not usable; retake needed. | no |
| `retake_uploaded` | Retake has been uploaded but not resolved. | no |
| `data_check_required` | Answer-key/crop/student-answer mismatch needs operator check. | no |
| `confirmed` | Legacy collapsed final status; `source` carries the actual final source. | yes |
| `student_selected_candidate` | Student selected a candidate answer. | yes |
| `student_direct_input` | Lab/debug direct input source; not the preferred student UI path. | yes |
| `safe_auto_grade_after_retake` | Retake result accepted automatically. | yes |
| `student_selected_candidate_after_retake` | Student selected a candidate after retake. | yes |
| `student_direct_input_after_retake` | Lab/debug direct input after retake. | yes |

## Source Enum

| Source | Allowed with |
|---|---|
| `safe_auto_grade` | `safe_auto_grade`, or `confirmed` when preserving legacy collapsed status. |
| `student_selected_candidate` | `student_selected_candidate`, or `confirmed`. |
| `student_direct_input` | `student_direct_input`, or `confirmed`; lab/debug only for student UI policy. |
| `retake_uploaded` | `retake_uploaded` only; never bridge-final. |
| `safe_auto_grade_after_retake` | `safe_auto_grade_after_retake`. |
| `student_selected_candidate_after_retake` | `student_selected_candidate_after_retake`. |
| `student_direct_input_after_retake` | `student_direct_input_after_retake`. |
| `null` | `review_required`, `retake_required`, `data_check_required`. |

## Final Review Payload

A final review payload uses the same top-level and item shape, but every item must be bridge-final:

- allowed final statuses: `safe_auto_grade`, `confirmed`, `student_selected_candidate`, `student_direct_input`, `safe_auto_grade_after_retake`, `student_selected_candidate_after_retake`, `student_direct_input_after_retake`
- blocked statuses: `review_required`, `retake_required`, `retake_uploaded`, `data_check_required`
- every item must have non-empty single-line `final_answer`
- `safe_auto_grade` and `safe_auto_grade_after_retake` are rejected when erased/overwritten safety warnings are present
- no question may be missing, duplicated, or outside range
- `problem_count` values other than 20 are rejected

## answersText Bridge

Bridge input: final review payload only.

Bridge output:

```text
answer for q001
answer for q002
...
answer for q020
```

Rules:

- Sort final items by `question_no`.
- Emit exactly `problem_count` lines.
- Each line is the item `final_answer`.
- Do not add question numbers or labels.
- Reject empty answers and answers containing newline characters.
- Reject warning/candidate strings containing newline characters.
- Reject unresolved statuses before producing `answersText`.
- Reject answer-key-only and grading fields anywhere in the student-facing payload.
- The bridge does not call `/api/submit-test`; submission remains a separate operating flow.

## Local Validation

Run:

```powershell
python tools/subjective_sheet_lab/validate_ocr_review_contract.py
python tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py
```

The validator checks:

- `subjective_review_dry_run_review_payload.json`
- `subjective_review_dry_run_final_payload.json`
- `phase1_internal_contract_review_payload.json` nested `review_payload`
- `final_review_payload_bridge_fixture.json`
- existing golden `answersText` files
- negative regression cases for malformed or unsafe payloads
