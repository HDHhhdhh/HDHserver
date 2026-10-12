# Human Transcription Evaluation Guide

This lab workflow separates two different questions:

- Answer-key grading accuracy: `recognized.json` compared with `expected.json`
- OCR transcription accuracy: `recognized.json` compared with `human_transcription.json`

Use it when a Vision/OCR result appears wrong against the answer key, but may still be a correct transcription of what the student actually wrote.

## Required Inputs

Each same-contact case output folder needs:

- `recognized.json`
- `human_transcription.json`

The matching benchmark input folder needs:

- `expected.json`

`human_transcription.json` must contain exactly 20 unique `question_no` values:

```json
{
  "case_id": "case_name",
  "source": "human_visual_transcription",
  "answers": [
    {"question_no": 1, "human_answer": "5", "confidence": "high", "notes": ""}
  ]
}
```

Human transcription represents what is visibly written, not the answer key. If handwriting is unclear, use `"confidence": "low"` and put alternatives in `notes`.

Do not put `expected`, `canonical_answer`, or `accepted_answers` inside `human_transcription.json`.

Low-confidence human labels are counted in `ambiguous_human_label_count` and excluded from the OCR transcription accuracy denominator. Missing OCR output is still reported in `missing`, but ambiguous handwriting is not treated as a wrong OCR read.

## Run

```powershell
python tools\subjective_sheet_lab\human_transcription_eval.py `
  --case-dir C:\server-ocr\gemini_outputs\<case>_same_contact `
  --expected C:\server-ocr\crop_benchmark_inputs\<case>\expected.json
```

Optional explicit paths are supported when a case uses non-default file names:

```powershell
python tools\subjective_sheet_lab\human_transcription_eval.py `
  --case-dir C:\server-ocr\gemini_outputs\<case>_same_contact `
  --recognized C:\server-ocr\gemini_outputs\<case>_same_contact\recognized.json `
  --human C:\server-ocr\gemini_outputs\<case>_same_contact\human_transcription.json `
  --expected C:\server-ocr\crop_benchmark_inputs\<case>\expected.json
```

For the existing daesu case:

```powershell
python tools\subjective_sheet_lab\human_transcription_eval.py `
  --case-dir C:\server-ocr\gemini_outputs\daesu_jisu1_lv3_r1_photo01_same_contact `
  --expected C:\server-ocr\crop_benchmark_inputs\daesu_jisu1_lv3_r1_photo01\expected.json
```

## Verify

```powershell
python tools\subjective_sheet_lab\verify_human_transcription_eval.py `
  --case-dir C:\server-ocr\gemini_outputs\<case>_same_contact
```

The verifier checks:

- required output files exist
- human transcription has question 1 through 20 exactly once
- forbidden answer-key fields are absent from human transcription entries
- source hashes still match the recognized, expected, cache, and policy files used for the evaluation
- output files do not contain secret-like tokens or direct submit endpoint strings

This verifier is local-only. It does not call Gemini, does not call `/api/submit-test`, and does not read `.env`.

## Outputs

The evaluator writes these files into the case output folder:

- `human_transcription_eval.json`
- `human_transcription_eval.csv`
- `human_transcription_eval.md`
- `combined_case_interpretation.md`

These are developer/lab-only outputs. They may include `expected` answer-key values for comparison, so they must not be rendered in student-facing UI.

It does not modify `recognized.json`, `gemini_provider_cache.json`, `final_eval_q001_q020.json`, or the answer-key file. The generated JSON includes source hashes so later verification can detect if any source file changed after the evaluation.

Normalization is deliberately conservative:

- ignores whitespace and casing
- treats `\sqrt`, `√`, `sqrt2`, `sqrt(2)`, and `sqrt{2}` as equivalent sqrt notation
- does not treat `?` as sqrt or any other symbol
- does not use `expected.json` to auto-correct OCR output

`human_transcription_eval.json` is marked with:

```json
{
  "audience": "developer_lab_only",
  "student_facing": false
}
```

The verifier requires those flags before accepting the output.

## Interpretation

If answer-key accuracy is lower than OCR transcription accuracy, the gap usually means the student wrote a different answer than the key, not that OCR failed.

For `daesu_jisu1_lv3_r1_photo01`, the expected result is:

- answer-key grading accuracy: 15/20 = 75%
- OCR transcription accuracy: 20/20 = 100%
- wrong safe auto grade against human transcription: 0

This workflow is lab-only. It does not call any provider API, does not submit student records, and does not modify the operating student page.
