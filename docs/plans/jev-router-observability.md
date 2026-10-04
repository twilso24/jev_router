# Implementation Plan: Jev Router Observability Extensions

## Overview

Add five backward-compatible evidence sources to the telemetry DB and CLI report
without altering routing behavior.

## Architecture Decisions

- SQLite stays the single source of truth; schema changes are additive with
  idempotent ALTER TABLE migrations.
- Cost/usage is recorded when the provider surface exposes it; otherwise null.
- Fallback blame is an extra column on the failing call row; the primary target
  is never overwritten.
- Session metrics are derived from the `decisions` table (no new framework hooks).
- Shadow mode adds a `shadow_target` flag on a parallel decision row; routing is
  unchanged.

## Task List

### Phase 1: Calls Table Schema & Migration

- [ ] Task 1: Extend `calls` table with `input_tokens INTEGER`, `output_tokens INTEGER`,
  `cost_usd REAL`, `fallback_from_preset TEXT` (all nullable)
  - Acceptance: `init_db` on a fresh DB creates columns; legacy DB gains columns via
    `_ensure_column`
  - Verify: `pytest tests/test_telemetry_calls.py::test_calls_table_new_columns_exist_after_init`
  - Files: `helpers/telemetry.py`, `tests/test_telemetry_calls.py`

- [ ] Task 2: Update `record_call` signature to accept the new fields and persist them
  - Acceptance: new columns are populated on every recorded call; existing callers
    without the new args still work (default None)
  - Verify: `pytest tests/test_telemetry_calls.py::test_record_call_persists_new_fields`
  - Files: `helpers/telemetry.py`, `tests/test_telemetry_calls.py`

### Checkpoint: Calls Table Migration

- [ ] All existing telemetry tests pass
- [ ] `report.py` still runs against migrated DBs

### Phase 2: Route Outcome Wiring for New Fields

- [ ] Task 3: Extract usage metadata from model response in `_on_call_outcome` and
  pass to `record_call`
  - Acceptance: successful calls record tokens/cost when the framework response
    provides them; failures still record the error
  - Verify: `pytest tests/test_telemetry_calls.py::test_record_call_usage_extraction`
  - Files: `extensions/python/chat_model_call_before/_10_jev_route.py`

- [ ] Task 4: Capture `fallback_from_preset` on failing outcomes (when route
  returned fallback=True and a target was selected)
  - Acceptance: every failing call row has the original chosen preset in
    `fallback_from_preset`; non-fallback failures get None
  - Verify: `pytest tests/test_telemetry_calls.py::test_fallback_preset_captured_on_failure`
  - Files: `extensions/python/chat_model_call_before/_10_jev_route.py`

### Phase 3: Percentile Reporting CLI

- [ ] Task 5: Add `preset_duration_stats(conn, limit=200)` returning
  `{'p50': float, 'p95': float, 'p99': float, 'count': int, 'avg': float}` per preset
  - Acceptance: percentiles computed with Python's nearest-rank method on
    successful call durations only
  - Verify: `pytest tests/test_report.py::test_preset_duration_percentiles`
  - Files: `helpers/telemetry.py`, `report.py`, `tests/test_report.py`

- [ ] Task 6: Expose `report.py stats` subcommand printing the percentile table
  - Acceptance: `python report.py stats [db]` prints per-preset p50/p95/p99
  - Verify: manual CLI smoke test
  - Files: `report.py`

### Checkpoint: Percentile Reporting

- [ ] All report tests pass
- [ ] CLI output is deterministic and human-readable

### Phase 4: Fallback Blame (Primary Target on Failure)

- [ ] Task 7: Ensure `fallback_from_preset` is populated on every failure path
  (fast-path factory failure, Jev query failure, gate fallback, factory exception)
  - Acceptance: failing call row always carries the intended preset name
  - Verify: `pytest tests/test_telemetry_calls.py::test_fallback_preset_on_all_failure_paths`
  - Files: `extensions/python/chat_model_call_before/_10_jev_route.py`

### Phase 5: Session-Level Metrics

- [ ] Task 8: Add `session_decision_stats(conn, session_id, limit=200)` returning
  `{'decisions': int, 'model_switches': int, 'fallback_rate': float, 'band_dist': dict}`
  - Acceptance: model_switches counts sequential decision target changes within the
    session; fallback_rate = failures / total calls
  - Verify: `pytest tests/test_telemetry_session_metrics.py`
  - Files: `helpers/telemetry.py`, `tests/test_telemetry_session_metrics.py`

### Phase 6: Shadow Mode (Additive Comparison)

- [ ] Task 9: Add `shadow_target TEXT` nullable column to `decisions` table
  - Acceptance: migration adds column; existing DBs gain it silently
  - Verify: `pytest tests/test_telemetry_shadow_records.py::test_decisions_shadow_column_exists`
  - Files: `helpers/telemetry.py`, `tests/test_telemetry_shadow_records.py`

- [ ] Task 10: Add `route_advise` path (read-only, no model swap) that writes a
  decision row with `shadow_target` set to the chosen preset while the actual
  route keeps the current model
  - Acceptance: a shadow decision is recorded for every routed message when
    shadow mode is enabled; routing behavior is identical
  - Verify: `pytest tests/test_telemetry_shadow_records.py::test_shadow_decision_recorded`
  - Files: `helpers/router.py`, `extensions/python/chat_model_call_before/_10_jev_route.py`

### Checkpoint: Complete

- [ ] Full test suite passes
- [ ] All 5 features observable via CLI and WebUI data functions

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Usage metadata shape varies by provider | Medium | Defensively extract; default to None; never break call |
| Migration on large legacy DBs | Low | ALTER TABLE is fast for SQLite; idempotent | 
| Percentile math off-by-one | Low | Use `statistics` module or simple nearest-rank; test with known arrays |
| Shadow rows double decision volume | Low | Optional flag; off by default; bounded to one extra row per message |

## Open Questions

- None — spec decisions resolved in design phase.