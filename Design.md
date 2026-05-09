# Design System Baseline (Admin)

## 1) Goal
- Keep the current product structure (plain HTML/CSS/JS) and improve visual consistency/readability.
- Use reference designs only for style language (tokens + layout rhythm), not full copy/paste UI blocks.
- Prioritize Korean readability in dense admin screens (table + calendar + controls).

## 2) Recommended Reference Set
Use these in `Style Extractor` in this order:

1. Tabler (base dashboard rhythm)
- https://preview.tabler.io/
- https://tabler.io/

2. Kiaalap (education domain patterns)
- https://github.com/puikinsh/kiaalap

3. CoreUI (high-density admin table/chart patterns)
- https://coreui.io/product/free-bootstrap-admin-template/
- https://coreui.io/product/free-bootstrap-dashboard-with-charts/

Optional scan:
- https://adminlte.io/themes/v4/index.html
- https://tailadmin.com/

## 3) Style Extractor Prompt (Copy/Paste)
Use this prompt per reference and merge results:

```text
Extract style tokens and component-level visual rules from this page for an education admin dashboard.
Output JSON with keys:
- color: {bg, surface, surfaceAlt, border, text, textMuted, primary, primarySoft, success, warning, danger}
- typography: {fontFamily, titleSize, bodySize, captionSize, lineHeightBody, lineHeightDense, weightRegular, weightMedium, weightBold}
- radius: {sm, md, lg, xl, pill}
- shadow: {soft, card, floating}
- spacing: {2,4,6,8,10,12,14,16,20,24,28,32}
- component: {topbar, card, button, input, table, badge, tabs, calendarEvent}
Also add:
- readability rules for Korean text in dense tables/calendars.
- avoid rules (what not to copy because it hurts legibility).
```

## 4) Canonical Token Set (Merged Baseline)
This is the recommended base token set for this project after merging references.

### Light
```css
:root {
  --ds-bg: #f3f6fb;
  --ds-surface: #ffffff;
  --ds-surface-2: #f8fbff;
  --ds-border: #d7e2f0;
  --ds-border-strong: #c2d3e8;
  --ds-text: #1f2f45;
  --ds-text-muted: #637b9b;

  --ds-primary: #2f77ec;
  --ds-primary-soft: #deebff;
  --ds-success: #1cad73;
  --ds-warning: #d49a1f;
  --ds-danger: #d84d52;

  --ds-radius-sm: 8px;
  --ds-radius-md: 12px;
  --ds-radius-lg: 16px;
  --ds-radius-xl: 22px;
  --ds-radius-pill: 999px;

  --ds-shadow-soft: 0 6px 16px rgba(17, 34, 58, 0.08);
  --ds-shadow-card: 0 10px 26px rgba(17, 34, 58, 0.12);

  --ds-space-4: 4px;
  --ds-space-8: 8px;
  --ds-space-12: 12px;
  --ds-space-16: 16px;
  --ds-space-20: 20px;
  --ds-space-24: 24px;
}
```

### Dark
```css
body.dark {
  --ds-bg: #0d1728;
  --ds-surface: #13253d;
  --ds-surface-2: #19314e;
  --ds-border: #2c4a6d;
  --ds-border-strong: #39608c;
  --ds-text: #e5efff;
  --ds-text-muted: #9ebbe0;

  --ds-primary: #6fb0ff;
  --ds-primary-soft: rgba(111, 176, 255, 0.20);
  --ds-success: #44d19c;
  --ds-warning: #f1c05d;
  --ds-danger: #ff8d95;

  --ds-shadow-soft: 0 8px 20px rgba(0, 0, 0, 0.24);
  --ds-shadow-card: 0 14px 30px rgba(0, 0, 0, 0.30);
}
```

## 5) Component Rules (Use Across Pages)

### Topbar
- Height: 56~64px visual weight.
- Title: 22~28px, `700`.
- Subtitle/help text: 12~13px, muted color.
- Keep action controls grouped with min 8px gaps.

### Card
- Surface uses `--ds-surface`.
- Border: `1px solid --ds-border`.
- Radius: `--ds-radius-lg` or `--ds-radius-xl` for major panels.
- Padding: 14~20px (not below 12px on desktop).

### Button/Input/Select
- Control height: 36~40px.
- Border radius: 8~10px.
- Focus ring should be visible in both themes.
- Primary CTA should only use one strong accent tone per screen.

### Table (Important)
- Header font: 12~13px medium/bold.
- Body font: 13~14px.
- Row height: 36~42px.
- Zebra/hover should be subtle; do not over-saturate rows.
- Keep numeric columns right-aligned.

### Calendar Event Chips (Important)
- Minimum readable text: 12px (avoid 10~11px).
- Max one-line chip if dense; abbreviate as `학교 학년 과목` format.
- Priority order in same date cell:
  1. 수학 시험일
  2. 기타 시험/행사
- Limit visual variants to 2~3 colors per month view.

### Badge/Pill
- Rounded pill with 11~12px text.
- Use muted backgrounds for count/meta; avoid pure saturated backgrounds.

## 6) Korean Readability Rules (Do / Don't)

Do:
- Use `Noto Sans KR` + fallback stack.
- Keep body line-height >= `1.45`.
- Keep dense lists/tables at 13px minimum.
- Prefer concise labels (`학년`, `수학`, `중간`, `기말`).

Don't:
- Don't use extra-tight letter-spacing for Korean.
- Don't stack more than 3 visual emphases in one row (color + bold + badge).
- Don't use too many event colors in monthly calendar.

## 7) Mapping to Current Files
- Global admin token anchor: `static/css/admin.css` (`body.admin` and `body.admin.dark` vars)
- Legacy/lightweight screens: `static/css/style.css` (`:root`, `body.dark` vars)
- Calendar behavior/labels: `static/js/admin/features/calendar.js`
- Test management dense UI: `static/tests.html`, `static/js/tests.js`

## 8) Rollout Plan (Safe)
1. Token alignment only
- Map existing vars to `--ds-*` equivalents (no layout changes).

2. Dense readability pass
- Table font-size/row-height/cell padding normalization.
- Calendar event chip font and ordering cleanup.

3. Component consistency pass
- Buttons/inputs/cards radius + border + focus style unify.

4. Final polish
- One accent per page, muted secondaries, reduced visual noise.

## 9) Acceptance Checklist
- [ ] Korean text readable at 100% zoom on 1366px width.
- [ ] Table rows are scan-friendly and not cramped.
- [ ] Calendar events readable without color overload.
- [ ] Light/dark themes keep contrast and focus visibility.
- [ ] No page-specific one-off styles that break token consistency.
