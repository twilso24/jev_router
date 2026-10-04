# S11 (TDD) RED→GREEN: evidence summary without performance dial.
import json
import sys
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import report as report_mod
from helpers import telemetry as tel


def _setup(tmp_root, auto_tune=True):
    cfg = tmp_root / 'config.json'
    cfg.write_text(json.dumps({}))  # no performance_dial key
    pol = tmp_root / 'routing-policy.yaml'
    pol.write_text(yaml.safe_dump({
        'band_orders': {'light': ['Fast', 'Default', 'Power'],
                        'heavy': ['Power', 'Default', 'Fast']},
        'pinned_bands': {'heavy': True},
        'auto_tune': auto_tune,
    }))
    db = tmp_root / 't.db'
    conn = tel.init_db(db)
    for _ in range(12):
        tel.record_call(conn, 'prov', 'Power', True, 0.1, None)
    conn.close()
    return cfg, pol, db


def test_evidence_summary_auto_tune_true_returns_file_orders(tmp_path):
    cfg, pol, db = _setup(tmp_path, auto_tune=True)
    s = report_mod.evidence_summary(cfg, pol, db)
    assert 'dial' not in s  # dial field removed
    assert s['auto_tune'] is True
    assert s['pins'] == {'heavy': True}
    assert s['preset_stats']['Power']['ok'] == 12
    assert s['preset_stats']['Power']['fail'] == 0
    # orders == file orders exactly (no dial applied)
    assert s['orders']['light'] == ['Fast', 'Default', 'Power']
    assert s['orders']['heavy'] == ['Power', 'Default', 'Fast']


def test_evidence_summary_auto_tune_false_returns_file_orders(tmp_path):
    cfg, pol, db = _setup(tmp_path, auto_tune=False)
    s = report_mod.evidence_summary(cfg, pol, db)
    assert 'dial' not in s
    assert s['auto_tune'] is False
    # orders still == file orders (no dial)
    assert s['orders']['light'] == ['Fast', 'Default', 'Power']
    assert s['orders']['heavy'] == ['Power', 'Default', 'Fast']


def test_evidence_summary_never_raises_on_missing_files(tmp_path):
    s = report_mod.evidence_summary(tmp_path / 'none.json',
                                    tmp_path / 'none.yaml',
                                    tmp_path / 'none.db')
    assert 'dial' not in s
    assert s['auto_tune'] is False
    assert s['pins'] == {}
    assert s['preset_stats'] == {}
    assert s['orders'] == {}


# --- Percentile subcommand (unchanged) ---

def _setup_calls(tmp_root):
    db = tmp_root / 't.db'
    conn = tel.init_db(db)
    for dur in [0.05, 0.10, 0.15, 0.20, 0.25]:
        tel.record_call(conn, 'prov', 'Power', True, dur, None)
    for dur in [0.01, 0.02, 0.03]:
        tel.record_call(conn, 'prov', 'Fast', True, dur, None)
    tel.record_call(conn, 'prov', 'Fast', False, 0.1, 'err')
    conn.close()
    return db


def test_percentile_subcommand_outputs_p50_p95_p99(tmp_path, capsys):
    db = _setup_calls(tmp_path)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    from helpers.telemetry import preset_duration_stats
    stats = preset_duration_stats(conn, limit=200)
    conn.close()
    assert stats['Power']['p50'] == 0.15
    assert stats['Power']['p95'] == 0.25
    assert stats['Power']['p99'] == 0.25
    assert stats['Power']['count'] == 5
    assert stats['Fast']['p50'] == 0.02
    assert stats['Fast']['p95'] == 0.03
    assert stats['Fast']['p99'] == 0.03
    assert stats['Fast']['count'] == 3


def test_main_percentile_prints_formatted_output(tmp_path, capsys):
    db = _setup_calls(tmp_path)
    rc = report_mod.main(['percentile', str(db)])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'Power' in out
    assert 'Fast' in out
    assert 'p50' in out and 'p95' in out and 'p99' in out
    assert '0.15' in out and '0.25' in out
    assert '0.02' in out and '0.03' in out


# --- S4 per-band evidence surface (RED) ---


def test_evidence_summary_includes_band_stats(tmp_path):
    """evidence_summary exposes band_stats: {band: {preset: {ok, fail}}}."""
    import report
    from helpers import telemetry as tel

    pol = tmp_path / 'policy.yaml'
    pol.write_text('band_orders:\n  light: [Fast]\n')
    db = tmp_path / 't.db'
    conn = tel.init_db(db)
    for _ in range(3):
        tel.record_call(conn, 'p', 'Fast', True, 0.1, None, band='light')
    tel.record_call(conn, 'p', 'Power', False, 0.1, 'x', band='heavy')
    conn.close()

    s = report.evidence_summary(tmp_path / 'cfg.json', pol, db)
    assert 'band_stats' in s, s.keys()
    assert s['band_stats']['light'] == {'Fast': {'ok': 3, 'fail': 0}}
    assert s['band_stats']['heavy'] == {'Power': {'ok': 0, 'fail': 1}}
    # legacy no-band rows are excluded but global stats still count them
    assert s['preset_stats']['Fast']['ok'] == 3


def test_evidence_summary_band_stats_safe_defaults(tmp_path):
    """Missing DB -> band_stats is {} (never raises)."""
    import report

    pol = tmp_path / 'policy.yaml'
    pol.write_text('band_orders:\n  light: [Fast]\n')
    s = report.evidence_summary(tmp_path / 'cfg.json', pol,
                                tmp_path / 'missing.db')
    assert s['band_stats'] == {}
    # failure path keeps the four legacy keys intact
    assert set(s) >= {'auto_tune', 'pins', 'preset_stats', 'orders', 'band_stats'}


def test_dial_command_prints_band_block(tmp_path, capsys):
    """report.py dial prints a per-band outcomes block when band evidence exists."""
    import report
    from helpers import telemetry as tel

    pol = tmp_path / 'policy.yaml'
    pol.write_text('band_orders:\n  light: [Fast]\n')
    cfg = tmp_path / 'cfg.json'
    cfg.write_text('{}')
    db = tmp_path / 't.db'
    conn = tel.init_db(db)
    tel.record_call(conn, 'p', 'Fast', True, 0.1, None, band='light')
    conn.close()

    rc = report.main(['dial', str(cfg), str(pol), str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'band=' in out or 'per-band' in out, out
