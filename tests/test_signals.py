# Task 3 (TDD): Jev signal batch - RED first.
# helpers/signals.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_signals.py
import asyncio
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import signals


def _ok_result():
    return {'model': 'jev-latest', 'elapsed_ms': 500, 'answers': {
        'task_class': {'type': 'choice', 'choice': 'coding',
                       'confidence': 0.9,
                       'probabilities': {'coding': 0.9, 'other': 0.1}},
        'complexity': {'type': 'score', 'score': 1.5, 'confidence': 0.8,
                       'legend': {'0': 'trivial', '1': 'medium', '2': 'hard'},
                       'probabilities': {'0': 0.1, '1': 0.3, '2': 0.6}},
        'vision_needed': {'type': 'noul', 'noul': 0.05},
        'delegate_worthy': {'type': 'noul', 'noul': 0.8},
    }}


def test_success_parses_into_signals():
    async def fake_query(client, state, questions, model):
        return _ok_result()
    sig = asyncio.run(signals.judge(
        message='refactor this module and add tests',
        attachments=[],
        query_fn=fake_query, client=object(), model='jev-latest'))
    assert sig is not None
    assert sig.task_class == 'coding'
    assert sig.task_class_confidence == 0.9
    assert sig.complexity == 1.5
    assert sig.vision_needed == 0.05
    assert sig.delegate_worthy == 0.8


def test_query_exception_returns_none():
    async def boom(client, state, questions, model):
        raise RuntimeError('jev down')
    sig = asyncio.run(signals.judge(
        message='anything', attachments=[],
        query_fn=boom, client=object(), model='jev-latest'))
    assert sig is None


def test_timeout_returns_none():
    async def slow(client, state, questions, model):
        await asyncio.sleep(10)
        return _ok_result()
    sig = asyncio.run(signals.judge(
        message='anything', attachments=[],
        query_fn=slow, client=object(), model='jev-latest',
        timeout_s=0.05))
    assert sig is None


def test_malformed_answers_return_none():
    async def weird(client, state, questions, model):
        return {'model': 'x', 'answers': {'only_one': {'type': 'noul', 'noul': 0.5}}}
    sig = asyncio.run(signals.judge(
        message='x', attachments=[],
        query_fn=weird, client=object(), model='jev-latest'))
    assert sig is None




def test_build_state_includes_pool_snapshot():
    from helpers.pool import PoolEntry
    entries = [
        PoolEntry('Power', 'chat', 'zai_coding', 'glm-5.3', vision=False),
        PoolEntry('Default', 'chat', 'zai_coding', 'glm-5.3-flash', vision=True),
    ]
    state = signals.build_state('hi', [], pool_entries=entries)
    snap = state['available_models']
    assert len(snap) == 2
    assert snap[0] == {'preset': 'Power', 'provider': 'zai_coding',
                       'model': 'glm-5.3', 'vision': False}
    assert snap[1]['vision'] is True


def test_build_state_without_pool_omits_snapshot():
    state = signals.build_state('hi', [])
    assert 'available_models' not in state


def test_judge_passes_pool_snapshot_to_query():
    captured = {}

    async def fake_query(client, state, questions, model):
        captured['state'] = state
        return _ok_result()

    from helpers.pool import PoolEntry
    entries = [PoolEntry('Default', 'chat', 'p', 'm')]
    asyncio.run(signals.judge(
        message='x', attachments=[], query_fn=fake_query,
        client=object(), model='jev-latest', pool_entries=entries))
    assert captured['state']['available_models'][0]['preset'] == 'Default'


def _with_dbg_capture():
     """Patch signals._dbg to capture lines; returns (logged, restore)."""
     logged = []
     orig = getattr(signals, '_dbg', None)
     signals._dbg = lambda msg: logged.append(msg)

     def restore():
         if orig is not None:
             signals._dbg = orig
         elif hasattr(signals, '_dbg'):
             del signals._dbg

     return logged, restore


