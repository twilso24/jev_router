# jev_router

Standalone TypeSafe Jev-based auto-routing for Agent Zero. Classifies each incoming chat message (task class, complexity, vision, delegation-worthiness) in one fast Jev batch and routes the LLM call to the best provider/model from your `_model_config` presets. Pure-code policy, never-raise fallback to the active preset on any failure.

No other plugins required: the plugin bundles its own Jev helper and installs the `typesafe-sdk` Python package automatically via its lifecycle hook.

## Setup

1. **Install** the plugin through the Agent Zero Plugin Manager. On install, `hooks.py` runs `pip install typesafe-sdk` into the framework environment (safe to rerun; shared packages are never removed on uninstall).
2. **Open Settings**: Agent Zero **Settings → External → Jev Router → Settings**. Project- and agent-profile-scoped overrides are supported.
3. **Add your TypeSafe API key** (one of):
   - Paste it into the **TypeSafe API key** field (masked input with show/hide), or
   - Leave the field blank and set `TYPESAFE_API_KEY` in Agent Zero's secrets or environment — the blank field falls back to it.
   - Need a key? Use the **Get API key** link in the settings UI or visit <https://console.typesafe.ai/>.
4. Done. The first routed chat message confirms it in the debug log and telemetry DB.

## Architecture

- **Hook**: Intercepts `chat_model_call_before` to route the model per message.
- **Jev Judgment**: Classifies message complexity, task class, vision needs, and delegation worthiness.
- **Policy Engine**: Maps signals to presets using complexity bands, schedules, mentions, and health overrides.
- **Telemetry**: Logs every decision and real API-call outcome to SQLite.

## Features

### Core Routing (P1)
- **Model routing** per message via complexity band -> preset. ALL presets are first-class in every band (defaults: light->Fast, medium->Default, heavy->Power; full order per band in `routing-policy.yaml` `band_orders`, user-editable, re-read every call).
- **Fast path**: trivial short conversational messages skip Jev entirely.
- **Delegation advice**: when `delegate_worthy >= threshold`, a SystemMessage advisory suggests `call_subordinate`.
- **Eligibility**: static provider include/exclude in `routing-policy.yaml`.
- **Schedules**: time-based provider exclude/prefer (first matching window wins, midnight wrap supported).
- **Chat mentions**: per-message dials (`stop using zai`, `use venice`, `use free models`) with optional TTL (`tonight`, `today`, `for N hours`).
- **Circuit breaker**: auto-excludes providers on `breaker_threshold` build failures; recovers on success or cooldown expiry. Overrides all other rules for health.

### Telemetry & Auto-Tune (P2/P3)
- **Real-call tracking**: Every routed model is instrumented at build time. Real API outcomes (ok/fail, duration, error) feed the circuit breaker and persist to the `calls` table.
- **State-aware auto-tune**: Persisted `auto_tune` flag in `routing-policy.yaml`. When ON, the router ranks band orders from live call outcomes on every call (`[auto-tune]` tag in reasons). No manual Suggest needed.
- **Band tuning**: Deterministic suggestion from telemetry (healthy first, failing last, current order breaks ties). Panel allows manual ▲▼ reorder and one-click Apply.

### WebUI

- **Settings modal** (`Settings → External → Jev Router`): routing on/off, API key with env fallback, Jev model, HTTP timeout, judgment budget, delegation threshold/mode, new-chat pre-selection, breaker threshold/cooldown.
- **Right-canvas panel**: Shows routing stream, circuit-breaker state with reset buttons, and provider exclude chips.
- **State-aware chips**: Each provider chip shows live state (⛔ tripped / excluded / failing / healthy) with live actions (click to reset breaker or toggle exclude).
- **Diff-guarded polling**: 20s auto-refresh only updates the DOM when data changes (no flash, no typing clobber).
- **Endpoints**: `/api/plugins/jev_router/routing_stats`, `/routing_breaker`, `/routing_policy` (read/write/tuning/set_auto_tune).

## Configuration

### Settings (config.json)
- `enabled` (true): master on/off.
- `jev_api_key` (""): TypeSafe API key; blank falls back to the `TYPESAFE_API_KEY` secret/env var.
- `jev_model` (jev-latest): pin a Jev version available to your account.
- `jev_timeout` (30): per-TypeSafe HTTP attempt, seconds (1–300).
- `jev_timeout_s` (2.0): total judgment budget per message before falling back to the active preset.
- `delegation_threshold` (0.6), `delegation_mode` (advise|auto). In `auto`, new chats also get profile pre-selection.
- `chat_preselect` (true): auto-select the agent profile for new chats from a Jev judgment on the first message. Applies to WebUI and API chat creation; new/idle chats only; an explicit profile choice always wins. Set `delegation_mode: auto` for it to take effect.
- `breaker_threshold` (3), `breaker_cooldown_hours` (1.0).

### `routing-policy.yaml`
- `provider_rules`: include/exclude lists.
- `band_orders`: complexity-band preference orders over presets.
- `schedules`: time-based rules.
- `auto_tune`: boolean flag for state-aware band ranking.

### `presets.yaml`
- Re-read from disk on **every** chat model call; no server-side pool cache.
- Jev receives the eligible chat-role presets as `available_models`.
- Decision cache keys include a pool fingerprint: editing presets invalidates cached decisions immediately.

## Inspect decisions
```bash
/opt/venv-a0/bin/python /a0/usr/plugins/jev_router/report.py 20
```

## Tests
```bash
cd /a0 && for t in /a0/usr/plugins/jev_router/tests/test_*.py; do /opt/venv-a0/bin/python "$t"; done
```
**21 suites, 203 tests** covering pool, eligibility, fastpath, policy, router, signals, schedules, mentions, circuit breaker, call tracker, telemetry, tuning, webui data, bundled Jev helper, settings-UI wiring, extension behavior (no-key guard, failure-cache discipline), and new-chat profile pre-selection (gate, decision logic, and hooks for both API and WebUI chat creation).

## Safety boundaries
- The hook **never raises**: any error keeps the framework model.
- Embedding models are NOT routed (vector consistency).
- Disabled config = zero behavior change.
- Single switch: the plugin toggle in Plugin Settings is the ONLY on/off.
- No Jev client is built without a key: blank key + missing `TYPESAFE_API_KEY` = routing falls back to the active preset, logged.

## Development
- **TDD mandatory**: failing test first, watch it fail, implement, watch it pass.
- **Framework restart** required after changes to `helpers/` modules (sys.modules cache). Extensions hot-load per chat.
- **Sync rule**: canonical `plugin/` syncs to deployed `/a0/usr/plugins/jev_router` only after tests pass. Runtime files (`routing-policy.yaml`, `config.json`) are excluded from syncs to preserve live edits.
