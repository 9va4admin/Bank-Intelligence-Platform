---
colors:
  bg: "#03061a"
  surface: "#060d2e"
  surface-raised: "#0b1554"
  border: "#ffffff14"
  text: "#e2e8f0"
  text-muted: "#94a3b8"
  text-faint: "#475569"
  accent: "#f5c842"
  accent-dim: "#c99a1a"
  confirm: "#1D9E75"
  info: "#378ADD"
  warn: "#f59e0b"
  error: "#ef4444"
  light-bg: "#fafaf8"
  light-surface: "#ffffff"
  light-border: "#e2e8f0"
  light-text: "#0f172a"
  light-text-muted: "#64748b"
typography:
  family-sans: "Inter, system-ui, sans-serif"
  family-mono: "JetBrains Mono, Fira Code, monospace"
  size-xs: "0.75rem"
  size-sm: "0.875rem"
  size-base: "1rem"
  size-lg: "1.125rem"
  size-xl: "1.25rem"
  size-2xl: "1.5rem"
  weight-normal: "400"
  weight-medium: "500"
  weight-semibold: "600"
  weight-bold: "700"
  leading-tight: "1.25"
  leading-normal: "1.5"
  leading-relaxed: "1.625"
rounded:
  sm: "0.25rem"
  md: "0.375rem"
  lg: "0.5rem"
  xl: "0.75rem"
  2xl: "1rem"
  full: "9999px"
spacing:
  1: "0.25rem"
  2: "0.5rem"
  3: "0.75rem"
  4: "1rem"
  5: "1.25rem"
  6: "1.5rem"
  8: "2rem"
  10: "2.5rem"
  12: "3rem"
  16: "4rem"
components:
  button-primary-bg: "#f5c842"
  button-primary-text: "#03061a"
  button-secondary-bg: "#ffffff14"
  button-secondary-text: "#e2e8f0"
  button-danger-bg: "#ef4444"
  button-danger-text: "#ffffff"
  badge-critical-bg: "#7f1d1d"
  badge-critical-text: "#fca5a5"
  badge-warn-bg: "#451a03"
  badge-warn-text: "#fcd34d"
  badge-ok-bg: "#0a3828"
  badge-ok-text: "#5eead4"
  badge-info-bg: "#1e3a5f"
  badge-info-text: "#93c5fd"
---

# ASTRA Design System

## Overview

ASTRA is a banking-grade operations platform for Indian banks — CTS cheque clearing and ATM EJ intelligence. The design resolves one paradox: a system processing 500 cheques in parallel must feel completely in control.

**Creative North Star: The Precision Instrument.** Every surface is tuned, not decorated. The interface communicates authority through restraint — dense information arranged with purpose, color reserved for meaning, motion used only to convey state. An ops reviewer facing a 3-hour IET clock should feel calm confidence, not cognitive load.

**Register: Product.** Design serves the task. No flourishes. The tool disappears into the work.

**Theme strategy: Dark-native.** The primary surface is deep navy (`#03061a`) — chosen for dim ops rooms and extended sessions, not aesthetic fashion. Light theme is a first-class derivative for bright office environments, not an afterthought.

**Color commitment: Restrained.** One accent (gold) for primary actions and current selection only. Semantic colors carry operational meaning — red is risk, amber is warning, teal is confirmation. No decorative color. No gradients on text.

---

## Colors

### Dark theme (primary surface)

| Role | Token | Hex | Use |
|---|---|---|---|
| Canvas | `bg` | `#03061a` | Page background, sidebar base |
| Surface | `surface` | `#060d2e` | Cards, panels, modals |
| Raised | `surface-raised` | `#0b1554` | Dropdown menus, tooltips, popovers |
| Border | `border` | `rgba(255,255,255,0.08)` | All dividers and container edges |
| Row hover | — | `rgba(255,255,255,0.02)` | Table row, list item hover state |
| Text / Ink | `text` | `#e2e8f0` | Body copy, labels, data values |
| Text / Muted | `text-muted` | `#94a3b8` | Secondary labels, metadata, timestamps |
| Text / Faint | `text-faint` | `#475569` | Placeholder, disabled text |

### Light theme (derived surface)

| Role | Hex | Use |
|---|---|---|
| Canvas | `#fafaf8` | Page background |
| Surface | `#ffffff` | Cards, panels |
| Border | `#e2e8f0` | Dividers and edges |
| Text | `#0f172a` | Body copy |
| Text / Muted | `#64748b` | Secondary labels |

### Accent palette (semantic — not decorative)

