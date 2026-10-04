# Changelog

All notable changes to the Jev Router plugin.

## [0.7.13] - 2026-10-04

### Added
- **Reasoning effort for routed calls** (Option B + gap fix, spec: `docs/specs/fit-aware-routing.md`): effort now follows the complexity band Jev already judged - light->low, medium->medium, heavy->high - applied to the routed model's kwargs. The chat-level override from the `a0_reasoning_effort` plugin always wins (this closes the gap where routed models bypassed `agent.get_chat_model()` and silently lost the user's override). Capability-gated: `supports_reasoning()` probes the LiteLLM registry so unsupported models never receive the param. GLM-5.3 parity: effort moves into `extra_body` (plus `thinking:{type:enabled}` for zai/zai_coding) and only the low/high/max ladder passes, matching `a0_reasoning_effort`. New `helpers/reasoning.py` (band map, capability probe, chat-override reader, `resolve_effort`, `apply_to_model_kwargs`, `apply_for_route`); `RouteResult` gains `band` + `entry`; `execute()` applies effort after routing. 36 reasoning tests across `test_reasoning_effort.py` + `test_reasoning_effort_wiring.py`.
- **Local model cold-start tracking** (spec: `docs/specs/fit-aware-routing.md`): new `helpers/local_model_tracker.py` records per-provider idle time for local providers (e.g. `lm_studio`); a call after >5 min idle that takes >10 s is confirmed as a cold start and recorded once (`cold_start_count`, `avg_cold_start_ms`, `last_cold_start_ms`). The router brackets `model_factory` with `record_call_start`/`record_call_outcome`; telemetry `calls` table gains `cold_start`, `cold_start_ms` columns (idempotent `_ensure_column` migration). Documents why cold-start latency sits outside the circuit breaker's scope.
- **Context-window pressure detection + tiny-local delegation**: token estimation (4 chars ~= 1 token) compared against the selected local entry's `ctx_length` at the 85% `CONTEXT_PRESSURE_THRESHOLD`. On pressure the router sets `task_class='context_overflow'` so the gate maps to the `tiny-local` profile, and the extension records `context_pressure`, `ctx_length`, `estimated_tokens` in telemetry. `signals.py build_state()` now exposes `ctx_length` per pool model so Jev sees the constraint. Covers every local preset, including the 27,000-ctx utility/XS 2.6B entries.

### Changed
- `RouteResult` carries `band` and `entry` so extensions can act on the judged band and selected preset; fallback paths default them safely.
- Fit-aware routing spec gained a "Local Model Considerations" section documenting both behaviors.

## [0.7.11] - 2026-10-04

### Fixed
- **Auto-tune no longer promotes `Default` to every band** (regression from 0.7.10): a "degraded fallback to global stats" handed the aggregate ranking to every band whenever a band had no per-band evidence - with 0 banded rows (all legacy telemetry is band-less) every band re-ranked from global health, so `Default` (ok=135) headed all three bands again and panel polling displayed/wrote those rearranged orders over the user's curated band tuning. Corrected contract in `suggest_band_orders`: `band_preset_stats` omitted (`None`) = legacy global mode; a dict (even empty `{}`) = **band mode**, where a band with no own evidence keeps the user's file order verbatim and is never re-ranked from global stats. Fixed two truthiness bugs that coerced `None`/`{}` incorrectly (`if band_stats:` and the `is not None` check defeated by `else {}` normalization).
- Both production callers now fetch and pass band stats: `effective_band_orders` (router) and `tuning_report` (panel polling source, `webui_data.py`) - previously both passed only global stats, bypassing per-band ranking entirely.
- Failover test fixture (`test_auto_tune_routes_away_from_failing_preset`) now seeds band-scoped evidence (`band='heavy'`) matching the new telemetry contract; assertion unchanged (failing preset demoted, healthy preset chosen).
- Rewrote the wrongly-encoded `test_fallback_to_global_when_band_stats_missing` into `test_band_mode_never_falls_back_to_global` + `test_global_mode_when_band_stats_not_passed`; added `test_band_without_evidence_keeps_user_order_despite_global_health`, `test_effective_orders_no_band_evidence_returns_file_orders`, `test_band_evidence_still_ranks_when_present`. 481/481 tests pass.

