# Spec: Self-Contained Jev Dependency for Community Distribution

Status: IMPLEMENTED (2026-09-23) — bundled jev helper, hooks-managed typesafe-sdk, own settings namespace with TYPESAFE_API_KEY fallback

## Objective

Remove the hard dependency on the `typesafe_ai` plugin so `jev_router` works standalone for community users. The plugin must bundle its own Jev query helper, manage `typesafe_sdk` as a direct dependency, and store Jev configuration in its own settings namespace. Users who also have `typesafe_ai` installed are unaffected; the router no longer reads from it.

**User stories:**
- As a community user, I want to install `jev_router` without needing `typesafe_ai`.
- As a community user, I want to configure my TypeSafe API key, model, and timeout in `jev_router`'s own settings.
- As a current user with both plugins, I want zero breaking changes — my existing routing continues to work.

## Assumptions

1. `typesafe_sdk` is a pip-installable package (`pip install typesafe-sdk`) — not bundled in the framework by default.
2. The Jev API contract (`POST /v1/system/one` via `AsyncTypeSafeClient.system_one`) is stable and documented by TypeSafe.
3. Community users will provide their own TypeSafe API key (no shared key).
4. The existing `jev_router` helpers (`router.py`, `signals.py`) already accept a pluggable `query_fn` — no changes needed there.
5. WebUI panel does not display Jev-specific settings; config is managed via plugin settings UI or `config.json`.

→ Correct me now or I'll proceed with these.

## Tech Stack

- Python 3.12 on `/opt/venv-a0` (framework runtime)
- `typesafe-sdk` pip package (new direct dependency)
- Existing `jev_router` plugin structure unchanged except extension and helpers

## Commands

```
Test: cd /a0 && for f in /a0/usr/projects/jev_router/plugin/tests/test_*.py; do /opt/venv-a0/bin/python "$f"; done
Install deps: cd /a0/usr/projects/jev_router/plugin && /opt/venv-a0/bin/python -c "from hooks import install; install()"
Framework restart: required after helpers/ changes
```

## Project Structure

```
plugin/
  hooks.py                          # NEW: install typesafe-sdk
  helpers/
    jev.py                          # NEW: self-contained Jev query helper (copied + adapted from typesafe_ai)
  extensions/python/chat_model_call_before/
    _10_jev_route.py                # MODIFIED: remove typesafe_ai imports, use bundled jev.py
  config.json                       # MODIFIED: add jev_api_key, jev_model, jev_timeout
  plugin.yaml                       # MODIFIED: description updated
  tests/
    test_jev.py                     # NEW: unit tests for bundled jev helper
```

## Code Style

Follow existing jev_router conventions. Example of the new extension config reader:

```python
def _jev_config(self) -> dict:
    try:
        from helpers import plugins
        cfg = plugins.get_plugin_config('jev_router', self.agent) or {}
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return {}
```

## Testing Strategy

- TDD: write `test_jev.py` first with mocked `AsyncTypeSafeClient`
- Test validation: `validate_request` rejects bad shapes, accepts valid ones
- Test query: mocked `system_one` returns expected response shape
- Test failure: timeout, network error, incomplete answers → returns None
- All existing 109 tests must remain green

## Boundaries

- **Always:** fall back to active preset on any Jev failure; never raise from the hook; log every decision
- **Ask first:** changing the Jev API contract; adding non-TypeSafe routing backends
- **Never:** import from `typesafe_ai` in jev_router code; store API keys in plain text in committed files; break existing users' config

## Success Criteria

- [ ] `plugin/helpers/jev.py` exists with `validate_request`, `validate_config`, `async query`, `result_cards`
- [ ] `plugin/hooks.py` exists with `install()` that runs `pip install typesafe-sdk`
- [ ] `_10_jev_route.py` imports from `usr.plugins.jev_router.helpers.jev` — zero `typesafe_ai` imports
- [ ] `_jev_config()` reads from `jev_router` settings namespace, not `typesafe_ai`
- [ ] `config.json` includes `jev_api_key`, `jev_model`, `jev_timeout` fields
- [ ] New `test_jev.py` passes (validation + query + failure cases)
- [ ] All existing 109 tests pass
- [ ] Live smoke test: routing works with a valid TypeSafe key configured in jev_router settings

## Open Questions

1. Should we keep a fallback path that reads from `typesafe_ai` settings if `jev_router` has no key configured? (Recommended: no — cleaner separation; users migrate their key once.)
2. Should `hooks.py` pin a specific `typesafe-sdk` version? (Recommended: yes, pin the current installed version for reproducibility.)
