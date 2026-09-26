# TDD RED: telemetry-driven band-order suggestion + safe policy writes.
# helpers/tuning.py does not exist yet.
# Run: /opt/venv-a0/bin/python tests/test_tuning.py
import sys
import tempfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import tuning


def test_suggest_ranks_failures_first():
    stats = {'A': {'ok': 10, 'fail': 0},
             'B': {'ok': 10, 'fail': 2},
             'C': {'ok': 1, 'fail': 5}}
    s = tuning.suggest_band_orders(
        {'light': ['B', 'A', 'C']}, ['A', 'B', 'C'], stats)
    assert s['light'] == ['A', 'B', 'C']


def test_suggest_stable_on_ties():
    stats = {'A': {'ok': 5, 'fail': 0}, 'B': {'ok': 5, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'light': ['B', 'A']}, ['A', 'B'], stats)
    assert s['light'] == ['B', 'A']


def test_suggest_drops_presets_not_in_pool():
    stats = {'A': {'ok': 5, 'fail': 0}, 'X': {'ok': 5, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'light': ['X', 'A']}, ['A'], stats)
    assert s['light'] == ['A']


def test_suggest_missing_stats_keeps_current_order():
    s = tuning.suggest_band_orders(
        {'light': ['B', 'A']}, ['A', 'B'], {})
    assert s['light'] == ['B', 'A']


def test_suggest_covers_all_bands():
    s = tuning.suggest_band_orders({}, ['A'], {})
    assert sorted(s.keys()) == ['heavy', 'light', 'medium']
    assert s['light'] == ['A']


def test_write_band_orders_preserves_other_keys():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'policy.yaml'
        p.write_text(yaml.safe_dump({
            'provider_rules': {'include': [], 'exclude': ['zai_coding']},
            'band_orders': {'light': ['Fast']},
            'schedules': [{'name': 'n', 'window': '22:00-06:00'}],
        }))
        ok = tuning.write_band_orders(p, {'light': ['Default', 'Fast']})
        assert ok is True
        data = yaml.safe_load(p.read_text())
        assert data['provider_rules']['exclude'] == ['zai_coding']
        assert data['schedules'][0]['name'] == 'n'
        assert data['band_orders']['light'] == ['Default', 'Fast']


def test_write_band_orders_rejects_unknown_band():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'policy.yaml'
        p.write_text(yaml.safe_dump({'band_orders': {'light': ['Fast']}}))
        ok = tuning.write_band_orders(p, {'bogus': ['Fast']})
        assert ok is False
        data = yaml.safe_load(p.read_text())
        assert data['band_orders'] == {'light': ['Fast']}


def test_write_band_orders_merges_partial():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'policy.yaml'
        p.write_text(yaml.safe_dump({
            'band_orders': {'light': ['Fast'], 'heavy': ['Power']}}))
        assert tuning.write_band_orders(p, {'heavy': ['Local', 'Power']})
        data = yaml.safe_load(p.read_text())
        assert data['band_orders']['light'] == ['Fast']
        assert data['band_orders']['heavy'] == ['Local', 'Power']


def _main():
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    passed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print(f'PASS {name}')
        except Exception as exc:
            print(f'FAIL {name}: {exc}')
    print(f'--- {passed}/{len(fns)} passed')
    if passed != len(fns):
        raise SystemExit(1)


def test_read_auto_tune_default_false():
    assert tuning.read_auto_tune(Path('/nonexistent/rp.yaml')) is False


def test_read_auto_tune_roundtrip_preserves_keys():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'rp.yaml'
        p.write_text(yaml.safe_dump({
            'provider_rules': {'include': [], 'exclude': ['x']},
            'band_orders': {'light': ['Fast']},
        }))
        # S5 contract change: a readable policy file without the key
        # defaults auto-tune ON; explicit values still roundtrip unchanged.
        assert tuning.read_auto_tune(p) is True
        assert tuning.write_auto_tune(p, True) is True
        assert tuning.read_auto_tune(p) is True
        data = yaml.safe_load(p.read_text())
        assert data['provider_rules']['exclude'] == ['x']
        assert data['band_orders']['light'] == ['Fast']
        assert tuning.write_auto_tune(p, False) is True
        assert tuning.read_auto_tune(p) is False


