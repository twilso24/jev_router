# Spec: Remove the Performance Dial Mechanic

## Objective

Eliminate the performance dial (cost / balanced / quality / speed tiers) from jev_router entirely. Routing decisions must be governed only by the sources of truth that remain: **band orders + pins (routing-policy.yaml), signals (complexity/task class/vision), Jev fit (when configured), circuit breaker, auto-tune, and user band tuning in the panel**. The dial is a redundant re-ranking layer that conflicts with user-curated band orders; the user wants it gone.

## Current Behavior (verified live)

- `config.json: performance_dial` = `balanced` (no-op today — `dial.apply_dial()` returns orders unchanged for unknown/balanced dials).
- `helpers/dial.py: apply_dial(orders, dial, pinned)` re-ranks band orders by fuzzy preset-name tier mapping when dial != balanced; pinned bands keep file order verbatim.
- `report.py: dial_summary()` / `_main_dial()` read the dial and print `dial=... pins=...` evidence.
- Panel reason strings may contain dial-derived text (e.g. `"High Reliability band policy overrides medium"` seen in earlier live telemetry when dial was non-balanced).
- Settings UI (`webui/config.html`) exposes a `performance_dial` field.
- `tests/test_dial.py` pins dial behavior (no-op, total/pure, pin semantics).

## Removal Scope

### Remove
- `helpers/dial.py` — entire module (`apply_dial`, `_RANKS`, tier maps).
- `report.py` — `dial_summary()` dial field, `_main_dial` dial line (`dial=...`), `apply_dial` import; keep the auto_tune/pins/preset-stats/orders evidence minus dial.
- `router.py` / `policy.py` call sites passing `performance_dial` into band resolution; bands resolve directly from file orders.
- `config.json` `performance_dial` key (ignored if present — unknown keys tolerated, not migrated).
- `webui/config.html` dial selector field.
- Dial-derived reason strings (fallback path reasons must state the band/head logic only).
- `tests/test_dial.py` — replaced by removal regression tests (see below).

### Keep (explicitly NOT removed)
- `pinned_bands` semantics — pin still means "auto-tune must not reorder this band".
- Band orders, auto-wire, auto-tune, mentions (`helpers/mentions.py` per-message dial hints like "use free models" — different feature, out of scope unless user confirms).
- Circuit breaker, fast-path, fit, shadow mode, telemetry.

## Assumptions

1. `mentions` "dials" (per-message free/prefer hints) are a separate mechanic and stay.
2. Existing `performance_dial` keys in config files are left as inert orphans (tolerated), no migration script.
3. Panel "state-aware chips" that display dial state are removed; other chips stay.
4. Open question: does `config.json` in the deployed plugin get the key deleted by hand or on next save? (Answer: on next settings save; reads ignore it meanwhile.)

## Commands

- Test: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Focused: `/opt/venv-a0/bin/python -m pytest tests/test_report.py tests/test_router.py -q`
- Report: `/opt/venv-a0/bin/python report.py dial` (must still print auto_tune/pins/orders sans `dial=`)

## Testing Strategy (TDD)

1. **RED**: `test_report.py` — dial summary output no longer contains `dial=`; orders equal file orders exactly (no re-rank possible).
2. **RED**: `test_router.py` — band resolution reason never mentions dial/high-reliability override; quality-typed config dial value is ignored (resolve identical regardless of `performance_dial`).
3. **RED**: removal guard — `helpers/dial.py` absent and no `from helpers import dial` references remain (repo-wide grep assertion).
4. Keep: pin semantics tests move from `test_dial.py` into `test_policy.py` or `test_router.py` (pins honored = file order verbatim).
5. Full suite green; deployed copies byte-identical; CHANGELOG + version bump.

## Boundaries

- **Always:** keep pinned_bands behavior; keep band orders as the sole deterministic ranking; run full suite; sync deployed plugin.
- **Ask first:** touching `helpers/mentions.py` free/prefer hints; deleting live config.json key before settings save.
- **Never:** leave a half-removed dial (module gone but UI field writing it); break report.py CLI; weaken unrelated tests.

## Success Criteria

1. No `helpers/dial.py`, no `performance_dial` references in code/UI/tests (grep-verified, mentions excluded).
2. Routing decisions with identical signals/bands are identical for any legacy `performance_dial` value.
3. `report.py dial` still prints auto_tune, pins, preset stats, file orders.
4. Reason strings contain no dial-derived overrides.
5. Full suite passes; deployed copy synced; CHANGELOG documents removal.

## Open Questions

- Should the legacy `performance_dial` key be actively deleted from `config.json` on deploy, or tolerated indefinitely? (Default: tolerated; cleaned on next settings save.)