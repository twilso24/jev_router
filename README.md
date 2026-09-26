# jev_router

Standalone TypeSafe Jev-based auto-routing for Agent Zero. Classifies each incoming chat message (task class, complexity, vision, delegation-worthiness) in one fast Jev batch and routes the LLM call to the best provider/model from your `_model_config` presets. An optional mid-chat profile switcher re-evaluates the agent profile as the task changes. Pure-code policy, never-raise fallback to the active preset on any failure.

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
- **Chat mentions**: per-message dials (`stop using zai`, `use venice`, `use free models`) with optional TTL (`tonight`, `today`, `for N hours`). Quoted content (fenced code blocks, comment lines, blockquotes, inline backtick spans) is stripped before parsing, so pasting policy examples or tool output cannot trigger dials.
- **Circuit breaker**: auto-excludes providers on `breaker_threshold` build failures; recovers on success or cooldown expiry. Overrides all other rules for health.

### Dynamic Profile Switching (opt-in)
- **Mid-chat switching**: from message 2, one Jev judgment per user message (while the chat is idle) checks the task class. A switch needs confidence >= `dynamic_switch_threshold`, `dynamic_switch_consecutive` matching judgments in a row, and the `dynamic_switch_cooldown_seconds` per-profile cooldown.
- **Respects the user**: manual profile choices always win; only the main chat profile is switched; preselect owns message 1. Requires `delegation_mode: auto` and `chat_preselect: true`.
- **Fail-safe**: any error keeps the current profile; decisions are logged under the `[dynamic-switch]` tag in the debug log.

### Fit-Aware Model Selection (P5)
- **Dynamic fit judgment**: Jev judges a `preset_fit` choice over the live pool (preset/provider/vision are in the judgment state) with `preset_fit_confidence`. A confident fit (>= `fit_min_confidence`, default 0.6) wins the call with a `[fit]` tag — but only when the pick is in the judged band's order, present in the filtered pool, and vision-capable. Every other case keeps the configured band decision unchanged.
- **Profile-aware judgments**: the active agent profile enters the judgment state (`profile_match` judged per call) and joins the per-session decision cache key, so cached decisions never leak across profiles. Switching profiles remains dynamic-switch's opt-in job; fit only picks the model.
- **Telemetry**: every decision row records `preset_fit`, `fit_confidence`, `profile_match`, and `fit_used` (idempotent SQLite migration for existing DBs).
- **Settings UI**: *Fit-aware model selection* toggle + *Fit confidence floor* (0-1). Panel shows `profile:<name>` and `fit` / `fit-skipped` chips on recent decisions.

### Telemetry & Auto-Tune (P2/P3)
- **Real-call tracking**: Every routed model is instrumented at build time. Real API outcomes (ok/fail, duration, error) feed the circuit breaker and persist to the `calls` table.
- **State-aware auto-tune**: Persisted `auto_tune` flag in `routing-policy.yaml`, defaulting ON when the key is absent (explicit values win; missing files fail safe to off). When ON, the router ranks band orders from live call outcomes on every call (`[auto-tune]` tag in reasons).
- **Per-preset evidence floors**: a preset needs at least 10 own ok+fail observations before auto-tune will rank it; qualified presets rank healthy-first/failing-last, unproven presets keep their configured relative order behind them. One healthy call can never jump a preset to #1.
- **Band pins**: pin any band in the panel to freeze its order against auto-tune, the performance dial, and auto-wire (manual wins). The panel shows a change feed of what auto-tune promoted and why.
- **Performance dial**: `cost saver` / `balanced` / `max quality` re-ranks band emphasis on every call; explicit emphasis outranks auto-tune, pinned bands keep file order. Preset names without an exact tier entry classify by weighted keywords (power/max/expensive/unhinged vs fast/cheap/free/local/efficiency), so verbose pool names like *High Power and Free* tier correctly.
- **Delegation 2.0**: gate recommendations inject a structured `JEVDIALOG` data block (profile, task class, confidence, reason). `advise` mode suggests, `auto` mode directs; opt-in auto-execution (off by default) upgrades confident delegations to first-action directives, once per message. Decision rows show `advised` / `directed` chips.

Presets added to the chat pool become routable without hand-editing policy.

