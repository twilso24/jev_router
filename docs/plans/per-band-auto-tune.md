# Implementation Plan: Per-Band Auto-Tune

Spec: `docs/specs/per-band-auto-tune.md` (approved: "Yes. Go.")
Goal: replace global-ranking auto-tune (Default wins every band) with
genuine per-band evidence ranking; user keeps the mix approach (manual
curated orders where they want, adaptive where they want).

## Architecture Decisions

- **Schema: one `band` column on `calls` instead of a new table.**
  `_ensure_column(conn, 'calls', 'band', 'TEXT')` is the established
  idempotent migration path (same as fit columns). Legacy rows get
  `band = NULL` → excluded from per-band stats automatically (WHERE
  band IS NOT NULL). Global `preset_call_stats` unchanged (legacy-safe).
- **Band context flows through the instrument closure.** Router result
  exposes `.band` (Decision.band). The extension passes it to
  `_instrument(..., band=result.band)`; the `on_outcome` closure captures
  it; `_on_call_outcome` forwards it to `record_call(..., band=band)`.
  Kept-model fallbacks have no decision → `band=None` (global only).
- **Ranking precedence per band:** `band_preset_stats[band]` when present
  and non-empty for that band; otherwise fall back to global
  `preset_stats` for that band (degraded mode preserves today's
  behavior). Unqualified keep file order after qualified group — unchanged.
- **Pins still win:** `effective_band_orders` keeps its pin-freeze loop
  after suggesting per-band orders.

## Task List

### Phase 1: Telemetry schema + aggregation (RED → GREEN)

- [ ] Task 1: `helpers/telemetry.py`
  - Acceptance: `init_db` adds `band` TEXT to `calls` idempotently;
    `record_call(..., band=None)` writes it; new
    `band_preset_call_stats(conn, limit)` returns
    `{band: {preset: {ok, fail}}}` from rows WHERE band IS NOT NULL,
    newest-first limited like `preset_call_stats`; legacy rows excluded;
    `preset_call_stats` behavior byte-identical.
  - Verify: RED tests in `tests/test_telemetry_calls.py` (schema, write,
    per-band aggregation, legacy-row exclusion), then GREEN.
  - Files: helpers/telemetry.py, tests/test_telemetry_calls.py (S)

### Phase 2: Per-band ranking (RED → GREEN)

- [ ] Task 2: `helpers/tuning.py`
  - Acceptance: `suggest_band_orders(current, pool, preset_stats,
    band_preset_stats=None)` ranks each band using
    `band_preset_stats[band]` when it has data for that band, else the
    global stats; qualified/unqualified split and key function per band;
    `effective_band_orders` fetches band stats and passes them through;
    pins freeze after suggestion; auto_tune-off path unchanged.
  - Verify: RED tests in `tests/test_tuning.py`: different presets head
    light vs heavy with band stats; band-scoped evidence floor (P has 10
    calls in light, 3 in heavy → ranks in light only); fallback to global
    when band stats missing/empty; unqualified keep file order; pin
    freeze still wins. Then GREEN.
  - Files: helpers/tuning.py, tests/test_tuning.py (M)

### Checkpoint after Tasks 1-2
- [ ] Full suite green: `/opt/venv-a0/bin/python -m pytest tests/ -q`

### Phase 3: Band threading (RED → GREEN)

- [ ] Task 3: `extensions/python/chat_model_call_before/_10_jev_route.py`
  - Acceptance: `_instrument(ext, model, entry, band=None,
    fallback_from_preset=None)`; `on_outcome` closure captures band;
    `_on_call_outcome(..., band=band)` → `record_call(..., band=band)`;
    router call site passes `band=getattr(result, 'band', None)`;
    kept-model path stays band-less (None).
  - Verify: RED tests (new `tests/test_band_threading.py` or extend
    kept-model suite): instrumented outcome records the passed band;
    None band records NULL; extension call-site passes result.band.
  - Files: extensions/.../_10_jev_route.py, tests (S)

### Phase 4: Evidence surface + guard

- [ ] Task 4: `report.py` evidence summary
  - Acceptance: `evidence_summary` includes `band_stats` (per-band
    ok/fail) alongside global `preset_stats`; `report.py dial` prints a
    per-band block when band evidence exists; no dial field still.
  - Verify: extend `tests/test_report.py` with band_stats assertion.
  - Files: report.py, tests/test_report.py (S)

### Checkpoint after Tasks 3-4
- [ ] Full suite green

### Phase 5: Deploy

- [ ] Task 5: sync + versioning
  - Acceptance: helpers/telemetry.py, helpers/tuning.py,
    extensions/.../_10_jev_route.py, report.py, tests synced to
    `/a0/usr/plugins/jev_router/` and `plugin/` snapshot (byte-identical);
    CHANGELOG v0.7.10; plugin.yaml 0.7.10; guard: no dial regressions
    (`test_dial_removal` still green).
  - Verify: sha256 across copies; full suite; live `report.py dial`
    shows per-band block after restart.
  - Files: deployed plugin, CHANGELOG.md, plugin.yaml (S)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Legacy DB rows lack band | all bands start unqualified (flat) | expected: gradual re-learning; global fallback keeps current behavior meanwhile |
| Band recorded at instrument time but decision cache reuses models | stale band attribution on cached models | `_instrument` refresh path re-sets callback per call site, so band is refreshed each turn |
| Per-band evidence thin → churn | orders flap early | per-band evidence floor (10) mirrors global floor; unqualified keep file order |
| Kept-model fallbacks unattributed | band=None rows pollute | WHERE band IS NOT NULL excludes them from band stats |

## Open Questions

None — spec approved with task_class deferred.