| Name | Hex | Meaning | Never use for |
|---|---|---|---|
| Gold | `#f5c842` | Primary action, current selection, brand anchor | Decorative backgrounds, gradient text |
| Teal | `#1D9E75` | Confirm, success, cleared, approved | Risk indicators |
| Sky | `#378ADD` | Informational, links, neutral status | Warnings, errors |
| Amber | `#f59e0b` | Warning, elevated risk, pending human review | Confirmed states |
| Red | `#ef4444` | Error, critical risk, IET breach risk, fraud flag | Anything non-critical |
| Slate | `#94a3b8` | Neutral / inactive state | Active or hover states |

### Color rules

- Color carries meaning, never decoration. If the same visual would work in any color, it should be colorless.
- Red never appears in a "safe" context. Seeing red should always mean something is wrong or at risk.
- Gold (accent) appears on: primary buttons, active sidebar item, currently selected tab. Nowhere else in the dark theme.
- Every status color is paired with a label or icon — color is never the sole signal carrier (WCAG + colorblind safety).

---

## Typography

**One family: Inter.** Product UI does not need a display/body pairing. Inter carries headings, labels, buttons, data, and body equally well at this density level.

**Mono: JetBrains Mono.** Reserved for: cheque instrument IDs, workflow IDs, MICR strings, account number fragments, timestamps with seconds, code values. Not for decorative use.

### Type scale

| Step | Size | Weight | Line height | Use |
|---|---|---|---|---|
| Display | 1.5rem / 24px | 700 | 1.25 | Page titles (rare) |
| Heading | 1.125rem / 18px | 600 | 1.25 | Section headings, modal titles |
| Body | 0.875rem / 14px | 400 | 1.5 | Labels, descriptions, data rows |
| Small | 0.75rem / 12px | 500 | 1.25 | Badges, timestamps, meta labels |
| Mono | 0.8125rem / 13px | 400 | 1.5 | IDs, amounts, MICR data |

### Rules

- Scale ratio 1.125–1.2 between steps. The product carries many type elements simultaneously; exaggerated contrast creates noise.
- No fluid typography (`clamp()`). Ops workstations have consistent DPI; a fluid heading that resizes in a narrow panel looks wrong.
- Body prose (descriptions, instructions): cap at 65–75ch. Data and tables can run denser; 120ch+ is fine for wide tables.
- Uppercase tracking: used sparingly for column headers in dense tables only. Never as section eyebrows — that pattern is banned.
- `text-wrap: balance` on headings 2 lines or longer.

---

## Elevation

ASTRA uses **tonal layering** — no drop shadows in the primary dark theme. Elevation is communicated purely through background lightness:

| Level | Background | Use |
|---|---|---|
| 0 — Canvas | `#03061a` | Page base, sidebar background |
| 1 — Surface | `#060d2e` | Cards, content panels, table backgrounds |
| 2 — Raised | `#0b1554` | Dropdown menus, comboboxes, date pickers |
| 3 — Overlay | `rgba(0,0,0,0.7)` backdrop + `#060d2e` panel | Modals, side sheets |

**Border as separator:** `rgba(255,255,255,0.08)` — a single consistent edge weight. No side-stripe accents. No colored left borders on cards.

**Glassmorphism:** Available as a deliberate effect (`.glass`, `.glass-gold` utilities exist) for hero elements and the landing page only. Never on data tables, form controls, or operational UI where clarity is paramount.

**Light theme elevation:** Uses actual drop shadows sparingly — `0 1px 3px rgba(0,0,0,0.08)` for cards, `0 4px 16px rgba(0,0,0,0.12)` for modals. The light theme has no `.glass` — glass effects require a dark backdrop to read.

---

## Components

### Buttons

Three variants, one size system. Button shape is consistent across the entire product.

**Primary** — gold fill, dark text. One per view; this is the single commit action.
```
bg: #f5c842  |  text: #03061a  |  hover: #e8b830  |  border-radius: 6px
font: 0.875rem / 500 weight  |  padding: 6px 14px
```

**Secondary** — ghost with white/8 fill. Supporting actions, filters, non-destructive triggers.
```
bg: rgba(255,255,255,0.08)  |  text: #e2e8f0  |  hover: rgba(255,255,255,0.14)
border: 1px solid rgba(255,255,255,0.08)  |  same radius/font/padding as primary
```

**Destructive** — red fill. Irreversible actions (revoke, force-logout, terminate). Confirm step always required.
```
bg: #ef4444  |  text: #ffffff  |  hover: #dc2626
```

**Disabled state (all variants):** `opacity: 0.4; cursor: not-allowed` — do not change color.

**Loading state:** Replace label with a 16px spinner (white, 2px stroke). Never disable the button until the request resolves.

### Status badges

