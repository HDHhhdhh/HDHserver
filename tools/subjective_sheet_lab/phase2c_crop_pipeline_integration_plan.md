# Phase 2C Crop/Enhance Pipeline Integration Plan

Status: plan only. This document does not implement code, does not call Gemini/API,
does not call `/api/submit-test`, does not click `#tsSubmit`, and does not modify
operating app code, routes, static files, data, DB schema, tests-config, answer
keys, student records, or runtime progress/log/test data.

Phase 2C goal: connect the existing Phase 2B image-upload review route to the
local full-sheet crop/enhance/contact-sheet pipeline, then return a cached or
lab-derived student-safe review payload. Gemini remains disabled in Phase 2C.
Phase 2C must not grade directly and must preserve the existing final submit path.

## Evidence Inspected

Real repo confirmed earlier in this workstream:

- `C:\server\app.py`
- `C:\server\routes\api_tests.py`
- `C:\server\static\js\student.js`
- `C:\server\tests-config.json`
- `C:\server\tools\subjective_sheet_lab\`

Read-only evidence inspected for this plan:

- `C:\server\routes\api_tests.py`
- `C:\server\tools\subjective_sheet_lab\phase2_internal_ocr_route_integration_plan.md`
- `C:\server\tools\subjective_sheet_lab\phase2_internal_ocr_route_stub_plan.md`
- `C:\server\tools\subjective_sheet_lab\phase2a_internal_ocr_route_stub_report.md`
- `C:\server\tools\subjective_sheet_lab\phase2a_route_stub_manual_qa_report.md`
- `C:\server\tools\subjective_sheet_lab\ocr_review_payload_validator.py`
- `C:\server\tools\subjective_sheet_lab\ocr_review_schema.py`
- `C:\server\tools\subjective_sheet_lab\final_review_payload_bridge.py`
- `C:\server-ocr\extract_answer_sheet_crops.py`
- `C:\server-ocr\prepare_incoming_case.py`
- `C:\server-ocr\incoming_case_support.py`
- `C:\server-ocr\make_review_contact_assets.py`
- `C:\server-ocr\gemini_contact_images.py`
- `C:\server-ocr\gemini_contact_io.py`
- `C:\server-ocr\verify_review_contact_assets.py`
- `C:\server-ocr\crop_benchmark_inputs\daesu_jisu1_lv3_r1_photo01\case_manifest.json`
- `C:\server-ocr\gemini_contact_review_assets\person_03\asset_manifest.json`

Sparkshell was unavailable in this environment (`omo` was not on PATH), so the
inspection used read-only `rg`, PowerShell, CodeGraph, and direct file reads.

## 1. Existing Scripts And Components Found

### Full Sheet Intake

- `C:\server-ocr\prepare_incoming_case.py`
  - CLI entry point for preparing one incoming full-sheet case.
  - Inputs: `--case`, optional `--image`, optional `--expected`, optional
    `--incoming-root`, `--out-root`, `--debug-questions`.
  - Default image location: `C:\server-ocr\incoming_cases\<case>\full_sheet.jpg`.
  - Default expected location: `C:\server-ocr\incoming_cases\<case>\expected.json`.
  - Orchestrates marker detection, perspective correction, crop writing,
    enhanced crops, hard-enhanced crops, contact sheets, debug sheets, prompt,
    asset manifest, case manifest, and pending eval files.

- `C:\server-ocr\incoming_case_support.py`
  - Shared types and guard functions for intake.
  - Defines `DEFAULT_ROOT = C:\server-ocr`, `SOURCE_IMAGE_NAME = full_sheet.jpg`,
    `EXPECTED_NAME = expected.json`, `QUESTION_COUNT = 20`, `CONTACT_COUNT = 4`,
    default debug questions `(3, 10, 12, 14, 15, 16, 18, 20)`.
  - Validates generated crop/contact counts.
  - Scans generated text artifacts for forbidden references.
  - Writes `case_intake_metadata.json` and `pending_evaluation.json`.

- `C:\server-ocr\batch_prepare_incoming_cases.py`
  - Batch wrapper for preparing multiple `incoming_cases`.
  - Useful for offline lab preparation, not the first route-facing integration.

- `C:\server-ocr\prepare_full_sheet_same_contact_case.py`
  - Older direct full-sheet preparation script.
  - Contains fixed coordinate constants and a simpler marker detector.
  - Keep as reference only; prefer `prepare_incoming_case.py` because it uses
    the newer extractor and asset validation support.

### Marker Detection

- `C:\server-ocr\extract_answer_sheet_crops.py`
  - `find_markers(image)`: scans grayscale thresholds `(50, 70, 90, 110)`,
    finds square-ish dark marker candidates, dedupes nearby candidates, and
    requires at least four candidates.
  - `select_markers(candidates)`: chooses top-left, top-right, bottom-right,
    bottom-left by marker center geometry and requires four unique corners.
  - Failure type: `CropExtractionError`.

### Perspective Correction

- `C:\server-ocr\extract_answer_sheet_crops.py`
  - `warp_sheet(image, markers)`: maps selected marker centers onto a canonical
    `1600 x 2200` canvas using `cv2.getPerspectiveTransform` and
    `cv2.warpPerspective`.
  - Destination marker points are `[[140,140], [1460,140], [1460,2060], [140,2060]]`.
  - `write_warp_debug(...)` writes `warped_sheet.png`, `crop_overlay.png`, and
    `detected_markers.json`.

### Crop Generation q001-q020

- `C:\server-ocr\extract_answer_sheet_crops.py`
  - `write_question_crops(out_crops, warped)` writes `q001.png` through
    `q020.png`.
  - `detect_answer_boxes(warped)` attempts contour-based answer-box detection.
  - `fixed_answer_boxes()` is the fallback when contour detection does not
    find exactly 20 boxes in two 10-row columns.
  - `answer_region(rect)` excludes the question-number label gutter and keeps
    the answer area.

Existing crop output examples:

- `C:\server-ocr\crop_benchmark_inputs\daesu_jisu1_lv3_r1_photo01\crops\q001.png ... q020.png`
- `C:\server-ocr\crop_benchmark_inputs\person_03\crops\q001.png ... q020.png`

### Enhanced Crop Generation

- `C:\server-ocr\gemini_contact_images.py`
  - `prepare_enhanced(crop_dir, out_dir)` writes
    `out_dir\enhanced\q001.png ... q020.png`.
  - `enhance_crop(...)` converts to grayscale, autocontrasts, adjusts brightness,
    contrast, and sharpness, adds white padding, and scales 2x.
  - `prepare_hard_enhanced(crop_dir, out_dir)` writes
    `out_dir\hard_enhanced\q001.png ... q020.png`.
  - `hard_enhance_crop(...)` is explicitly a cautionary stronger-contrast view.

### Contact Sheet Generation

- `C:\server-ocr\make_review_contact_assets.py`
  - `write_contact_sheets(config, enhanced_dir)` writes four review contact
    sheets in groups `q001-q005`, `q006-q010`, `q011-q015`, `q016-q020`.
  - `write_debug_sheets(config, enhanced_dir, hard_dir)` writes per-question
    debug sheets for configured questions.
  - `write_manifest(...)` writes `asset_manifest.json`.
  - `prompt_text()` documents the same-contact rule: original crop is primary,
    soft enhanced crop is secondary, enhanced disagreements must not be guessed,
    arrow-like strokes must not be inferred as equals, and ambiguous values must
    become review-required.

- `C:\server-ocr\gemini_contact_images.py`
  - `build_contact_sheet(crop_dir, enhanced_dir, questions, target)` lays out
    original primary and soft enhanced secondary images.
  - `build_debug_sheet(crop_dir, enhanced_dir, hard_dir, question, target)`
    lays out original, soft enhanced, 3x original, and hard-contrast caution.

Existing contact asset output examples:

- `C:\server-ocr\gemini_contact_review_assets\person_03\contact_sheets\person_03_q001_q005_review.png`
- `C:\server-ocr\gemini_contact_review_assets\person_03\debug_sheets\person_03_q016_debug.png`
- `C:\server-ocr\gemini_contact_review_assets\person_03\asset_manifest.json`

### Review Payload Conversion And Policy

- `C:\server-ocr\gemini_contact_io.py`
  - `question_groups()` defines the four 5-question contact groups.
  - `parse_gemini_json(text)` parses contact-sheet OCR JSON into
    `RecognitionItem` values.
  - `evaluate(expected, recognized)` compares recognized values to expected
    answers and applies local warning policy.
  - `write_outputs(...)` writes `recognized.json`, `eval.json`,
    `benchmark_summary.json`, `eval.md`, and `benchmark_summary.md`.
  - Phase 2C must not expose `expected` or grading fields to students. This
    script is useful for lab evaluation but not directly student-facing.

- `C:\server-ocr\apply_contact_review_policy.py`
  - Applies local contact review policy to an existing `recognized.json`
    without provider calls.

- `C:\server\tools\subjective_sheet_lab\review_policy_evaluator.py`
  - Lab-side review policy evaluator for expected/recognized pairs.
  - Current policy routes mismatch, missing, equation-part, x/n, 0/6, jamo, and
    arrow/equal confusion away from safe auto grade.

- `C:\server\tools\subjective_sheet_lab\ocr_review_schema.py`
  - Defines student-facing review status/source enums.
  - Defines answer-key-only fields:
    `expected`, `canonical_answer`, `accepted_answers`.
  - Provides `find_forbidden_answer_key_paths(...)`.

- `C:\server\tools\subjective_sheet_lab\ocr_review_payload_validator.py`
  - Validates review/final payload shape.
  - Requires `test_id`, `round`, `problem_count=20`, one item per question
    `1..20`, single-line final answers, valid statuses/sources, and no
    answer-key-only fields.

- `C:\server\tools\subjective_sheet_lab\final_review_payload_bridge.py`
  - Re-exports the final payload to `answersText` bridge.
  - Final conversion remains separate from OCR route work.

### Validators

Existing relevant validators:

- `C:\server-ocr\verify_review_contact_assets.py`
  - Verifies contact/debug image counts and minimum image sizes.
  - Verifies required prompt safety phrases.

- `C:\server-ocr\run_same_contact_no_api_checks.py`
  - Runs local no-API same-contact policy and asset checks.

- `C:\server\tools\subjective_sheet_lab\verify_phase2a_internal_ocr_route_stub.py`
  - Verifies disabled route, guards, and 20-item route-stub payload.

- `C:\server\tools\subjective_sheet_lab\run_phase1_preflight_checks.py`
  - Verifies hidden OCR UI/preflight behavior and production default status.

- `C:\server\tools\subjective_sheet_lab\validate_ocr_review_contract.py`
  - Validates review/final contract fixtures and bridge output.

- `C:\server\tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py`
  - Negative contract tests for malformed payloads.

- `C:\server\tools\subjective_sheet_lab\verify_final_review_payload_bridge.py`
  - Validates final review payload to 20-line `answersText`.

## 2. Proposed Phase 2C Route Input/Output

Keep the existing route:

```http
POST /api/ocr-test-sheet-review
Content-Type: multipart/form-data
```

Do not create a direct grading endpoint and do not change `/api/submit-test`.

Request fields:

| Field | Required | Phase 2C rule |
|---|---:|---|
| `sid` | yes | Existing student id; reject empty and ghost sid. |
| `testId` | yes | Must remain allowlisted. Initial value: `t_unit_daesu_01_lv3_r1`. |
| `round` | yes | Must remain allowlisted. Initial value: `1`. |
| `image` | yes | Full answer-sheet image already validated by Phase 2B guard. |
| `clientMode` | optional | Diagnostic only; never authorization. |

Current route guard to preserve:

- Feature flag: `OCR_PHASE2_REVIEW_ROUTE_ENABLED`.
- Production default: disabled / `NO-GO`.
- Allowlisted test: `t_unit_daesu_01_lv3_r1`.
- Allowlisted round: `1`.
- Uploaded field name: `image`.
- Allowed image extensions: `jpg`, `jpeg`, `png`, `webp`.
- Allowed MIME types: `image/jpeg`, `image/png`, `image/webp`.
- Max image size: `8 MiB`.

Success response shape:

```json
{
  "ok": true,
  "review_payload": {
    "source": "phase2c_local_crop_cached_review",
    "test_id": "t_unit_daesu_01_lv3_r1",
    "round": "1",
    "problem_count": 20,
    "items": [
      {
        "question_no": 1,
        "status": "review_required",
        "recognized": "?",
        "warnings": ["crop_pipeline_pending_recognition"],
        "candidates": [],
        "final_answer": null,
        "source": null,
        "assets": {
          "crop": "opaque-local-asset-ref",
          "enhanced": "opaque-local-asset-ref",
          "contact_sheet": "opaque-local-asset-ref"
        }
      }
    ]
  },
  "warnings": []
}
```

Important response rules:

- `assets` are optional opaque references for future review UI/debugging. They
  must not expose raw absolute filesystem paths to the student browser unless a
  separate safe static asset route is designed and gated.
- Do not include answer-key-only fields: `expected`, `canonical_answer`,
  `accepted_answers`.
- Do not include grading fields or labels: `correct`, `incorrect`, `score`,
  `wrong`, `pct`.
- Do not include raw provider output, API keys, `.env` values, expected answers,
  or accepted-answer lists.
- `review_payload.items` must contain exactly `question_no` 1 through 20.
- If no cached recognition exists yet, the route should return blocking statuses
  such as `review_required` or `retake_required`, not fake safe answers.

Failure response shape:

```json
{
  "ok": false,
  "errorCode": "crop_pipeline_failed",
  "message": "Answer sheet could not be processed.",
  "warnings": []
}
```

Failure responses must not include `review_payload`.

## 3. Proposed Phase 2C Pipeline Connection

Target flow:

```text
student uploads image
  -> existing ?ocr=1 UI and allowlist gate
  -> POST /api/ocr-test-sheet-review
  -> existing Phase 2B image validation
  -> create temporary Phase 2C case id
  -> write uploaded image to temp case dir
  -> run local crop pipeline
  -> generate q001-q020 crops
  -> generate enhanced and hard-enhanced crops
  -> generate review contact/debug assets
  -> verify assets and manifests
  -> load cached/lab recognized or review payload
  -> normalize to student-safe review payload
  -> run forbidden-field scan
  -> return review payload
  -> existing review UI
  -> existing answersText bridge
  -> existing #tsSubmit only if student clicks it
  -> existing /api/submit-test final path
