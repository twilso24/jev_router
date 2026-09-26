# Task 7 (TDD): delegation gate - RED first.
# helpers/gate.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_gate.py
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import gate
from helpers.signals import Signals


def _sig(dele=0.5, cls='coding'):
    return Signals(task_class=cls, task_class_confidence=0.9,
                   complexity=1.5, vision_needed=0.05, delegate_worthy=dele)


def test_high_delegation_and_known_class_recommends():
    g = gate.evaluate(_sig(dele=0.8, cls='coding'),
                      {'delegation_threshold': 0.6})
    assert g.recommend is True
    assert g.profile == 'developer'
    assert 'coding' in g.reason or 'developer' in g.reason


def test_below_threshold_no_recommendation():
    g = gate.evaluate(_sig(dele=0.4), {'delegation_threshold': 0.6})
    assert g.recommend is False
    assert g.profile is None
    assert 'threshold' in g.reason.lower()


def test_unmapped_class_no_recommendation():
    g = gate.evaluate(_sig(dele=0.9, cls='chat'),
                      {'delegation_threshold': 0.6})
    assert g.recommend is False
    assert g.profile is None


def test_class_to_profile_map():
    assert gate.CLASS_TO_PROFILE['coding'] == 'developer'
    assert gate.CLASS_TO_PROFILE['research'] == 'researcher'
    assert gate.CLASS_TO_PROFILE['security'] == 'hacker'
    assert gate.CLASS_TO_PROFILE['testing'] == 'test-engineer'
    assert 'chat' not in gate.CLASS_TO_PROFILE


def test_mode_auto_vs_advise_in_reason():
    g_advise = gate.evaluate(_sig(dele=0.8),
                             {'delegation_threshold': 0.6,
                              'delegation_mode': 'advise'})
    g_auto = gate.evaluate(_sig(dele=0.8),
                           {'delegation_threshold': 0.6,
                            'delegation_mode': 'auto'})
    assert 'advise' in g_advise.reason.lower()
    assert 'auto' in g_auto.reason.lower()


def test_boundary_exactly_at_threshold():
    g = gate.evaluate(_sig(dele=0.6), {'delegation_threshold': 0.6})
    assert g.recommend is True


def test_none_signals_safe():
    g = gate.evaluate(None, {})
    assert g.recommend is False and g.profile is None


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS {t.__name__}')
        except Exception as exc:
            failed += 1
            print(f'FAIL {t.__name__}: {type(exc).__name__}: {exc}')
    print(f'--- {len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)


# --- S7 (TDD) RED: structured delegation advisory ---
import json


def test_advisory_payload_shape_when_recommending():
    sig = _sig(dele=0.8, cls='coding')
    g = gate.evaluate(sig, {'delegation_threshold': 0.6})
    payload = gate.advisory_payload(sig, g)
    assert payload is not None
    assert payload['profile'] == 'developer'
    assert payload['task_class'] == 'coding'
    assert abs(payload['confidence'] - 0.8) < 1e-9
    assert payload['reason']


def test_advisory_payload_none_when_not_recommending():
    sig = _sig(dele=0.4)
    g = gate.evaluate(sig, {'delegation_threshold': 0.6})
    assert gate.advisory_payload(sig, g) is None


def test_compose_advice_advise_mode_has_parseable_block():
    sig = _sig(dele=0.8, cls='coding')
    g = gate.evaluate(sig, {'delegation_threshold': 0.6})
    advice = gate.compose_advice(sig, g)
    assert 'call_subordinate(profile="developer")' in advice
    assert 'Consider' in advice
    marker = 'JEVDIALOG '
    assert marker in advice
    payload = json.loads(advice.split(marker, 1)[1])
    assert payload['profile'] == 'developer'


def test_compose_advice_auto_mode_is_directive():
    sig = _sig(dele=0.8, cls='coding')
    g = gate.evaluate(sig, {'delegation_mode': 'auto'})
    advice = gate.compose_advice(sig, g)
    assert 'unless blocked' in advice
    assert 'JEVDIALOG ' in advice


def test_compose_advice_never_raises_on_junk():
    sig = _sig(dele=0.8, cls='coding')
    g = gate.evaluate(sig, {'delegation_threshold': 0.6})
    assert gate.compose_advice(None, g) is None
    assert gate.compose_advice(sig, None) is None


# --- FIX F3 (review fan-out): malformed threshold must not disable routing ---

def test_malformed_threshold_falls_back_to_default():
    g = gate.evaluate(_sig(dele=0.7), {'delegation_threshold': 'garbage'})
    assert g.recommend is True
    assert g.profile == 'developer'
    g2 = gate.evaluate(_sig(dele=0.4), {'delegation_threshold': 'garbage'})
    assert g2.recommend is False
