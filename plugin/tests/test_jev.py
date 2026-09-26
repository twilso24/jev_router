"""Tests for the bundled jev query helper."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import jev


def _valid_questions():
    return {
        'task': {'type': 'choice', 'instructions': 'Classify', 'criteria': {'code': 'coding', 'other': 'other'}},
        'complexity': {'type': 'score', 'instructions': 'Rate', 'criteria': ['low', 'high']},
        'vision': {'type': 'noul', 'instructions': 'Need vision?'},
    }


def test_accepts_string_state():
    jev.validate_request('hello', _valid_questions())

def test_accepts_dict_state():
    jev.validate_request({'key': 'val'}, _valid_questions())

def test_accepts_list_state():
    jev.validate_request(['a', 'b'], _valid_questions())

def test_rejects_none_state():
    try:
        jev.validate_request(None, _valid_questions())
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_empty_questions():
    try:
        jev.validate_request('hello', {})
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_non_dict_questions():
    try:
        jev.validate_request('hello', ['a'])
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_bad_question_type():
    try:
        jev.validate_request('hello', {'q': {'type': 'unknown', 'instructions': 'x'}})
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_missing_instructions():
    try:
        jev.validate_request('hello', {'q': {'type': 'noul'}})
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_choice_with_one_criterion():
    try:
        jev.validate_request('hello', {'q': {'type': 'choice', 'instructions': 'x', 'criteria': {'a': 'desc'}}})
        assert False, 'should raise'
    except ValueError:
        pass

def test_rejects_score_with_one_criterion():
    try:
        jev.validate_request('hello', {'q': {'type': 'score', 'instructions': 'x', 'criteria': ['a']}})
        assert False, 'should raise'
    except ValueError:
        pass

def test_config_valid_minimal():
    model, timeout = jev.validate_config({'api_key': 'k'})
    assert model == 'jev-latest'
    assert timeout == 30

def test_config_valid_full():
    model, timeout = jev.validate_config({'api_key': 'k', 'model': 'jev-1', 'timeout': 10})
    assert model == 'jev-1'
    assert timeout == 10

def test_config_rejects_missing_key():
    try:
        jev.validate_config({})
        assert False, 'should raise'
    except ValueError:
        pass

def test_config_rejects_empty_model():
    try:
        jev.validate_config({'api_key': 'k', 'model': '  '})
        assert False, 'should raise'
    except ValueError:
        pass

def test_config_rejects_bad_timeout():
    try:
        jev.validate_config({'api_key': 'k', 'timeout': 0})
        assert False, 'should raise'
    except ValueError:
        pass

def _fake_response():
    resp = MagicMock()
    resp.answers = {
        'task': {'choice': 'code', 'probabilities': {'code': 0.9, 'other': 0.1}, 'confidence': 0.8},
        'complexity': {'score': 1.2, 'probabilities': {'low': 0.3, 'high': 0.7}, 'confidence': 0.7},
        'vision': {'noul': 0.1, 'probabilities': {'yes': 0.1, 'no': 0.9}, 'confidence': 0.9},
    }
    resp.model = 'jev-latest'
    resp.usage = {'input_tokens': 10, 'output_tokens': 5}
    return resp


def test_query_success():
    import msgspec
    import unittest.mock
    client = MagicMock()
    client.system_one = AsyncMock(return_value=_fake_response())
    fake_builtins = {
        'answers': {
            'task': {'choice': 'code', 'probabilities': {'code': 0.9, 'other': 0.1}, 'confidence': 0.8},
            'complexity': {'score': 1.2, 'probabilities': {'low': 0.3, 'high': 0.7}, 'confidence': 0.7},
            'vision': {'noul': 0.1, 'probabilities': {'yes': 0.1, 'no': 0.9}, 'confidence': 0.9},
        },
        'model': 'jev-latest',
        'usage': {'input_tokens': 10, 'output_tokens': 5},
    }
    with unittest.mock.patch.object(msgspec, 'to_builtins', return_value=fake_builtins):
        result = asyncio.run(jev.query(client, 'hello', _valid_questions(), 'jev-latest'))
    assert 'answers' in result
    assert 'elapsed_ms' in result
    assert result['model'] == 'jev-latest'

def test_query_incomplete_answers_raises():
    client = MagicMock()
    resp = _fake_response()
    resp.answers = {'task': {'choice': 'code', 'probabilities': {}, 'confidence': 0.5}}
    client.system_one = AsyncMock(return_value=resp)
    result = asyncio.run(jev.query(client, 'hello', _valid_questions(), 'jev-latest'))
    assert result is None

def test_query_network_error_returns_none():
    client = MagicMock()
    client.system_one = AsyncMock(side_effect=RuntimeError('connection refused'))
    result = asyncio.run(jev.query(client, 'hello', _valid_questions(), 'jev-latest'))
    assert result is None

def test_query_timeout_returns_none():
    async def slow(*a, **k):
        await asyncio.sleep(10)
    client = MagicMock()
    client.system_one = slow
    result = asyncio.run(jev.query(client, 'hello', _valid_questions(), 'jev-latest', timeout_s=0.1))
    assert result is None

def test_result_cards_shape():
    result = {
        'answers': {
            'task': {'choice': 'code', 'probabilities': {'code': 0.9, 'other': 0.1}, 'confidence': 0.8},
        },
        'model': 'jev-latest',
        'usage': {'input_tokens': 10},
        'elapsed_ms': 50,
    }
    questions = {'task': {'type': 'choice', 'instructions': 'Classify', 'criteria': {'code': 'coding', 'other': 'other'}}}
    cards = jev.result_cards(result, questions)
    assert 'cards' in cards
    assert len(cards['cards']) == 1
    assert cards['cards'][0]['id'] == 'task'
    assert 'distribution' in cards['cards'][0]


def test_resolve_api_key_prefers_config():
    assert jev.resolve_api_key({'jev_api_key': 'cfg-key'}, {'TYPESAFE_API_KEY': 'env-key'}) == 'cfg-key'

def test_resolve_api_key_falls_back_to_env():
    assert jev.resolve_api_key({'jev_api_key': ''}, {'TYPESAFE_API_KEY': 'env-key'}) == 'env-key'

def test_resolve_api_key_missing_everywhere():
    assert jev.resolve_api_key({}, {}) == ''

def test_resolve_api_key_strips_config_value():
    assert jev.resolve_api_key({'jev_api_key': '  k  '}, {}) == 'k'

def test_query_reports_errors_via_on_error():
    client = MagicMock()
    client.system_one = AsyncMock(side_effect=RuntimeError('boom'))
    seen = []
    result = asyncio.run(jev.query(
        client, 'hello', _valid_questions(), 'jev-latest', on_error=seen.append))
    assert result is None
    assert seen, 'on_error must receive the failure detail'
    assert 'RuntimeError' in seen[0]



def test_get_client_reuses_instance_per_key_model_timeout():
    a = jev.get_client('k1', 'jev-latest', 30)
    assert jev.get_client('k1', 'jev-latest', 30) is a
    assert jev.get_client('k2', 'jev-latest', 30) is not a
    assert jev.get_client('k1', 'jev-x', 30) is not a
    assert jev.get_client('k1', 'jev-latest', 10) is not a

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