```

Recommended route-facing adapter, later implementation only:

```text
phase2c_process_uploaded_sheet(
  image_stream,
  sid,
  test_id,
  round_no,
  request_id
) -> Phase2CResult
```

Recommended internal stages:

1. `save_upload_to_temp_case(...)`
2. `extract_sheet_crops(...)`
3. `build_review_assets(...)`
4. `verify_review_assets(...)`
5. `load_cached_review_payload(...)`
6. `normalize_student_review_payload(...)`
7. `scan_forbidden_student_fields(...)`

Do not call Gemini/API in any Phase 2C stage.

## 4. Temp Storage Strategy

Recommended root:

```text
C:\server-ocr\phase2c_runtime\
```

Recommended per-request case id:

```text
phase2c_<UTC_YYYYMMDDTHHMMSSZ>_<short_random>_<safe_test_id>_r<round>
```

Do not include raw `sid` in filenames. If correlation is needed, store a short
hash in `request_manifest.json`.

Recommended per-request root:

```text
C:\server-ocr\phase2c_runtime\<case_id>\
```

Recommended manifest:

```json
{
  "case_id": "phase2c_20260629T000000Z_ab12cd34_t_unit_daesu_01_lv3_r1_r1",
  "created_at": "2026-06-29T00:00:00Z",
  "sid_hash": "sha256-prefix",
  "test_id": "t_unit_daesu_01_lv3_r1",
  "round": "1",
  "source_image": "incoming/full_sheet.jpg",
  "pipeline_version": "phase2c_plan_v1",
  "status": "prepared"
}
```

Storage rules:

- Store the uploaded image only under the temp case root.
- Copy or write only local lab artifacts under `C:\server-ocr`, never under
  operating app `data`, `static`, DB, or student directories.
- Do not copy answer keys into the temp case root for route processing.
- For Phase 2C cached recognition, lookup by allowlisted `testId` and controlled
  fixture id, not by reading answer keys from `tests-config.json`.
- If implementation needs expected answers for a lab-only policy run, keep that
  strictly outside student response construction and verify no leak before
  returning.

## 5. File Cleanup Strategy

Default production-hidden QA behavior:

- Delete raw uploaded image immediately after crop extraction succeeds and
  artifacts are written, unless debug retention is explicitly enabled.
- Delete the whole temp case root after response if `OCR_PHASE2C_RETAIN_ARTIFACTS`
  is false.
- Preserve only a small `request_result.json` if a lab debug flag explicitly
  allows it; it must contain no answer keys, no API keys, no raw provider output,
  and no student-identifying plain sid.

Recommended debug-retention flags, later implementation only:

```text
OCR_PHASE2C_PIPELINE_ENABLED=0
OCR_PHASE2C_RETAIN_ARTIFACTS=0
OCR_PHASE2C_ARTIFACT_TTL_HOURS=24
OCR_PHASE2C_ALLOW_CACHED_RECOGNITION=1
OCR_PHASE2C_ALLOW_GEMINI=0
```

Cleanup cases:

- Success: remove temp root unless retention flag is on.
- Whole-sheet failure: keep no raw image by default; optionally retain
  `crop_pipeline_error.json` under debug retention.
- Partial crop failure: keep no artifacts by default; optionally retain
  overlay/debug files under debug retention.
- Exception: best-effort cleanup in `finally`.
- Scheduled cleanup: remove `phase2c_runtime` case dirs older than TTL when
  retention is enabled.

## 6. Crop Output Folder Structure

Recommended retained debug structure:

```text
C:\server-ocr\phase2c_runtime\<case_id>\
  incoming\
    full_sheet.jpg
  crop_benchmark_inputs\
    <case_id>\
      case_manifest.json
      crop_manifest.json
      detected_markers.json
      warped_sheet.png
      crop_overlay.png
      crops\
        q001.png
        ...
        q020.png
  review_assets\
    enhanced\
      q001.png
      ...
      q020.png
    hard_enhanced\
      q001.png
      ...
      q020.png
    contact_sheets\
      <case_id>_q001_q005_review.png
      <case_id>_q006_q010_review.png
      <case_id>_q011_q015_review.png
      <case_id>_q016_q020_review.png
    debug_sheets\
      <case_id>_q003_debug.png
      ...
    same_contact_review_prompt.md
    asset_manifest.json
    asset_verification.json
    asset_verification.md
  payload\
    cached_recognized_source.json
    review_payload_student_safe.json
    forbidden_field_scan.json
  request_manifest.json
