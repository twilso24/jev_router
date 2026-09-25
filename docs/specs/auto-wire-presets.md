# Spec: Auto-wire new presets into band orders

## Objective

When a user adds a chat preset to `presets.yaml` (any arbitrary name), the
router must make it a first-class routing candidate **automatically**:
append it to the tail of every complexity-band order in `routing-policy.yaml`,
and prune preset names that no longer exist. The WebUI panel shows what was
auto-wired so the user can reposition presets deliberately.

Root cause being fixed: band-order matching is exact-name, first-match-wins.
Unlisted presets are unreachable (dead pool weight); new presets never earned
telemetry, so nothing could ever promote them.

User decisions (locked 2026-09-25): **1A** auto-wire + panel flag,
**2 tail** insertion position, **3 yes** auto-prune dead names.

## Success Criteria

1. Adding preset `X` to presets.yaml and triggering any routed call (or panel
   refresh) appends `X` to the tail of light/medium/heavy orders in
   routing-policy.yaml within one trigger.
2. Removing preset `X` from presets.yaml prunes `X` from all band orders on
   the next sync.
3. Sync is idempotent: no file write (byte-identical, mtime preserved) when
   nothing changes.
4. All other routing-policy.yaml keys (provider_rules, schedules, auto_tune,
   comments-structure as YAML data) survive every sync.
5. Sync never raises; malformed YAML or missing files result in a no-op
   report.
6. The panel tuning card lists `unwired` presets (should be empty in steady
   state) and the last auto-wire report (added/pruned names).
7. Full existing test suite still passes.

## Tech Stack

Python 3.13 (framework runtime `/opt/venv-a0/bin/python`), stdlib + PyYAML.
No new dependencies.

## Commands

- Run focused tests: `/opt/venv-a0/bin/python -m pytest tests/test_auto_wire.py -q`
- Run full suite: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Deploy after green: sync canonical tree to `/a0/usr/plugins/jev_router`
  (runtime files `routing-policy.yaml`, `config.json` excluded), then restart
  framework (helpers are import-cached in the live process).

## Project Structure (files touched)

- `helpers/auto_wire.py` (new) — pure sync logic + wire-state sidecar IO.
- `helpers/webui_data.py` — tuning_report gains `unwired` + wire state.
- `extensions/python/chat_model_call_before/_10_jev_route.py` — fingerprint
  guard triggers sync.
- `api/routing_policy.py` — new `wire_sync` action for panel.
- `extensions/webui/right-canvas-panels/jev-router-panel.html` +
  `webui/jev-router-panel.html` — chip showing auto-wire result.
- `tests/test_auto_wire.py` (new), `tests/test_webui_data.py` (extend).
- Mirrored `plugin/` copies for deployment (sync step, not hand-edited).

## Design

### Sync function

`auto_wire.sync_band_orders(policy_path, pool_presets, state_path) -> WireReport`

- `pool_presets`: chat-role preset names (deduped, order-preserving).
- Load current orders via `policy.load_band_orders` (defaults fill missing
  bands — keeps every preset first-class in all three bands).
- `added` = pool names absent from every band order → appended to tail of
  each band, preserving pool file order.
- `pruned` = band-order names absent from pool → removed from each band.
- Write only when changed, via existing atomic `tuning.write_band_orders`.
- Persist `WireReport(added, pruned, ts)` as JSON sidecar `wire-state.json`
  next to the policy file; panel reads it. Failed/no-op sync never touches a
  previous report except on a real change.
- Returns the report; never raises (broad except → empty report).

### Trigger points

1. Route extension: it already hashes the pool per call
   (`pool_fingerprint`). Keep a module-level `_LAST_FP`; when it changes,
   run sync (cheap fingerprint compare per call, sync only on change).
2. API action `wire_sync`: runs sync and returns the report + unwired list;
   panel chip button uses it.

### Panel

`tuning_report(...)` gains:
- `unwired`: pool presets missing from all band orders (steady state: []).
- `wire_state`: last report (added/pruned/ts) or null.

Chip: `Auto-wired: +N −M` with names in tooltip/inline; hidden when null.

## Testing Strategy

TDD mandatory (project rule): failing test first in `tests/test_auto_wire.py`
against a tmp policy/pool/state, then implement `helpers/auto_wire.py`.
WebUI additions tested in `tests/test_webui_data.py`. Idempotence asserted via
unchanged file bytes + mtime. Malformed-YAML test asserts no raise + no write.

## Boundaries

- Always: TDD; atomic writes; never raise from sync; chat-role-only pool names.
- Ask first: none anticipated (no deps, no schema changes).
- Never: rewrite user comments in routing-policy.yaml beyond what YAML
  round-trip already does today (write_band_orders precedent); no new config
  knobs (user chose plain A, not C).

## Open Questions

None — design locked by user decisions 1A/tail/prune.
