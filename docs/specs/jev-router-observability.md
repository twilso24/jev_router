# Spec: Jev Router Observability Extensions

## Objective

Extend the existing SQLite telemetry with five additive evidence sources so
routing quality, health, and drift can be verified without changing routing
behavior.

## Commands

- Init/report DB: `/opt/venv-a0/bin/python /a0/usr/projects/jev_router/report.py [limit] [db]`
- Incremental see percentile view: `/opt/venv-a0/bin/python /a0/usr/projects/jev_router/report.py stats`
- Quick unit smoke: `/opt/venv-a0/bin/python /a0/usr/projects/jev_router/tests/test_telemetry_calls.py`
- Full suite: `cd /a0 && /opt/venv-a0/bin/python -m pytest usr/projects/jev_router/tests -q`

## Project Structure

- `helpers/telemetry.py` streams both existing tables plus schema migration
- `helpers/call_tracker.py` records only behavior wires (no changes)
- `report.py` gains statistical CLI query over the calls table
- `extensions/python/chat_model_call_before/_10_jev_route.py`ribes outcomes into telemetry
- Relevant unit tests under `tests/`:
  - `test_telemetry_calls.py`, `test_report.py`,
  - `test_telemetry_session_metrics.py`, `test_telemetry_shadow_records.py`

## Implementation Structure

1. calls table nullable additions: `input_tokens`, `output_tokens`, `cost_usd`,
   `fallback_from_preset`
2. decisions table nullable addition to support the additive shadow comparison:
   `shadow_target`
3. report module exposes percentile (p50/p95/p99) summaries from the calls table
4. session-level skill is `stats_from_decisions(session_id, limit)` that returns
   both decision count and switch count (sequential decision targets)
5. hooks for extracting usage from the traced model result attributes,
  comparison rows written with the `shadow_target` flag but unchanged route
context is not altered

## Code Style

Python 3.12, `pathlib.Path`, nullable extras, defensive try/except wrappers, all
observability flows can fail silenlty at runtime and always return normalized
structures (empty maps and None respectively).

## Testing Strategy

TDD remains mandatory, one smallest-behavior test at a time:

- Telemetry: migrations are idempotent, parsing is case-tolerant and complete.
- report.py CLI: empty DB prints zeros, distributions match Python percentile rules.
- Fallback capture: a failing outcome shall not lose the original target.
- Session metrics: the computed counts match the ordered decisions input rows.
- Shadow recorder: only one new entry exists, `shadow_target` captures what would
  have been chosen, and nothing else flips routing state.

## Boundaries

- Always: run the impacted test modules after every implementation slice.
- Never: mutate shared runtime providers, write direct to legacy YAML, change
  Jev judgment criteria, or throw errors from observability during a real call.

## Success Criteria

- New optional call columns are readable and robust, with cost only set when known.
- report output accurately prints p50/p95/p99 on traceable durations.
- Primary-target blame (`fallback_from_preset`) exists for every failing call.
- Session aggregates report on decision and switching pressure alone.
- Shadow-mode examples are persisted but the decisions flow untouched.