# Spec: Product Redesign — Routing Without Thinking

Status: SHIPPED — Option C complete, 373 tests green (post-ship audits and hardening), v0.7.0 (2026-09-25)
Date: 2026-09-25
Builds on: fit-aware-routing, auto-wire-presets, dynamic-profile-switch specs

## Purpose

Make the router feel invisible for general use: zero required configuration, one coherent decision story, automation by default with manual as override. This spec consolidates all prior refinements into the intended product shape and offers three scopes.

## Problems (current UX evidence)

1. Three overlapping selectors (band order, auto-tune, fit) with no visible precedence story per call.
2. Decision stream shows raw reason tags ([auto-tune], [fit], [dynamic-switch]); users must know internals.
3. Suggest/Apply is manual ceremony; auto-tune exists but defaults OFF and reads as a feature toggle, not the product default.
4. Delegation is a one-line text advisory the model may ignore; no structured handoff, no panel visibility.
5. Settings expose every expert knob to everyone; no simple mode.

## Design principles

- P1 Automation by default, manual as override (pin beats toggle).
- P2 Every decision explainable in one human line, on demand.
- P3 Constraints first, then ranking; one ladder, rendered once.
- P4 Progressive disclosure: Simple by default, Advanced opt-in.
- P5 Delegation is a first-class routing surface, not a text hint.

## The redesign (5 moves)

### M1 Decision cards

Every routed call records a structured explanation: chosen preset, one-line human reason, deciding rule (band / fit / breaker / mention / schedule / fastpath / auto-tune), runner-up, confidence. Panel renders decision cards instead of raw tags; dynamic-switch and delegation events join the same stream. Data comes from existing Decision + Signals; policy gains reason_human. TDD: policy produces reason_human; webui_data exposes it; panel renders.

### M2 Auto-tune by default with pins

- auto_tune defaults ON for fresh installs; existing installs keep their stored flag and get a one-click enable affordance.
- Suggest/Apply buttons removed. Band card shows the live order plus a change feed: what auto-tune changed and why (e.g. promoted openrouter: 92 percent ok over 14 calls).
- Per-band pin freezes that band order (manual wins, pin icon shown); unpin returns to auto. Pins live in routing-policy.yaml.
- Pinned bands also freeze against auto-wire reordering; the wire report lists them.
- This resolves the earlier auto-tune toggle question: the toggle is replaced by pins plus a default-on policy.

### M3 One selection ladder, documented and previewed

Precedence: constraints (fastpath, mentions with TTL, schedules, breaker, eligibility) then ranking (band order or auto-ranked) then fit confidence override then call. Fit is the pre-call judgment; auto-tune is the post-call statistics fallback order. They are complementary, not redundant. No mechanic change; the M1 card names which rung fired.

### M4 Delegation 2.0

- Structured advisory: when delegate_worthy >= threshold, inject a machine-readable advisory (JSON block in the SystemMessage: suggested profile, task class, confidence, reason) plus a tightened advisory contract so the agent acts on it when the task matches and otherwise ignores it deliberately.
- delegation_mode auto upgrades phrasing from advice to directive (delegate this unless blocked).
- Panel: delegation chip on decision rows (advised / directed).
- Subordinate alignment: routed subordinate calls show their owning profile on the decision card (visibility only; the hook already routes them).

### M5 Simple/Advanced settings

- Simple: enable, API key, and a performance dial (cost saver / balanced / max quality) mapping to deterministic band-emphasis presets and delegation threshold presets.
- Advanced: the current full knob set, unchanged.
- The dial writes emphasis via the existing band order apply path.

## Scope options

| Option | Contents | Effort | Risk |
|---|---|---|---|
| A - Clarity pass | M1 + M3 documentation | ~2 slices, low | none to behavior |
| B - Intended default | A + M2 + M4 + M5 | ~6-8 TDD slices | moderate, flagged below |
| C - Full vision | B + closed-loop learning (fit outcomes feed auto-tune evidence with per-preset floors, dial telemetry report, delegation auto-execution experiment) | staged, larger | higher |