```

For non-retained mode, the same structure can be created under a temporary
directory and removed after the response.

Do not write Phase 2C runtime artifacts into:

- `C:\server\static\`
- `C:\server\data\`
- `C:\server\tests-config.json`
- DB files
- student records
- `progress.json`, `logs.json`, or tests runtime files

## 7. Review Payload Handoff Strategy

Phase 2C should not do direct grading. It should return a review payload only.

Recommended source hierarchy:

1. **Cached student-safe review payload fixture**, if available for the exact
   allowlisted `testId`, round, and local pipeline fixture.
2. **Cached `recognized.json` plus local policy conversion**, if a cached
   recognition file exists and a non-leaking converter is added in lab/core.
3. **Blocking review payload**, if no cached recognition exists.

Initial Phase 2C should prefer option 1 or 3 to avoid accidentally introducing
answer-key leakage through expected-vs-recognized evaluation.

Recommended first safe handoff:

- Run crop/enhance/contact/asset verification from the upload.
- Return a payload where all 20 items are `review_required` or `retake_required`
  unless a prebuilt cached review payload has already passed
  `validate_ocr_review_contract.py`.
- Do not mark anything `safe_auto_grade` unless the value came from a trusted
  cached recognition/review fixture and the item has no warnings.

Payload invariants:

- `test_id` matches request.
- `round` is string `"1"`.
- `problem_count` is `20`.
- `items` covers `question_no` 1..20 exactly once.
- Unresolved statuses have `source: null` and `final_answer: null`.
- `safe_auto_grade` items have `source: "safe_auto_grade"` and non-empty
  single-line `final_answer`.
- `review_required`, `retake_required`, `retake_uploaded`, and
  `data_check_required` remain blocking until student review or retake handling
  resolves them.
- Choice-number validation remains client-side and server-side contract tested.

Handoff to final submit:

- OCR route returns review payload only.
- Existing review UI renders and resolves it.
- Existing bridge fills `#tsAnswersText` only after all blocking items are
  resolved.
