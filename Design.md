# Server Student UI Design System

This document mixes current UI contracts with a retired student test-submit/OCR design reference. The test submit modal, hidden `?ocr=1` flow, OCR routes, and submit result are not current product surfaces and must not be restored without a new feature decision. The admin components, answer-link preview rules, and student previous-video review section remain active where current code uses them.

## 1. Atmosphere & Identity

The student modal should feel like a calm study utility: compact, direct, and low-friction. The signature is a cool neutral surface with one clear blue action color, where uncertain OCR results are handled through clear cards and large confirmation controls rather than dense free-form typing. The UI should read as operational and trustworthy, not decorative or marketing-like.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|---|---|---:|---:|---|
| Surface/modal | `--ts-card-bg` | `#fff` | `#0f172a` | Modal cards and result surfaces |
| Text/primary | `--ts-card-fg` | `#191f28` | `#e5e7eb` | Headings, body, entered answers |
| Border/default | `--ts-border` | `#e5e8eb` | `#334155` | Inputs, cards, table borders |
| Text/muted | `--ts-muted` | `#8b95a1` | `#94a3b8` | Help copy, metadata, status text |
| Field/surface | `--ts-field-bg` | `#ffffff` | `#0b1220` | Textareas, selects, compact cards |
| Focus | `--ts-focus` | `#3182f6` | `#60a5fa` | Focus ring and input focus border |
| Accent/primary | `--ts-primary` | `#3182f6` | `#60a5fa` | Primary buttons, selected choices, answer links |
| Accent/on-primary | `--ts-primary-fg` | `#ffffff` | `#ffffff` | Text on primary buttons |
| OCR tint | `--ts-ocr-tint` | `#f7f8fa` | `#14232c` | Review navigation and photo-selection surfaces |
| OCR rule | `--ts-ocr-rule` | `#e5e8eb` | `#30515d` | Review section dividers and candidate outlines |
| Warning/text | `--ts-warning` | `#e66b00` | `#f59e0b` | OCR warnings and manual-check notices |
| Warning/surface | `--ts-warning-bg` | `#fff7ed` | `#2a1d0b` | Warning cards |
| Overlay | `--ts-backdrop` | `rgba(25,31,40,.48)` | `rgba(0,0,0,.55)` | Modal backdrops |
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

- **Structure**: `.ts-ocr-entry`, `.ts-ocr-file-control`, photo label and selected filename, `사진 선택`/`다른 사진 선택` button, visually hidden file input, `사진 인식 결과 확인` button, `#tsOcrStatus`, review panel.
- **Surface**: a restrained worksheet divider rather than a nested blue card. Use the OCR tint only for the navigator and photo-selection row.
- **Variants**: ready, image selected, loading/progress, success, error, disabled/ineligible.
- **States**:
  - Ready copy: `사진을 선택해 주세요.`
  - Selected copy: original filename with a `다른 사진 선택` action.
  - No-image error: `답안지 사진을 먼저 선택해주세요.`
  - Progress stages: photo correction, answer-box extraction, recognition preparation, cache/live recognition check, review screen preparation.
  - Error status uses `data-state="error"`.
  - Success status uses `data-state="ok"`.
- **Accessibility**: the visible photo-selection button opens the native file picker; the filename and status remain `aria-live="polite"`; route errors must not use alert-only feedback.
- **Motion**: route progress is text-based, not spinner-based.

### OCR review card

- **Structure**: question title, compact mode label, candidate buttons or five-choice grid, input/keypad, and confirm action.
- **Variants**: `choice_number`, `answer_value`, warning-required, candidate-required, unresolved.
- **States**: default, selected choice, typed answer, confirmed, validation error.
- **Sizing**: card padding `12px`, internal gap `12px`, choice buttons `48px` minimum height, confirm buttons `40px` minimum height, current-answer input `42px` minimum height.
- **Accessibility**: choice controls use visible button states; focus ring must remain visible.
- **Rules**: use square-cornered controls and divider-led groups, not stacked tinted cards or status pills. Candidate suggestions appear only as a selected choice or input value; the confirm action occupies its own full row. Only confirmation-needed questions appear as cards. Auto-recognized items stay in collapsed summary/details.

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

### Admin record popup reuse

