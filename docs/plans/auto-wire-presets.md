# Plan: Auto-wire new presets into band orders

Spec: docs/specs/auto-wire-presets.md — decisions 1A/tail/prune locked.

## Tasks

- [ ] Task 1: `helpers/auto_wire.py` — sync core
  - Acceptance: sync_band_orders appends new pool names to every band tail,
    prunes dead names, writes atomically only on change, persists
    wire-state.json report, never raises.
  - Verify: tests/test_auto_wire.py (failing first, then green).
  - Files: helpers/auto_wire.py, tests/test_auto_wire.py.

- [ ] Task 2: Panel data — webui_data.tuning_report gains `unwired` +
  `wire_state`; API action `wire_sync`.
  - Acceptance: report lists unwired presets (empty in steady state) and last
    wire report; wire_sync returns report + unwired.
  - Verify: tests/test_webui_data.py extension (failing first, then green).
  - Files: helpers/webui_data.py, api/routing_policy.py, tests/test_webui_data.py.

- [ ] Task 3: Route-extension trigger — module-level `_LAST_FP` guard runs
  sync once per pool fingerprint change.
  - Acceptance: fingerprint change triggers exactly one sync; identical
  fingerprint does not re-run; failures never break routing.
  - Verify: tests/test_route_wiring.py (failing first, then green).
  - Files: extensions/python/chat_model_call_before/_10_jev_route.py,
    tests/test_route_wiring.py.

- [ ] Task 4: Panel chip in tuning card — `Auto-wired: +N −M` chip with
  names; hidden when no report.
  - Acceptance: chip renders from wire_state; stale-state safe.
  - Verify: manual panel smoke via browser after deploy + existing panel
    tests still pass.
  - Files: webui/jev-router-panel.html,
    extensions/webui/right-canvas-panels/jev-router-panel.html.

- [ ] Task 5: Mirror to plugin/ deployment copies, full test suite, sync to
  live /a0/usr/plugins/jev_router (runtime files excluded), framework
  restart note.
  - Verify: full pytest green; live wiring works end-to-end.
  - Files: plugin/** mirrors.

## Risks

- Concurrent writes (panel save + route sync): mitigated by atomic
  tmp+replace writes (write_band_orders precedent) and idempotent sync.
- YAML round-trip drops comments: pre-existing behavior of write_band_orders,
  documented in spec Boundaries; live file already comment-free after earlier
  tuning writes.
