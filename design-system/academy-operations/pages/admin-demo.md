# Admin Demo Page Override

Scope: `/demo/rh3123` only. This page is the first visual experiment and does not authorize production `/admin` styling changes.

- Preserve the production page's exact element order, position, width, height, spacing, display mode, and breakpoint behavior.
- Do not introduce or override `display`, `position`, grid/flex placement, dimensions, padding, margin, gap, overflow, typography metrics, transforms, or border widths.
- Restyle buttons through fill, text color, border color, radius, shadow, and stable hover/active/focus states only.
- Restyle surfaces, tables, forms, switches, and modals through paint and elevation only.
- Use `/demo/rh3123?design=off` as the unchanged visual baseline for automated coordinate comparison; it is QA-only and no-store.
- Preserve every existing DOM id, data attribute, form control, endpoint, and JavaScript module contract.
- Use the existing synthetic demo API and session storage. No live API request may be introduced by the design layer.