- Existing `#tsSubmit` remains the only path that posts to `/api/submit-test`.

## 8. Failure Modes

| Failure | Phase 2C route response | Student outcome |
|---|---|---|
| Route flag disabled | `503 feature_disabled` | OCR unavailable; manual textarea remains usable. |
| Missing image | `400 missing_image` | Ask for image; manual textarea remains usable. |
| Unsupported image type | `415 unsupported_image_type` | Ask for supported image; manual textarea remains usable. |
| Image too large | `413 image_too_large` | Ask for smaller image; manual textarea remains usable. |
| Corrupt/unreadable image | `400 invalid_image` | Ask for retake; manual textarea remains usable. |
| Fewer than four markers | `ok:false`, `whole_sheet_retake_required` | Ask for full-sheet retake; do not render fake review. |
| Marker selection ambiguous | `ok:false`, `whole_sheet_retake_required` | Ask for full-sheet retake. |
| Perspective warp fails | `ok:false`, `whole_sheet_retake_required` | Ask for full-sheet retake. |
| Crop count not 20 | `ok:false`, `crop_pipeline_failed` | Do not enter review; manual fallback remains. |
| One crop missing/unreadable | 20-item payload with that item `retake_required` | Fill is blocked until resolved/manual fallback. |
| Contact sheet generation fails | `ok:false`, `contact_asset_failed` | Do not render review payload. |
| Asset verifier fails | `ok:false`, `asset_verification_failed` | Do not render review payload. |
| No cached recognition available | 20-item blocking review payload | No safe auto-grade; manual fallback remains. |
| Cached payload malformed | `500 contract_violation` | Do not render payload; manual fallback remains. |
| Answer-key/grading field leak detected | `500 contract_violation` | Do not render payload. |
| Gemini/provider attempted | hard failure in validation | Phase 2C NO-GO. |
| Any `/api/submit-test` call during OCR | hard failure in QA | Phase 2C NO-GO. |

