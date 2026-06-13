# SHARED JS KNOWLEDGE BASE

## Overview
Cross-page browser helpers live here. Admin, all-students, student, and utility pages import these modules, so behavior changes can fan out quickly.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Fetch and JSON helpers | `api.js` | `ApiError`, `ensureOk`, `fetchJson*`, `sendJson`, `JSON_HEADERS`. |
| Search normalization | `search.js` | Hangul initials, Dubeolsik keyboard variants, whitespace-as-AND matching. |
| School calendar normalization | `schoolCalendar.js` | V1/V2 calendar payloads, grade/phase flattening, nonblank merge behavior. |
| Self-study day helpers | `selfStudy.js` | `selfStudyDays`, `day1`-`day5`, weekday/date matching. |

## Conventions
- Keep helpers framework-free ES modules.
- Preserve exported names; page modules import them directly.
- `fetchJsonOr` intentionally swallows failures and returns a caller-provided fallback. Use checked helpers when bootstrap data is critical.
- `sendJson` defaults only the method, JSON headers, and body. Callers own credentials/cache options.
- Search helpers must keep Korean initials, composed Hangul, Latin keyboard variants, and multi-term AND behavior aligned.
- Calendar helpers should merge only nonblank override values so common school schedule fields survive sparse grade entries.
- Self-study helpers support both `selfStudyDays` and legacy `dayNSelfStudy` fields.

## Anti-Patterns
- Do not add page-specific DOM or state dependencies here.
- Do not replace Korean search normalization with plain lowercase matching.
- Do not make `fetchJson` silently ignore HTTP errors; checked behavior belongs in `fetchJsonChecked` / `ensureOk`.
- Do not make calendar normalization drop unknown payload fields unless every caller is updated.

## Verification
- For `api.js`, check at least one admin/all caller that exercises the helper path you touched.
- For `search.js`, verify a Korean initial search and a Latin keyboard-layout search.
- For calendar/self-study changes, verify both admin today rows and all-students table consumers when applicable.
