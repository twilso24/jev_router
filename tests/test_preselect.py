"""Pre-selection pure logic: gates, request parsing, mapping, decide, run.

RED first: helpers/preselect.py does not exist yet.
Run: cd /a0 && /opt/venv-a0/bin/python <this file>
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import preselect

CFG_AUTO = {'enabled': True, 'chat_preselect': True, 'delegation_mode': 'auto'}
PROFILES = ['default', 'developer', 'researcher', 'hacker', 'agent0']


def test_gate_off_when_disabled():
    assert not preselect.should_preselect({'enabled': False, 'chat_preselect': True, 'delegation_mode': 'auto'})

def test_gate_off_when_preselect_disabled():
    assert not preselect.should_preselect({'enabled': True, 'chat_preselect': False, 'delegation_mode': 'auto'})

def test_gate_off_in_advise_mode():
    assert not preselect.should_preselect({'enabled': True, 'chat_preselect': True, 'delegation_mode': 'advise'})

def test_gate_on_when_all_set():
    assert preselect.should_preselect(CFG_AUTO)

def test_gate_tolerates_missing_keys():
    assert not preselect.should_preselect({})


def test_parse_new_chat_message():
    msg, explicit = preselect.parse_request({'message': 'fix this python bug'})
    assert msg == 'fix this python bug'
    assert explicit is None

def test_parse_skips_existing_context():
    msg, explicit = preselect.parse_request({'message': 'hi', 'context_id': 'abc'})
    assert msg == ''

def test_parse_reports_explicit_profile():
    msg, explicit = preselect.parse_request({'message': 'hi', 'agent_profile': 'researcher'})
    assert msg == 'hi'
    assert explicit == 'researcher'

def test_parse_tolerates_none():
    assert preselect.parse_request(None) == ('', None)


def test_profile_for_known_class():
    assert preselect.profile_for('coding', PROFILES) == 'developer'

def test_profile_for_missing_profile_returns_none():
    assert preselect.profile_for('testing', PROFILES) is None  # test-engineer not in list

def test_profile_for_unknown_class_returns_none():
    assert preselect.profile_for('chat', PROFILES) is None

def test_profile_for_empty_available():
    assert preselect.profile_for('coding', []) is None


def test_decide_skips_chat_class():
    profile, reason = preselect.decide('chat', 0.99, PROFILES, CFG_AUTO)
    assert profile is None
    assert 'chat' in reason

def test_decide_low_confidence_skips():
    profile, reason = preselect.decide('coding', 0.3, PROFILES, CFG_AUTO)
    assert profile is None
    assert 'confidence' in reason

def test_decide_good_confidence_selects():
    profile, reason = preselect.decide('coding', 0.9, PROFILES, CFG_AUTO)
    assert profile == 'developer'
    assert 'developer' in reason

def test_decide_confidence_threshold_boundary():
    assert preselect.decide('coding', 0.5, PROFILES, CFG_AUTO)[0] == 'developer'


def _fake_query(choice='coding', conf=0.9):
    async def q(client, state, questions, model):
        return {'answers': {'task_class': {'choice': choice, 'confidence': conf}},
                'model': 'jev-latest', 'usage': {}}
    return q


def test_run_success_returns_profile():
    profile, reason = asyncio.run(preselect.run(
        'refactor this module', CFG_AUTO, _fake_query(), object(), 'jev-latest', PROFILES, 2.0))
    assert profile == 'developer'

def test_run_query_failure_keeps_default():
    async def boom(client, state, questions, model):
        raise RuntimeError('jev down')
    profile, reason = asyncio.run(preselect.run(
        'x', CFG_AUTO, boom, object(), 'jev-latest', PROFILES, 2.0))
    assert profile is None
    assert 'jev query failed' in reason

def test_run_timeout_keeps_default():
    async def slow(client, state, questions, model):
        await asyncio.sleep(5)
    profile, reason = asyncio.run(preselect.run(
        'x', CFG_AUTO, slow, object(), 'jev-latest', PROFILES, 0.1))
    assert profile is None
    assert 'jev query failed' in reason

def test_run_bad_answer_keeps_default():
    async def weird(client, state, questions, model):
        return {'answers': {'task_class': {'choice': None}}}
    profile, reason = asyncio.run(preselect.run(
        'x', CFG_AUTO, weird, object(), 'jev-latest', PROFILES, 2.0))
    assert profile is None


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
