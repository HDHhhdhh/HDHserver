# Admin Demo Page Override

Scope: `/demo/rh3123` only. This page is the first visual experiment and does not authorize production `/admin` styling changes.

The following geometry lock governs `admin-design-test.css` only. The separately loaded `threadPreview.js` / `demo-thread-preview.css` experiment changes demo-only memo DOM and spacing; see `design-qa.md`. It is present on both palette variants and is not a production baseline.

- Preserve the production page's exact element order, position, width, height, spacing, display mode, and breakpoint behavior.
- Do not introduce or override `display`, `position`, grid/flex placement, dimensions, padding, margin, gap, overflow, typography metrics, transforms, or border widths.
- Restyle buttons through fill, text color, border color, radius, shadow, and stable hover/active/focus states only.
- Restyle surfaces, tables, forms, switches, and modals through paint and elevation only.
- Use `/demo/rh3123?design=off` as the palette-off baseline for automated coordinate comparison; it is QA-only and no-store. This does not turn off the separate thread preview.
- Preserve every existing DOM id, data attribute, form control, endpoint, and JavaScript module contract.
- Use the existing synthetic demo API and session storage. No live API request may be introduced by the design layer.
