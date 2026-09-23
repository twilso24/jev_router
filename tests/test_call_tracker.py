# TDD RED: real API-call tracking feeding breaker + telemetry.
# helpers/call_tracker.py does not exist yet.
# Run: /opt/venv-a0/bin/python tests/test_call_tracker.py
import asyncio
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import call_tracker


class _FakeModel:
    def __init__(self, behave='ok'):
        self.behave = behave
        self.calls = 0

    async def unified_call(self, **kwargs):
        self.calls += 1
        if self.behave == 'raise':
            raise RuntimeError('boom')
        return 'resp'


def _run(coro):
    return asyncio.run(coro)


def test_instrument_wraps_once():
    m = _FakeModel()
    assert call_tracker.instrument(m, 'prov', 'Preset', lambda *a: None) is True
    assert call_tracker.instrument(m, 'prov', 'Preset', lambda *a: None) is False
    assert m.calls == 0  # wrap does not call the model


def test_success_records_outcome():
    m = _FakeModel()
    seen = []
    call_tracker.instrument(m, 'prov', 'Preset', lambda *a: seen.append(a))
    resp = _run(m.unified_call(messages=[]))
    assert resp == 'resp'
    assert len(seen) == 1
    provider, preset, ok, dur, err = seen[0]
    assert provider == 'prov' and preset == 'Preset'
    assert ok is True and err is None and dur >= 0


def test_failure_records_and_reraises():
    m = _FakeModel('raise')
    seen = []
    call_tracker.instrument(m, 'prov', 'Preset', lambda *a: seen.append(a))
    try:
        _run(m.unified_call(messages=[]))
        raise AssertionError('should have raised')
    except RuntimeError as exc:
        assert str(exc) == 'boom'
    assert len(seen) == 1
    provider, preset, ok, dur, err = seen[0]
    assert provider == 'prov' and ok is False and 'boom' in err


def test_callback_failure_never_breaks_call():
    m = _FakeModel()

    def bad(*a):
        raise ValueError('cb')

    call_tracker.instrument(m, 'prov', 'Preset', bad)
    assert _run(m.unified_call(messages=[])) == 'resp'
    assert m.calls == 1


def test_instrument_refreshes_callback_on_cached_model():
    # models may be cached; a second instrument() must rebind the outcome
    # callback (and attribution) without double-wrapping the call.
    m = _FakeModel()
    seen1, seen2 = [], []
    assert call_tracker.instrument(m, 'prov', 'Preset', lambda *a: seen1.append(a)) is True
    assert call_tracker.instrument(m, 'prov', 'Preset2', lambda *a: seen2.append(a)) is False
    _run(m.unified_call(messages=[]))
    assert seen1 == []
    assert len(seen2) == 1
    _provider, preset, ok, _dur, _err = seen2[0]
    assert preset == 'Preset2' and ok is True


def _main():
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    passed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print(f'PASS {name}')
        except Exception as exc:
            print(f'FAIL {name}: {exc}')
    print(f'--- {passed}/{len(fns)} passed')
    if passed != len(fns):
        raise SystemExit(1)


if __name__ == '__main__':
    _main()
