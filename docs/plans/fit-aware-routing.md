# Plan: Fit-Aware Routing & Profile-Aware Judgments

Spec: docs/specs/fit-aware-routing.md. Sequential TDD slices (RED -> GREEN per task). REVIEW uses the sanctioned parallel persona fan-out.

- [ ] T1 Signals: preset_fit/profile_match questions, state profile, tolerant parse
  - Files: helpers/signals.py, tests/test_signals.py
  - Verify: pytest tests/test_signals.py -q
- [ ] T2 Policy: fit-honoring resolve + Decision.fit_used
  - Files: helpers/policy.py, tests/test_policy.py
  - Verify: pytest tests/test_policy.py -q
- [ ] T3 Telemetry: decisions columns, idempotent migration, record fields
  - Files: helpers/telemetry.py, tests/test_telemetry_calls.py
  - Verify: pytest tests/test_telemetry_calls.py -q
- [ ] T4 Router: agent_profile param, state passthrough, fit-aware resolve, telemetry fields
  - Files: helpers/router.py, tests/test_router.py
  - Verify: pytest tests/test_router.py -q
- [ ] T5 Extension: profile read, cache key segment, route call update
  - Files: extensions/python/chat_model_call_before/_10_jev_route.py, tests/test_route_wiring.py
  - Verify: pytest tests/test_route_wiring.py -q
- [ ] T6 WebUI: webui_data fields + panel profile/fit display
  - Files: helpers/webui_data.py, webui/jev-router-panel.html, tests/test_webui_data.py
  - Verify: pytest tests/test_webui_data.py -q; JS syntax check
- [ ] T7 Config: fit_enabled + fit_min_confidence in config.json and settings UI
  - Files: config.json, webui/config.html, tests/test_settings_ui.py
  - Verify: pytest tests/test_settings_ui.py -q
- [ ] T8 Full verification: combined suite + per-file loop; record harness verification
- [ ] REVIEW: delegate_parallel fan-out (code-reviewer, security-auditor, test-engineer); fix findings
- [ ] SHIP: version 0.6.0, CHANGELOG/README, deploy sync (checkpoint), commit + push (checkpoint)