### Behavior notes
- Bands with banded evidence rank per-band (health within that band); bands without keep file order. Legacy band-less rows never influence band ranking.
- The panel "Apply" button writes whatever orders are displayed; with this fix, auto-tune-on polls display file orders until real per-band evidence exists.

## [0.7.10] - 2026-10-03

### Added
- **Per-band auto-tune** (spec: `docs/specs/per-band-auto-tune.md`): auto-tune now ranks each band from its own outcome evidence instead of one global ranking. Root cause fixed: `suggest_band_orders` previously used global per-preset stats, so the globally healthiest preset (Default, ok=135) headed EVERY band - band orders flattened and auto-tune was effectively a no-op. Now:
  - `calls` table gains a `band` TEXT column (idempotent `_ensure_column` migration; legacy rows keep NULL and are excluded from per-band stats).
  - `record_call(..., band=None)` persists the routing band; new `band_preset_call_stats(conn, limit)` aggregates `{band: {preset: {ok, fail}}}` from banded rows only.
  - The extension threads the decision band through the instrument closure: `_instrument(..., band=)` -> `on_outcome` -> `_on_call_outcome(..., band=)` -> `record_call(band=)`. The router call site passes `band=getattr(result, 'band', None)`; kept-model fallbacks record band-less (NULL).
  - `suggest_band_orders(current, pool, preset_stats, band_preset_stats=None)` qualifies and ranks per band using `band_preset_stats[band]` when present, else falls back to the global stats (degraded mode = previous behavior). Per-band evidence floor remains 10 own calls IN THAT BAND. Unqualified presets keep file order after the qualified group; pins still freeze after suggestion.
  - `effective_band_orders` fetches band stats alongside global stats and passes both through.
  - `report.evidence_summary` now returns `band_stats`; `report.py dial` prints a per-band outcomes block when band evidence exists.
  - New guard tests: `tests/test_band_threading.py` (4 tests, extension band threading), band tests in `test_telemetry_calls.py` (7) and `test_tuning.py` (5), `band_stats` tests in `test_report.py` (3). 474/474 tests pass.

### Changed
- Migration note: existing telemetry rows lack band context, so all bands start unqualified and retain file order; per-band evidence accumulates as new calls arrive (gradual re-learning).

## [0.7.9] - 2026-10-03

### Removed
- **Performance dial mechanic removed entirely** (spec: `docs/specs/remove-performance-dial.md`): band orders are now the sole deterministic ranking truth, with auto-tune reordering unpinned bands and pins freezing their file order. Removed `helpers/dial.py`, the `performance_dial` call in `helpers/router.py`, the `dial` field and `apply_dial` in `report.py` (the `report.py dial` CLI subcommand remains as the evidence summary entrypoint but prints no dial column), the settings selector in `webui/config.html`, and the legacy `config.json` key (deleted from live and shipped config). `report.dial_summary` is now `report.evidence_summary` returning `{auto_tune, pins, preset_stats, orders}` with orders exactly equal to the policy file orders. Pin semantics preserved and now covered by `test_pinned_band_skips_auto_tune`. New guard suite `tests/test_dial_removal.py` scans production paths for zero dial references. 458/458 tests pass.

### Changed
- Router band resolution flow is now: tuning (auto-tune or file) → schedules → resolution, with no intermediate re-ranking layer.

## [0.7.8] - 2026-10-03

### Changed
- **Inline plain-text model definitions** (corrected UX): Presets panel now lets users define EXISTING model presets with plain text inline per row. Removed Add preset, Edit, Delete buttons and standalone structured form. Each model preset row has a description textarea (1-300 chars) and Save action calling the new `describe` API.
- **API contract simplified**: Only `list` and `describe` actions remain. `list` returns only model presets (entries with valid `chat` block). `describe` updates only the description field on an existing model preset, preserving all other YAML blocks.
- **Server-side concurrency control**: `describe` and `save` actions serialized via framework `thread_lock` to prevent lost updates under concurrent requests.
- **Focus guard in panel**: Auto-refresh pauses while any description input is focused, preventing clobber of in-progress edits.
- **Spec & tests updated**: Living spec at `docs/specs/plain-text-presets.md` reflects corrected UX. TDD tests cover describe action, list filtering, and panel contract (no Add/Edit/Delete/form).

