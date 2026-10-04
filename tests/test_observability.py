# Observability features (calls usage/cost, fallback blame, percentiles,
# session aggregates, shadow comparison). Additive tests kept separate so the
# restored test_telemetry_calls.py contract stays untouched.
# Run: /opt/venv-a0/bin/python tests/test_observability.py
import asyncio
import importlib.util
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import telemetry


# --- Task A: pure usage/fallback field helpers in telemetry ---

def _usage_result(**kw):
    return SimpleNamespace(usage=kw)


def test_usage_fields_extracts_token_and_cost():
    fields = telemetry.usage_fields(_usage_result(
        input_tokens=500, output_tokens=200, cost=0.0123))
    assert fields['input_tokens'] == 500
    assert fields['output_tokens'] == 200
    assert abs(fields['cost_usd'] - 0.0123) < 1e-9


def test_usage_fields_reads_prompt_completion_aliases():
    # LiteLLM-style usage dicts
    fields = telemetry.usage_fields(_usage_result(
        prompt_tokens=42, completion_tokens=7, cost=0.001))
    assert fields['input_tokens'] == 42
    assert fields['output_tokens'] == 7
    assert abs(fields['cost_usd'] - 0.001) < 1e-12


def test_usage_fields_handles_missing_usage():
    assert telemetry.usage_fields(object()) == {
        'input_tokens': None, 'output_tokens': None, 'cost_usd': None}
    assert telemetry.usage_fields(None) == {
        'input_tokens': None, 'output_tokens': None, 'cost_usd': None}


def test_usage_fields_tolerates_malformed_types():
    fields = telemetry.usage_fields(_usage_result(
        input_tokens='bogus', cost='x'))
    assert fields['input_tokens'] is None
    assert fields['cost_usd'] is None


def test_resolve_fallback_uses_intended_then_called_preset():
    assert telemetry.resolve_fallback(
        intended='Power', called='Fast') == 'Power'
    assert telemetry.resolve_fallback(intended='Fast', called='Fast') is None
    assert telemetry.resolve_fallback(intended=None, called='Fast') is None


# --- Task B: call_tracker extracts usage on success, fallback on failure ---

def _tracker():
    from helpers import call_tracker
    return call_tracker


class _FakeTurn:
    def __init__(self, behave='ok'):
        self.behave = behave

    async def unified_turn(self, **kwargs):
        if self.behave == 'raise':
            raise RuntimeError('boom')
        return SimpleNamespace(usage={
            'input_tokens': 10, 'output_tokens': 5, 'cost': 0.001})


def test_tracker_reports_usage_and_fallback_to_wide_callback():
    ct = _tracker()
    m = _FakeTurn()
    seen = []

    def cb(provider, preset, ok, duration, error, usage, fallback,
           cold_start=False, cold_start_ms=None, context_pressure=False,
           ctx_length=None, estimated_tokens=None):
        seen.append((provider, preset, ok, usage, fallback))

    ct.instrument(m, 'prov', 'Fast', cb, fallback_from_preset='Power')
    resp = asyncio.run(m.unified_turn(messages=[]))
    assert resp is not None
    assert len(seen) == 1
    provider, preset, ok, usage, fallback = seen[0]
    assert provider == 'prov' and preset == 'Fast' and ok is True
    assert usage == {'input_tokens': 10, 'output_tokens': 5,
                     'cost_usd': 0.001}
    assert fallback == 'Power'


def test_tracker_legacy_varargs_callback_gets_original_5tuple():
    ct = _tracker()
    m = _FakeTurn()
    seen = []
    ct.instrument(m, 'prov', 'Fast', lambda *a: seen.append(a))
    asyncio.run(m.unified_turn(messages=[]))
    assert len(seen) == 1
    assert len(seen[0]) == 5, 'varargs callback must keep the legacy 5-tuple'


def test_tracker_failure_reports_none_usage_and_fallback():
    ct = _tracker()
    m = _FakeTurn('raise')
    seen = []

    def cb(provider, preset, ok, duration, error, usage, fallback,
           cold_start=False, cold_start_ms=None, context_pressure=False,
           ctx_length=None, estimated_tokens=None):
        seen.append((ok, usage, fallback))

    ct.instrument(m, 'prov', 'Fast', cb, fallback_from_preset='Power')
    try:
        asyncio.run(m.unified_turn(messages=[]))
        raise AssertionError('should have raised')
    except RuntimeError:
        pass
    ok, usage, fallback = seen[0]
    assert ok is False
    assert usage == {
        'input_tokens': None, 'output_tokens': None, 'cost_usd': None}
    assert fallback == 'Power'


# --- Task D: percentile helpers in telemetry ---

