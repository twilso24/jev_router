# Spec: Fit-Aware Routing & Profile-Aware Judgments

Target: 0.6.0 | Date: 2026-09-25 | Status: approved-in-goal (autonomous mode)

## Objective

Routing today selects a preset by complexity band + static user band orders (first-match-wins). Two gaps:

1. No dynamic comparison of the message against the actual candidate models: Jev classifies the task but never chooses among eligible presets.
2. Agent profiles are invisible to routing: never judged, never recorded, never used.

This feature makes Jev compare state and data dynamically, and makes the active agent profile a first-class observable signal.

## User stories

- With 11 presets, a story request should route to the storytelling model when it genuinely fits, not to the band head.
- Telemetry and the panel should show which profile was active and whether it matched the task.
- A kill switch and confidence floor must exist for automatic fit selection.

## Design decisions

- D1 Single-batch fit: one Jev round-trip adds `preset_fit` (choice over eligible presets). No second call; success latency unchanged.
- D2 Constrained application: the fit pick is honored only when it is in the judged band's order AND present in the filtered pool AND confidence >= `fit_min_confidence` AND vision-capable when vision is required. Otherwise behavior is byte-identical to legacy.
- D3 Profiles observed, not switched: the active profile enters judgment state; a `profile_match` noul is judged and recorded. Switching remains dynamic_switch's opt-in job.
- D4 Fail-safe everywhere: absent/invalid fit answers, migration failures, panel errors never raise; each falls back to today's behavior.
- D5 Cache correctness: DECISION_CACHE key gains a profile segment so the same message under a different profile re-judges.

## Signals schema (helpers/signals.py)

- `preset_fit: str | None` - validated against the criteria names actually offered
- `preset_fit_confidence: float` - 0.0 when absent
- `profile_match: float | None` - noul result or None

## Questions

- `preset_fit`: choice; criteria = eligible preset names, each described by provider/model/vision.
- `profile_match`: noul; instructions reference `state.agent_profile`.
- `build_questions` grows optional args with backward-compatible defaults.

## State

- `agent_profile: str` ('' when unknown) passed by the router into `build_state`.

## Policy (helpers/policy.py)

`resolve(..., honor_fit=True, fit_min_confidence=0.6)` honors fit per D2. `Decision.fit_used: bool = False`; reason gains a ' [fit]' tag; `wanted` stays the band head.

## Telemetry (helpers/telemetry.py)

`decisions` table gains `profile TEXT`, `fit_preset TEXT`, `fit_confidence REAL`, `fit_used INTEGER DEFAULT 0` via idempotent PRAGMA-based migration (pattern proven for `session_id`).

## Router + extension

`route(..., agent_profile='')`: profile into state, fit-aware resolve, telemetry carries profile/fit. The extension reads `agent.config.profile`, passes it to `route`, and appends it to the cache key.

## WebUI

`webui_data` decision rows expose the new fields; the panel decision line shows the profile and a fit chip.

## Config (config.json + settings UI)

- `fit_enabled: true` (kill switch)
- `fit_min_confidence: 0.6`

## Commands

```
cd /a0/usr/projects/jev_router && /opt/venv-a0/bin/python -m pytest tests/ -q
```

## Testing strategy

TDD per slice: signals parse/validation, policy fit rules + fallback equivalence, router passthrough, telemetry migration + record, extension cache key, webui fields, settings keys. Combined suite and per-file loop green before any sync.

## Boundaries

- Always: TDD; hooks never raise; suite green before sync.
- Ask first: deploy sync; git commit/push; version bump/release.
- Never: break fallback behavior; commit secrets; add a second Jev round-trip.

## Success criteria

1. A story-like message with the storytelling preset in-band picks it via ' [fit]' in tests.
2. Low-confidence/absent/invalid fit produces the exact legacy decision (same entry and reason).
3. `decisions` rows carry profile + fit columns; legacy DBs migrate in place.
4. The panel shows profile and fit; settings expose both tunables.
5. Combined pytest green (existing 265 + new).

## Open questions

None - resolved autonomously per goal authorization and recorded as D1-D5.