## 9. Validation Plan

Plan-artifact validation for this pass:

- Confirm `C:\server\tools\subjective_sheet_lab\phase2c_crop_pipeline_integration_plan.md`
  exists.
- Confirm only this lab plan file was created/modified by this task.
- Confirm no Gemini/API command was run.
- Confirm `/api/submit-test` was not called.
- Confirm operating app files were not modified by this planning task.

Future implementation validation:

Static checks:

```powershell
python -m py_compile routes\api_tests.py
node --check static\js\student.js
python -m py_compile tools\subjective_sheet_lab\validate_ocr_review_contract.py
```

Route guard checks:

- Disabled default returns `503 feature_disabled`.
- Enabled local route rejects missing/invalid image.
- Enabled local route rejects blocked testId.
- Enabled local route rejects wrong round.
- Enabled local route rejects ghost sid.
- Enabled local route accepts only `t_unit_daesu_01_lv3_r1`, round `1`.

Pipeline checks:

```powershell
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\prepare_incoming_case.py --case <case> --image <image> --expected <expected>
C:\server-ocr\.venv\Scripts\python.exe C:\server-ocr\verify_review_contact_assets.py --manifest <asset_manifest>
```

Contract checks:

```powershell
python tools\subjective_sheet_lab\validate_ocr_review_contract.py
python tools\subjective_sheet_lab\verify_ocr_review_contract_negative.py
python tools\subjective_sheet_lab\verify_final_review_payload_bridge.py
python tools\subjective_sheet_lab\verify_phase2a_internal_ocr_route_stub.py
python tools\subjective_sheet_lab\run_phase1_preflight_checks.py
```

