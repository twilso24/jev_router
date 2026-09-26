# S9 (TDD) RED: delegation auto-execution (approved experiment).
# gate.auto_exec verdict + first-action directive + router guard.
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import gate
from helpers.signals import Signals


def _sig(dele=0.9, cls='coding'):
    return Signals(task_class=cls, task_class_confidence=0.9,
                   complexity=1.5, vision_needed=0.05, delegate_worthy=dele)


AUTO_CFG = {'delegation_mode': 'auto', 'delegation_auto_execute': True}


def test_auto_exec_requires_mode_flag_and_floor():
    assert gate.evaluate(_sig(), AUTO_CFG).auto_exec is True
    # flag off (even in auto mode) -> advisory/directive only
    assert gate.evaluate(_sig(), {'delegation_mode': 'auto'}).auto_exec is False
    # mode advise -> never
    assert gate.evaluate(_sig(), {'delegation_auto_execute': True}).auto_exec is False
    # below default floor (0.8)
    assert gate.evaluate(_sig(dele=0.75), AUTO_CFG).auto_exec is False
    # custom floor
    assert gate.evaluate(
        _sig(dele=0.75),
        dict(AUTO_CFG, delegation_auto_execute_floor=0.7)).auto_exec is True
    assert gate.evaluate(None, AUTO_CFG).auto_exec is False


def test_auto_exec_advice_is_strong_directive():
    import json
    sig = _sig()
    g = gate.evaluate(sig, AUTO_CFG)
    advice = gate.compose_advice(sig, g)
    assert 'first action' in advice
    payload = json.loads(advice.split('JEVDIALOG ', 1)[1])
    assert payload['auto_exec'] is True


def test_plain_auto_advice_has_no_auto_exec():
    import json
    sig = _sig()
    g = gate.evaluate(sig, {'delegation_mode': 'auto'})
    assert g.auto_exec is False
    advice = gate.compose_advice(sig, g)
    payload = json.loads(advice.split('JEVDIALOG ', 1)[1])
    assert payload.get('auto_exec') is False