- **Structure**: the all-students row action uses the same unified launcher as the admin board, opening the fixed student tooltip, counseling/log card, video-assignment card, and test-assignment card together; no parallel popup skin or screenshot substitute is allowed.
- **Visual parity**: while the unified popup is open on the all-students page, suspend the roster stylesheet and use the administrator page's `main.css` → `admin.css` → `student-work-light.css` stack and `body.admin` scope. Restore the roster stylesheet and `body.all-page` immediately after every popup closes; no separate popup skin is introduced at initial page load.
- **All-students state**: class-log notes, homework, and video/test assignments are read-only. Video save permits only right-click skip changes. The separate assistant-note thread supports list/create, but existing-note edit/delete/pin actions are locked; hidden log-save controls must not be described as active primary actions.
- **Progress state**: left click and left drag do not mutate cells; right click retains the admin `skip` behavior and only changed progress values may be saved.
- **Compact and tablet screens**: at `900px` and below, a fixed four-tab switcher (`영상`, `조교 메모`, `숙제·정보`, `테스트`) keeps every unified surface reachable one at a time; the active card fills the usable viewport, Korean labels stay intact, and no card may be stranded off-screen.

### All-students roster table

- **Linked books**: the former editable sub-book inputs are replaced by quiet border-first labels sourced from the latest registered homework books.
- **Row action**: the counseling button remains a compact table action. It loads the reused admin popup modules on first activation, shows a short `로딩…` state during that one-time load, then opens the unified record popup.
- **Responsive**: below `900px`, preserve the roster's readable `1120px` table canvas and give `#allWrap` horizontal scroll ownership. Never squeeze every column into the device width or break Korean labels one syllable per line.

### Admin video auto-assignment count buttons

- **Structure**: the video assignment popup preserves the original compact pill controls, using six real buttons labeled `1개` through `6개`, plus a live text summary of the configured count.
- **States**: default count, focused, selected, saved, save error, and consecutive-class preview.
- **Consecutive-class copy**: when the selected date has adjacent regular slots such as `금1` and `금2`, the summary shows both the configured count and the effective automatic count.
- **Consecutive-class rule**: the effective count is `configured × 2`, so `2` becomes `4`, `3` becomes `6`, and `6` becomes `12`.
- **Accessibility**: keep every count choice as a labeled native button and expose the selected state with `aria-pressed`.
- **Surface**: preserve the original `30px`-high fully rounded pill shape, white idle state, and blue selected state; do not replace it with square segmented buttons, another card, or decorative animation.

### Assistant student memo author state

- **Metadata**: author and dates are structured student-scoped fields, not an automatically inserted `M.D [작성자]` text prefix. Meaning and sort priority are owned by canonical §12.
- **Persisted appearance**: light-theme body text is dark neutral; each note retains its own author's rail/dot/tag colors. Pin emphasis uses that author's top-to-bottom tint, not a shared orange fill.
- **Selection state**: author buttons remain real buttons with `aria-pressed`. Choosing a draft author changes the composer border/focus color without recoloring saved notes or adding text.
- **Layout**: author/pin and reminder status/dates share the header, compact edit/delete actions align right, and the body starts on the next row with wrapping before the date/action column. No completion control is added.

### Admin operation memo panel

- **Structure**: one server-backed list, one compact text input, a `등록` action, and a per-row `제거` action.
- **Desktop layout**: occupy only the existing empty third column of the five-column admin hero grid. The hero summary, metric cards, quick actions, announcement composer, and reply dock keep their existing track sizes.
- **Responsive layout**: below the wide command-board breakpoint, span the available hero width as an independent row. Hide the panel in `admin-simple` mode so it cannot collide with the compact metric and action tracks.
- **Surface**: reuse the admin page's `--card`, `--line`, `--ink`, `--ink-soft`, `--brand`, and `--danger` tokens. Do not introduce a second memo color system.
- **Component tokens**: keep memo dimensions centralized on `.admin-operation-notes`. `--admin-note-panel-*`, `--admin-note-head-*`, `--admin-note-row-*`, and `--admin-note-list-*` control layout rhythm; `--admin-note-control-*`, `--admin-note-input-*`, `--admin-note-submit-*`, and `--admin-note-focus-*` control inputs/actions; `--admin-note-*-size` and `--admin-note-*-weight` define the local type scale; `--admin-note-motion-duration` limits interaction feedback; `--admin-note-responsive-height` keeps the stacked panel at 250px. Descendants consume these variables instead of redefining the same dimensions.
- **Typography**: the administrator memo uses a deliberate 130% local type scale without changing the panel or neighboring dashboard tracks: title `23.4px`, body `16.9px`, secondary/input `15.6px`, metadata/actions `14.3px`, and status caption `13px`.
- **Row marker**: populated rows use a `12px` hollow brand ring with a `2px` stroke in an explicit in-row grid column. Do not use an outside list marker inside the scrolling list because the overflow boundary can clip its leading edge.
- **States**: loading, empty, populated, saving, deleting, success, and inline error. List content scrolls inside the panel; the page controls never resize when notes are added.
- **Accessibility**: keep create/delete actions as native buttons, render note text with `textContent`, retain visible focus rings, and announce async status through `role="status"`. Korean note copy uses keep-all, pretty wrapping with an anywhere fallback for long unbroken text so a short final word is not orphaned.
- **Motion**: button press feedback only. Do not animate list layout.

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
- Inner OCR review areas: separators and quiet paper contrast, not heavy shadows or stacked tinted cards.
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