Phase 2C-specific tests to add later:

- Valid uploaded full-sheet image produces 20 crop files in a temp case dir.
- Marker detection failure returns whole-sheet retake and no review payload.
- Crop count failure returns `crop_pipeline_failed`.
- Contact asset verifier failure returns `asset_verification_failed`.
- No cached recognition returns blocking 20-item review payload, not safe answers.
- Cached review payload passes validator and forbidden-field scan.
- Success response contains no `expected`, `canonical_answer`, `accepted_answers`,
  `correct`, `incorrect`, `score`, `wrong`, or `pct`.
- Success response has exactly 20 items and question numbers 1..20.
- OCR route does not write app runtime data.
- OCR route does not call Gemini/API.
- OCR route does not call `/api/submit-test`.

Browser/manual QA:

- Default student URL: OCR UI hidden.
- `?ocr=1` allowlisted student/test/round: OCR upload visible.
- Upload valid image: network calls only `/api/ocr-test-sheet-review`, not
  `/api/submit-test`.
- Returned review payload opens the existing review UI.
- Blocking statuses prevent `#tsAnswersText` fill.
- Resolved payload fills exactly 20 non-empty newline-separated lines.
- `#tsSubmit` is not clicked during OCR QA.

Runtime diff checks:

- Capture hashes/timestamps before and after route tests for:
  - `C:\server\tests-config.json`
  - app DB file
  - app data directory
  - student records
  - progress/log/test runtime JSON files
