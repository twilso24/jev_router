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
        assert tuning.read_auto_tune(p) is False
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


if __name__ == '__main__':
    _main()
