# Server Student UI Design System

This document captures the existing student-page modal design system so future OCR UI work stays consistent. It is intentionally narrow: the current contract covers the student test submit modal, hidden `?ocr=1` OCR review flow, submit result panel, and answer-preview modal.

## 1. Atmosphere & Identity

The student modal should feel like a calm study utility: compact, direct, and low-friction. The signature is a quiet blue-accented worksheet workflow, where uncertain OCR results are handled through clear cards and large confirmation controls rather than dense free-form typing. The UI should read as operational and trustworthy, not decorative or marketing-like.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|---|---|---:|---:|---|
| Surface/modal | `--ts-card-bg` | `#ffffff` | `#0f172a` | Modal cards, OCR notice, result surfaces |
| Text/primary | `--ts-card-fg` | `#0f172a` | `#e5e7eb` | Headings, body, entered answers |
| Border/default | `--ts-border` | `#e5e7eb` | `#334155` | Inputs, cards, table borders |
| Text/muted | `--ts-muted` | `#6b7280` | `#94a3b8` | Help copy, metadata, status text |
| Field/surface | `--ts-field-bg` | `#ffffff` | `#0b1220` | Textareas, selects, compact cards |
| Focus | `--ts-focus` | `#2563eb` | `#60a5fa` | Focus ring and input focus border |
| Accent/primary | `--ts-primary` | `#2563eb` | `#2563eb` | Primary buttons, selected choices, answer links |
| Accent/on-primary | `--ts-primary-fg` | `#ffffff` | `#ffffff` | Text on primary buttons |
| Warning/text | `--ts-warning` | `#b45309` | `#f59e0b` | OCR warnings and manual-check notices |
| Warning/surface | `--ts-warning-bg` | `#fff7ed` | `#2a1d0b` | Warning cards |
| Overlay | `--ts-backdrop` | `rgba(0,0,0,.45)` | `rgba(0,0,0,.55)` | Modal backdrops |
| Status/error | literal | `#dc2626` | `#dc2626` | OCR status error text |
| Status/success | literal | `#059669` | `#059669` | OCR status success text |

### Rules

- Use blue only for actions, focus, selected choices, and informational OCR/result accents.
- Use warning amber only when the student must inspect or manually confirm an answer.
- Do not add new raw colors in the modal/OCR surface. Add a token here first.
- `color-mix()` may derive subtle blue or warning surfaces from these tokens.

## 3. Typography

### Font Stack

- Primary page font: `IBM Plex Sans KR`, then system sans-serif fallback.
- Display/accent font available from the page: `Sora`.
- Numeric answer values should use the inherited modal font with heavy weight. If tabular alignment becomes necessary, add a numeric/mono rule here first.

### Scale

| Level | Size | Weight | Line Height | Usage |
|---|---:|---:|---:|---|
| Modal title | `18px` | `800` | normal | Test submit modal heading |
| Result title | `21px` | `900` | `1.22` | Result panel title |
| Result rate | `42px` | `900` | `.95` | Large score/rate number |
| Result metric | `21px` | `900` | `1.12` | Correct/wrong/total metric values |
| Section/row label | `17px` | `900` | normal | Wrong-answer comparison title |
| Body/value | `15px` to `17px` | `900` for answers | `1.2` to normal | Result comparison labels and answer chips |
| OCR card title | `16px` | `900` | `1.25` | Per-question review card title |
| Help/status | `12px` to `14px` | `400` to `800` | `1.45` to `1.5` where multiline | Help, status, badges, warning copy |

### Rules

- Keep OCR instructional text short and sentence-case Korean.
- Avoid exclamation marks in success or error messages.
- Preserve CJK readability: do not narrow containers or buttons so much that Korean particles or endings orphan onto their own line.

## 4. Spacing & Layout

### Base Unit

All modal spacing should stay on the existing 4px rhythm.

| Token | Value | Current usage |
|---|---:|---|
| `--space-1` | `4px` | Small summary/list margin |
| `--space-2` | `8px` | Default compact gap, notice padding top/bottom |
| `--space-3` | `12px` | Button horizontal padding, preview header gap |
| `--space-4` | `16px` | Standard nearby spacing, mobile-safe text breathing |
| `--space-5` | `20px` | Reserved for larger future modal spacing |
| `--space-6` | `24px` | Reserved for broader student page panels |

### Layout

- Submit modal width: `480px`, max `92vw`.
- Submit modal max height: `80vh`, `88vh` on narrow screens.
- Preview modal: `min(1100px, 96vw)` by `min(760px, 90vh)`.
- OCR review panel: grid with `12px` gaps.
- Choice grids: exactly five equal buttons for `choice_number`.
- Mobile breakpoint: `520px`; stack result head and metrics at this width.

### Rules

- Keep answer confirmation controls stable in size. Buttons, labels, warnings, and dynamic status copy must not resize the grid enough to shift the workflow.
- The first line in `#tsAnswersText` is question 1. Any UI that fills the textarea must preserve exactly 20 non-empty newline-separated lines.

