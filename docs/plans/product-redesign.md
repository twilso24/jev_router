# Plan: Product Redesign — Option C (full vision)

Spec: docs/specs/product-redesign.md (APPROVED 2026-09-25). Sequential TDD slices, RED before GREEN. Runtime: /opt/venv-a0/bin/python. All slices verify with `cd /a0 && /opt/venv-a0/bin/python -m pytest /a0/usr/projects/jev_router/tests/<file> -q`.

## Architecture decisions

- reason_human lives on Decision (policy owns explanation; router and panel only consume).
- Pins live in routing-policy.yaml (`pinned_bands: {band: true}`); effective_band_orders respects them; auto-wire skips pinned bands.
- Auto-tune default ON applies only when the key is absent (absent != false); stored false stays false.
- Structured delegation advisory is a JSON block inside the existing SystemMessage advice; parse-failure keeps plain wording (never-raise).
- Auto-execute requires config.delegation_auto_execute AND delegation_mode auto AND confidence >= 0.8; never on fastpath; once per user message; telemetry column auto_exec.
- Fit write-back: record_call gains fit_applied; a separate tuning-side function folds fit outcomes into band evidence with the existing sparse floor.
- Dial (cost saver / balanced / max quality) is a config value mapped to band-emphasis orders via the existing write_band_orders path.

## Task list

### Phase 1: Clarity (M1 + M3)

- [x] S1 reason_human on Decision + router population (+tests: test_policy.py, test_router.py)
  - Files: helpers/policy.py, helpers/router.py, tests/test_policy.py, tests/test_router.py
- [x] S2 webui_data decision card fields (reason, rule, runner-up) (+tests: test_webui_data.py)
  - Files: helpers/webui_data.py, tests/test_webui_data.py
- [x] S3 Panel decision cards + delegation/dynamic chips (+JS syntax check)
  - Files: webui/jev-router-panel.html

### Checkpoint 1: full suite green; panel renders human reasons

### Phase 2: Automation defaults (M2 + M5)

- [x] S4 Pins: read/write pinned_bands, effective_band_orders respects pins, auto_wire skips pinned (+tests: test_tuning.py, test_auto_wire.py)
  - Files: helpers/tuning.py, helpers/auto_wire.py, api/routing_policy.py (pin action), tests
- [x] S5 auto_tune default ON when key absent; panel enable-all affordance; toggle row replaced by pin UI + change feed (+tests: test_tuning.py, test_settings_ui.py)
  - Files: helpers/tuning.py, webui/jev-router-panel.html, tests
- [x] S6 Performance dial: config performance_dial, emphasis mapping to band orders, Simple/Advanced settings split (+tests: test_settings_ui.py, new test_dial.py)
  - Files: config.json, webui/config.html, helpers/tuning.py, tests

### Checkpoint 2: full suite green; upgrader safety proven (stored false stays off)

### Phase 3: Delegation (M4 + M8)

- [x] S7 Structured advisory JSON block + tightened contract wording (+tests: test_router.py, test_gate.py)
  - Files: helpers/router.py, helpers/gate.py, tests
- [x] S8 Panel advised/directed chips (+JS syntax check)
  - Files: webui/jev-router-panel.html
- [x] S9 Auto-execute: config flag + floor, directive builder, once-per-message guard, telemetry auto_exec column, panel chip (+tests: new test_auto_execute.py, test_telemetry_calls.py)
  - Files: config.json, helpers/gate.py, helpers/router.py, extensions/python/chat_model_call_before/_10_jev_route.py, helpers/telemetry.py, tests

### Checkpoint 3: full suite green; never-raise paths proven (parse failure keeps advisory)

### Phase 4: Closed loop (M6 + M7)

- [x] S10 Fit-outcome write-back: fit_outcome_applied column + folding into band evidence under sparse floor (+tests: test_telemetry_calls.py, test_tuning.py)
  - Files: helpers/telemetry.py, helpers/tuning.py, tests
- [x] S11 Dial report: report.py dial mode (calls, ok rate, p50/p95 per dial position) + panel dial summary line (+tests: new test_report.py, test_webui_data.py)
  - Files: report.py, helpers/webui_data.py, webui/jev-router-panel.html, tests

### Checkpoint 4: full suite green

### Phase 5: Ship (S12)

- [x] S12 README/CHANGELOG/spec disposition updates, full suite, review fan-out (code-reviewer, security-auditor, test-engineer), deploy sync to /a0/usr/plugins/jev_router (runtime files excluded), framework restart note

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| auto_tune default ON flips upgraders | Med | default only when key absent; test proves stored false stays off |
| Directive phrasing over-triggers delegation | Med | double gate (mode auto + flag), 0.8 floor, once-per-message, fastpath excluded |
| Pins vs auto-wire conflict | Low | auto_wire skips pinned bands; wire report lists them |
| Panel DOM complexity | Low | reuse diff-guard signature rendering; JS syntax check each slice |
| helpers/ restart requirement | Low | note after each helpers change; restart before live verification |

## Open questions

- None; scope approved (C + auto-execute).
