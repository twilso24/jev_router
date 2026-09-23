# Changelog

All notable changes to the Jev Router plugin.

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
