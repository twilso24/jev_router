# Spec: Per-Band Auto-Tune

## Objective

Replace the global-ranking auto-tune (which promotes the globally healthiest preset to #1 in ALL bands) with genuine per-band dynamic ranking:
- **Light band**: ranks presets by their success on *light* calls (e.g., Mercury 2.5 for speed)
- **Medium band**: ranks by success on *medium* calls (e.g., Ling 3.0 Flash for balanced work)
- **Heavy band**: ranks by success on *heavy* calls (e.g., High Power for complex reasoning)

Only presets with ≥10 own calls *in that band* are "qualified" and ranked healthy-first/failing-last; unqualified presets keep their file-order position after the qualified group.

## Current Problem

`helpers/tuning.py:suggest_band_orders` uses `preset_stats` — a single `{preset: {ok, fail}}` dict per preset — so the globally healthiest preset (Default: ok=135) wins every band. This flattens band differentiation and makes auto-tune a no-op for band-specific optimization.

## Telemetry Schema Change

### Existing
```sql
CREATE TABLE calls (
    id INTEGER PRIMARY KEY,
    ts REAL, provider TEXT, preset TEXT,
    ok INTEGER, dur REAL, err TEXT
);
```

### New
```sql
-- calls table unchanged (backward compatible)
-- NEW table for per-band evidence:
CREATE TABLE band_calls (
    id INTEGER PRIMARY KEY,
    ts REAL, band TEXT, preset TEXT,
    ok INTEGER, dur REAL, err TEXT
);
```

- `band` ∈ {light, medium, heavy}
- `preset_call_stats(conn)` remains for backward compat (global)
- NEW `band_preset_call_stats(conn)` returns `{band: {preset: {ok, fail}}}`
- Migration: existing `calls` rows lack `band` → all bands start with zero evidence (unqualified). New calls record to BOTH tables.

## suggest_band_orders Modification

### Signature
```python
def suggest_band_orders(current: dict, pool_presets: list,
                        preset_stats: dict,      # global (legacy)
                        band_preset_stats: dict  # NEW: {band: {preset: {ok, fail}}}
                       ) -> dict:
```

### Logic per band
```python
for band in BANDS:
    # use band_preset_stats[band] for qualification & ranking
    qual = [p for p in order if band_qualified(band, p)]
    unqual = [p for p in order if not band_qualified(band, p)]
    out[band] = sorted(qual, key=band_key(band)) + unqual
```

- `band_qualified(band, p)` → `band_preset_stats[band].get(p, {ok+fail}) >= MIN_EVIDENCE_CALLS`
- `band_key(band, p)` ranks qualified: `(fail>0, fail, -ok, order.index)` using BAND stats
- Fallback: if `band_preset_stats` missing/empty, fall back to global `preset_stats` (degraded mode)

## Migration Strategy

1. **Schema**: `telemetry.init_db()` adds `band_calls` table idempotently (ALTER TABLE / CREATE IF NOT EXISTS)
2. **Recording**: `record_call()` writes to BOTH `calls` (global) and `band_calls` (with `band` from router context)
3. **Router change**: `router.route()` computes `band` and passes it to `telemetry.record_call(conn, ..., band=band)`
4. **Existing data**: old `calls` rows lack band → ignored for per-band ranking. All bands start unqualified.
5. **Re-learning**: as new calls arrive, per-band evidence accumulates; qualified presets begin ranking per band

## Backward Compatibility

- `preset_call_stats()` unchanged → panel stats still work
- `suggest_band_orders` signature adds optional `band_preset_stats` with fallback to global
- If `band_preset_stats` missing/empty → degraded global mode (current behavior)
- `report.py` evidence summary still prints global stats (no breaking change)

## TDD Test Strategy

| Phase | Test | Expectation |
|---|---|---|
| **1. Schema** | `test_band_calls_table_created` | `band_calls` table exists after `init_db()` |
| | `test_record_call_writes_band` | `record_call(conn, ..., band='light')` inserts row in `band_calls` |
| | `test_band_preset_call_stats_returns_per_band` | `band_preset_call_stats(conn)` returns `{light: {P: {ok, fail}}, medium: {...}, ...}` |
| **2. Ranking** | `test_suggest_band_orders_uses_per_band_stats` | Light band ranks P1 healthy-first, heavy band ranks P2 healthy-first (different) |
| | `test_band_evidence_floor_per_band` | Preset qualified in light (10 calls) but unqualified in heavy (3 calls) → ranks only in light |
| | `test_fallback_to_global_when_band_stats_missing` | If `band_preset_stats` empty, falls back to global `preset_stats` |
| | `test_unqualified_keeps_file_order` | Unqualified presets keep relative file order after qualified group |
| **3. Router** | `test_router_passes_band_to_record_call` | `router.route()` calls `telemetry.record_call(conn, ..., band=band)` |
| **4. Migration** | `test_missing_band_stats_starts_unqualified` | No band evidence → all presets unqualified per band → file order |
| | `test_gradual_relearning` | 10 calls in light for P1 → P1 qualifies in light only, ranks #1 in light |

## Boundaries

- **Always**: record to both tables; per-band ranking when band stats available
- **Ask first**: changing `MIN_EVIDENCE_CALLS` (currently 10); adding new telemetry columns
- **Never**: break existing `calls` table schema; break `preset_call_stats()` API

## Success Criteria

1. Light band orders ≠ Medium band orders ≠ Heavy band orders (when evidence exists)
2. Per-band qualification works: P qualifies in light but not heavy → ranks in light only
3. All existing tests pass (backward compat)
4. Full suite green → sync → CHANGELOG v0.7.10
5. Live: after ~10 calls per band, each band shows distinct order in panel

## Open Questions

1. Should `band_calls` also record `task_class` for future task-specific ranking? (Defer — scope creep)
2. `band_calls` table name vs `band_stats` view? (Table is fine, query via function)
3. Retention policy for `band_calls`? (Same as `calls` — handled by existing cleanup if any)

Default: defer task_class, keep simple table, no new retention logic.