## 8. Student previous-video review

The previous-video review surface is a deliberately opened study utility within the existing playlist card footer, directly after today's video list. It reuses the existing player and page language; it does not introduce a modal, second player, auto-open, auto-play, or a new visual hierarchy.

### Component contract

- **Disclosure**: `.previous-videos` contains a native `영상 복습` button with a count. It controls one hidden panel, starts disabled when no fresh server-authorized rows exist, and exposes `aria-expanded`/`aria-controls`.
- **Chooser/list**: `.previous-videos-panel` contains a native `영상 등록` button and `.previous-videos-list`. Every eligible `reviewVideosCache` row is a semantic label containing exactly one native checkbox followed by one visible title node, `${chapter}. ${title}`. The chooser keeps the server order and title-only copy; `reviewStatus` never renders as status/meta text.
- **Authorization state**: `reviewStatus: "done"` remains internal server-authorized membership metadata. `interrupted` is not eligible. The status must not create a visible badge, `완료` row copy, or `차시 N` metadata.
- **Registered state**: registered rows remain checked and can be unchecked to remove the local selection; `등록됨` is an accessible label, not a permanent disabled state. Registration never rewrites the fresh server review set.
- **Local registration**: the browser stores only an ordered, deduped SID/date-scoped MID list and intersects it with current server review membership on load. A newly registered selection triggers one page reload as approved in canonical §9; it does not write server assignments, logs, counseling history, progress, or watch. Do not describe the reload as network-free.
- **Playlist**: registered review items append after today's assignment rows, deduped by MID. Registration does not directly auto-play; the existing delegated playlist handler owns playback. A page reload may reinitialize the existing player, so current-player identity is not an invariant of registration.
- **Restrictions**: regular and self-study students share the chooser and registration flow. Course-blocked, absent, archived, ghost, malformed, empty, and outside-academy states expose no actionable registration or unauthorized playlist row; disabled metadata remains title-only where the existing access contract permits it.
- **Motion/responsive**: chooser opening, row/title clicks, selection, and registration use no layout animation or direct playback; playback remains owned by the existing playlist rows. Keep 44px minimum targets, visible `:focus-visible` rings, light/dark tokens, and readable Korean wrapping at narrow, tablet, and desktop widths.

### Student-page review tokens

Rows use the existing student accent and card/line tokens; no status-color tokens are needed because `reviewStatus` is authorization metadata only and never renders in a row.

The review component consumes the narrowly scoped geometry/type tokens `--stu-review-gap`, `--stu-review-tight-gap`, `--stu-review-section-space`, `--stu-review-mobile-section-space`, `--stu-review-tap-min-height`, `--stu-review-control-pad-block`, `--stu-review-control-pad-inline`, `--stu-review-item-pad-block`, `--stu-review-item-pad-inline`, `--stu-review-title-size`, `--stu-review-summary-size`, `--stu-review-summary-weight`, `--stu-review-summary-line-height`, `--stu-review-copy-line-height`, `--stu-review-control-weight`, `--stu-review-focus-width`, `--stu-review-focus-offset`, and `--stu-review-mobile-control-pad-inline`. These tokens cover the compact chooser rows, checkbox/title gap, register action alignment, and focus treatment; no status/meta row geometry or status-color tokens are needed because rows remain title-only.