def test_read_auto_tune_invalid_falls_back_false():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'rp.yaml'
        p.write_text('auto_tune: [not, a, bool]\n')
        assert tuning.read_auto_tune(p) is False
        p2 = Path(td) / 'rp2.yaml'
        p2.write_text('auto_tune: 42\n')
        assert tuning.read_auto_tune(p2) is False


# --- auto-tune sparse-evidence floor (user intervention 2026-09-25) ---


def test_suggest_sparse_evidence_keeps_current_orders():
    """With only one observed call, auto-tune must NOT promote that preset
    over the user's configured band orders (production bug: Default, ok=1,
    jumped to position 1 of every band)."""
    s = tuning.suggest_band_orders(
        {'light': ['Fast', 'Default', 'Power'],
         'medium': ['Default', 'Fast', 'Power'],
         'heavy': ['Power', 'Default', 'Fast']},
        ['Fast', 'Default', 'Power'],
        {'Default': {'ok': 1, 'fail': 0}})
    assert s['light'] == ['Fast', 'Default', 'Power']
    assert s['medium'] == ['Default', 'Fast', 'Power']
    assert s['heavy'] == ['Power', 'Default', 'Fast']


def test_suggest_engages_once_evidence_sufficient():
    """Per-preset floors met, ranking resumes (failures last)."""
    stats = {'Default': {'ok': 9, 'fail': 1},
             'Power': {'ok': 12, 'fail': 0},
             'Fast': {'ok': 10, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'light': ['Default', 'Power', 'Fast']},
        ['Default', 'Power', 'Fast'], stats)
    assert s['light'][0] != 'Default'  # failing preset demoted
    assert s['light'][-1] == 'Default'


# --- S4 (TDD) RED: per-band pins override auto-tune ---
import yaml


def test_read_pinned_bands_default_empty():
    assert tuning.read_pinned_bands('/nonexistent/rp.yaml') == {}


def test_write_pin_roundtrip_preserves_keys(tmp_path):
    p = tmp_path / 'rp.yaml'
    p.write_text(yaml.safe_dump({'auto_tune': True,
                                 'band_orders': {'light': ['A']}}))
    assert tuning.write_pin(p, 'light', True) is True
    assert tuning.read_pinned_bands(p) == {'light': True}
    assert tuning.read_auto_tune(p) is True
    assert tuning.write_pin(p, 'light', False) is True
    assert tuning.read_pinned_bands(p) == {'light': False}


def test_write_pin_rejects_unknown_band(tmp_path):
    p = tmp_path / 'rp.yaml'
    p.write_text(yaml.safe_dump({'auto_tune': True}))
    assert tuning.write_pin(p, 'bogus', True) is False
    assert 'pinned_bands' not in yaml.safe_load(p.read_text())


def test_effective_orders_pin_beats_auto_tune(tmp_path):
    p = tmp_path / 'rp.yaml'
    p.write_text(yaml.safe_dump({
        'auto_tune': True,
        'pinned_bands': {'heavy': True},
        'band_orders': {'light': ['A', 'B'], 'medium': ['A'],
                        'heavy': ['B', 'A']},
    }))
    db = tmp_path / 't.db'
    from helpers import telemetry as tel
    conn = tel.init_db(db)
    # B failing heavily, A healthy: auto-tune would promote A everywhere
    for _ in range(6):
        tel.record_call(conn, 'p1', 'A', True, 0.1, None)
        tel.record_call(conn, 'p2', 'B', False, 0.1, 'err')
    conn.close()
    orders, applied = tuning.effective_band_orders(
        p, db, ['A', 'B'])
    assert applied is True
    assert orders['heavy'] == ['B', 'A'], 'pinned band must keep file order'
    assert orders['light'][0] == 'A', 'unpinned band gets auto-ranked'


# --- S5 (TDD) RED: auto-tune is the default when the key is absent ---
def test_read_auto_tune_absent_key_defaults_on(tmp_path):
    p = tmp_path / 'rp.yaml'
    p.write_text(yaml.safe_dump({'band_orders': {'light': ['A']}}))
    assert tuning.read_auto_tune(p) is True
    # an explicit false always wins over the default
    p.write_text(yaml.safe_dump({'auto_tune': False}))
    assert tuning.read_auto_tune(p) is False
    # missing file fails safe to legacy off
    assert tuning.read_auto_tune(tmp_path / 'none.yaml') is False