Recommendation: B.

## Disposition of previous refinements

- Fast path: keep (constraint rung).
- Mentions + TTL: keep; add active-dial chip.
- Schedules: keep; render window in panel status.
- Circuit breaker: keep; already visible.
- Auto-wire: keep; pinned bands freeze, tail-append unchanged for unpinned.
- Fit-aware: keep as pre-call selector; floor stays 0.6 default.
- Auto-tune: default-on with pins; toggle replaced.
- Dynamic switch: keep opt-in; surfaced in cards.
- Preselect: keep; card on new chats.

## Phased plan (Option B, sequential TDD slices, RED before GREEN)

- S1 reason_human in policy + router (+tests).
- S2 webui_data decision card payload (+tests).
- S3 panel decision cards + chips (+JS syntax check).
- S4 tuning pins: per-band pin list, apply_tuning respects pins, panel pin/unpin + change feed (+tests).
- S5 defaults: auto_tune true for fresh config; enable-all affordance (+tests, settings).
- S6 structured delegation advisory + auto directive phrasing (+tests: router advisory builder, extension injection).
- S7 Simple/Advanced settings + performance dial mapping (+tests: settings ui, policy emphasis).
- S8 README/CHANGELOG, spec updates, full suite, review fan-out (code-reviewer, security-auditor, test-engineer), deploy sync (runtime files excluded), framework restart.

## Risks

- Auto-tune default ON changes behavior for upgraders: mitigate by honoring the stored flag; fresh installs only.
- Advisory phrasing changes agent behavior: keep advise phrasing conservative; directive only in auto mode.
- Pin + auto-wire interaction: pinned freeze documented; wire report lists them.
- Panel card complexity: reuse the existing diff-guard signature rendering.

## Open decisions (user)

1. ~~Scope: A, B, or C.~~ RESOLVED: C.
2. Dial naming: cost saver / balanced / max quality (default: balanced).
3. ~~Delegation auto-execution.~~ RESOLVED: approved, gated behind delegation_mode auto and explicit config flag.

## Option C additions (closed loop + auto-delegation)

### M6 Closed-loop learning

- Fit outcomes write back into auto-tune evidence: when a fit-chosen call succeeds or fails, that outcome counts toward the chosen preset's position in its band order, so a confident-but-wrong fit decays naturally.
- Per-preset evidence floors stay (sparse-evidence rule from 2026-09-25): no promotion without minimum observed calls.
- Telemetry gains fit_outcome_applied flag on decision rows (idempotent migration).

### M7 Performance-dial telemetry report

- report.py gains a dial mode: per-dial-position aggregates (calls, ok rate, p50/p95 duration, estimated cost class) so users can verify their dial choice against reality.
- Panel: small dial summary line in the Band Tuning card fed by webui_data.

### M8 Delegation auto-execution (approved experiment)

- New config flag delegation_auto_execute (default false) and requires delegation_mode auto. Both must be on; otherwise behavior is exactly M4 advisory.
- When on and gate confidence >= auto-execute floor (0.8 default, separate from advisory threshold): the router extension emits a structured directive instructing the agent to call call_subordinate with the suggested profile as its first action unless blocked; the directive includes the M4 structured payload.
- Safety rails: never fires on fastpath or trivial messages; never fires more than once per user message; subordinate calls themselves are routed normally by the existing hook; any parse or execution failure keeps M4 advisory wording (never-raise).
- Telemetry records auto_exec on the decision row; panel chip shows directed-auto.

### Plan extension (Option C slices, after S8)

- S9 fit-outcome write-back into tuning evidence (+tests: tuning integration, telemetry flag).
- S10 dial report mode in report.py + panel dial summary (+tests: report parsing, webui_data field).
- S11 delegation auto-execution flag, directive builder, wiring, panel chip (+tests: gate config, extension injection, never-raise paths).
- S12 docs (README/CHANGELOG/spec disposition), review fan-out, deploy sync, restart.