- Only allowed changes are lab/temp Phase 2C artifacts under
  `C:\server-ocr\phase2c_runtime\` when debug retention is explicitly enabled.

## 10. Rollback Plan

Immediate rollback without code revert after future implementation:

1. Leave `OCR_PHASE2_REVIEW_ROUTE_ENABLED` unset/false.
2. Leave `OCR_PHASE2C_PIPELINE_ENABLED` unset/false.
3. Leave normal student URLs without `?ocr=1`.
4. Keep manual `#tsAnswersText` entry available.

Code rollback after future implementation:

1. Revert only the Phase 2C adapter/pipeline patch.
2. Keep Phase 2A/2B route guards if they remain valid and disabled by default.
3. Do not revert unrelated dirty worktree changes.
4. Do not touch `tests-config.json`, answer keys, DB schema, student records,
   progress/log/test runtime data, or `/api/submit-test`.

Data/artifact rollback:

1. Delete only `C:\server-ocr\phase2c_runtime\<case_id>\` dirs created by
   Phase 2C QA.
2. Do not delete existing benchmark cases under `crop_benchmark_inputs`,
   `gemini_contact_review_assets`, or `gemini_outputs` unless the Phase 2C
   implementation explicitly created them and a manifest proves ownership.
3. If a future bug accidentally writes operating data, stop immediately, back up
   the touched files, identify exact rows/records, and perform a separate
   surgical cleanup task.

## 11. GO / NO-GO Gate Before Implementation

GO to implement Phase 2C only if all are true:

- Phase 2B image-upload stub manual QA is green or its blockers are explicitly
  resolved.
- Production default remains `NO-GO`.
- Route remains disabled unless `OCR_PHASE2_REVIEW_ROUTE_ENABLED` is enabled
  locally.
- `?ocr=1` remains required for OCR UI visibility.
- Server allowlist remains restricted to `t_unit_daesu_01_lv3_r1`, round `1`.
- Uploaded image validation remains bounded by MIME/type/size.
- Local crop pipeline can be run in a temp directory without touching operating
  app data.
- The planned response is a review payload only, not direct grading.
- No answer-key or grading fields are present in student-facing payloads.
- Cached/lab review payload source is available or the route will return
  blocking statuses, not fabricated safe answers.
- Validation plan includes route guards, crop/contact failure cases,
  forbidden-field scan, no-provider-call scan, no-submit-call scan, and runtime
  diff checks.

NO-GO if any are true:

- Any Phase 2C path requires Gemini/API.
- Any Phase 2C path calls `/api/submit-test`.
- Any Phase 2C path clicks or simulates `#tsSubmit`.
- OCR UI appears without `?ocr=1`.
- Non-allowlisted tests or rounds can access the route.
- Route response includes answer-key fields, accepted-answer fields, grading
  fields, raw provider payload, API keys, or `.env` values.
- Route writes operating app code/data, DB schema, tests-config, answer keys,
  student records, or progress/log/test runtime data.
- Route returns `safe_auto_grade` from an uncached or unverified OCR value.
- Review-required or retake-required items can fill `#tsAnswersText` without
  resolution.
- Production default is changed away from `NO-GO`.

## 12. Explicit No-Change Statement

This planning task made no code/API/data changes.

Only this plan document was created:

- `C:\server\tools\subjective_sheet_lab\phase2c_crop_pipeline_integration_plan.md`

This planning task did not:

- implement Phase 2C
- modify `app.py`
- modify `routes\api_tests.py`
- modify `static\js\student.js`
- modify any operating route/static/app code
- modify `tests-config.json`
- modify answer keys
- modify DB schema
- modify student records
- modify progress/log/test runtime data
- call Gemini/API
- call `/api/submit-test`
- click `#tsSubmit`

## Recommendation

Implement Phase 2C as a route-internal preprocessing adapter behind the existing
Phase 2B image-upload route guard:

```text
existing route guards
  -> existing Phase 2B image validation
  -> new Phase 2C temp case adapter
  -> existing local crop/enhance/contact-sheet scripts
  -> asset verification
  -> cached or blocking student-safe review payload
  -> existing review UI
  -> existing answersText bridge
  -> existing #tsSubmit and /api/submit-test only when the student submits
```

The first implementation should prove crop/enhance/contact generation and
contract-safe payload handoff with Gemini disabled. It should not attempt live
recognition, direct grading, or production enablement.
