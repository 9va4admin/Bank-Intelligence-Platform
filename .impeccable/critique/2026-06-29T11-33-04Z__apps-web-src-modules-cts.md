---
target: apps/web/src/modules/cts
total_score: 32
p0_count: 2
p1_count: 2
timestamp: 2026-06-29T11-33-04Z
slug: apps-web-src-modules-cts
---
## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 4/4 | IET timer always visible, STP live stream, session elapsed clock — no latency fog |
| 2 | Match System / Real World | 3/4 | Excellent domain language (IET, NGCH, MICR) but "Siamese SNN" and "SHAP" exposed raw to ops |
| 3 | User Control and Freedom | 3/4 | Good queue navigation; no undo after Confirm/Return (intentional for audit, but still limiting) |
| 4 | Consistency and Standards | 4/4 | Theme tokens, spacing, badge styles, button patterns uniform across all CTS pages |
| 5 | Error Prevention | 3/4 | Return requires reason (disabled guard); Confirm has no confirmation modal — one misclick pays fraud |
| 6 | Recognition Rather Than Recall | 4/4 | Return reasons presented as list, status badges instant-read, IDs in mono for scannability |
| 7 | Flexibility and Efficiency | 3/4 | No keyboard shortcuts; single-cheque-at-a-time review; trained ops hit a throughput ceiling |
| 8 | Aesthetic and Minimalist Design | 4/4 | Zero decorative slop. Every element earns its pixel. Pipeline visualizer is purposeful, not decorative |
| 9 | Error Recovery | 2/4 | 800ms "Filing…" delay is the only recovery window; no undo, no recall after decision is filed |
| 10 | Help and Documentation | 2/4 | No tooltips, no in-app help, no onboarding. Assumes domain expertise. "OPA", "SHAP", "Vault miss" unexplained |
| **Total** | | **32/40** | **Good — address weak areas, solid foundation** |

## Anti-Patterns Verdict

**LLM assessment**: Clean. No AI slop detected. The CTS workstation avoids every canonical anti-pattern: no gradient text, no side-stripe accent borders, no identical card grids, no uppercase eyebrow kickers on every section, no hero-metric cards. The pipeline arc visualization in CTSPresentment.jsx is a deliberate design choice — one spatial metaphor, not three chart types. The STP live stream sidebar is ambient data, not a KPI dashboard. The design reads as purposeful throughout.

**Deterministic scan**: The detector CLI could not run (missing `design-system.mjs` and `findings.mjs` modules in the skill package — a tooling gap, not a codebase issue). Manual pattern scan across 69 JSX files produced **0 high-confidence antipattern violations**. Two pattern classes were flagged for context review:
- **Gradient backgrounds** (18 instances): All functional — IET progress bar uses green→red to signal risk spectrum, pipeline nodes use glow for active state. Not decorative.
- **Purple/cyan/violet** (47+ instances): Each maps to a named status role (purple = VAULT_MISS, cyan = action/focus, violet = AI_EXTRACTED). Color is always paired with a label — never sole signal carrier.

Both are **false positives in context**. The detector would need domain-aware configuration to distinguish them from slop.

**Overall anti-pattern verdict: PASS.** This design does not look AI-generated. It looks like it was built for a specific, high-stakes use case by someone who understood the domain.

## Overall Impression

The CTS workstation is 32/40 — genuinely good, not polished-to-ship good. The foundation is exceptional: information architecture is correct, emotional tone is calibrated (calm confidence, not anxiety), and the "Cheque Digital Passport" timeline is a standout example of transparency at high stakes. The gaps are in the final operational mile — keyboard efficiency for power users, a safety net on the Confirm action, and help for anyone who didn't train for six months before touching this screen. Fix those three things and this is a 37/40 interface.

## What's Working

**1. The Cheque Digital Passport timeline (ReviewPanel.jsx, lines 396–483)**
The two-bank pipeline rendered as a vertical timeline with timestamped, colour-coded nodes is the best single design decision in the product. Each step shows icon + timestamp + elapsed time + explanatory note. An ops reviewer can verify that the system was thorough before making a decision. This is what "absorbing complexity so the user doesn't have to" looks like in practice. A typical SaaS would show a flat checklist of ticks; this tells a story.

**2. Ambient STP live stream (CTSWorkstation.jsx, lines 183–244)**
The right sidebar showing real-time STP decisions without demanding interaction is exactly right for an ops workstation. It reinforces that parallel automation is running while the reviewer focuses on one cheque. The colour coding is immediate (emerald = confirmed, red = returned) and the count updates live. This is ambient data done correctly — information flows to the op, not the other way.