def test_timeout_failure_is_logged_with_detail():
     logged, restore = _with_dbg_capture()
     try:
         async def slow(client, state, questions, model):
             await asyncio.sleep(10)
             return _ok_result()
         sig = asyncio.run(signals.judge(
             message='anything', attachments=[], query_fn=slow,
             client=object(), model='jev-latest', timeout_s=0.05))
         assert sig is None
         assert logged, 'timeout failure was not logged'
         line = logged[0]
         assert 'TimeoutError' in line, line
         assert 'timeout_s=0.05' in line, line
         assert 'elapsed_ms=' in line, line
     finally:
         restore()


def test_query_exception_failure_is_logged_with_detail():
     logged, restore = _with_dbg_capture()
     try:
         async def boom(client, state, questions, model):
             raise RuntimeError('jev down')
         sig = asyncio.run(signals.judge(
             message='anything', attachments=[], query_fn=boom,
             client=object(), model='jev-latest'))
         assert sig is None
         assert logged, 'exception failure was not logged'
         line = logged[0]
         assert 'RuntimeError' in line, line
         assert 'jev down' in line, line
         assert 'elapsed_ms=' in line, line
     finally:
         restore()


def test_timeout_retry_recovers_on_second_attempt():
    logged, restore = _with_dbg_capture()
    calls = []
    try:
        async def flaky(client, state, questions, model):
            calls.append(1)
            if len(calls) == 1:
                await asyncio.sleep(10)
            return _ok_result()
        sig = asyncio.run(signals.judge(
            message='refactor module and add tests', attachments=[],
            query_fn=flaky, client=object(), model='jev-latest',
            timeout_s=0.05))
        assert sig is not None, 'retry did not recover the judgment'
        assert sig.task_class == 'coding', sig
        assert len(calls) == 2, f'expected 2 attempts, got {len(calls)}'
        assert any('retry' in m.lower() for m in logged), logged
    finally:
        restore()


def test_timeout_retry_exhausted_returns_none():
    logged, restore = _with_dbg_capture()
    calls = []
    try:
        async def always_slow(client, state, questions, model):
            calls.append(1)
            await asyncio.sleep(10)
            return _ok_result()
        sig = asyncio.run(signals.judge(
            message='anything', attachments=[], query_fn=always_slow,
            client=object(), model='jev-latest', timeout_s=0.05))
        assert sig is None
        assert len(calls) == 2, f'expected 2 attempts, got {len(calls)}'
        assert any('attempts=2' in m for m in logged), logged
        assert any('TimeoutError' in m for m in logged), logged
    finally:
        restore()


def test_non_timeout_error_is_not_retried():
    logged, restore = _with_dbg_capture()
    calls = []
    try:
        async def boom(client, state, questions, model):
            calls.append(1)
            raise RuntimeError('jev down')
        sig = asyncio.run(signals.judge(
            message='anything', attachments=[], query_fn=boom,
            client=object(), model='jev-latest', timeout_s=0.05))
        assert sig is None
        assert len(calls) == 1, f'non-timeout error was retried ({len(calls)})'
        assert any('RuntimeError' in m and 'attempts=1' in m for m in logged), logged
    finally:
        restore()




# --- Fit-aware routing & profile-aware judgments (T1) ---


def _entries():
    from helpers.pool import PoolEntry
    return [
        PoolEntry('Fast', 'chat', 'openrouter', 'm1', vision=False),
        PoolEntry('Story', 'chat', 'a0_venice', 'aion', vision=True),
    ]


def _fit_result(fit='Story', conf=0.8, profile=0.9):
    r = _ok_result()
    r['answers']['preset_fit'] = {
        'type': 'choice', 'choice': fit, 'confidence': conf,
        'probabilities': {fit: conf}}
    r['answers']['profile_match'] = {'type': 'noul', 'noul': profile}
    return r


def test_build_questions_default_returns_core_four():
    q = signals.build_questions()
    assert set(q) == {'task_class', 'complexity', 'vision_needed',
                      'delegate_worthy'}


def test_build_questions_pool_adds_preset_fit_choice():
    q = signals.build_questions(pool_entries=_entries())
    fit = q.get('preset_fit')
    assert fit and fit['type'] == 'choice'
    assert set(fit['criteria']) == {'Fast', 'Story'}
    assert 'a0_venice' in fit['criteria']['Story']
    assert 'vision' in fit['criteria']['Story']


