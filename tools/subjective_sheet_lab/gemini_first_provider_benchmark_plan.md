# Gemini-First Provider Benchmark Plan

Classification: PLANNING_ONLY_P1_NON_STUDENT_BENCHMARK.

## Purpose and boundary

This plan prepares a paid Gemini benchmark only. It does not authorize a provider
request, create a provider budget, collect a student sheet, alter a cache or
recognized result, or begin a rollout. Production default remains NO-GO.

The benchmark does not require three to five newly collected sheets by default.
Its real input requirement is enough independent, key-free handwriting evidence:
distinct writer/capture families, sufficient question count, usable source
images or crops, actual-writing human transcription, and at least one holdout
writer or holdout item block that was not used for Gemini prompt tuning.

Each case is identified only by an anonymous case ID. A case ID must not encode
a person, school, assignment, or filesystem location.

## Per-case intake contract

For every case, retain the full source locally under the controlled lab process.
Any future provider request may receive only a deidentified q001-q020 crop pack
or contact pack with generic item labels. The provider packet must exclude:

- student identity, student-record data, assignment metadata, and school labels;
- answer keys, expected or canonical answers, accepted-answer lists, correctness,
  grading fields, or grading outcomes;
- filesystem paths and path-derived identifiers;
- recognized output or cache content from another case.

Before a future request, record a key-free human transcription for q001-q020.
Every entry must retain a confidence label and an ambiguity label. Unclear,
erased, overwritten, crossed-out, or multiple-answer content remains unresolved
and review-gated; it is not normalized or inferred.

## Measurement sheet

The benchmark ledger must contain only anonymous case IDs and aggregate metrics.
For each case and for the aggregate, record:

| Metric | Definition |
| --- | --- |
| Candidate coverage | Questions with at least one OCR candidate divided by 20. |
| OCR-vs-human accuracy | Exact agreement with the key-free human transcription over comparable, non-ambiguous items. |
| High-confidence accuracy | OCR-vs-human accuracy restricted to human and OCR entries both eligible for the high-confidence comparison. |
| Missing | Items with no candidate or no usable OCR output. |
| Unresolved | Items that remain ambiguous, conflicting, unreadable, or otherwise review-gated. |
| Partial-fill candidates | Questions safe enough to present as candidates while leaving unresolved questions blank/manual. |
| Provider failures | Failed, timed-out, malformed, or unavailable provider responses; do not retry outside the approved rule. |
| Wrong-safe-auto-grade | Any item presented as safe for automatic grading that disagrees with the human comparison. |
| Student-facing leak | Any answer-key, grading, identity, or filesystem-path disclosure in a student-facing payload/report. |

The comparison is strictly OCR against human transcription. It must not use an
answer key or grading result to decide whether OCR is correct.

## Benchmark gates

The following gates apply before the benchmark can be described as ready for a
separate pilot decision:

- High-confidence OCR-vs-human accuracy: at least 80%; target at least 90%.
- Partial-fill candidates: at least 15 of 20 questions per qualifying case.
- Wrong-safe-auto-grade: exactly 0.
- Student-facing leak: exactly 0.

Any unresolved item remains review-required even when aggregate accuracy passes.
A provider failure, leak, or nonzero wrong-safe-auto-grade count blocks the
benchmark result until separately investigated; no automatic retry, cache
overwrite, or grading change is implied.

## Planned sequence after separate authorization

1. Inventory existing anonymous benchmark and QA artifacts before requesting new
   handwriting.
2. Classify every usable artifact as development, validation, untouched holdout,
   or unusable.
3. Request only the missing amount if writer diversity, question count, format
   coverage, or holdout coverage is insufficient.
4. Prepare and leak-audit only the deidentified q001-q020 crop/contact packs.
5. Obtain one explicit paid-batch approval using the companion approval packet.
6. Run only within the declared provider-call budget and stop/resume rule.
7. Compare output to the human transcription, publish aggregate gate results,
   and preserve every non-passing item as review-required.

No step above authorizes actual-student transfer, student rollout, final submit,
or a production-default change.

## Current status

P1 benchmark preparation is closed as `READY_WITH_CAVEATS`. New handwriting
collection is no longer a blocker.

The sprint uses the existing standardized benchmark plus the newly prepared
`teacher_01` and `teacher_02` cases. Round 1 freezes five cases and 100 question
positions:

- development: `person_02_same_contact`, `person_04_same_contact`, `teacher_01`;
- validation: `daesu_jisu1_lv3_r1_photo01_same_contact`,
  `person_03_same_contact`.

`teacher_02` is sealed as the 20-question Round 2 holdout. Its q007 and q018
human transcriptions are low-confidence because a prior mark is crossed out;
those items remain review-gated. The older teacher dry-run remains extra lab
evidence and is not required for this sprint.

The next task is `GEMINI_LIVE_BENCHMARK_ROUND_1`, pending one explicit paid-call
approval. It uses stable `gemini-2.5-flash`, Prompt A-D, and the four-contact
P1 package. Expected and hard provider-call count: 20. Round 1 has no second
pass and no automatic 429/503 retry.

After Round 1, exactly two prompts advance. Round 2 will require separate
authorization and will compare those prompts on the sealed holdout with
selective two-pass OCR. Only after Round 2 may the final prompt, input package,
and confidence policy be fixed.

The completed approval packet records official Standard pricing checked on
2026-07-20: USD 0.30 per million text/image/video input tokens and USD 2.50 per
million output tokens. Historical same-package usage gives an expected Round 1
cost of about USD 0.02; the hard maximum is USD 0.10.

Declared provider calls in this preparation task: 0. Actual provider calls: 0.
Production default remains `NO-GO`; student rollout and submission remain
forbidden.
