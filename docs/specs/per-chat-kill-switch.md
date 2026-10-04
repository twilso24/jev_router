# Spec: Per-Chat Jev Router Kill-Switch

## Objective

Jev Router's master kill-switch today is the global `enabled` flag in
`config.json`, edited in the Settings config UI. It is global and buried —
useless for "turn routing off in *this* chat only".

This feature adds a per-chat kill-switch rendered in the main interface, in
the model-context strip above the composer (the row showing the active model
preset and agent profile — the location marked in the user's screenshot).

User story: *As a chat user, I can toggle Jev routing off for the current
chat from the context strip; the choice persists for that chat across
reloads and is honored by every routing hook, while other chats keep their
own state.*

### ASSUMPTIONS (correct me now)
1. The control renders via the plugin's `extensions/webui/model-context-strip-end/`
   directory (same extension point `a0_reasoning_effort` uses), so no core
   framework WebUI files are modified.
2. Per-chat state is stored server-side with `context.set_data(JEV_KEY,
   {...})` + `save_tmp_chat(context)` + `mark_dirty_for_context(...)`, mirroring
   the reasoning-effort API handler — survives reloads, not browser-local.
3. Semantics: the per-chat switch *overrides* the global `enabled` flag for
   that chat only. Global off ⇒ off everywhere regardless of chat state;
   global on ⇒ chat switch decides.
4. Effective state: OFF in a chat when global `enabled` is false OR the
   chat-level flag says off. Default for a chat with no stored state follows
   the global flag.
5. Hooks that must honor it: `chat_model_call_before/_10_jev_route.py`
   (JevRouteChatCall), the preselect hooks (`_10_jev_preselect.py` in
   `initialize_agent` and `user_message_ui`), and `_20_jev_dynamic_switch.py`.
   They share one helper (e.g. `helpers/gate.py::routing_allowed(agent)`) so
   the rule is defined once.
6. Toggling while the chat is running returns HTTP 409 (same contract as
   reasoning-effort: change applies after the current run finishes).
7. The settings-config global switch stays as-is (instance-wide master);
   this feature is additive, not a move that removes it.

## Tech Stack

Existing only: plugin API handler (`api/`), Python extension hooks, an
Alpine.js store + HTML fragment in `extensions/webui/model-context-strip-end/`,
`api.callJsonApi` / `createStore(/js/AlpineStore.js)`, pytest. No new runtime
dependencies.

## Commands

- Focused tests: `/opt/venv-a0/bin/python -m pytest tests/ -q -k "gate or kill or strip"`
- Full suite: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Sync to deployed: copy changed runtime files to `/a0/usr/plugins/jev_router/`
  (extension files hot-load per chat; no framework restart for WebUI/extension
  changes; helpers/ changes DO require a framework restart).

## Project Structure (files touched)

- `helpers/gate.py` — add `routing_allowed(context/agent)` single source of
  truth (global cfg AND per-chat flag).
- `api/routing_session.py` (or new `api/routing_kill.py`) — `get`/`set`
  actions keyed by `context_id`, 409 while running, persists via context data.
- `extensions/python/chat_model_call_before/_10_jev_route.py` and the two
  preselect hooks + dynamic_switch — consult `routing_allowed()` instead of
  raw `cfg.get('enabled')`.
- `extensions/webui/model-context-strip-end/jev-kill-switch.html` +
  `webui/jev-kill-switch-store.js` — toggle button in the context strip.
- `tests/test_gate.py` (new) — contract tests for the effective-state rule and
  API semantics; extend existing hook tests where they pin `enabled` behavior.

## Code Style

Mirror the reasoning-effort extension: Alpine store with `refresh(contextId)`,
`select/toggle(contextId)`, request-id guarding, `x-effect` placement before
`.agent-profile-anchor`; backend handler returns plain dicts, guards with
`context.is_running()`.

## Testing Strategy

- TDD mandatory: failing tests first in `tests/`:
  - `test_routing_allowed_truth_table` — global off ⇒ off; global on + chat
    off ⇒ off; global on + chat unset ⇒ on; global on + chat on ⇒ on.
  - `test_kill_switch_api_set_get_roundtrip` — set persists via context data;
    get returns stored value; missing state defaults to follow-global.
  - `test_kill_switch_api_409_while_running`.
  - `test_hooks_use_gate_helper` — routing/preselect hooks call
    `routing_allowed()` (source-level contract) rather than raw cfg read.
- Strip HTML contract test: extension file exists, contains the toggle and
  store import (mirrors panel-consistency style).
- Manual: hard-refresh WebUI, toggle in strip, send message in that chat
  (no routing entries appear in Recent Decisions), switch chats — state is
  per-chat, reload persists.

## Boundaries

- Always: single-source `routing_allowed()` helper; 409 while running; keep
  global settings switch functional; per-chat state server-side only.
- Ask first: also exposing the switch in the right-canvas panel; changing the
  global `enabled` semantics; subagent/child-context inheritance.
- Never: write per-chat state to `config.json`/`routing-policy.yaml`; modify
  core framework WebUI files; remove the settings-config switch.

## Success Criteria

1. Toggle visible in the context strip for the selected chat; reflects
   effective state (shows disabled when global off).
2. Turning it off for a chat stops all routing hooks in that chat only;
   other chats unaffected.
3. State persists across reloads (server-side context data).
4. `pytest tests/` fully green.

## Open Questions

1. Label/visual: a small chip (e.g. `route on` / `route off`) with a
   material icon — acceptable?
2. Subagent contexts: inherit the parent chat's kill state, or independent?
   Proposed: inherit (routing decisions are chat-scoped intent).
