# TDD: reasoning effort wiring for routed calls (Option B + gap fix).
# Run: /opt/venv-a0/bin/python -m pytest tests/test_reasoning_effort_wiring.py
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import reasoning
from helpers.router import RouteResult


def test_route_result_carries_band():
    r = RouteResult(model=None, reason='x', band='light')
    assert r.band == 'light'
    # default must not break existing constructors
    r2 = RouteResult(model=None, reason='x')
    assert r2.band == ''


def test_light_band_maps_to_low_effort():
    assert reasoning.effort_for_band('light') == 'low'


def test_medium_band_maps_to_medium_effort():
    assert reasoning.effort_for_band('medium') == 'medium'


def test_heavy_band_maps_to_high_effort():
    assert reasoning.effort_for_band('heavy') == 'high'


def test_unknown_band_yields_no_effort():
    assert reasoning.effort_for_band('') is None
    assert reasoning.effort_for_band(None) is None


def test_resolve_prefers_chat_override_over_band():
    out = reasoning.resolve_effort('heavy', True, chat_override='minimal')
    assert out == 'minimal'


def test_resolve_falls_back_to_band_effort():
    out = reasoning.resolve_effort('medium', True, chat_override='')
    assert out == 'medium'


def test_resolve_returns_none_for_unsupported_models():
    out = reasoning.resolve_effort('heavy', False, chat_override='high')
    assert out is None


def test_apply_writes_effort_to_kwargs():
    out = reasoning.apply_to_model_kwargs('a0_venice', 'some-model', {}, 'high')
    assert out['reasoning_effort'] == 'high'


def test_apply_none_leaves_kwargs_untouched():
    kwargs = {'api_base': 'http://x'}
    out = reasoning.apply_to_model_kwargs('p', 'm', kwargs, None)
    assert out == {'api_base': 'http://x'}


def test_apply_never_raises_on_bad_input():
    out = reasoning.apply_to_model_kwargs(None, None, None, 'high')
    assert isinstance(out, dict)


def test_apply_glm53_uses_extra_body():
    out = reasoning.apply_to_model_kwargs(
        'zai_coding', 'glm-5.3', {}, 'high')
    assert 'reasoning_effort' not in out
    assert out['extra_body']['reasoning_effort'] == 'high'
    assert out['extra_body']['thinking'] == {'type': 'enabled'}


def test_chat_override_reads_context_key():
    class _Ctx:
        def get_data(self, key):
            return {'model': 'a0_venice/m', 'effort': 'xhigh'}

    class _Agent:
        context = _Ctx()

    assert reasoning.chat_override(_Agent(), 'a0_venice/m') == 'xhigh'


def test_chat_override_mismatched_model_is_ignored():
    class _Ctx:
        def get_data(self, key):
            return {'model': 'other/m', 'effort': 'high'}

    class _Agent:
        context = _Ctx()

    assert reasoning.chat_override(_Agent(), 'a0_venice/m') == ''


# --- apply_for_route: end-to-end effort application on a routed model ---

class _FakeEntry:
    def __init__(self, provider='a0_venice', model='m'):
        self.provider = provider
        self.model = model


class _FakeResult:
    def __init__(self, band='', entry=None, model=None):
        self.band = band
        self.entry = entry
        self.model = model


class _FakeModel:
    def __init__(self, kwargs=None):
        self.kwargs = kwargs if kwargs is not None else {}


class _NoAgent:
    context = None


def test_apply_for_route_sets_band_effort(monkeypatch):
    monkeypatch.setattr(reasoning, 'supports_reasoning',
                        lambda p, m: True)
    model = _FakeModel()
    result = _FakeResult(band='heavy', entry=_FakeEntry(), model=model)
    out = reasoning.apply_for_route(_NoAgent(), result)
    assert out == 'high'
    assert model.kwargs['reasoning_effort'] == 'high'


def test_apply_for_route_chat_override_wins(monkeypatch):
    monkeypatch.setattr(reasoning, 'supports_reasoning',
                        lambda p, m: True)

    class _Ctx:
        def get_data(self, key):
            return {'model': 'a0_venice/m', 'effort': 'xhigh'}

    class _Agent:
        context = _Ctx()

    model = _FakeModel()
    result = _FakeResult(band='light', entry=_FakeEntry(), model=model)
    out = reasoning.apply_for_route(_Agent(), result)
    assert out == 'xhigh'
    assert model.kwargs['reasoning_effort'] == 'xhigh'


def test_apply_for_route_unsupported_model_untouched(monkeypatch):
    monkeypatch.setattr(reasoning, 'supports_reasoning',
                        lambda p, m: False)
    model = _FakeModel({'api_base': 'x'})
    result = _FakeResult(band='heavy', entry=_FakeEntry(), model=model)
    out = reasoning.apply_for_route(_NoAgent(), result)
    assert out is None
    assert 'reasoning_effort' not in model.kwargs
    assert model.kwargs == {'api_base': 'x'}


def test_apply_for_route_missing_entry_or_model_returns_none():
    # no model object -> nothing to write
    assert reasoning.apply_for_route(
        _NoAgent(), _FakeResult(band='light', entry=_FakeEntry(),
                                model=None)) is None
    # no entry -> no capability check possible
    assert reasoning.apply_for_route(
        _NoAgent(), _FakeResult(band='light', entry=None,
                                model=_FakeModel())) is None
    # fallback result (model None, entry None) must never raise
    assert reasoning.apply_for_route(_NoAgent(), _FakeResult()) is None


def test_apply_for_route_never_raises(monkeypatch):
    def _boom(p, m):
        raise RuntimeError('capability probe exploded')
    monkeypatch.setattr(reasoning, 'supports_reasoning', _boom)
    result = _FakeResult(band='heavy', entry=_FakeEntry(),
                         model=_FakeModel())
    # resolve_effort/supports failures degrade to no-op, not raise
    assert reasoning.apply_for_route(_NoAgent(), result) is None
