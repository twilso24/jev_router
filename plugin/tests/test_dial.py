# S6 (TDD) RED: performance dial reorders band emphasis; pins stay frozen.
# helpers/dial.py does not exist yet; expect ImportError.
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import dial


def _orders():
    return {
        'light': ['Fast', 'Efficiency', 'Default', 'Unhinged', 'Local', 'Power'],
        'medium': ['Default', 'Power', 'Unhinged', 'Local', 'Efficiency', 'Fast'],
        'heavy': ['Power', 'Unhinged', 'Default', 'Local', 'Efficiency', 'Fast'],
    }


def test_balanced_is_noop():
    assert dial.apply_dial(_orders(), 'balanced') == _orders()


def test_cost_promotes_cheap_tiers_in_medium():
    out = dial.apply_dial(_orders(), 'cost')
    assert out['medium'][0] == 'Efficiency'
    assert out['medium'].index('Power') > out['medium'].index('Default')


def test_quality_promotes_power_everywhere():
    out = dial.apply_dial(_orders(), 'quality')
    for band in ('light', 'medium', 'heavy'):
        assert out[band][0] == 'Power'


def test_unknown_presets_keep_relative_order_after_known():
    orders = {'light': ['Mystery', 'Fast', 'Power', 'Zed']}
    out = dial.apply_dial(orders, 'cost')
    assert out['light'] == ['Fast', 'Mystery', 'Zed', 'Power']


def test_pinned_band_unchanged():
    out = dial.apply_dial(_orders(), 'quality', pinned={'heavy': True})
    assert out['heavy'] == _orders()['heavy']


def test_invalid_dial_is_noop():
    assert dial.apply_dial(_orders(), 'bogus') == _orders()


def test_apply_dial_total_on_junk_input():
    """FIX F6 (review): pure-and-total contract on malformed inputs."""
    assert dial.apply_dial(None, 'cost') == {}
    assert dial.apply_dial({'light': 'notalist'}, 'cost') == {}
    assert dial.apply_dial({'light': [1, 2]}, 'quality') == {'light': ['1', '2']}


def test_apply_dial_truthy_nonbool_pins():
    out = dial.apply_dial(_orders(), 'quality', pinned={'heavy': 'yes'})
    assert out['heavy'] == _orders()['heavy']