**3. Trust Score strip (ReviewPanel.jsx, lines 248–284)**
Four inline mini-bars (OCR, Sig, Fraud, IET) give a glance-able confidence profile in one horizontal band. The IET bar inverts its scale — low remaining time = red — which is uninstructive but intuitively right. Tabular-nums prevents layout shift as digits change. This is how you make high-dimensional model output scannable under time pressure.

## Priority Issues

**[P0] No confirmation guard on the Confirm action**
- **What**: The "✓ Confirm" button (ReviewPanel.jsx ~line 506) has no modal. One misclick confirms a cheque for payment. Return has a guard (reason required, button disabled until selected); Confirm does not.
- **Why it matters**: A confirmed fraudulent cheque means the bank pays regardless. The asymmetry between Return (guarded) and Confirm (unguarded) is inverted risk management.
- **Fix**: Add a brief confirmation: either a 2-second "Confirming… [Esc to cancel]" interruptible state (no modal, no extra click for speed), or a minimal modal: "Confirm payment of ₹[range] to [payee]?" with keyboard shortcut `Enter` to proceed.
- **Suggested command**: `/impeccable harden apps/web/src/modules/cts/pages/ReviewPanel.jsx`

**[P0] Return reason dropdown is a throughput chokepoint**
- **What**: RETURN_REASONS is a flat list of 18 options. Under IET pressure with 30 cheques in queue, scrolling an 18-item dropdown to select "Signature mismatch confirmed" is measurable friction. There is no search, no grouping, no keyboard shortcut.
- **Why it matters**: Decision velocity is the product's core value. A trained op should process a cheque in 45–90 seconds. The dropdown alone costs 3–8 seconds per return decision — compounded across a clearing session, this is material.
- **Fix**: (a) Searchable/autocomplete dropdown: type "sig" → filters to 2 options, Enter selects. (b) Group reasons into 3 categories (Presenting Bank / Drawee Bank / System/Policy) with visual separator. (c) Persist the last 3 used reasons at the top of the list.
- **Suggested command**: `/impeccable polish apps/web/src/modules/cts/pages/ReviewPanel.jsx`

**[P1] No keyboard shortcuts**
- **What**: All decisions require mouse. No keyboard shortcut for Confirm, Return, next/previous cheque, or reason selection. CTSWorkstation.jsx has no keyboard event listeners.
- **Why it matters**: An ops reviewer processing 200 cheques per shift is a power user by definition. Mouse-only interaction is a throughput cap. At T-60 minutes with 30 cheques remaining, every second of mouse travel counts.
- **Fix**: Implement: `C` = Confirm (with 2s cancel window), `R` = focus return reason dropdown, `↓`/`↑` = next/previous cheque in queue, `1`–`9` = quick-select top reasons, `Esc` = cancel in-flight action. Show shortcuts in a `?` overlay.
- **Suggested command**: `/impeccable harden apps/web/src/modules/cts/`

**[P1] No in-app help for domain jargon**
- **What**: "Vault miss", "OPA policy", "SHAP", "Siamese SNN" appear in the UI without explanation. A reviewer six months into the job knows these. A reviewer on day three does not.
- **Why it matters**: New ops make slower, lower-confidence decisions when they don't understand what the system is telling them. Training happens outside the product; it should happen inside it.
- **Fix**: Add `?` icon tooltips next to Vault Miss status, OPA policy name, SHAP explainer header, and Signature SNN score label. Tooltip text: one sentence, plain language. "Vault miss — no signature specimen found in the system. You must decide manually." No links, no modals, no onboarding wizard.
- **Suggested command**: `/impeccable clarify apps/web/src/modules/cts/`

**[P2] SHAP explainer lacks interpretive context**
- **What**: ShapExplainer.jsx shows SHAP bars (risk-increasing vs. risk-reducing factors) but does not explain what SHAP values mean, what the magnitude threshold is, or how to use them in a decision.
- **Why it matters**: An ops reviewer who sees "Signature mismatch −0.34" has no reference for whether that's a strong signal or noise. The model's transparency benefit is lost if the output is uninterpretable.
- **Fix**: Add one header line: "AI Decision Factors — the strongest influences on the fraud score. Values above ±0.1 are significant." Add a subtle legend. Consider grouping factors by category (Signature / OCR / Account Status).
- **Suggested command**: `/impeccable clarify apps/web/src/modules/cts/pages/ShapExplainer.jsx`

