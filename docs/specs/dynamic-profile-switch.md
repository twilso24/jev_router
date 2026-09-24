# Spec: Dynamic Profile Switching (Jev Router)

## Objective

Add mid-chat, **automatic profile switching** that re-evaluates the appropriate profile on every new user message. The feature applies **only to the main chat profile** and respects manual user selection.

## Tech Stack

- Python 3.12+ on `/opt/venv-a0`
- Jev judgment via `usr.plugins.jev_router.helpers.jev`
- Extension hook point: `user_message_ui`
- Config in `config.json` and `routing-policy.yaml`

## Commands

```bash
# Tests
cd /a0 && /opt/venv-a0/bin/python plugin/tests/test_dynamic_switch.py

# Live verification (after restart)
cd /a0 && /opt/venv-a0/bin/python run_ui.py
```

## Project Structure

```
plugin/
  extensions/python/user_message_ui/
    _20_jev_dynamic_switch.py    # NEW: extension (message 2+; message 1 belongs to preselect)
  helpers/
    dynamic_switch.py            # NEW: core logic (gates, judgment, decision)
  tests/
    test_dynamic_switch.py       # NEW: TDD test suite
```

## Code Style

Follow existing helpers and extensions:

```python
def _dbg(msg: str) -> None:
    try:
        from datetime import datetime as _dt
        with open(DEBUG_LOG, 'a') as f:
            f.write(_dt.now().strftime('%H:%M:%S.%f')[:-3] + ' [dynamic-switch] ' + msg + '\n')
    except Exception:
        pass

async def run(message: str, cfg: dict, query_fn, client, model: str, profiles: list) -> tuple[str | None, str]:
    """Jev-based dynamic profile decision. Never raises."""
    ...```

## Testing Strategy

- **Unit tests**: gates, task-class mapping, consecutive matching, cooldown logic, fallback behavior
- **Integration tests**: extension fires, query called, profile swapped without mutating chat
- **Edge cases**: Jev timeout, low confidence, task-class flip, manual profile selected

## Boundaries

**Always:**
- Fall back to current profile on any failure
- Log every decision with reason
- Honor manual profile selection (do not override)

**Ask first:**
- Changing `config.json` schema
- Introducing new dependencies

**Never:**
- Switch profiles while the agent loop is active
- Switch on empty messages
- Persist switching state beyond the chat session

## Success Criteria

- [ ] Extension fires at `user_message_ui` hook for every new user message
- [ ] Manual profile selection prevents automatic switching until a user explicitly re-enables it
- [ ] Requires `confidence >= threshold` AND `two consecutive matching judgments`
- [ ] Implements a 30-second cooldown before re-evaluating the same profile
- [ ] Returns `(None, reason)` for all failure modes
- [ ] All tests pass with exit code 0
- [ ] `/a0/tmp/jev_router_debug.log` shows `[dynamic-switch]` decisions

## Resolved Decisions (implementation)

- `dynamic_switch_threshold` default: **0.7** (config.json)
- `dynamic_switch_consecutive` default: **2** (config.json, honored end-to-end)
- `dynamic_switch_cooldown_seconds` default: **30** (config.json)
- Manual lock: inferred from profile state (current != default AND != last auto-switch target); stored per-chat in context data, no explicit flag

## Assumptions

- Switching only affects the main agent profile (not `call_subordinate` delegation)
- Profile changes are made while the chat is idle (before the next loop starts)
- Jev judgment is bounded to ≤2 seconds
- The plugin is enabled and configured with `delegation_mode=auto`

## Implementation Order

1. Write failing TDD test file
2. Implement `dynamic_switch.py` helper (pure logic)
3. Implement extension `_10_jev_dynamic_switch.py`
4. Write integration tests
5. Verify via live hook execution
6. Update `config.json` with new tunables