- **Automatic wiring:** on the next routed call the router compares the live pool fingerprint with `routing-policy.yaml`, appends new presets to the **tail of every complexity band**, and prunes names that are no longer in the pool. One fingerprint change triggers one sync.
- **Names stay opaque:** a new preset starts as a fallback candidate, so promote it in the panel (or the live policy) to give it a useful position; there is no task-class matching by name.
- **Idempotent and never-raise:** an unchanged policy is not rewritten, and a failed sync never breaks routing.
- **Panel visibility:** the Band Tuning card shows `+ added` / `- pruned` chips plus any presets that are still unwired.
- **State sidecar:** `wire-state.json` records the last applied sync and is git-ignored because it is runtime state, not configuration.

### WebUI

- **Settings modal** (`Settings → External → Jev Router`): routing on/off, API key with env fallback, Jev model, HTTP timeout, judgment budget, delegation threshold/mode, new-chat pre-selection, dynamic profile switching (toggle, confidence, streak, cooldown), breaker threshold/cooldown.
- **Right-canvas panel**: Shows routing stream, circuit-breaker state with reset buttons, and provider exclude chips.
- **State-aware chips**: Each provider chip shows live state (⛔ tripped / excluded / failing / healthy) with live actions (click to reset breaker or toggle exclude).
- **Diff-guarded polling**: 20s auto-refresh only updates the DOM when data changes (no flash, no typing clobber).
- **Endpoints**: `/api/plugins/jev_router/routing_stats`, `/routing_breaker`, `/routing_policy` (read/write/tuning/set_auto_tune/wire_sync).

## Configuration

### Settings (config.json)
- `enabled` (true): master on/off.
- `jev_api_key` (""): TypeSafe API key; blank falls back to the `TYPESAFE_API_KEY` secret/env var.
- `jev_model` (jev-latest): pin a Jev version available to your account.
- `jev_timeout` (30): per-TypeSafe HTTP attempt, seconds (1–300).
- `jev_timeout_s` (5.0): judgment budget per attempt. A timed-out judgment is retried once before falling back to the active preset (worst case is about twice the budget).
- `delegation_threshold` (0.6), `delegation_mode` (advise|auto).
- `chat_preselect` (true): Jev suggests the agent profile for new chats.
- `dynamic_switch_enabled` (false): opt-in mid-chat profile switching.
- `dynamic_switch_threshold` (0.7): minimum Jev confidence for a judgment to count toward a switch.
- `dynamic_switch_consecutive` (2): matching judgments in a row required before switching.
- `dynamic_switch_cooldown_seconds` (30): minimum time between switches to the same profile.
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
cd /a0/usr/projects/jev_router && /opt/venv-a0/bin/python -m pytest tests/ -q
```
**30 suites, 373 tests** covering pool, eligibility, fastpath, policy, router, signals, schedules, mentions, circuit breaker, call tracker, telemetry, tuning, webui data, bundled Jev helper, settings-UI wiring, extension behavior (no-key guard, failure-cache discipline), new-chat profile pre-selection (gate, decision logic, and hooks for both API and WebUI chat creation), and dynamic profile switching (policy state, streak/cooldown logic, and extension wiring), auto-wiring (band-order sync, pruning, wire state, route-trigger wiring, and the policy API action), per-file import isolation in the combined pytest run, and fit-aware routing (Jev fit/profile questions, constrained fit-honoring resolve, telemetry fit columns and migration, router config passthrough, extension profile wiring, and panel data exposure), plus the performance dial (tier ranks, fuzzy keyword tiers, pin protection), structured delegation advisory and auto-execution (session-scoped digest claims), and post-ship security hardening (atomic policy writes, generic API errors, task-class whitelist).

## Safety boundaries
- The hook **never raises**: any error keeps the framework model.
- Embedding models are NOT routed (vector consistency).
- Disabled config = zero behavior change.
- Dynamic switching is opt-in and never overrides a manually chosen profile.
- Single switch: the plugin toggle in Plugin Settings is the ONLY on/off.
- No Jev client is built without a key: blank key + missing `TYPESAFE_API_KEY` = routing falls back to the active preset, logged.

## Development
- **TDD mandatory**: failing test first, watch it fail, implement, watch it pass.
- **Framework restart** required after changes to `helpers/` modules (sys.modules cache). Extensions hot-load per chat.
- **Test isolation**: `tests/conftest.py` isolates each test file's import environment so `python -m pytest tests/` matches per-file runs (the framework `helpers` namespace package is shadowed by the plugin's regular `helpers` package once the project root is on `sys.path`).
- **Sync rule**: this canonical workspace syncs to deployed `/a0/usr/plugins/jev_router` only after tests pass. Runtime files (`routing-policy.yaml`, `config.json`) are excluded from syncs to preserve live edits.
