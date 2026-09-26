# S11 (TDD) RED: dial-aware telemetry report summary.
import json
import sys
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import report as report_mod
from helpers import telemetry as tel


def _setup(tmp_root, dial='quality'):
    cfg = tmp_root / 'config.json'
    cfg.write_text(json.dumps({'performance_dial': dial}))
    pol = tmp_root / 'routing-policy.yaml'
    pol.write_text(yaml.safe_dump({
        'band_orders': {'light': ['Fast', 'Default', 'Power'],
                        'heavy': ['Power', 'Default', 'Fast']},
        'pinned_bands': {'heavy': True},
    }))
    db = tmp_root / 't.db'
    conn = tel.init_db(db)
    # Power qualified-healthy: 12 own ok observations (>= evidence floor)
    for _ in range(12):
        tel.record_call(conn, 'prov', 'Power', True, 0.1, None)
    conn.close()
    return cfg, pol, db


def test_dial_summary_quality_promotes_and_pins_hold(tmp_path):
    cfg, pol, db = _setup(tmp_path)
    s = report_mod.dial_summary(cfg, pol, db)
    assert s['dial'] == 'quality'
    assert s['auto_tune'] is True          # keyless policy defaults on
    assert s['pins'] == {'heavy': True}
    assert s['preset_stats']['Power']['ok'] == 12
    assert s['preset_stats']['Power']['fail'] == 0
    assert s['orders']['light'][0] == 'Power'   # quality promotes qualified
    assert s['orders']['heavy'] == ['Power', 'Default', 'Fast']  # pinned


def test_dial_summary_balanced_keeps_file_orders(tmp_path):
    cfg, pol, db = _setup(tmp_path, dial='balanced')
    s = report_mod.dial_summary(cfg, pol, db)
    assert s['dial'] == 'balanced'
    assert s['orders']['light'] == ['Fast', 'Default', 'Power']


def test_dial_summary_never_raises_on_missing_files(tmp_path):
    s = report_mod.dial_summary(tmp_path / 'none.json',
                                tmp_path / 'none.yaml',
                                tmp_path / 'none.db')
    assert s['dial'] == 'balanced'
    assert s['auto_tune'] is False   # missing file fails safe
    assert s['pins'] == {}
    assert s['preset_stats'] == {}
    assert s['orders'] == {}
