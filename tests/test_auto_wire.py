# TDD RED: auto-wire new presets into band orders + prune dead names.
# helpers/auto_wire.py does not exist yet.
# Run: /opt/venv-a0/bin/python tests/test_auto_wire.py
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import auto_wire


def _policy(tmp: Path, orders=None, extra=None) -> Path:
    data = {'provider_rules': {'include': [], 'exclude': ['lm_studio']}}
    if orders:
        data['band_orders'] = orders
    if extra:
        data.update(extra)
    p = tmp / 'routing-policy.yaml'
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def _read(p: Path) -> dict:
    return yaml.safe_load(p.read_text())


def test_append_new_preset_to_every_band_tail(tmp_path):
    p = _policy(tmp_path, orders={
        'light': ['Fast', 'Default'],
        'medium': ['Default', 'Fast'],
        'heavy': ['Power', 'Default'],
    })
    rep = auto_wire.sync_band_orders(
        p, ['Default', 'Fast', 'Power', 'Storyteller'], tmp_path / 'wire-state.json')
    out = _read(p)['band_orders']
    assert out['light'] == ['Fast', 'Default', 'Storyteller']
    assert out['medium'] == ['Default', 'Fast', 'Storyteller']
    assert out['heavy'] == ['Power', 'Default', 'Storyteller']
    assert rep.added == ['Storyteller']
    assert rep.pruned == []


def test_prune_dead_names_from_bands(tmp_path):
    p = _policy(tmp_path, orders={
        'light': ['Ghost', 'Fast', 'Default'],
        'medium': ['Default', 'Ghost'],
        'heavy': ['Power', 'Default', 'Phantom'],
    })
    rep = auto_wire.sync_band_orders(
        p, ['Default', 'Fast', 'Power'], tmp_path / 'wire-state.json')
    out = _read(p)['band_orders']
    assert out['light'] == ['Fast', 'Default']
    assert out['medium'] == ['Default']
    assert out['heavy'] == ['Power', 'Default']
    assert rep.added == []
    assert sorted(rep.pruned) == ['Ghost', 'Phantom']


def test_sync_idempotent_no_rewrite(tmp_path):
    p = _policy(tmp_path, orders={
        'light': ['Fast', 'Default'],
        'medium': ['Default', 'Fast'],
        'heavy': ['Power', 'Default'],
    })
    state = tmp_path / 'wire-state.json'
    auto_wire.sync_band_orders(p, ['Default', 'Fast', 'Power'], state)
    before = p.read_bytes()
    mtime = os.path.getmtime(p)
    time.sleep(0.05)
    rep = auto_wire.sync_band_orders(p, ['Default', 'Fast', 'Power'], state)
    assert p.read_bytes() == before
    assert os.path.getmtime(p) == mtime
    assert rep.added == [] and rep.pruned == []


def test_report_persisted_and_reloaded(tmp_path):
    p = _policy(tmp_path, orders={
        'light': ['Fast'], 'medium': ['Fast'], 'heavy': ['Fast'],
    })
    state = tmp_path / 'wire-state.json'
    rep = auto_wire.sync_band_orders(p, ['Fast', 'New1'], state)
    data = json.loads(state.read_text())
    assert data['added'] == ['New1']
    assert data['pruned'] == []
    assert isinstance(data['ts'], float)
    # no-op sync must not clobber the last real report
    auto_wire.sync_band_orders(p, ['Fast', 'New1'], state)
    assert json.loads(state.read_text())['added'] == ['New1']
    assert rep.added == ['New1']


def test_malformed_yaml_is_noop(tmp_path):
    p = tmp_path / 'routing-policy.yaml'
    p.write_text('band_orders: [unclosed')
    before = p.read_bytes()
    rep = auto_wire.sync_band_orders(
        p, ['A', 'B'], tmp_path / 'wire-state.json')
    assert p.read_bytes() == before
    assert rep.added == [] and rep.pruned == []


def test_preserves_other_policy_keys(tmp_path):
    p = _policy(tmp_path, orders={
        'light': ['Fast'], 'medium': ['Fast'], 'heavy': ['Fast'],
    }, extra={'auto_tune': True,
              'schedules': [{'name': 'night', 'window': '22:00-06:00'}]})
    auto_wire.sync_band_orders(
        p, ['Fast', 'X'], tmp_path / 'wire-state.json')
    data = _read(p)
    assert data['auto_tune'] is True
    assert data['schedules'] == [{'name': 'night', 'window': '22:00-06:00'}]
    assert data['provider_rules']['exclude'] == ['lm_studio']
    assert data['band_orders']['light'] == ['Fast', 'X']


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))
