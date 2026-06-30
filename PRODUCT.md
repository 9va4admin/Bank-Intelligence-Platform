# Product

## Register

product

## Users

**Primary — Ops Reviewer**: Bank operations staff clearing the human-review cheque queue under the 3-hour IET clock. High-stakes, time-pressured, needs zero cognitive friction. A wrong action costs the bank crores; a slow interface costs the bank the IET window. Works across environments — dimly lit ops rooms and bright open-plan offices — so both dark and light themes are a genuine operational requirement, not a feature.

**Secondary — Bank IT Admin**: Configures the platform, manages users, monitors system health, approves maker-checker workflows. Lower time pressure but high accountability. Needs clarity and confidence, not speed.

**Context**: Indian bank ops workstations, data centres, multi-monitor setups. Users are trained professionals, not casual consumers. They live inside this product for hours at a time.

## Product Purpose

ASTRA (Automated Settlement and Transaction Recognition Architecture) is an AI-native banking platform that handles CTS cheque clearing (inward + outward) and ATM EJ intelligence for Indian banks. It enforces RBI's T+3 hour IET mandate — zero breaches — by running one AI agent per inward cheque, 500 parallel agents per batch, decision in < 600ms. The platform must feel as precise and reliable as the system it runs.

## Brand Personality

**Precision. Authority. Craft.**

- Precision: every element earns its place; nothing decorative that doesn't signal meaning
- Authority: the interface communicates "this is under control" even when processing 500 cheques simultaneously
- Craft: obsessive attention to spacing, hierarchy, and micro-detail — not flashy, but unmistakably refined

The emotional goal: an ops reviewer should feel **calm confidence** when opening ASTRA, not anxiety. The design absorbs complexity so the user doesn't have to.

## Anti-references

- **Generic SaaS dashboard**: no purple-to-blue gradients, no hero-metric cards, no identical rounded-card grids, no Inter-font-plus-gradient-text combinations. Avoid the AI scaffold default entirely.
- **Consumer fintech softness**: no Monzo/PhonePe pastel aesthetics — too friendly for a platform where incorrect decisions carry regulatory and financial consequences
- **Legacy banking core**: no TCS BaNCS / Finacle grey-table interfaces from 2005

## Design Principles

1. **Information density over empty space** — ops staff read signals, not prose. Pack meaningful data; trim decorative whitespace.
2. **Color carries meaning, never decoration** — every use of color signals status, risk, or action. No gradient text, no decorative accent splashes.
3. **Dark-native, light-capable** — the dark theme is the primary design surface; light theme is a first-class derivative, not an afterthought.
4. **Hierarchy through contrast, not rules** — visual weight creates structure. Avoid the AI reflex of borders-as-separators everywhere; use negative space and typographic contrast instead.
5. **Zero cognitive load at critical moments** — at T-180 to T-0 seconds on an IET clock, the UI must be immediately readable. Labels must be unambiguous; actions must be obvious; error states must be unmissable.

## Reference aesthetic

**Linear's obsessive polish applied to Datadog's information density.** A precision banking command centre that happens to look extraordinary. Keyboard-first thinking, micro-interaction quality, purposeful color, no wasted pixel.

## Accessibility & Inclusion

- WCAG 2.1 AA minimum; AA on contrast is non-negotiable given the operational context
- Full keyboard navigation (ops staff use keyboards extensively)
- Both `prefers-reduced-motion` and `prefers-color-scheme` respected
- Color is never the sole signal carrier — always paired with label, icon, or shape
