# Spec: Jev Router — TypeSafe-based auto-routing for Agent Zero

Status: APPROVED (user review 2026-09-21)
Date: 2026-09-21
Owner: user (PUT3R), built by Agent Zero

## Objective

A plugin (`jev_router`) that selects the best provider/model/profile for every LLM call and every new chat by combining **Jev typed judgments** (TypeSafe System One) with an explicit, user-owned routing policy. The user always keeps control; the router is a decision assistant with full visibility, not a black box.

**User stories:**
- As the instance owner, I want trivial messages to use cheap/fast models and hard tasks to use power models, automatically.
- As the instance owner, I want coding tasks to reach a developer-profile subordinate automatically when delegation pays off.
- As the instance owner, I want to include/exclude providers statically, by time of day, and per chat mention — and see why every routing decision happened.
- As the instance owner, I want zero downtime: if Jev or a provider fails, routing degrades to the active preset, loudly logged.

## Locked decisions (user-approved)

| # | Decision | Detail |
|---|---|---|
| 1 | All three roles | chat: per-call routing (P1); utility: per-call (P3); embedding: **per-store fixed model**, never per-call |
| 2 | Dynamic pool | derives from `presets.yaml` + all configured providers; new presets picked up automatically; live catalog prices cached, refreshed weekly |
| 3 | All signals | task class (Choice), complexity (Score), vision need (Noul), delegation gate (Noul), cost/speed/quality dials |
| 4 | Visible log | every routing decision logged with signals, filter outcomes, chosen target, and reason |
| 5 | Profile routing A+B | auto-delegate via `call_subordinate` in-chat AND pre-selection of new-chat profile |
| 6 | Dials, not modes | cost / speed / quality dials; chat mentions and UI toggles set them; empty corners resolved explicitly |
| 7 | Monitoring split | objective telemetry (counts, errors, latency, tokens, cost) + explicit user feedback (thumbs, re-route button); no inferred quality signals |
| 8 | No IQ benchmarks | live catalog metadata only (price, ctx, modality, throughput class); power ranking comes from user presets + accumulated feedback |
| 9 | Availability rules | static include/exclude + time-window schedules + ephemeral chat-mention controls (see below) |
| 10 | Fast path | heuristic skips Jev for trivial messages; judgment cache for repeats |

## Architecture

```
message ─► [0 fast-path check] ─► [1 eligibility filter chain] ─► [2 Jev batch] ─► [3 policy table] ─► [4 profile gate] ─► [5 execute] ─► [6 log+telemetry]
```

### 1. Eligibility filter chain (deterministic, ordered)

Provider/model is routable iff it passes ALL:
1. Static include/exclude (`provider_rules`)
2. Active schedule window (include/exclude/prefer within window)
3. Ephemeral controls from chat mentions / UI toggles (scope + TTL)
4. Dial constraints (e.g. cost=free)
5. Circuit breaker health state (auto-exclusion after consecutive failures, with cooldown)
6. Task requirements (vision capable, context length, modality)

The routing log records **which filter removed what and why** — user rule vs window vs breaker vs dial. An unanswerable 'why did it route to X?' is a bug.

### 2. Jev judgment batch (one request, ~0.5s)
- task_class: Choice over profile/task categories
- complexity: Score 0–2
- vision_needed: Noul
- delegate_worthy: Noul (fresh-context benefit vs cost)
- Fuzzy dial parsing fallback when keywords miss

### 3. Policy table (user-editable YAML)
Maps (task_class, complexity band, dial values, vision) → pool entry. Hard constraints first, soft preferences as tie-breakers. Unsatisfiable combos resolved explicitly + logged.

### 4. Profile gate
`delegate_worthy > threshold` and confidence adequate → `call_subordinate(profile=task_class)`; else advisory hint injected into agent0's loop. New-chat pre-selection (B) runs at chat creation and sets `agent_profile`.

### 5. Execution
Per-call model override via hook (`before_main_llm_call` / `util_model_call_before`); preset switching via `_model_config` scoped config; delegation via `call_subordinate`. No core framework patching.

### 6. Routing log + telemetry
SQLite: decisions (timestamp, message digest, signals, filter outcomes, target, reason, outcome, latency, tokens, est. cost) + feedback (thumb up/down, re-route events). Circuit breaker state per provider. WebUI panel (P2): routing stream, stats per provider/model, dial toggles, include/exclude editor, breaker reset.

## Availability rules (decision #9)

