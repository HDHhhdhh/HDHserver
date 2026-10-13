# Non-Student Handwriting Provider Accuracy Plan

## Purpose

Prepare a provider-accuracy evaluation using handwriting created by an adult,
teacher, or test author who is not a student. This is a preparation document
only. It neither authorizes a provider call nor changes the production OCR
default.

## Eligible Source Material

- Use an independently written, real-test-format sample with no student name,
  student ID, student record, assignment metadata, schedule, or notes.
- Keep source material separate from student case folders and runtime data.
- Assign a random case ID and random item IDs before any provider input is
  constructed.
- Do not send a full sheet when crop-only inputs are sufficient.

## Human Transcription Baseline

- Create a 20-item q001-q020 transcription from visible handwriting only.
- Mark uncertain entries as `?` with a confidence label; do not guess.
- Do not use answer keys, expected values, canonical answers, accepted answers,
  correctness labels, scores, or grading fields.
- Evaluate OCR-vs-human separately from answer-key grading. Answer-key grading
  is outside this track.

## Provider Gate

- A live provider call requires a separate process-local user authorization.
- The authorization must declare a positive maximum provider-call budget.
- Use cache-first behavior. A valid matching cache must prevent a new call.
- Do not overwrite canonical recognized output or provider cache. New results
  belong in a fresh variant/cache folder.
- Recognized-only output remains `review_required`; it must not become
  `safe_auto_grade` merely because text was recognized.

## Required Measurements

| Measure | Minimum | Target |
| --- | ---: | ---: |
| High-confidence OCR-vs-human accuracy | 80% | 90% |
| Partial-fill eligible items | 15/20 | 17/20 |
| `wrong_safe_auto_grade` | 0 | 0 |
| Missing and unresolved items | Report separately | Reduce without guessing |

Ambiguous, erased, crossed-out, overwritten, multiple-candidate, or unclear
answers must stay `review_required` or `retake_required` and cannot count as
safe automatic grading.

## Failure and Resume Policy

- On 429, 503, invalid provider JSON, malformed cache, or missing questions,
  stop the run and preserve a fail-closed review/manual-input path.
- Do not automatically retry a provider call.
- Resume only from a valid cache or a new explicit authorization with a new
  declared budget.
- Record actual provider-call count, cache status, unresolved count, and
  `wrong_safe_auto_grade` in the lab report.

## Permanent Boundaries

- Production default remains `NO-GO`.
- This plan is not actual-student accuracy evidence.
- This plan is not production-readiness evidence.
- This plan is not a live-call approval.
- `/api/submit-test` and `#tsSubmit`/final submit remain outside this track.

## Next Approval Needed

Authorize one non-student handwriting sample for provider evaluation with a
declared process-local Gemini/API budget. The approval must keep student data,
submit paths, production default, answer keys, and canonical cache outputs out
of scope.
