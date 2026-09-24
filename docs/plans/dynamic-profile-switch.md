# Implementation Plan: Dynamic Profile Switching

Status: COMPLETE (2026-09-24)
Spec: docs/specs/dynamic-profile-switch.md (user-approved defaults)

## Architecture Decisions

- Hook point: `extensions/python/user_message_ui/_20_jev_dynamic_switch.py` — fires for **every** message (new and existing chats) before `context.communicate()`, while the context is still idle.
- Fresh-chat split: message 1 of a fresh chat is owned by `_10_jev_preselect` (empty log guard in the dynamic extension); dynamic switching acts from message 2 onward.
- Manual lock: current profile differs from the instance default AND is not a profile we recorded switching to automatically → treat as user intent, never override.
- State: `context.set_data('jev_dynamic_switch_state', ...)` — streak, last task class, last switch time/profile. No new storage.
- Swap: sanctioned pattern from `api/agent_profile_set.py` (initialize_agent → assign config → save_tmp_chat → mark_dirty_for_context), only while idle.
- Decision policy: confidence ≥ threshold (default 0.7), 2 consecutive matching judgments, 30 s same-profile cooldown; a different target profile than the last switch bypasses the cooldown (task genuinely changed).

## Task List

### Task 1: Helper module (pure logic) — RED verified
- [x] RED: `plugin/tests/test_dynamic_switch.py` — 16 tests fail with ImportError (no module).
- [x] GREEN: implement `plugin/helpers/dynamic_switch.py`: `should_dynamic_switch`, `parse_request`, `profile_for`, `decide`, `new_state`, `record_match`, `should_switch`.
- Verify: `cd /a0 && /opt/venv-a0/bin/python plugin/tests/test_dynamic_switch.py` → 16/16, exit 0.

### Task 2: Extension + integration tests — RED then GREEN
- [x] RED: `plugin/tests/test_dynamic_switch_ext.py` loads the real extension file with stubbed framework modules (mirrors test_preselect_ui.py): fires on message 2+, skips fresh/busy/subordinate/no-key/advise, never overrides manual profile, never raises on swap failure.
- [x] GREEN: `plugin/extensions/python/user_message_ui/_20_jev_dynamic_switch.py`.
- Verify: both dynamic test files 100% pass; preselect suites still pass (no regression).

### Task 3: Deploy + live probe
- [x] Checkpoint, then sync changed files to `/a0/usr/plugins/jev_router/` (excluding runtime config.json, per sync rule).
- [x] Live probe: framework discovery of `_20_jev_dynamic_switch.JevDynamicSwitch` at `user_message_ui`; isolated execution with a simulated non-fresh chat → observed swap decision; `/a0/tmp/jev_router_debug.log` shows `[dynamic-switch]` lines.

### Task 4: Review + report
- [x] code-reviewer subordinate on the new files; fix blocking findings.
- [x] Report with file paths, checks run, and not-run limits. Note helpers/ restart requirement for the live WebUI process.

## Risks

| Risk | Mitigation |
|---|---|
| Flip-flopping between profiles | Consecutive + cooldown policy, logged reasons |
| Fighting the preselect hook | Empty-log guard: fresh chats are preselect's domain |
| Overriding manual choice | Default-profile comparison + auto-switch record |
| Slowing every message | One bounded Jev call (≤2 s budget), fail-open to current profile |
