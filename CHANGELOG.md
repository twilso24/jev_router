# Changelog

All notable changes to the Jev Router plugin.

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