# --- S10 (TDD) RED: per-preset evidence floors (closed loop) ---

def test_suggest_unqualified_stays_when_others_qualified():
    """Per-preset floor: Default (1 own obs) must not move just because
    Power has plenty of evidence - the old global gate let it jump."""
    stats = {'Power': {'ok': 12, 'fail': 0},
             'Default': {'ok': 1, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'light': ['Fast', 'Default', 'Power']},
        ['Fast', 'Default', 'Power'], stats)
    assert s['light'][0] == 'Power'   # qualified healthy -> promoted
    assert s['light'][1] == 'Fast'    # unqualified keep current order
    assert s['light'][2] == 'Default'


def test_suggest_qualified_healthy_moves_without_global_gate():
    stats = {'Power': {'ok': 12, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'light': ['Fast', 'Default', 'Power']},
        ['Fast', 'Default', 'Power'], stats)
    assert s['light'] == ['Power', 'Fast', 'Default']


def test_suggest_qualified_failing_demoted_last():
    """Group semantics (matches ranks_failures_first): qualified presets
    rank by outcomes (healthy first, failing last); unqualified presets
    keep their relative order at the tail."""
    stats = {'Power': {'ok': 3, 'fail': 7}, 'Fast': {'ok': 10, 'fail': 0}}
    s = tuning.suggest_band_orders(
        {'heavy': ['Power', 'Default', 'Fast']},
        ['Power', 'Default', 'Fast'], stats)
    assert s['heavy'] == ['Fast', 'Power', 'Default']


def test_suggest_unqualified_failing_keeps_position():
    """2 own observations: not qualified, not demoted (sparse safety)."""
    stats = {'Power': {'ok': 0, 'fail': 2}}
    s = tuning.suggest_band_orders(
        {'heavy': ['Power', 'Default', 'Fast']},
        ['Power', 'Default', 'Fast'], stats)
    assert s['heavy'] == ['Power', 'Default', 'Fast']


def test_suggest_evidence_floor_boundary_at_exact_floor():
    """FIX F6 (review): 9 own oks stay unqualified; exactly 10 qualifies."""
    s = tuning.suggest_band_orders(
        {'light': ['Fast', 'Power']},
        ['Fast', 'Power'], {'Power': {'ok': 9, 'fail': 0}})
    assert s['light'] == ['Fast', 'Power']
    s2 = tuning.suggest_band_orders(
        {'light': ['Fast', 'Power']},
        ['Fast', 'Power'], {'Power': {'ok': 10, 'fail': 0}})
    assert s2['light'] == ['Power', 'Fast']


# --- Audit round 2 (live probe): atomic, serialized policy writes ---


def test_failed_write_leaves_no_tmp_file(tmp_path):
    """A failed publish must not leave staging files behind."""
    from unittest.mock import patch
    p = tmp_path / 'rp.yaml'
    p.write_text('band_orders:\n  light: [A]\n')

    def boom(src, dst):
        raise OSError('replace failed')

    with patch('os.replace', boom):
        assert tuning.write_band_orders(p, {'light': ['B']}) is False
    leftovers = list(tmp_path.glob('*.tmp*'))
    assert leftovers == [], f'tmp leftovers: {leftovers}'
    assert yaml.safe_load(p.read_text())['band_orders']['light'] == ['A']


def test_policy_writers_serialize_on_shared_lock(tmp_path):
    """Concurrent policy writers must wait on one shared lock."""
    import threading
    import time
    p = tmp_path / 'rp.yaml'
    p.write_text('band_orders:\n  light: [A]\n')
    lock = getattr(tuning, '_POLICY_LOCK', None)
    assert lock is not None, 'policy writers must share a lock'
    done = threading.Event()
    lock.acquire()
    try:
        t = threading.Thread(
            target=lambda: (tuning.write_auto_tune(p, True), done.set()))
        t.start()
        time.sleep(0.3)
        assert not done.is_set(), 'write must wait for the shared lock'
    finally:
        lock.release()
    t.join(timeout=5)
    assert done.is_set()