### Fixed
- `applyAuto` reassignment order fixed so focus-guard activates when toggling auto-refresh.
- Removed unused variables `presetsGuardActive`, `originalApplyAuto` from panel.
- Removed dead `delete` action and `_handle_delete` from API.
- `apply_edit` no longer carries `from` field (users don't edit model preset references).
# Changelog

All notable changes to the Jev Router plugin.

## [0.7.6] - 2026-10-03

### Fixed
- **Presets API "load error":** the framework instantiates handlers as `handler_cls(app, lock)`, but `RoutingPresets.__init__` only accepted `presets_path` — TypeError on every live request (list/save/delete), surfacing as the panel's "load error" with no console errors. The constructor is now framework-compatible (`__init__(app=None, lock=None, presets_path=None)`, calling `super().__init__(app, lock)` when app is provided), so direct test construction still works. New RED-first guard test `test_handler_instantiates_with_framework_args` pins framework-style instantiation — earlier tests passing a `presets_path` kwarg had masked the defect. Remaining save/delete lazy imports use plugin-qualified paths (`usr.plugins.jev_router.helpers`). 448/448 tests pass.
- Note: the framework's `api_handlers` watchdog only watches `/a0/api/` and `/a0/usr/api/` — plugin `api/` changes are not hot-cleared, so a **framework restart** is required to load this fix.

## [0.7.5] - 2026-10-02

### Added
- **Preset Editor in the right-canvas panel:** create/edit/delete presets directly from the Jev Router panel with typed fields (name locked on edit, provider, model, description with 300-char counter, ctx_length/ctx_history sliders, vision switch, rl_* inputs), inline validation matching server rules, atomic writes with `.bak` backup, and auto-wire sync on save/delete. The form pauses auto-refresh to prevent clobbering in-progress edits. API: `plugins/jev_router/routing_presets` (list/save/delete actions).
- **Plain-language preset descriptions affect Jev nuance:** values entered in the form's description field flow into `preset_fit` criteria per v0.7.3, so adding prose like "free, fast, good for trivia" directly shifts Jev's pick.

### Changed
- **Visual uplift:** Linear-inspired palette — electric indigo `#5e6ad2` accent (light) / `#7c7cf8` (dark), dark surface `#1e1f24`, hairline borders. All existing chips/badges inherit the accent automatically.

## [0.7.4] - 2026-10-02

### Changed
- **Auto-wire now runs on every chat-model call.** The fingerprint guard skipped the sync whenever the live pool itself was unchanged, so a hand-edited `routing-policy.yaml` (or any external shrink of band_writes) stayed persistently severed and the panel's preset list silently dropped unwired presets. The sync already writes only on real adds/prunes, so retries are cheap; running it unconditionally heals manual edits on the next turn. Regression tests now assert sync fires on every call while still receiving correct preset names, and the failure-safe path is unchanged.

## [0.7.3] - 2026-10-02

### Added
- **Plain-language preset descriptions:** an optional `description:` field per preset in `presets.yaml` now flows into Jev's `preset_fit` choice criteria and the `available_models` state, so Jev judges nuance (tone, persona, cost tier, speed) instead of bare preset names. Presets without a description keep the technical-facts-only criteria; fingerprinting and band wiring are unaffected. Regression tests cover parsing, defaults, state inclusion, and criteria text.

## [0.7.2] - 2026-10-02

### Fixed
- **Auto-routing collapsed to the Default preset regardless of signals:** band-order preference names (Fast/Efficiency/Power, etc.) were matched verbatim against live preset names, so user-renamed presets (Efficient, High Power) never matched and every band fell through to Default. `policy.resolve()` now matches normalized names (case/spacing-insensitive) plus an explicit alias map (Fast/Efficiency/Efficient, Power/High Power), direct matches always win positionally, and the Jev fit pick uses the same matching. Regression tests cover alias picks per band, positional priority, normalization, and aliased fit picks.
- **Silent band-order drift had no surface:** new `policy.validate_band_orders()` reports order names matching no live preset (direct or alias); the router logs `WARNING band-orders unresolved ...` to the debug log so fallthrough-to-Default becomes visible. Router guard-rail tests cover fired and silent cases.

### Changed
- Shipped `routing-policy.yaml` band_orders now name the real first-class presets (Efficient/Default/High Power); the live deployed copy got the same edit while preserving local rules (ollama exclude, auto_tune flag).

## [0.7.1] - 2026-09-27

### Fixed
- **Panel exclude saves failed with `error: write failed`:** `write_provider_rules` imported `helpers.tuning` via an absolute import that bound to the framework namespace package in the live process (no such module there), the swallowed exception failed every provider exclude/re-include save from the panel chips. Now uses a relative import like the rest of the package. Regression tests: a subprocess test reproducing the live process import graph and a static guard banning absolute `helpers` imports inside the helpers package.
- **Recovered providers stayed flagged as failing in the panel:** the chip "failing" state used raw failure counts with no recency, so one old failure kept an orange flag until 200 newer calls pushed it out. `provider_call_stats` now reports `last_ok` (latest outcome in the window) and the panel flags a provider failing only while its latest recorded outcome is a failure. Regression tests cover both layers.
- **Call outcomes stopped being recorded under the unified-turn chat path:** the framework chat turn now invokes `unified_turn`, but the call tracker wrapped only `unified_call`, so real outcomes (breaker feedback + telemetry) silently vanished and a recovered provider kept its last failure forever. The tracker now wraps both entry points with an in-flight guard (exactly one report per call, delegation-safe, same idempotency and never-raise guarantees). Five regression tests including concurrency.
- **Keep-model fallbacks remained untracked:** when Jev was unavailable, the framework kept its cached chat model, but the extension only instrumented models created by the router. Those fallback calls therefore produced no breaker feedback or telemetry, leaving a recovered provider stuck on an old failure. Fallback models are now instrumented from their framework `a0_model_conf` attribution when available; unattributable models are skipped silently. Extension regression tests cover success, failure, missing attribution, empty-provider skip, and empty-name fallback to provider; the tracker now logs swallowed kept-model instrumentation failures and `is_wrapped` has direct coverage.

## [0.7.0] - 2026-09-25

### Added
- **Performance dial:** new *cost saver / balanced / max quality* setting re-ranks band emphasis per call (explicit emphasis wins over auto-tune; pinned bands keep file order). Unknown presets join the neutral middle rank; malformed configs are no-ops.
- **Auto-tune by default:** a readable `routing-policy.yaml` without an `auto_tune` key defaults ON; explicit values always win; missing/malformed files fail safe to off. Panel shows a one-click auto-tune chip, a change feed of telemetry-ranked promotions, and per-band pins (pinned bands freeze against auto-tune, the dial, and auto-wire).
- **Delegation 2.0:** structured advisory with a machine-readable `JEVDIALOG` data block (profile, task_class, confidence, reason) appended to the LLM context as a SystemMessage. `advise` keeps advisory wording, `auto` uses a directive. New opt-in **delegation auto-execution** (off by default, floor 0.8): high-confidence delegations become first-action directives, fired once per message. Panel decision rows show `advised` / `directed` (+ `·auto`) chips.
- **Per-preset evidence floors:** auto-tune now ranks a preset only after it has at least 10 own ok+fail observations (was: a global 10-call gate let 1-call presets jump to #1). Qualified presets rank healthy-first/failing-last; unproven presets keep their relative order behind them.
- **Simple/Advanced settings:** routing enable, API key, and the performance dial stay primary; the 11 expert knobs moved into a collapsed Advanced section.
- **Dial-aware CLI report:** `report.py dial [config] [policy] [db]` prints the active dial, auto-tune state, pins, per-preset call outcomes, and effective orders (never raises).

### Fixed
- **Delegation advisory actually reaches the model:** the route extension created an injection slot but never assigned the router's advice to it, so advisories were dead code while telemetry still recorded chips.
- A malformed `delegation_threshold` value now falls back to the default 0.6 instead of raising and silently disabling routing for every subsequent message.
- Stats API clamps client-supplied `limit` (negative limits previously returned the full table unbounded).
- Panel auto-wire report collapsed to a one-line summary (age-stamped, expandable, dismissible; reports older than 24h auto-hide) instead of rendering every added/pruned preset as a permanent chip wall.
- **Fuzzy dial tiers:** preset names without an exact tier entry are classified by weighted keywords (power/max/expensive/unhinged vs fast/cheap/free/local/efficiency), so the performance dial works with verbose pool names like *Fast and Free* or *High Power and Free*; keyword ties stay neutral and exact-name maps keep precedence.

### Security
- The advisory payload is explicitly framed as reference-only data (not instructions) to keep the LLM-context injection channel data-only; profile strings still come exclusively from the task-class whitelist.
- Review hardening: dead code removed, auto-exec claim guard gained a reset hook and FIFO-bound test, legacy telemetry DBs verified to gain all newer columns on migration.

## [0.6.0] - 2026-09-25

### Added
- **Fit-aware model selection (P5):** Jev judges a `preset_fit` choice over the live pool (with `preset_fit_confidence`) and a `profile_match` against the active agent profile. A confident fit (>= `fit_min_confidence`) wins the call with a `[fit]` tag only when it is in the judged band's order, present in the filtered pool, and vision-capable; every other case keeps the configured band decision byte-identical to before, and `fit_used` records whether the fit was honored.
- **Profile-aware judgments:** the active agent profile (`agent.config.profile`) enters the Jev judgment state, joins the per-session decision cache key, and every decision row records `preset_fit`, `fit_confidence`, `profile_match`, and `fit_used` (idempotent SQLite migration for existing telemetry DBs).
- **Settings UI:** new *Fit-aware model selection* toggle and *Fit confidence floor* (0-1) fields. Defaults: `fit_enabled: true`, `fit_min_confidence: 0.6`.
- **Panel visibility:** recent decisions show `profile:<name>` and `fit` / `fit-skipped` chips; the stats API exposes the new fields.

### Fixed
- **Auto-tune no longer overrides curated orders on sparse data:** `suggest_band_orders` requires at least 10 total observed calls before re-ranking; below that evidence floor the configured band orders pass through unchanged. Previously a single healthy call promoted that preset to the head of every band on every routed call.
- Telemetry schema aligned with spec: added `fit_confidence REAL` column alongside the fit fields.
- Review hardening: orphaned legacy script runners removed from test files (pytest-only collection, no recursive re-runs), router fit-config read documented, `.jev-fit-skip` panel styling.

## [0.5.0] - 2026-09-25

### Added
- **Auto-wired presets (P4):** adding a preset to the chat pool now makes it routable without hand-editing policy. On the next routed call the router compares the live pool fingerprint with `routing-policy.yaml` and appends new preset names to the tail of every complexity band, pruning names that left the pool. Names stay opaque keys, so a new preset starts as a fallback candidate and is promoted from the panel.
- **Sync visibility in the WebUI panel:** the Band Tuning card shows `+ added` / `- pruned` chips and any presets that are still unwired; `tuning_report` exposes `unwired` and `wire_state` and the policy API gained a `wire_sync` action.
- **Fingerprint-guarded trigger:** the route extension syncs at most once per pool change, and a failed sync never breaks routing.
- **Generated state sidecar:** `wire-state.json` records the last applied sync (git-ignored; runtime state only).

### Fixed
- **Combined pytest run is now order-independent:** `tests/conftest.py` gives each test file its own import environment (`sys.modules` / `sys.path`), so `python -m pytest tests/` matches per-file results. Root cause was structural: the framework `helpers` namespace package is shadowed by the plugin's regular `helpers` package once `python -m pytest` seeds the project root into `sys.path`. The previously recommended per-file loop is no longer required, and runtime policy/config stay excluded from syncs as before.

### Changed
- README documents auto-wire behavior, the `wire_sync` endpoint, the combined test command, and the import-isolation constraint.
- `plugin.yaml` bumped to 0.5.0; generated `wire-state.json` ignored by git.

## [0.4.1] - 2026-09-24

### Fixed
- **Chat mentions no longer fire on quoted text:** fenced code blocks, comment lines, blockquotes, and inline backtick spans are stripped before dial parsing. Pasting policy examples (such as the `routing-policy.yaml` help comment) or tool output can no longer exclude every provider and empty the pool.
- **Judgment failures are observable:** `signals.judge` logs `[signals] judge failed: <ExceptionType>: <message> elapsed_ms=<ms> timeout_s=<s> attempts=<n>` instead of silently swallowing exceptions.

### Changed
- **Bounded retry for hung Jev judgments:** a `TimeoutError` gets exactly one retry; every other exception still fails fast. Motivated by production telemetry showing intermittent server-side hangs consuming the full budget; in live traffic the retry recovered real failures within 0.3-1.4 s.
- README refreshed: mention quoting behavior, judgment retry and observability, per-attempt timeout semantics, corrected test counts (23 suites, 253 tests).

## [0.4.0] - 2026-09-24

### Added
- **Dynamic Profile Switching (opt-in):** mid-chat automatic profile switching from message 2. One Jev judgment per user message while the chat is idle; a switch requires confidence at or above `dynamic_switch_threshold`, `dynamic_switch_consecutive` matching judgments in a row, and the per-profile cooldown. Manual profile choices always win; only the main chat profile is switched; message 1 belongs to preselect. Never raises - any failure keeps the current profile.
- **Settings UI:** new fields for dynamic switching (enable toggle, confidence threshold, consecutive count, cooldown) alongside the existing routing settings.

### Changed
- Default `jev_timeout_s` raised from 2.0 to 5.0 seconds: live telemetry showed the 2-second budget cutting off borderline judgments.
- Live-presets pool test derives expectations from the presets file instead of hard-coded preset names, so user retuning cannot break the suite.
- README documents dynamic profile switching, the four new settings, and updated test counts.


## [0.3.0] - 2026-09-23

### Added
- **Profile Pre-Selection (Task 8):** New chats automatically select an appropriate agent profile based on the first message content using Jev classification.
  - **API Path:** Implicit hook at `initialize.initialize_agent` (POST `/api/message`).
  - **WebUI Path:** Implicit hook at `user_message_ui` (POST `/message_async`).
  - Supports `coding`→`developer`, `research`→`researcher`, `security`→`hacker`, `testing`→`test-engineer`.
  - Safeguards: fresh chat only, explicit user choices win, never raises.
- **Settings:** `chat_preselect` flag (default true) and `delegation_mode: auto` configuration.

### Changed
- Documentation updated to reflect full implementation of profile pre-selection.
- Test suite expanded (21 suites, 203 tests).

### Fixed
- WebUI chat transport verification (`/message_async`).
- Error logging clarity for routing failures.

---

## [0.2.0] - 2026-09-22

### Added
- Standalone Jev router with bundled helper (`hooks.py` installs `typesafe-sdk`).
- Real-call telemetry and circuit breaker.
- State-aware auto-tune and band tuning.
- Live WebUI panel with state chips and diff-guarded polling.

### Changed
- Removed dependency on external `typesafe_ai` plugin.
- Updated API key resolution (settings field or `TYPESAFE_API_KEY` env var).

## 0.7.12 — 2026-10-04

- Fix auto-tune polling promoting Default to every band: tuning_report now always
  passes band stats in band mode (never degrades to global when band_stats is
  empty), and applies pinned-band freezes to `suggested` so the panel displays
  and Applies pinned orders instead of globally-ranked ones. Pins now win in
  polling just like in the router path.
- Two tests added: band-mode preservation with 0 banded rows, and pin
  application to suggested orders.

## 0.7.12 — 2026-10-04

- Fix auto-tune polling promoting Default to every band: tuning_report now always
  passes band stats in band mode (never degrades to global when band_stats is
  empty), and applies pinned-band freezes to `suggested` so the panel displays
  and Applies pinned orders instead of globally-ranked ones. Pins now win in
  polling just like in the router path.
- Two tests added: band-mode preservation with 0 banded rows, and pin
  application to suggested orders.
