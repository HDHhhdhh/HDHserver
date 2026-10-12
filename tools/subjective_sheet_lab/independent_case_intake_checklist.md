# Independent Handwriting Case Intake Checklist

Use this checklist before adding a new full-sheet handwriting case to the same-contact benchmark.

## Scope

- Work only in `C:\server-ocr` and `tools\subjective_sheet_lab`.
- Do not change operating Flask app files.
- Do not write student records or production data.
- Do not run provider evaluation during intake.
- Do not include expected answers in generated images or prompts.

## Case Folder

Create:

```text
C:\server-ocr\incoming_cases\<case_name>\
  full_sheet.jpg
  expected.json
```

If the image is already elsewhere, keep the folder empty and pass `--image`.

Case name rules:

- Use letters, numbers, underscores, or hyphens.
- Avoid spaces.
- Avoid student names and personal identifiers.
- Prefer stable names such as `person_03`, `person_04_tilted`, or `trial_20260627_a`.

## Photo Check

Before running intake, confirm:

- Full A4 sheet is visible.
- Four black corner markers are visible.
- The sheet is not cut off.
- The page is reasonably flat.
- Motion blur is low.
- Shadows do not cover answer strokes.
- Answers are written inside the boxes and near the center.

## Prep Command

Default answer-key location:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\prepare_incoming_case.py --case person_03
```

Create placeholder folders for the next independent cases:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\batch_prepare_incoming_cases.py --create-placeholders person_03,person_04,person_05 --cases person_03,person_04,person_05
```

After adding `full_sheet.jpg` and `expected.json` to each folder, prepare all three without API calls:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\batch_prepare_incoming_cases.py --cases person_03,person_04,person_05
```

External image location:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\prepare_incoming_case.py --case person_03 --image "C:\path\to\full_sheet.jpg"
```

External answer-key file:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\prepare_incoming_case.py --case person_03 --expected C:\path\to\expected.json
```

External image and answer key:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\prepare_incoming_case.py --case person_03 --image "C:\path\to\full_sheet.jpg" --expected C:\path\to\expected.json
```

## Generated Assets

Confirm these are created:

```text
C:\server-ocr\crop_benchmark_inputs\<case_name>\warped_sheet.png
C:\server-ocr\crop_benchmark_inputs\<case_name>\crop_overlay.png
C:\server-ocr\crop_benchmark_inputs\<case_name>\crops\q001.png ... q020.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\enhanced\q001.png ... q020.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\hard_enhanced\q001.png ... q020.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\contact_sheets\<case_name>_q001_q005_review.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\contact_sheets\<case_name>_q006_q010_review.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\contact_sheets\<case_name>_q011_q015_review.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\contact_sheets\<case_name>_q016_q020_review.png
C:\server-ocr\gemini_contact_review_assets\<case_name>\asset_manifest.json
C:\server-ocr\gemini_outputs\<case_name>_same_contact\pending_evaluation.json
```

## Image Validation

Open `crop_overlay.png` first and check:

- q001-q020 boxes match the actual answer regions.
- The left column maps to q001-q010 from top to bottom.
- The right column maps to q011-q020 from top to bottom.
- No crop is shifted into the printed question number area.

Then open the contact sheets and check:

- Original crop is the primary left-side view.
- Soft-enhanced crop is the secondary right-side view.
- The `qNNN` label is outside the answer box.
- Labels do not overlap handwriting.
- Expected/canonical answers are not visible.
- Each sheet contains exactly five questions.

## Later Safe Evaluation

Run only one provider call at a time:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\gemini_provider.py --contact-dir C:\server-ocr\gemini_contact_review_assets\person_03\contact_sheets --out C:\server-ocr\gemini_outputs\person_03_same_contact\recognized.json --resume --max-calls 1
```

After each successful call:

- Preserve the cache file.
- Evaluate the partial `recognized.json`:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\review_policy_evaluator.py --expected C:\server-ocr\crop_benchmark_inputs\person_03\expected.json --recognized C:\server-ocr\gemini_outputs\person_03_same_contact\recognized.json --out-dir C:\server-ocr\gemini_outputs\person_03_same_contact
```

- Stop immediately on quota exhaustion.
- Continue only when the previous result is saved and reviewed.

## No-API Asset Verification

Before provider calls, run:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\verify_review_contact_assets.py --manifest C:\server-ocr\gemini_contact_review_assets\person_03\asset_manifest.json --expected-debug-count 8
```

## Pass Criteria

- 20 crops exist.
- 4 contact sheets exist.
- Review asset manifest verifies successfully.
- Metadata files were generated.
- `C:\server-ocr\incoming_cases\batch_intake_report.md` shows `prepared` for each intended case.
- No provider credentials are written to files.
- No production app files changed.
- No production submit flow was used.
