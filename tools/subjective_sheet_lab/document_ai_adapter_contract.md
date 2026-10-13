# Document AI OCR Adapter Contract

Status: PROVIDER_ZERO_INTERFACE_MAP_READY
Scope: adult-authored non-student benchmark only

## Boundary

This is a lab-only interface map. It is not mounted in app.py, routes, or the student page. It preserves the current local intake, crop, cache, calibration, four-tier classification, and review UI contracts.

## Versioned configuration

Required process-local configuration:

- provider: google_document_ai
- processor_type: OCR_PROCESSOR
- processor_version: pretrained-ocr-v2.1-2024-08-07
- location: asia-southeast1
- adapter_schema_version: document_ai_candidate_v1
- math_ocr_enabled: false for baseline, true for Math pipeline
- provider_enabled: false by default

Project ID, processor ID, and credentials are deployment secrets. They are never serialized into evidence, cache payloads, UI payloads, or student output.

## Input envelope

Allowed fields:

- anonymous_case_id
- anonymous_item_start
- anonymous_item_end
- generic_label
- mime_type
- content_sha256
- deidentification_gate_version
- preprocessing_version
- processor_version
- math_ocr_enabled
- image bytes

Rejected fields:

- student name or SID
- assignment metadata
- answer key
- expected
- canonical_answer
- accepted_answers
- grading or score fields
- local filesystem path
- full-sheet content for a student-data path

## Request map

- Endpoint uses the selected regional processor-version process method.
- RawDocument supplies MIME type and content.
- OCR config enables image quality scores and symbols.
- Optional language hints may be configured only from documented languageHints values.
- The Math pipeline enables premiumFeatures.enableMathOcr.
- Selection-mark detection remains disabled when Math OCR is active.

## Response normalization

1. Validate response schema and exact processor-version provenance.
2. Extract text anchors, token/symbol confidence, geometry, and image quality scores.
3. Extract math_formula visual elements and LaTeX text when Math OCR is active.
4. Use the local contact-sheet region manifest to associate provider geometry with q001-q020.
5. Normalize each item to candidate-only output.
6. Never synthesize missing items and never create final_answer or safe_auto_grade.
7. Apply the existing calibrated provenance gate independently of provider confidence.
8. Emit exactly one of AUTO_CONFIRM, REVIEW_RECOMMENDED, DIRECT_INPUT, or RETAKE_REQUIRED.

## Candidate item contract

Allowed item fields:

- question_no
- classification
- candidates
- candidate_source
- provider_provenance
- processor_version
- math_ocr_enabled
- provider_confidence
- crop_quality
- parser_warnings
- requires_confirmation
- allow_direct_input
- warning

AUTO_CONFIRM is allowed only when the existing calibration contract passes. Provider confidence by itself cannot satisfy the gate.

## Fail-closed behavior

| Condition | Result |
| --- | --- |
| Provider disabled + cache hit | Return validated cache through normal classification gate |
| Provider disabled + cache miss | Stop provider work; return explicit manual/review fallback |
| Timeout or 429/503 | No retry loop; preserve blank/direct-input fallback |
| Malformed JSON/schema | Reject response; no synthetic candidate |
| Missing page/item | Missing item becomes DIRECT_INPUT or RETAKE_REQUIRED |
| Version mismatch | Reject cache/response and require explicit re-benchmark |
| Identifier/key/path field detected | Block before provider call |
| Math formula conflicts with text OCR | REVIEW_RECOMMENDED |

## Cache key

Cache identity includes:

- provider
- processor type
- exact processor version
- region
- Math OCR flag
- content SHA-256
- preprocessing version
- deidentification gate version
- adapter schema version

Caches are benchmark-local and cannot overwrite canonical production cache.

## Benchmark plan

- Inputs: eight verified adult-authored contact sheets, four from teacher_01 and four from teacher_02.
- Pipeline A: Enterprise OCR baseline.
- Pipeline B: same input with Math OCR enabled.
- Maximum online calls: 16.
- Human comparison: existing read-only actual-writing transcription.
- Metrics: OCR-vs-human, actionable coverage, symbol-type accuracy, wrong_auto_confirm, latency, and cost.

No live processor call is authorized by this document.
