# OCR Training Pack Crop Fixture Spec

Date: 2026-07-06 KST

## Purpose

Define the provider-free crop fixture layout needed before Training Pack OCR replay can be tested without touching canonical benchmark outputs or runtime data.

## Current State

- Source readiness artifact: `ocr_training_pack_crop_fixture_readiness.json`
- Targets: 4
- Existing complete crop fixture sets: 0
- Provider calls: 0
- `/api/submit-test` calls: 0
- `#tsSubmit` clicks: 0
- Production default: `NO-GO`

## Targets

| test_id | round | fixture directory |
|---|---:|---|
| `t_training_pack_gongsu2_non_frequent_r1` | 1 | `tools/subjective_sheet_lab/visual_evidence/training_pack_crop_fixtures/t_training_pack_gongsu2_non_frequent_r1` |
| `t_training_pack_gongsu2_non_frequent_r2` | 2 | `tools/subjective_sheet_lab/visual_evidence/training_pack_crop_fixtures/t_training_pack_gongsu2_non_frequent_r2` |
| `t_training_pack_mijeok1_non_frequent_r1` | 1 | `tools/subjective_sheet_lab/visual_evidence/training_pack_crop_fixtures/t_training_pack_mijeok1_non_frequent_r1` |
| `t_training_pack_mijeok1_non_frequent_r2` | 2 | `tools/subjective_sheet_lab/visual_evidence/training_pack_crop_fixtures/t_training_pack_mijeok1_non_frequent_r2` |

## Required Layout Per Target

```text
full_sheet.jpg or full_sheet.png
crops/q001.png
...
crops/q020.png
contact_sheets/contact_01.png
asset_manifest.json
crop_quality_report.json
review_payload_cache.json
```

## Acceptance Rules

- Exactly 20 crop files must exist per target.
- Crop names must be `q001.png` through `q020.png`.
- Question order must be preserved: question 1 is `q001`, question 20 is `q020`.
- Contact sheet must be derived from the same 20 crops.
- Quality report must include width, height, blur, brightness, contrast, and blank-like signal per crop.
- Student-facing payloads must not contain local filesystem paths.
- Existing benchmark recognized/cache outputs must not be overwritten.
- Provider calls remain 0 until a separate live-call approval is present.

## Blocker

Training Pack replay remains blocked until these provider-free crop/contact-sheet fixtures are captured. This spec does not create the fixtures and does not modify operating data.
