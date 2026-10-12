# Academy Operations Design System

Status: experimental, validated first on `/demo/rh3123` only.

The geometry and typography lock below applies to the `admin-design-test.css` palette layer, not every experiment loaded by the demo. The separate thread preview changes demo-only avatar DOM, spacing, and type; its historical evidence is in `design-qa.md`. Neither document authorizes production changes. `?design=off` disables only the palette layer, not the thread preview.

## Direction

The visual language is an ink-and-mineral operations surface: calm warm neutrals, mineral teal actions, and restrained semantic accents. It improves hierarchy through paint and state feedback while keeping the established product geometry untouched.

## Principles

1. Status before decoration. Counts, progress, date, and exceptions receive the strongest hierarchy.
2. Geometry is a contract. Existing position, size, spacing, display, and responsive behavior are inherited without override.
3. One visual language. Surfaces, controls, tables, and modals share the same tokens and state rules.
4. Meaning survives color. State text, labels, and focus indicators accompany semantic colors.
5. Stable feedback. Hover, active, focus, and disabled states use color, border, and shadow without motion or layout shift.

## Foundation Tokens

### Color — light

| Token | Value | Role |
|---|---|---|
| `--ops-canvas` | `#f6f5f1` | App background |
| `--ops-surface` | `#fffefa` | Primary surface |
| `--ops-surface-subtle` | `#f2f5f3` | Secondary surface |
| `--ops-ink` | `#18272b` | Primary text |
| `--ops-muted` | `#5c6d71` | Secondary text |
| `--ops-line` | `#d7dfdc` | Boundary and divider |
| `--ops-primary` | `#155f5a` | Primary action and focus |
| `--ops-success` | `#1a7654` | Completed/online |
| `--ops-warning` | `#9a5a13` | Needs attention |
| `--ops-danger` | `#b83a42` | Destructive/absence |

### Color — dark

| Token | Value | Role |
|---|---|---|
| `--ops-canvas` | `#101719` | App background |
| `--ops-surface` | `#182326` | Primary surface |
| `--ops-surface-subtle` | `#1d2d30` | Secondary surface |
| `--ops-ink` | `#edf5f3` | Primary text |
| `--ops-muted` | `#a9bbb8` | Secondary text |
| `--ops-line` | `#354a4c` | Boundary and divider |
| `--ops-primary` | `#78c9c0` | Primary action and focus |
| `--ops-success` | `#72d3a7` | Completed/online |
| `--ops-warning` | `#efbd78` | Needs attention |
| `--ops-danger` | `#ff9299` | Destructive/absence |

### Typography

- Inherit the production font family, size, line height, letter spacing, weight, and numeral metrics unchanged.
- Visual experiments may change text color only; typography metrics remain layout-owned.

### Shape and elevation

- Radius: 10px control, 14px card, 20px shell/feature surface, pill only for status.
- Elevation 1: `0 1px 2px rgba(15, 23, 42, .06)`.
- Elevation 2: `0 12px 30px rgba(15, 23, 42, .10)`.
- Existing spacing and box dimensions are immutable. Radius, border color, and shadow may change because they do not participate in layout.

### Motion and focus

- Fast feedback: 120ms for color, border, and shadow only.
- Never use transform, border-width, font-weight, or any other state change that can move content or alter bounds.
- Every interactive control has a 3px `:focus-visible` ring with a 2px surface offset.
- Under `prefers-reduced-motion: reduce`, remove non-essential transitions and transforms.

## Responsive Rules

- Inherit every production breakpoint and responsive placement exactly.
- The visual layer contains no media-query layout overrides.
- Baseline and redesigned pages must report identical `x`, `y`, `width`, and `height` for the same elements at the same viewport.

## Component Contracts

- Primary action: solid primary fill; one dominant action per group.
- Destructive action: danger fill and explicit text label; never color alone.
- Secondary action: surface fill, visible border, high-contrast text.
- Status: dot or icon plus text. Online green is not presented as a standalone color cue.
- KPI card: preserve its original structure and dimensions; distinguish state through accent color and surface treatment.
- Table: preserve the original header, cell, and scroll geometry; change only row/header paint and focus feedback.
- Modal: preserve the original panel geometry; change only scrim, surface, border color, and shadow.