## Persona Red Flags

**Alex (Power User / Ops Reviewer — primary user)**
Alex processes 200+ cheques per shift, knows every return reason, has been using this interface for 3 months. Lives inside CTSWorkstation 6–8 hours a day.
- ❌ No keyboard shortcuts anywhere. Alex's hands are on the mouse the entire shift. Throughput hit is real and measurable.
- ❌ Dropdown requires mouse navigation to an 18-item flat list. Alex knows the answer before the dropdown opens but still has to scroll to find it.
- ❌ No "Fast Path" mode. High-confidence green cheques (fraud < 0.10, sig > 0.97) still get the full review flow. No single-gesture confirm for the obvious cases.
- ❌ No session pace indicator. Alex cannot see "you're processing at 95 sec/cheque; at this rate, 6 cheques will miss the IET window" — that signal would change behaviour.
- ✓ IET timer always visible. Trust Score strip gives glance-able confidence in under a second. Decision is recorded and visible in STP stream immediately.

**Sam (Accessibility-Dependent)**
Keyboard-only navigation, screen reader (NVDA), WCAG AA requirements.
- ❌ No ARIA labels on interactive elements — tabs in ReviewPanel.jsx will not announce correctly to a screen reader.
- ❌ Cheque image preview is hover-only (ReviewPanel.jsx). Keyboard users cannot access it.
- ❌ IET urgency is communicated by colour progression (green→amber→red) — colour is the primary signal, not a secondary one. Needs text: "IET: 8 minutes remaining (critical)".
- ❌ FraudGauge.jsx is an SVG radial arc — requires `aria-label` or accessible text description for screen readers.
- ❌ Font sizes of 10px and 9px at normal zoom. At 150% zoom these are acceptable; at default zoom they are borderline.
- ✓ Text labels exist on all action buttons. Status badges pair colour with text. No icon-only navigation.

**IET Specialist (custom — ops reviewer at T-60 min with 30 cheques pending)**
It is 11:00 AM. IET deadline is 12:00 PM. 30 cheques remain. Each takes ~90 seconds. Shortfall: 15 cheques worth of time. Maximum operational stress.
- ❌ No escalation path. When an op is behind, the UI offers no way to route overflow to a backup reviewer or alert a supervisor.
- ❌ No queue reordering by IET risk. High-risk cheques (those closest to IET expiry) are not surfaced to the top automatically.
- ❌ Return reason dropdown chokepoint becomes critical. Under maximum speed, a flat 18-item list causes mis-selections — wrong reason code filed to NGCH.
- ❌ No "express Confirm" for obviously safe cheques. Every cheque, regardless of fraud score, gets the same flow.
- ✓ BatchStats shows queue depth in real-time. Session elapsed clock gives pace reference. IETWatchdogWorkflow files emergency at T-30s regardless of UI state — the safety net holds even if the op is overwhelmed.

## Minor Observations

- The STP live stream is read-only. If an STP auto-decision looks wrong, there's no challenge path from the UI. Consider making stream items clickable to show the full audit trail.
- Sub-member cheque amber banner (ReviewPanel.jsx, ~line 198) is appropriately prominent, but does not explain what different return behaviour applies for SMB instruments. One line of copy would close that gap.
- OPA dual-approval policy (>₹1Cr) is shown as text but not enforced in the UI — the Confirm button is not blocked for single-reviewer sign-off on high-value cheques. If the enforcement happens downstream (Temporal workflow), make that explicit in the UI.
- Model version, retraining date, and last-known accuracy are not shown on the FraudGauge or ShapExplainer. Ops benefit from knowing whether the fraud model is current.
- No search across sessions. The search bar (AppShell, ~line 292) appears global, but historical cheques from closed sessions are not reachable from the workstation. A link to the audit view would close this.

## Questions to Consider

- "What if the Confirm action showed the payee name and amount range in the button label — 'Confirm payment to R*** (₹1L–5L)' — making the decision feel more deliberate without adding a modal?"
- "Should high-confidence green cheques (fraud < 0.10, sig > 0.97, no vault miss) have a fast-path mode where the reviewer confirms with a single keyboard shortcut and the system auto-advances to the next?"
- "What does the interface look like to a supervisor watching 8 ops reviewers? Is there a queue-depth-by-reviewer view that would let them spot who is falling behind?"