Pill shape (`border-radius: 9999px`), `0.75rem / 500 weight`, `4px 10px` padding.

| State | Background | Text |
|---|---|---|
| CRITICAL / BREACH | `rgba(127,29,29,0.8)` | `#fca5a5` |
| HIGH / FRAUD | `rgba(153,27,27,0.6)` | `#fca5a5` |
| WARNING / PENDING | `rgba(120,53,15,0.7)` | `#fcd34d` |
| OK / CLEARED | `rgba(10,56,40,0.8)` | `#5eead4` |
| INFO / PROCESSING | `rgba(30,58,138,0.6)` | `#93c5fd` |
| NEUTRAL / INACTIVE | `rgba(255,255,255,0.06)` | `#94a3b8` |

### Tables

Data tables are the primary surface. They hold the operational information an ops reviewer lives inside.

- Row height: 44px minimum (touch-friendly, not cramped)
- Header: `0.75rem / 500 weight / uppercase / letter-spacing: 0.05em` in `#475569`
- Row border: `1px solid rgba(255,255,255,0.04)` — barely visible, providing rhythm without visual noise
- Row hover: `rgba(255,255,255,0.02)` — confirmation of interactivity, not a spotlight
- Selected row: `rgba(245,200,66,0.06)` with `border-left: 2px solid #f5c842` — exception to the no-side-stripe rule: selection state earns it
- Sticky header: always. Tables scroll; the column context must not scroll away.
- Column alignment: numbers right-aligned, text left-aligned, status badges centered

### Form controls

- Input height: 36px
- Border: `1px solid rgba(255,255,255,0.12)` idle → `rgba(245,200,66,0.5)` focused
- Background: `rgba(255,255,255,0.04)` — subtle darkening that distinguishes the field
- Border-radius: 6px
- Error state: `border-color: #ef4444` + red helper text below
- Label: `0.75rem / 500 weight` above the input, `#94a3b8` color
- Placeholder: `#475569` — must meet 4.5:1 against field background (check at `rgba(255,255,255,0.04)` on `#03061a`)

### IET Countdown

The most critical UI element. Displayed on every item in human review queue.

- Clock container: distinct border treatment, amber color at < 60 minutes, red at < 15 minutes
- Time display: JetBrains Mono, 1.25rem, bold — monospace prevents layout shift as digits change
- Never hidden, never below the fold when the item is in review
- Reduced motion: number updates without animation; color transition is still permitted (not motion)

---

## Do's and Don'ts

### Do

- **Use JetBrains Mono for all machine-generated identifiers.** Instrument IDs, MICR strings, workflow IDs, account suffixes. Monospace makes scanning and copy-pasting reliable.
- **Right-align numbers in tables.** Amounts, counts, percentages — always right-aligned so decimal points line up.
- **Pair every status color with a text label or icon.** The badge color alone is never sufficient.
- **Show skeleton states, not spinners, for content loading.** Skeletons preserve layout; spinners introduce a blank void.
- **Use `position: fixed` or the popover API for dropdowns inside scrollable containers.** `position: absolute` inside `overflow: hidden` will clip.
- **Keep IET clocks visible at all times during human review.** If the user has scrolled past a countdown, they are working blind.
- **Use gold sparingly — one primary action per view.** Its scarcity is what makes it scannable.
- **Give empty states purpose.** "No cheques in queue" should teach the interface — explain why, what to expect next, or what the user just accomplished.

### Don't

- **No gradient text.** `background-clip: text` with a gradient is banned. Gold accent is a solid color.
- **No side-stripe borders as decoration.** Left or right borders > 1px as colored card accents are banned. Selection state on table rows is the one earned exception.
- **No identical card grids.** Same-sized icon + heading + text cards repeated across a page. This is the SaaS dashboard pattern ASTRA explicitly rejects.
- **No uppercase kicker eyebrows on every section.** `OVERVIEW`, `DETAILS`, `ACTIONS` as small-caps labels above every section heading is the AI scaffold reflex. Use it once as a deliberate system, or not at all.
- **No decorative motion.** Animations only for state transitions, feedback, and loading. No entrance choreography just because a panel opened.
- **No modal as first thought.** Modals block the clock. Prefer inline progressive disclosure, side sheets, or confirmation within the same row. Reserve modals for irreversible actions that genuinely require isolation.
- **No `asyncio.sleep()` or arbitrary delays in loading states.** Skeleton → content, as fast as the data arrives. Artificial loading theatre is disrespectful of the IET clock.
- **No softness.** Rounded corners cap at `0.5rem` on data surfaces. Larger radiuses read as consumer fintech — wrong register for a regulatory compliance platform.
