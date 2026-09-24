"""Dynamic profile switching: gates, decision logic, consecutive matching, cooldown.

Run: cd /a0 && /opt/venv-a0/bin/python <this file>
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import dynamic_switch

CFG_AUTO = {'enabled': True, 'chat_preselect': True, 'delegation_mode': 'auto',
            'dynamic_switch_enabled': True, 'dynamic_switch_threshold': 0.7,
            'dynamic_switch_consecutive': 2, 'dynamic_switch_cooldown_seconds': 30}
PROFILES = ['default', 'developer', 'researcher', 'hacker', 'test-engineer']


def test_gate_off_when_dynamic_disabled():
    cfg = CFG_AUTO.copy()
    cfg['dynamic_switch_enabled'] = False
    assert not dynamic_switch.should_dynamic_switch(cfg)


def test_gate_off_when_advise_mode():
    cfg = CFG_AUTO.copy()
    cfg['delegation_mode'] = 'advise'
    assert not dynamic_switch.should_dynamic_switch(cfg)


def test_gate_on_when_threshold_missing():
    """Missing threshold defers to decide()'s default; gate stays on."""
    cfg = CFG_AUTO.copy()
    del cfg['dynamic_switch_threshold']
    assert dynamic_switch.should_dynamic_switch(cfg)


def test_gate_on_when_all_set():
    assert dynamic_switch.should_dynamic_switch(CFG_AUTO)


def test_decide_low_confidence():
    profile, reason = dynamic_switch.decide('coding', 0.5, PROFILES, CFG_AUTO)
    assert profile is None
    assert 'confidence' in reason


def test_decide_good_confidence():
    profile, reason = dynamic_switch.decide('coding', 0.9, PROFILES, CFG_AUTO)
    assert profile == 'developer'


def test_decide_unknown_task_class():
    profile, reason = dynamic_switch.decide('creative', 0.9, PROFILES, CFG_AUTO)
    assert profile is None


def test_decide_task_class_no_match():
    profile, reason = dynamic_switch.decide('chat', 0.9, PROFILES, CFG_AUTO)
    assert profile is None


def test_decide_nan_confidence_keeps_current():
    profile, reason = dynamic_switch.decide('coding', float('nan'), PROFILES, CFG_AUTO)
    assert profile is None
    assert 'confidence' in reason


def test_consecutive_matching_first_only():
    """First matching judgment should NOT trigger switch."""
    state = dynamic_switch.new_state()
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 0.9) is False


def test_consecutive_matching_second_triggers():
    """Second consecutive matching judgment SHOULD trigger switch."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 0.9) is True


def test_consecutive_breaks_on_change():
    """A changed class never counts as consecutive with the old one."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    # first research message: stored class is still coding -> must NOT switch
    assert dynamic_switch.should_switch(state, 'research', 'researcher', 0.9) is False
    state = dynamic_switch.record_match(state, 'research', 'researcher', 0.9)
    # second consecutive research message: approved policy says switch now
    assert dynamic_switch.should_switch(state, 'research', 'researcher', 0.9) is True


def test_second_consecutive_after_change_switches():
    """E2E regression: other -> coding -> coding switches on the 2nd coding."""
    state = dynamic_switch.new_state()
    assert dynamic_switch.should_switch(state, 'other', None, 0.9) is False
    state = dynamic_switch.record_match(state, 'other', None, 0.9)
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 1.0) is False
    state = dynamic_switch.record_match(state, 'coding', 'developer', 1.0)
    # msg3: second consecutive coding judgment (conf 1.00 then 0.99 live)
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 0.99) is True


def test_consecutive_tunable_honored():
    """dynamic_switch_consecutive=3 requires three total judgments."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    assert dynamic_switch.should_switch(
        state, 'coding', 'developer', 0.9, consecutive=3) is False  # 2 < 3
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    assert dynamic_switch.should_switch(
        state, 'coding', 'developer', 0.9, consecutive=3) is True  # 3 >= 3


def test_cooldown_prevents_switch():
    """Within cooldown, switch should NOT occur."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state['last_switch_time'] = 100
    state['last_switch_profile'] = 'developer'
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 0.9, now=110) is False


def test_cooldown_allows_switch_after():
    """After cooldown, switch SHOULD occur."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state['last_switch_time'] = 100
    state['last_switch_profile'] = 'developer'
    assert dynamic_switch.should_switch(state, 'coding', 'developer', 0.9, now=140) is True


def test_class_flip_requires_new_streak():
    """A single flipped-class judgment must NOT switch (conservative policy)."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state['last_switch_time'] = 100
    state['last_switch_profile'] = 'developer'
    assert dynamic_switch.should_switch(state, 'security', 'hacker', 0.9, now=110) is False


def test_different_profile_bypasses_cooldown_after_new_streak():
    """Different target profile bypasses the same-profile cooldown."""
    state = dynamic_switch.new_state()
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state = dynamic_switch.record_match(state, 'coding', 'developer', 0.9)
    state['last_switch_time'] = 100
    state['last_switch_profile'] = 'developer'
    state = dynamic_switch.record_match(state, 'security', 'hacker', 0.9)  # flip resets
    state = dynamic_switch.record_match(state, 'security', 'hacker', 0.9)  # streak=1
    assert dynamic_switch.should_switch(state, 'security', 'hacker', 0.9, now=110) is True


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
