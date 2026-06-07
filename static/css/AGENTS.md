# CSS KNOWLEDGE BASE

## Overview
Shared stylesheets live here. `admin.css`, `student.css`, and `style.css` are broad cascade surfaces that can affect multiple pages from one selector.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Admin layout/theme | `admin.css` | Largest stylesheet; admin shell, tables, modals, chat panel, dark mode, responsive rules. |
| Student page styling | `student.css` | Student shell, announcement modals, test cards, mobile layout, Korean font fallbacks. |
| Legacy/shared page styling | `style.css` | All-students, tests, file manager, shared tables, tooltip, utility pages. |
| Small shared base | `main.css` | Root tokens and base form/table styling for simpler pages. |

## Conventions
- Scope selectors to the page body class or stable shell id whenever possible: `body.admin`, `body.student-page`, `body.all-page`, or a known wrapper.
- Preserve Korean-readable font stacks: include `Apple SD Gothic Neo`, `Noto Sans KR`, or `Malgun Gothic` where page text can contain Korean.
- Check both light and dark theme variables when changing colors.
- Keep modal, tooltip, floating panel, and toast z-index changes coordinated with existing modal layers.
- For table layout changes, verify admin today/done tables, all-students roster, and test-management tables separately.
- Add responsive rules near the related component block unless the file already has a dedicated page-level media section.

## Anti-Patterns
- Do not add unscoped global selectors in `admin.css` or `style.css` unless every affected page is intentional.
- Do not remove body-page classes or wrapper selectors from existing rules; they are blast-radius controls.
- Do not solve one modal overlap by raising z-index blindly above the admin chat and modal backdrop layers.
- Do not replace Korean-capable font stacks with Latin-only system stacks.
- Do not hand-edit generated screenshots or QA artifacts into this directory.
