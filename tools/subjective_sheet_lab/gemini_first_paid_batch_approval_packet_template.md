# Gemini-First Paid-Batch Approval Packet Template

Classification: TEMPLATE_ONLY_NOT_LIVE_CALL_AUTHORIZATION.

This template is not a live-call authorization. A provider batch remains blocked
until the user answers the single filled-in approval question below immediately
before that batch. Do not infer a model, budget, price, sample count, retry
policy, or actual-student transfer permission from this template.

## Fill-in record

| Required field | Value to be supplied immediately before the batch |
| --- | --- |
| Stable Gemini model identifier | [MODEL_ID] |
| Non-student anonymous case IDs | [CASE_IDS] |
| Number of input sheets | [SHEET_COUNT] |
| First-pass contact/crop requests | [FIRST_PASS_MAX] |
| Maximum eligible second-pass crop requests | [SECOND_PASS_MAX] |
| Cache-hit estimate | [CACHE_HIT_ESTIMATE] |
| Official unit-price source | [OFFICIAL_PRICING_SOURCE] |
| Maximum cost estimate | [MAX_COST_ESTIMATE] |
| Declared provider-call budget | [DECLARED_CALL_BUDGET] |
| 429/503 stop and resume rule | [STOP_RESUME_RULE] |
| Deidentification confirmation | [DEIDENTIFICATION_CONFIRMED] |
| Leak-gate confirmation | [LEAK_GATE_CONFIRMED] |
| Sample class | [NON_STUDENT_ONLY_OR_SEPARATE_TRANSFER_APPROVAL_REFERENCE] |

The sample class must be NON_STUDENT_ONLY unless a separate, explicit
actual-student transfer-policy approval is already recorded. A provider budget
is not a transfer approval.

## Required single approval question

Immediately before the proposed batch, ask exactly this one filled-in question:

> Do you authorize one non-student Gemini benchmark batch using model
> [MODEL_ID] for [SHEET_COUNT] anonymous sheets, with at most
> [FIRST_PASS_MAX] first-pass contact/crop requests and
> [SECOND_PASS_MAX] eligible second-pass crop requests, a cache-hit estimate
> of [CACHE_HIT_ESTIMATE], official pricing source [OFFICIAL_PRICING_SOURCE],
> maximum estimated cost [MAX_COST_ESTIMATE], and hard provider-call budget
> [DECLARED_CALL_BUDGET]; with [STOP_RESUME_RULE] for 429/503, confirmed
> deidentification and answer-key/grading/path leak gates, and
> [NON_STUDENT_ONLY_OR_SEPARATE_TRANSFER_APPROVAL_REFERENCE] sample scope?

No request may be sent until the user affirmatively answers this completed
question. An incomplete field, missing price source, absent hard budget, or
unclear stop/resume rule is a stop condition.

## Pre-dispatch confirmations

- Input consists only of deidentified q001-q020 crops/contact packs and generic
  item labels.
- Full source sheets remain local; no student identity, student record,
  assignment metadata, answer-key, expected/canonical/accepted-answer, grading,
  correctness, or filesystem-path value is included.
- The human-transcription comparison is key-free and ambiguous items are marked
  review-required.
- The provider is authorized only for the stated non-student scope and budget.
- No route, browser, final-submit, runtime-data, recognized-output, or cache
  overwrite action is included in this approval.

## Batch stopping record

Record only aggregate counts: attempted calls, successful calls, failed calls,
cache hits, 429/503 events, and budget remaining. On a stop condition, do not
retry, expand scope, substitute a model, increase budget, or alter stored
artifacts without a new explicit approval.

## Post-batch handoff

The permitted result is a key-free benchmark comparison against human
transcription with the benchmark gates applied. It is not student rollout,
automatic grading, final-submit certification, or production-default approval.

Provider calls made while preparing this template: 0.
