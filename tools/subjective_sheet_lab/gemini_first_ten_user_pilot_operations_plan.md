# Gemini-First Ten-User Pilot Operations Plan

Classification: PLANNING_ONLY_P2_TEACHER_SUPERVISED_PILOT.

## Scope and non-authorization

This is an operations plan for a teacher-supervised, staged 1 -> 3 -> 10 user
pilot on t_unit_daesu_01_lv3_r1, round 1, using the hidden ?ocr=1 surface
only. It does not start a pilot, open the hidden surface, call a provider, call a
route, write runtime data, or enable production. Production default remains
NO-GO.

Every stage - one student, three students, and ten students - requires its own
explicit real-student rollout approval. Approval for a prior stage does not
authorize the next stage, a new test/round, provider transfer, or final submit.

## Operating model

The supervised workflow is local crop -> deidentify -> cache/review -> teacher
review. Provider candidates are review-gated throughout. They are not treated
as grading facts and do not replace manual confirmation.

- Preserve partial fill only for teacher-confirmed candidates.
- Keep ambiguous, missing, erased, crossed-out, overwritten, conflicting, and
  low-confidence positions blank for manual input or retake handling.
- Keep the answer area editable; a blank/manual fallback is valid.
- Do not use answer-key, expected/canonical/accepted-answer, or grading data to
  resolve a candidate.
- Do not expose student identity, answer-key/grading values, or filesystem paths
  in any student-facing payload or plan record.

The existing final submission control is identified as #tsSubmit, but this plan
does not direct its use. Any final submit is outside this pilot plan and requires
separate authorization after an independently scoped certification decision.

## Stage gates

| Stage | Entry approval required | Minimum operating evidence | Advancement decision |
| --- | --- | --- | --- |
| 1 student | Explicit approval for one anonymized real-student session | Local/deidentified processing, teacher review, review-gated candidate handling, partial-fill and manual/blank fallback, no unintended submit | Separate user decision after reviewing safety and quality evidence |
| 3 students | New explicit approval for the next two anonymized sessions | Stage-1 safeguards remain intact for each session; no cross-student cache collision or shared-runtime drift | Separate user decision after an aggregate review |
| 10 students | New explicit approval for the remaining seven anonymized sessions | All previous safeguards remain intact; records remain anonymous and each result is teacher-reviewed | Separate production-readiness decision; no default enablement follows automatically |

## Session checklist

Before an approved session, confirm the target test/round, hidden-only scope,
teacher supervision, local source retention, deidentification boundary,
cache-key isolation, and review-gated response behavior. Record anonymous
session labels and aggregate safety counts only.

During review, the teacher may accept a candidate only where the source and
candidate are sufficiently clear. All other positions stay manual/blank or are
classified for retake. No candidate may be promoted to safe_auto_grade from a
partial, ambiguous, or conflict state.

After a session, record counts for reviewed items, manual/blank items,
retake-required items, unresolved items, cache collisions, and stop events.
Do not place source paths, student identifiers, answer keys, or grading outcomes
in the pilot summary.

## Mandatory stop conditions

Stop the current stage immediately and preserve the review/manual fallback if
any of the following occurs:

- privacy, answer-key, grading, or filesystem-path leak;
- any wrong-safe-auto-grade result;
- shared runtime drift or unplanned original-code mutation;
- cross-student cache collision or ambiguous cache provenance;
- provider budget overrun, unapproved provider attempt, or failed provider gate;
- unintended submit or final-submit behavior;
- a target test/round outside t_unit_daesu_01_lv3_r1, round 1;
- loss of teacher supervision, deidentification, or the ability to leave items
  manual/blank.

Stopping does not authorize retries, artifact cleanup, cache overwrite, runtime
restore, route/UI reruns, or escalation to the next stage. Each requires a
separate scope decision.

## Evidence required for each stage review

- Anonymous session count and test/round confirmation.
- Provider call count, which remains 0 unless a separate positive-budget
  authorization is recorded.
- Candidate/review/manual/blank/retake counts without answer values.
- Wrong-safe-auto-grade count and leak count, each required to be 0.
- Shared-runtime and cache-isolation result.
- Submit and final-submit counts, each required to be 0 for this plan.
- Confirmation that production default remains NO-GO.

## Current status

P2 is ready only as a planning artifact. Actual-student rollout is blocked until
the applicable stage has explicit approval. Provider calls made while preparing
this plan: 0. Submit and final-submit actions: 0.
