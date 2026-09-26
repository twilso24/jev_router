# Changelog

All notable changes to the Jev Router plugin.

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
