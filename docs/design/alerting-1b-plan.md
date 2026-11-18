# Alerting Phase 1b: routing, on-call, acknowledgement and escalation

Builds on docs/design/alerting-blueprint.md (sections 5, 8, 13, 21). Decisions already taken (section 13): scope order **Bank, then PU, then SMB**, the bank level being a floor that nothing below can remove; acknowledgement and escalation are in the first release.

## Steps (each test-first, each live-checked where it can be)

| # | Step | Result |
|---|---|---|
| 1 | **Routing rules engine** (pure code) | Given an incident and the policies at each level, who is notified, on which channels, and when it escalates. Accumulate-and-floor across Bank, PU, SMB. Policy validation. |
| 2 | **Policy store** | `platform.alert_routing_policies` (versioned, per bank and scope), with audit events on every change and a default policy built from today's flat settings, so a bank that does nothing sees no change. |
| 3 | **On-call rota** | Weekly shifts with overrides, a holiday calendar, a fallback group; resolves "who is on call now" to people. |
| 4 | **Escalation workflow** | One Temporal workflow per open incident: waits for each step's time, escalates to the next level, stops on acknowledgement or resolution, re-notifies on the policy's interval. Patch-marked, replay-tested. |
| 5 | **Wire the send path** | The alert send uses the resolved routing (people, not raw lists) and the incident's scope; the legacy flat lists remain the fallback. |
| 6 | **Policy and simulator API** | Read and change policies with maker-checker, plus "who would be notified for this incident" without sending anything. |
| 7 | **Migration** | Today's flat settings and the 18 event routes of `shared/notifications/routing.py` become the default bank policy. |

The screens for all of this are Phase 2.

## The rules (how the three levels combine)

- A level's policy is an ordered list of rules; the **first rule that matches** the incident wins at that level.
- The **bank** level always applies. The **PU** level applies only to an incident of that PU, the **SMB** level only to an incident of that SMB.
- Targets **accumulate**: everyone any level names is notified; a person named twice gets the union of their channels.
- A lower level can **add** people, channels and escalation steps; it can never remove or mute what a higher level requires.
- On any **conflict** (escalation timing of the same step, quiet-hold) the **higher level wins**.
- Quiet-hold (keep a low-priority alert for the next working hours) applies to P2 and P3 only, and only if the bank level allows it. P0 and P1 are never held.
- An incident no rule matches is reported as such (the send path then uses the legacy lists); a policy that leaves P0 uncovered is refused when saved.