## 5. Components

### Test submit modal

- **Structure**: fixed backdrop, centered `.ts-card`, header, test selectors, answer textarea, OCR entry, memo, result panel, actions.
- **Variants**: normal, OCR-enabled with `?ocr=1`, dark mode via `body.dark`.
- **Spacing**: `14px` card padding, `10px` grid gap, `8px` compact row gap.
- **States**: open, closed, OCR eligible, OCR ineligible, result rendered.
- **Accessibility**: keep close and submit controls as real buttons; preserve `aria-live` status for OCR.
- **Motion**: none required. Do not add decorative animation.

### OCR entry

- **Structure**: `.ts-ocr-entry`, `.ts-ocr-notice`, file input, helper copy, `답안 사진 넣기` button, `#tsOcrStatus`, review panel.
- **Variants**: ready, image selected, loading/progress, success, error, disabled/ineligible.
- **States**:
  - Ready copy: `답안지 사진을 선택한 뒤 답안 사진 넣기 버튼을 눌러주세요.`
  - No-image error: `답안지 사진을 먼저 선택해주세요.`
  - Progress stages: photo correction, answer-box extraction, recognition preparation, cache/live recognition check, review screen preparation.
  - Error status uses `data-state="error"`.
  - Success status uses `data-state="ok"`.
- **Accessibility**: status remains `aria-live="polite"`; route errors must not use alert-only feedback.
- **Motion**: route progress is text-based, not spinner-based.

### OCR review card

- **Structure**: question title, mode pill, recognized value, warning/prefill note, candidate buttons or five-choice grid, input/keypad, confirm/reset actions.
- **Variants**: `choice_number`, `answer_value`, warning-required, candidate-required, unresolved.
- **States**: default, selected choice, typed answer, confirmed, validation error.
- **Sizing**: card padding `12px`, internal gap `12px`, choice buttons `48px` minimum height, confirm buttons `40px` minimum height, current-answer input `42px` minimum height.
- **Accessibility**: choice controls use visible button states; focus ring must remain visible.
- **Rules**: only confirmation-needed questions appear as cards. Auto-recognized items stay in collapsed summary/details.

### OCR summary and apply action

- **Structure**: status count pills, safe-auto-grade details, apply button.
- **States**: fillable, blocked by review-required item, blocked by retake/data-check item, success.
- **Rules**: never auto-click submit. Filling answers is separate from final submission.

### Submit result panel

- **Structure**: result heading, score/rate, metric cards, wrong-answer comparison cards, answer-preview actions.
- **Variants**: no wrong answers, wrong-answer table, answer-link available, answer-link restricted.
- **States**: hidden, rendered, preview modal open.
- **Sizing**: wrong-answer comparison cards use `12px` padding and `10px` gaps; answer chips use `44px` minimum height and `17px` heavy text.
- **Rules**: wrong-answer comparison should show question number, student's answer, and correct answer clearly at readable size. On mobile, prefer card rows over compact tables so answer values remain large and tappable.

### Answer preview modal

- **Structure**: fixed backdrop, preview card, header, iframe, loading/status layer, close button, external link.
- **States**: closed, open/loading, open/loaded.
- **Rules**: iframe must not expose local filesystem paths. Google Drive file links use `/preview` inside the iframe, while the external link keeps the original Drive URL. Keep external Drive links as links, not embedded secrets.
- **Loading state**: show a calm centered status message while the Drive preview iframe initializes, then hide it on iframe `load`. If Drive remains slow, the external-link action stays available.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|---|---:|---|---|
| Micro | `100ms` to `150ms` | `ease-out` | Future button press feedback only |
| Standard | `200ms` to `300ms` | `ease-in-out` | Future modal state polish only |

### Rules

- Current modal intentionally uses minimal motion.
- Do not animate layout properties.
- Do not add motion unless it communicates loading, selection, confirmation, or disabled state.
- Respect reduced-motion if future transitions are added.

## 7. Depth & Surface

### Strategy

Depth strategy: mixed, but restrained.

- Modal depth: border plus shadow.
- Inner OCR/result cards: borders and tonal shifts, not heavy shadows.
- Status and warning surfaces: token-based tonal backgrounds.
- Choice buttons: border-first, filled primary only when selected.

### Elevation

| Level | Value | Usage |
|---|---|---|
| Modal | `0 12px 32px rgba(0,0,0,.35)` | Test submit modal |
| Preview modal | `0 20px 48px rgba(0,0,0,.4)` | Full answer preview |
| Inner panels | border plus `color-mix()` tonal surface | OCR entry and result panel |

### Rules

- Do not nest card-like frames inside multiple additional card shells unless the frame represents a real workflow boundary.
- Keep OCR warning surfaces visually stronger than neutral help text, but weaker than final submit actions.
- Any new surface style used more than once must be documented here before code changes.