def test_preset_duration_percentiles_nearest_rank():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        for d in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            telemetry.record_call(conn, 'p', 'Fast', True, d, None)
        telemetry.record_call(conn, 'p', 'Fast', False, 9.9, 'x')
        # failures excluded: percentiles are over successful durations only
        stats = telemetry.preset_duration_stats(conn, limit=100)
        conn.close()
        assert 'Fast' in stats
        st = stats['Fast']
        assert st['count'] == 10
        assert abs(st['avg'] - 0.55) < 1e-9
        # nearest-rank on [0.1..1.0]
        assert abs(st['p50'] - 0.5) < 1e-9
        assert abs(st['p95'] - 1.0) < 1e-9
        assert abs(st['p99'] - 1.0) < 1e-9


def test_preset_duration_percentiles_empty_and_single():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        stats = telemetry.preset_duration_stats(conn, limit=100)
        assert stats == {}
        telemetry.record_call(conn, 'p', 'Solo', True, 0.42, None)
        stats = telemetry.preset_duration_stats(conn, limit=100)
        conn.close()
        st = stats['Solo']
        assert st['count'] == 1
        assert abs(st['p50'] - 0.42) < 1e-9
        assert abs(st['p95'] - 0.42) < 1e-9
        assert abs(st['p99'] - 0.42) < 1e-9
        assert abs(st['avg'] - 0.42) < 1e-9


# --- Task E: session-level metrics ---

_VALID_POOL_ENTRY = {
    'preset_name': 'X', 'role': 'chat', 'provider': 'prov', 'model': 'model'
}

def test_session_decision_stats_counts_switches_and_bands():
    from helpers.policy import Decision
    from helpers.pool import PoolEntry
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        def mk(name, pres):
            entry = PoolEntry(**dict(_VALID_POOL_ENTRY, preset_name=pres))
            return Decision(entry, 'light', name)
        telemetry.record_decision(
            conn, mk('r1', 'Fast'), None, 'd1', session_id='s1')
        telemetry.record_decision(
            conn, mk('r2', 'Fast'), None, 'd2', session_id='s1')
        telemetry.record_decision(
            conn, mk('r3', 'Power'), None, 'd3', session_id='s1')
        telemetry.record_decision(
            conn, Decision(None, 'light', 'keep'), None, 'd4',
            session_id='s1')
        st = telemetry.session_decision_stats(conn, 's1', limit=100)
        conn.close()
        assert st['decisions'] == 4
        assert st['model_switches'] == 1  # Fast -> Power
        assert st['band_dist'] == {'light': 4}


def test_session_decision_stats_missing_session_is_zeroes():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        st = telemetry.session_decision_stats(conn, 'nosuch', limit=100)
        conn.close()
        assert st == {
            'decisions': 0, 'model_switches': 0,
            'fallback_rate': 0.0, 'band_dist': {}}


# --- Task F: shadow_target column decisions ---

def test_decisions_shadow_column_exists_and_records():
    from helpers.policy import Decision
    from helpers.pool import PoolEntry
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(decisions)')}
        assert 'shadow_target' in cols, cols
        entry = PoolEntry(**dict(_VALID_POOL_ENTRY, preset_name='Power'))
        telemetry.record_decision(
            conn, Decision(entry, 'heavy', 'route'), None, 'd1',
            session_id='s', shadow_target='Efficiency')
        row = telemetry.last_decisions(conn, 1)[0]
        conn.close()
        assert row['shadow_target'] == 'Efficiency'
        assert row['target'] == 'Power'


def test_shadow_target_defaults_to_none_on_old_calls():
    from helpers.policy import Decision
    from helpers.pool import PoolEntry
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        entry = PoolEntry(**dict(_VALID_POOL_ENTRY, preset_name='Fast'))
        telemetry.record_decision(
            conn, Decision(entry, 'light', 'r'), None, 'd1')
        row = telemetry.last_decisions(conn, 1)[0]
        conn.close()
        assert row['shadow_target'] is None


def test_legacy_db_gains_shadow_column():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 'old.db'
        raw = sqlite3.connect(db)
        raw.executescript('''
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                msg_digest TEXT NOT NULL,
                task_class TEXT,
                complexity REAL,
                band TEXT,
                vision REAL,
                delegate REAL,
                target TEXT,
                reason TEXT,
                compromise INTEGER NOT NULL DEFAULT 0
            );
        ''')
        raw.commit()
        raw.close()
        conn = telemetry.init_db(db)
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(decisions)')}
        conn.close()
        assert 'shadow_target' in cols


def _main():
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    passed = 0
    failed = []
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print(f'PASS {name}')
        except Exception as exc:
            failed.append(name)
            print(f'FAIL {name}: {exc.__class__.__name__}: {exc}')
    print(f'--- {passed}/{len(fns)} passed ---')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    _main()
