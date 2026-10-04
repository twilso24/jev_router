# jev_router reasoning effort: band->effort mapping + chat override precedence.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import reasoning


# --- band mapping ---

def test_effort_for_band_maps_complexity_bands():
    assert reasoning.effort_for_band('light') == 'low'
    assert reasoning.effort_for_band('medium') == 'medium'
    assert reasoning.effort_for_band('heavy') == 'high'


def test_effort_for_band_unknown_band_returns_none():
    assert reasoning.effort_for_band('') is None
    assert reasoning.effort_for_band('unknown') is None
    assert reasoning.effort_for_band(None) is None


# --- precedence: chat override > band effort ---

def test_chat_override_wins_over_band_effort():
    out = reasoning.resolve_effort(
        band='heavy', supported=True, chat_override='minimal')
    assert out == 'minimal'


def test_band_effort_used_when_no_chat_override():
    out = reasoning.resolve_effort(
        band='medium', supported=True, chat_override='')
    assert out == 'medium'


def test_unsupported_model_gets_none_even_with_override():
    out = reasoning.resolve_effort(
        band='heavy', supported=False, chat_override='high')
    assert out is None


def test_disabled_returns_none():
    out = reasoning.resolve_effort(
        band='heavy', supported=True, chat_override='high', enabled=False)
    assert out is None


def test_no_band_no_override_returns_none():
    out = reasoning.resolve_effort(
        band='', supported=True, chat_override='')
    assert out is None


# --- capability check: never raises, plugin may be absent ---

def test_supports_reasoning_never_raises():
    val = reasoning.supports_reasoning('some_provider', 'some/model')
    assert isinstance(val, bool)


def test_supports_reasoning_rejects_empty_args():
    assert reasoning.supports_reasoning('', '') is False
    assert reasoning.supports_reasoning(None, None) is False


# --- chat override reader: defensive against missing plugin ---

def test_chat_override_from_context_defensive():
    class _Ctx:
        def get_data(self, key):
            return {'model': 'p/m', 'effort': 'minimal'}

    class _Agent:
        context = _Ctx()

    out = reasoning.chat_override(_Agent(), 'p/m')
    assert out == 'minimal'


def test_chat_override_mismatched_model_returns_empty():
    class _Ctx:
        def get_data(self, key):
            return {'model': 'other/m', 'effort': 'high'}

    class _Agent:
        context = _Ctx()

    out = reasoning.chat_override(_Agent(), 'p/m')
    assert out == ''


def test_chat_override_without_context_returns_empty():
    class _Agent:
        context = None

    assert reasoning.chat_override(_Agent(), 'p/m') == ''


def test_chat_override_broken_context_returns_empty():
    class _Ctx:
        def get_data(self, key):
            raise RuntimeError('boom')

    class _Agent:
        context = _Ctx()

    assert reasoning.chat_override(_Agent(), 'p/m') == ''


# --- apply effort into model kwargs ---

def test_apply_sets_reasoning_effort_kwarg():
    kwargs = {}
    out = reasoning.apply_to_model_kwargs(
        'a0_venice', 'some-model', kwargs, 'high')
    assert out.get('reasoning_effort') == 'high'


def test_apply_none_effort_leaves_kwargs_unchanged():
    kwargs = {'api_base': 'x'}
    out = reasoning.apply_to_model_kwargs('p', 'm', kwargs, None)
    assert out == {'api_base': 'x'}


def test_apply_never_raises_on_bad_input():
    out = reasoning.apply_to_model_kwargs(None, None, None, 'high')
    assert isinstance(out, dict)


def test_apply_glm53_moves_effort_into_extra_body():
    # GLM-5.3 expects reasoning_effort inside extra_body (plugin parity)
    out = reasoning.apply_to_model_kwargs(
        'zai_coding', 'glm-5.3', {}, 'high')
    assert 'reasoning_effort' not in out
    assert out['extra_body']['reasoning_effort'] == 'high'
    # zai providers also need the thinking flag
    assert out['extra_body']['thinking'] == {'type': 'enabled'}
