# CSS KNOWLEDGE BASE

## Overview
Shared stylesheets live here. `admin.css`, `student.css`, and `style.css` are broad cascade surfaces that can affect multiple pages from one selector.

## Where To Look
| Task | Location | Notes |
|---|---|---|
| Admin layout/theme | `admin.css` | Largest stylesheet; admin shell, tables, modals, chat panel, dark mode, responsive rules. |
| Class-log export modal | `admin-export-logs.css` | Admin-only export dialog scope; loaded after `admin.css` only by `admin.html`. |
| Admin CSS ownership | `../../docs/ADMIN_CSS_INVENTORY.md` | Canonical consumer map, applied export split, and unresolved domain decision queue. |
| Test management | `tests.css` | Test-only catalog/editor/statistics/modal cascade; loaded after `main.css` and `admin.css` by `tests.html`. |
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
- Before moving a domain out of `admin.css`, update the canonical inventory only when its consumer or ownership evidence changes; do not restate that map in another guide.
- Keep `tests.css` selectors under `body.admin.tests-page`; preserve its current declaration and breakpoint order when moving rules because it intentionally overrides shared admin styles.

## Anti-Patterns
- Do not add unscoped global selectors in `admin.css` or `style.css` unless every affected page is intentional.
- Do not remove body-page classes or wrapper selectors from existing rules; they are blast-radius controls.
- Do not solve one modal overlap by raising z-index blindly above the modal backdrop layers.
- Do not replace Korean-capable font stacks with Latin-only system stacks.
- Do not hand-edit generated screenshots or QA artifacts into this directory.

## Verification
- Check every shell sharing the edited stylesheet; `admin.css` also affects the tests page.
- Run `node scripts/verify_admin_css_inventory.mjs`; it independently inventories the direct and dynamic consumers and preserves the extracted export-domain pre-split baseline.
- For `admin-export-logs.css`, keep the pre-split hash, `/admin`-only load order, existing export feature verifier, and two-browser computed-style comparison complementary.
- For `tests.css`, run `node scripts/verify_tests_stylesheet_extraction.mjs`, the existing mobile-touch and admin record-detail UI checks, then compare computed styles and modal interaction in the in-app Browser and Chrome.
- Verify light/dark themes, mobile breakpoints, modal stacking, and Korean fallback fonts where relevant.
- Use DOM/computed-style evidence before screenshots when diagnosing cascade or z-index changes.
