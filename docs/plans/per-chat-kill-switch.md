# Plan: Per-Chat Jev Router Kill-Switch

Derived from `docs/specs/per-chat-kill-switch.md`.

## Dependency Order

```
1. helpers/gate.py (routing_allowed)          ← single source of truth
2. api/routing_kill.py (API handler)          ← persists per-chat state
3. Extension hooks (4 sites)                  ← consult routing_allowed()
   - extensions/python/chat_model_call_before/_10_jev_route.py
   - extensions/python/user_message_ui/_10_jev_preselect.py
   - extensions/python/_functions/initialize/_10_jev_preselect.py
   - extensions/python/user_message_ui/_20_jev_dynamic_switch.py
4. WebUI extension (model-context-strip-end)  ← toggle in context strip
   - extensions/webui/model-context-strip-end/jev-kill-switch.html
   - webui/jev-kill-switch-store.js
5. Contract tests                             ← gate truth table, API, strip HTML
6. Sync & verify                              ← deployed copy, full suite
```

## Tasks

### T1: helpers/gate.py — `routing_allowed(agent)` / `routing_allowed_context(ctx)`
- **Acceptance**: function returns `bool` implementing the truth table:
  - global `enabled=false` → `False`
  - global `enabled=true` + per-chat `enabled=false` → `False`
  - global `enabled=true` + per-chat unset → `True`
  - global `enabled=true` + per-chat `enabled=true` → `True`
- Reads global from `cfg.get('enabled', True)`; per-chat from
  `context.get_data(JEV_KILL_KEY)` (or `agent.config` when in hook).
- **Verify**: `pytest tests/test_gate.py::test_routing_allowed_truth_table -v`
- **Files**: `helpers/gate.py` (new or extend existing)

### T2: api/routing_kill.py — API handler `get` / `set`
- **Acceptance**:
  - `GET {action:'get', context_id}` → `{enabled: bool, effective: bool}`
  - `SET {action:'set', context_id, enabled: bool}` → 409 if `context.is_running()`,
    else persists via `context.set_data(JEV_KILL_KEY, {'enabled': bool})`,
    `save_tmp_chat(context)`, `mark_dirty_for_context(context.id, 'jev_kill_switch')`;
    returns fresh state.
  - Missing context_id → 400; unknown context → 404; invalid action → 400.
- **Verify**: `pytest tests/test_gate.py::test_kill_switch_api_set_get_roundtrip -v`
  and `::test_kill_switch_api_409_while_running -v`
- **Files**: `api/routing_kill.py` (new), register in `hooks.py` / `plugin.yaml`

### T3: Update four hook sites to use `routing_allowed()`
- **Acceptance**: each hook imports and calls `routing_allowed(agent)` (or
  `routing_allowed_context(context)`) instead of `cfg.get('enabled')`.
  Source-level contract test: `test_hooks_use_gate_helper` greps for
  `routing_allowed` in each hook file and asserts absence of raw
  `cfg.get('enabled')` in routing logic.
- **Files**:
  - `extensions/python/chat_model_call_before/_10_jev_route.py` (line 179)
  - `extensions/python/user_message_ui/_10_jev_preselect.py`
  - `extensions/python/_functions/initialize/_10_jev_preselect.py`
  - `extensions/python/user_message_ui/_20_jev_dynamic_switch.py`
- **Verify**: `pytest tests/test_gate.py::test_hooks_use_gate_helper -v`
  plus existing hook tests still pass.

### T4: WebUI extension — `model-context-strip-end` toggle
- **Acceptance**:
  - `extensions/webui/model-context-strip-end/jev-kill-switch.html` exists,
    mirrors `a0_reasoning_effort` pattern (Alpine store, request-id guard,
    `x-effect` placement before `.agent-profile-anchor`).
  - `webui/jev-kill-switch-store.js` with `refresh(contextId)`,
    `toggle(contextId)` calling `plugins/jev_router/routing_kill`.
  - Button shows chip: `route on` / `route off` with material icon;
    disabled when global `enabled=false`.
  - `x-effect` watches `$store.chats.selectedContext?.agent_profile` and
    `$store.chats.selected` to refresh on chat switch.
- **Verify**: `pytest tests/test_panel_consistency.py -k strip -v` (new
  contract test), manual hard-refresh shows toggle in context strip.
- **Files**: two new files in project, copied to deployed.

### T5: Contract tests
- **Acceptance**: all tests in `tests/test_gate.py` pass:
  - `test_routing_allowed_truth_table` (4 cases)
  - `test_kill_switch_api_set_get_roundtrip`
  - `test_kill_switch_api_409_while_running`
  - `test_hooks_use_gate_helper`
- **Files**: `tests/test_gate.py` (new), extend `test_panel_consistency.py`
  for strip HTML contract.

### T6: Sync & full verification
- Copy changed runtime files to `/a0/usr/plugins/jev_router/`:
  - `helpers/gate.py`
  - `api/routing_kill.py`
  - 4 hook files under `extensions/python/`
  - `extensions/webui/model-context-strip-end/jev-kill-switch.html`
  - `webui/jev-kill-switch-store.js`
- Run `pytest tests/ -q` → 485+ tests pass.
- Hard-refresh WebUI; verify toggle appears in context strip, works per-chat,
  persists across reloads, global-off disables it.

## Risk Mitigation
- Helpers changes require framework restart; schedule after extension files.
- Test 409-while-running by sending a message, then immediately toggling
  (the handler checks `context.is_running()`).
- Subagent inheritance: gate helper reads parent context data when
  `agent.number > 0` (or context.parent_id exists).

## Rollback
- Disable new API handler in `plugin.yaml` / `hooks.py`.
- Revert the four hook files to read `cfg.get('enabled')`.
- Delete extension directory and store file.

## Commands
- Focused: `/opt/venv-a0/bin/python -m pytest tests/test_gate.py -v`
- Full: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Sync: `rsync -a --delete /a0/usr/projects/jev_router/helpers/gate.py /a0/usr/projects/jev_router/api/routing_kill.py /a0/usr/projects/jev_router/extensions/python/ /a0/usr/projects/jev_router/extensions/webui/ /a0/usr/projects/jev_router/webui/ /a0/usr/plugins/jev_router/`
  (then framework restart for helpers changes)