```yaml
provider_rules:
  include: []        # empty = all configured providers
  exclude: []        # hard static blocklist

schedules:           # first matching window wins; avoids conflict resolution
  - name: daytime-quality
    window: "08:00-20:00"        # midnight wrap supported: "22:00-06:00"
    days: [mon, tue, wed, thu, fri]
    timezone: instance            # from settings (America/Chicago here)
    prefer: [zai_coding]          # soft boost
  - name: night-free
    window: "22:00-06:00"
    prefer: [openrouter, a0_venice]
  - name: weekend-no-paid
    days: [sat, sun]
    exclude: [zai_coding]
```

Ephemeral (chat-mention, highest precedence below explicit UI):
- 'stop using zai tonight' → session-scoped exclude, TTL until chat end or stated expiry
- 'use free models for this one' → task-scoped dial constraint

**Precedence chain:** chat mention > UI toggle > schedule window > Jev judgment > active preset. Circuit breaker overrides all for health, logged distinctly.

**Deliberately simple:** windows + days only. No cron expressions, holidays, or exceptions — that is a calendar engine, not a router. Extend later only if a real need appears.

## Tech Stack

- Python 3.12 on `/opt/venv-a0` (framework side); plugin lives in `usr/plugins/jev_router/`
- Reuse `typesafe_ai` plugin Jev client (no new HTTP stack)
- Policy: YAML; telemetry: SQLite; WebUI: plugin extension surfaces
- Hooks: `extensions/python/before_main_llm_call/`, `util_model_call_before/`, chat-creation point for B

## Project Structure

```
usr/plugins/jev_router/
  plugin.yaml
  config.json            # scoped config (enabled, thresholds, breaker params)
  routing-policy.yaml    # user-editable policy + availability rules
  extensions/python/
    before_main_llm_call/_10_jev_route.py
    util_model_call_before/_10_jev_route_utility.py   (P3)
  helpers/
    eligibility.py  jev_batch.py  policy.py  gate.py  telemetry.py  fastpath.py
  webui/
    routing-panel.html  dials.html  stats.html
  tests/
    test_eligibility.py  test_policy.py  test_gate.py  test_fastpath.py  test_hooks.py
```

## Code Style

Follow framework conventions (see `/a0/AGENTS.md` chain). Example:

```python
async def route(agent, loop_data) -> RouteDecision:
    pool = eligibility.filter_pool(await policy.load())
    if fastpath.is_trivial(loop_data):
        return RouteDecision.default(pool, reason="fast-path: trivial message")
    signals = await jev_batch.judge(state_from(loop_data))
    return policy.resolve(pool, signals)
```

Pure, typed, small functions; every branch returns a reason string that lands in the log.

## Testing Strategy

- TDD (test-driven-development skill): tests first for policy, eligibility, gate, fast-path
- Unit: window math incl. midnight wrap; precedence chain; breaker cooldown; dial parsing
- Integration: hooks fire with mocked Jev; Jev failure → preset fallback; delegation threshold
- Verification: `/opt/venv-a0/bin/python -m pytest usr/plugins/jev_router/tests/`

## Boundaries

- **Always:** fall back to active preset on any router failure; log every decision; honor explicit user choice above all
- **Ask first:** new dependencies; changes to settings schema; touching `presets.yaml`
- **Never:** patch core framework files; route embeddings per-call; silently persist ephemeral controls beyond their TTL; import external benchmark scores

## Success Criteria

- [ ] Every routed call produces a log entry: signals → filter outcomes → target + reason
- [ ] Jev unreachable → calls still succeed via active preset, fallback logged
- [ ] Trivial messages skip Jev (fast-path) with < 50 ms router overhead
- [ ] Include/exclude honored, including midnight-wrapping windows, in instance timezone
- [ ] 'use free models' in chat changes the next call's routing and is logged
- [ ] Delegation gate spawns correct profile subordinate on qualifying tasks; advisory hint otherwise
- [ ] Telemetry shows per-provider calls, errors, p50/p95 latency, tokens, est. cost
- [ ] Circuit breaker auto-excludes failing provider and recovers after cooldown

## Phases

| Phase | Contents | Useful alone? |
|---|---|---|
| P1 Core | chat-role routing, profile A+B, Jev batch, policy table, static include/exclude, visible log, preset fallback | yes |
| P2 Control | dials + chat mentions, schedules, ephemeral controls, SQLite telemetry, WebUI panel, circuit breaker | yes |
| P3 Extent | utility-role routing, per-store embedding selection, per-model stats report | yes |

## Resolved Questions (user answers 2026-09-21)

1. New-chat profile pre-selection (B) applies to **WebUI and API-created chats** alike.
2. UI dial presets: **Free / Balanced / Max Quality**.
3. Delegation threshold default: **0.6**, configurable.
