# Implementation Plan: jev_router (P1 Core)

Companion to `docs/specs/jev-router.md` (APPROVED). This plan covers Phase 1 (Core); P2/P3 plans follow after P1 acceptance.

## Architecture Decisions (grounded in source)

- **Override point**: `chat_model_call_before` hook in `agent.py` `call_chat_model()` — the extension receives mutable `call_data` with `model`, `messages` keys and may swap `call_data["model"]` before `unified_call`. Cleaner than `before_main_llm_call` (has actual messages; fires once per LLM call, not per loop iteration).
- **Model construction**: build `LiteLLMChatWrapper` instances from policy entries via `models.py` (`ModelConfig.build_kwargs`, `get_rate_limiter`) — same path presets use.
- **Jev client**: reuse `usr/plugins/typesafe_ai/helpers/jev.py` (`query(client, state, questions, model)`). No new HTTP stack.
- **Pool source**: parse `usr/plugins/_model_config/presets.yaml` + provider metadata from `_model_config/provider_metadata.yaml`; cache in memory, re-read on mtime change.
- **Profiles**: delegation via `call_subordinate` tool profile keys (developer, researcher, hacker, code-reviewer, security-auditor, test-engineer); new-chat pre-selection reads `agent_profile` at chat creation (WebUI + API both pass through shared init path — verify exact call site in Task 8).

## Task List

### Phase 1: Foundation

- [ ] **Task 1: Plugin skeleton + pool loader**
  - Acceptance: plugin dir with plugin.yaml (name jev_router, always_enabled false), config.json defaults (enabled, thresholds, delegation_threshold=0.6), helpers/pool.py loads presets.yaml into typed PoolEntry list (provider, model, ctx, vision, cost_tier); unknown yaml fields tolerated.
  - Verify: pytest test_pool.py (loads real presets.yaml, 3 presets parsed; malformed entry skipped with warning)
  - Files: plugin.yaml, config.json, helpers/pool.py, tests/test_pool.py
  - Deps: none. Size: S.

- [ ] **Task 2: Eligibility filter chain**
  - Acceptance: helpers/eligibility.py applies static include/exclude from routing-policy.yaml in order; each removal returns (entry, filter_name, reason); empty result → returns (active_preset, 'fallback:empty_pool').
  - Verify: pytest test_eligibility.py (include-only, exclude, empty-pool fallback)
  - Files: helpers/eligibility.py, routing-policy.yaml, tests/test_eligibility.py
  - Deps: 1. Size: S.

- [ ] **Task 3: Jev signal batch**
  - Acceptance: helpers/signals.py builds one batch (task_class Choice over 7 profile categories + other, complexity Score 0-2, vision_needed Noul, delegate_worthy Noul); consumes last user message + attachments list; returns Signals dataclass or None on failure/timeout (2s budget).
  - Verify: pytest test_signals.py with mocked jev.query (success shape, failure→None, timeout→None)
  - Files: helpers/signals.py, tests/test_signals.py
  - Deps: 1. Size: M.

### Checkpoint A: Foundation
- [ ] All foundation tests green; pool parses live presets.yaml

### Phase 2: Core Features

- [ ] **Task 4: Policy resolver + routing log**
  - Acceptance: helpers/policy.py maps (signals, dials) → PoolEntry via routing-policy.yaml table (complexity bands 0-0.66 light / 0.67-1.33 medium / 1.34-2 heavy; vision requirement hard filter); telemetry.py writes SQLite row per decision (ts, msg_digest, signals, filter_outcomes, target, reason); every branch returns reason string.
  - Verify: pytest test_policy.py (band boundaries, vision hard filter, unsatisfiable→explicit compromise+log); sqlite row exists after fake decision
  - Files: helpers/policy.py, helpers/telemetry.py, tests/test_policy.py
  - Deps: 2,3. Size: M.

- [ ] **Task 5: Fast path**
  - Acceptance: helpers/fastpath.py returns trivial verdict (<50ms, no LLM) for short plain messages with no attachments/code/tool-context; router uses it to skip Jev and route to light entry.
  - Verify: pytest test_fastpath.py (trivial detection, non-trivial passthrough)
  - Files: helpers/fastpath.py, tests/test_fastpath.py
  - Deps: 4. Size: S.

- [ ] **Task 6: chat_model_call_before extension (the router core)**
  - Acceptance: extensions/python/chat_model_call_before/_10_jev_route.py — disabled→passthrough; enabled→pool→fastpath→signals→policy; on any exception or signals=None → keep call_data model, log fallback. Never raises. Adds routing decision to loop data for visibility.
  - Verify: pytest test_hooks.py with fake agent/call_data (swap happens, fallback on Jev failure, disabled passthrough); manual smoke on live instance
  - Files: extensions/python/chat_model_call_before/_10_jev_route.py, tests/test_hooks.py
  - Deps: 4,5. Size: M.

- [ ] **Task 7: Delegation gate (A)**
  - Acceptance: helpers/gate.py decides delegate vs advisory using delegate_worthy ≥ 0.6 and task_class in subordinate profiles; in-chat hook path injects advisory hint below threshold; above threshold triggers call_subordinate profile recommendation into loop (first P1: advisory + explicit recommendation only — auto-spawn behind config flag delegation_mode: advise|auto, default advise).
  - Verify: pytest test_gate.py (threshold math, unknown class→advisory, config flag)
  - Files: helpers/gate.py, extensions/python/message_loop_start/_10_jev_delegation.py, tests/test_gate.py
  - Deps: 3. Size: M.

- [x] **Task 8: New-chat profile pre-selection (B)**
  - Implementation: two hooks cover both chat creation paths:
    - API path: implicit hook at `initialize.initialize_agent` (for POST `/api/message`) — live smoke test passed
    - WebUI path: implicit hook at `user_message_ui` (for POST `/message_async`) — tested
  - Gates: main agent only; fresh chat only (idle + empty log + profile still default); enabled + chat_preselect + delegation_mode=auto + API key
  - Swap pattern: sanctioned profile-swap (initialize_agent → assign config → save_tmp_chat → mark_dirty)
  - Never raises; explicit user choice always wins
  - Deps: 3. Size: M.

### Checkpoint B: Core E2E
- [ ] Live instance: message routes per policy, routing log visible in DB, Jev-kill test falls back to preset

### Phase 3: Verification & Docs

- [ ] **Task 9: Failure drills + docs**
  - Acceptance: simulated Jev outage → preset fallback logged; malformed policy yaml → safe defaults + loud warning; README.md with install/config/policy examples; telemetry query CLI (last N decisions).
  - Verify: pytest full suite green; failure drill script passes; README reviewed
  - Files: README.md, tests/test_failure.py, helpers/report.py
  - Deps: 6,7,8. Size: S.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| chat_model_call_before call_data contract differs at runtime | High | Task 6 starts with a logging-only extension probe on live instance |
| Jev latency spikes >1s | Med | 2s timeout, fastpath, judgment cache keyed on msg digest (P2) |
| New-chat creation has no hook point | Med | Task 8 verifies; fallback = advisory first-message hint instead of pre-init |
| Parallel streams (swarm/subordinates) trigger router repeatedly | Med | Route once per context_id+msg digest; cache decision |

## Boundaries (from spec)
Never patch core files; never raise from the hook; fallback to active preset always; ask before touching presets.yaml.