def test_build_questions_single_preset_skips_fit():
    from helpers.pool import PoolEntry
    q = signals.build_questions(pool_entries=[PoolEntry('Only', 'chat', 'p', 'm')])
    assert 'preset_fit' not in q


def test_build_questions_profile_adds_profile_match():
    q = signals.build_questions(agent_profile='developer')
    pm = q.get('profile_match')
    assert pm and pm['type'] == 'noul'
    assert 'developer' in pm['instructions']


def test_build_questions_no_profile_skips_profile_match():
    assert 'profile_match' not in signals.build_questions()


def test_build_state_carries_profile():
    state = signals.build_state('hi', [], agent_profile='hacker')
    assert state['agent_profile'] == 'hacker'
    assert signals.build_state('hi', [])['agent_profile'] == ''


def test_signals_new_fields_default_off():
    s = signals.Signals(task_class='chat', task_class_confidence=1.0,
                        complexity=0.0, vision_needed=0.0, delegate_worthy=0.0)
    assert s.preset_fit is None
    assert s.preset_fit_confidence == 0.0
    assert s.profile_match is None


def test_parse_tolerates_missing_fit_answers():
    s = signals._parse(_ok_result())
    assert s is not None
    assert s.preset_fit is None
    assert s.preset_fit_confidence == 0.0
    assert s.profile_match is None


def test_parse_reads_valid_fit_and_profile():
    s = signals._parse(_fit_result(), fit_options=['Fast', 'Story'])
    assert s.preset_fit == 'Story'
    assert s.preset_fit_confidence == 0.8
    assert s.profile_match == 0.9


def test_parse_rejects_fit_outside_options():
    s = signals._parse(_fit_result(fit='Ghost'), fit_options=['Fast', 'Story'])
    assert s.preset_fit is None
    assert s.preset_fit_confidence == 0.0


def test_parse_fit_confidence_defaults_to_zero():
    r = _fit_result()
    del r['answers']['preset_fit']['confidence']
    s = signals._parse(r, fit_options=['Story'])
    assert s.preset_fit == 'Story'
    assert s.preset_fit_confidence == 0.0


def test_judge_carries_profile_and_fit_into_query():
    captured = {}

    async def fake_query(client, state, questions, model):
        captured['state'] = state
        captured['questions'] = questions
        return _fit_result()

    s = asyncio.run(signals.judge(
        message='write an epic', attachments=[], query_fn=fake_query,
        client=object(), model='jev-latest', agent_profile='developer',
        pool_entries=_entries()))
    assert captured['state']['agent_profile'] == 'developer'
    assert 'preset_fit' in captured['questions']
    assert 'profile_match' in captured['questions']
    assert s.preset_fit == 'Story'
    assert s.profile_match == 0.9


def test_judge_without_profile_or_pool_asks_core_only():
    captured = {}

    async def fake_query(client, state, questions, model):
        captured['questions'] = questions
        return _ok_result()

    asyncio.run(signals.judge(
        message='hi', attachments=[], query_fn=fake_query,
        client=object(), model='jev-latest'))
    assert 'profile_match' not in captured['questions']
    assert 'preset_fit' not in captured['questions']


def test_judge_drops_invalid_fit_choice():
    async def fake_query(client, state, questions, model):
        return _fit_result(fit='Ghost')

    s = asyncio.run(signals.judge(
        message='x', attachments=[], query_fn=fake_query,
        client=object(), model='jev-latest', pool_entries=_entries()))
    assert s.preset_fit is None
    assert s.preset_fit_confidence == 0.0


# --- Audit round 2: task_class must be one of the offered options ---


def test_parse_out_of_options_task_class_falls_back_to_chat():
    res = {'answers': {
        'task_class': {'type': 'choice', 'choice': 'drop table users',
                       'confidence': 0.9},
        'complexity': {'score': 1.2},
        'vision_needed': {'noul': 0.1},
        'delegate_worthy': {'noul': 0.5}}}
    sig = signals._parse(res)
    assert sig is not None, 'a bogus class must not kill the judgment'
    assert sig.task_class == 'chat'
