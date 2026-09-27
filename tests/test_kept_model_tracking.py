# TDD RED: keep-model fallback turns must also feed call telemetry.
# The framework's cached model stays in call_data['model'] when the router
# falls back; its outcomes were invisible to the tracker and breaker.
import asyncio
import importlib.util
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

EXT_PATH = (Path(__file__).resolve().parents[1]
            / 'extensions/python/chat_model_call_before/_10_jev_route.py')


def _load_ext(track):
    """Load the REPO extension file with stubbed plugin modules so the
    test gates this tree, never the deployed copy. `track` is a dict the
    stub call_tracker/telemetry/circuit_breaker record into."""
    fake_messages = types.ModuleType('usr.plugins.jev_router.helpers.messages')
    fake_messages.last_human_text = lambda msgs: msgs
    fake_messages.extract_user_text = lambda raw: 'please route this'
    fake_messages.has_image_parts = lambda msgs: False

    fake_mentions = types.ModuleType('usr.plugins.jev_router.helpers.mentions')
    fake_mentions.parse = lambda text, providers: SimpleNamespace(
        exclude=[], prefer=[], free=False, ttl_hours=0)
    fake_mentions.session_excludes = lambda sid: []
    fake_mentions.remember = lambda *a, **k: None

    fake_pool = types.ModuleType('usr.plugins.jev_router.helpers.pool')
    fake_pool.pool_fingerprint = lambda entries: 'fp1'

    fake_auto_wire = types.ModuleType('usr.plugins.jev_router.helpers.auto_wire')
    fake_auto_wire.sync_band_orders = lambda *a, **k: SimpleNamespace(
        added=[], pruned=[], ts=1.0)

    fake_jev = types.ModuleType('usr.plugins.jev_router.helpers.jev')
    fake_jev.resolve_api_key = lambda cfg, env: 'test-key'
    fake_jev.get_client = lambda key, model, timeout: object()

    fake_router = types.ModuleType('usr.plugins.jev_router.helpers.router')

    async def fake_route(**kwargs):
        # keep-model fallback: framework model stays in place
        return SimpleNamespace(
            model=None,
            reason='jev query failed; keeping active preset model',
            fallback=True, advice=None)

    fake_router.route = fake_route

    fake_tracker = types.ModuleType('usr.plugins.jev_router.helpers.call_tracker')

    def instrument(model, provider, preset, on_outcome):
        if getattr(model, '_fake_wrapped', False):
            return False
        model._fake_wrapped = True
        model._fake_on = on_outcome
        track['instrumented'].append((model, provider, preset))
        return True

    fake_tracker.instrument = instrument
    fake_tracker.is_wrapped = lambda m: getattr(m, '_fake_wrapped', False)

    fake_tel = types.ModuleType('usr.plugins.jev_router.helpers.telemetry')

    def init_db(_path):
        return _FakeConn(track)

    def record_call(conn, provider, preset, ok, duration, error):
        track['calls'].append((provider, preset, bool(ok), error))

    fake_tel.init_db = init_db
    fake_tel.record_call = record_call

    fake_cb = types.ModuleType('usr.plugins.jev_router.helpers.circuit_breaker')
    fake_cb.record_success = lambda p: track['breaker'].append(('ok', p))
    fake_cb.record_fail = lambda p, **k: track['breaker'].append(('fail', p))

    for name, mod in [
        ('usr.plugins.jev_router.helpers.messages', fake_messages),
        ('usr.plugins.jev_router.helpers.mentions', fake_mentions),
        ('usr.plugins.jev_router.helpers.pool', fake_pool),
        ('usr.plugins.jev_router.helpers.auto_wire', fake_auto_wire),
        ('usr.plugins.jev_router.helpers.jev', fake_jev),
        ('usr.plugins.jev_router.helpers.router', fake_router),
        ('usr.plugins.jev_router.helpers.call_tracker', fake_tracker),
        ('usr.plugins.jev_router.helpers.telemetry', fake_tel),
        ('usr.plugins.jev_router.helpers.circuit_breaker', fake_cb),
    ]:
        sys.modules[name] = mod

    saved = {k: v for k, v in sys.modules.items()
             if k == 'helpers' or k.startswith('helpers.')}
    for k in list(saved):
        del sys.modules[k]

    spec = importlib.util.spec_from_file_location('jev_kept_model_test', EXT_PATH)
    ext_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ext_mod)

    for k in [k for k in sys.modules
              if k == 'helpers' or k.startswith('helpers.')]:
        if k not in saved:
            del sys.modules[k]
    sys.modules.update(saved)
    return ext_mod


class _FakeConn:
    def __init__(self, track=None):
        pass

    def close(self):
        pass

class _KeptModel:
    """Stand-in for the framework's cached chat model."""

    def __init__(self, behave='ok'):
        self.behave = behave
        self.turns = 0
        self.a0_model_conf = SimpleNamespace(
            provider='keptprov', name='kept-model-name')

    async def unified_turn(self, **kwargs):
        self.turns += 1
        if self.behave == 'raise':
            raise RuntimeError('boom')
        return ('resp', 'reasoning')


def _new_track():
    return {'instrumented': [], 'calls': [], 'breaker': []}


def _make_ext(ext_mod):
    ext = ext_mod.JevRouteChatCall.__new__(ext_mod.JevRouteChatCall)
    ext.agent = SimpleNamespace(context=SimpleNamespace(id='sess-kept'))
    ext_mod._plugin_cfg = lambda agent: {
        'enabled': True, 'jev_api_key': 'k'}
    ext_mod._pool_entries = lambda: [
        SimpleNamespace(preset_name='P', role='chat')]
    ext_mod._make_model_factory = lambda e=None: (lambda entry: 'FAKE_MODEL')
    ext._jev_client = lambda: object()
    ext._jev_model = lambda: 'jev-latest'
    ext._jev_config = lambda: {}
    ext._telemetry_path = lambda: Path('/tmp/jev_kept_test.db')  # fake conn ignores
    return ext

def test_fallback_instruments_kept_model():
    track = _new_track()
    ext_mod = _load_ext(track)
    ext = _make_ext(ext_mod)
    kept = _KeptModel()
    call_data = {'model': kept,
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))

    assert call_data['model'] is kept, 'fallback must keep the framework model'
    assert track['instrumented'] and track['instrumented'][0][0] is kept, (
        'kept model must be instrumented so its outcome reaches telemetry')
    assert track['instrumented'][0][1] == 'keptprov', (
        'attribution must come from a0_model_conf.provider')

    # outcome flows to telemetry + breaker with the captured callback
    kept._fake_on('keptprov', 'kept-model-name', True, 0.5, None)
    assert track['calls'] == [('keptprov', 'kept-model-name', True, None)]
    assert track['breaker'] == [('ok', 'keptprov')]


def test_fallback_failure_recorded():
    track = _new_track()
    ext_mod = _load_ext(track)
    ext = _make_ext(ext_mod)
    kept = _KeptModel('raise')
    call_data = {'model': kept,
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))

    kept._fake_on('keptprov', 'kept-model-name', False, 1.0, 'boom')
    assert track['calls'] == [('keptprov', 'kept-model-name', False, 'boom')]
    assert track['breaker'] == [('fail', 'keptprov')]


def test_unattributable_kept_model_skipped_silently():
    track = _new_track()
    ext_mod = _load_ext(track)
    ext = _make_ext(ext_mod)
    plain = SimpleNamespace()  # no a0_model_conf -> cannot attribute
    call_data = {'model': plain,
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))
    assert call_data['model'] is plain
    assert track['instrumented'] == []


def test_kept_model_empty_provider_skipped():
    track = _new_track()
    ext_mod = _load_ext(track)
    ext = _make_ext(ext_mod)
    kept = SimpleNamespace(
        a0_model_conf=SimpleNamespace(provider='', name='some-model'))
    call_data = {'model': kept,
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))
    assert track['instrumented'] == []


def test_kept_model_empty_name_falls_back_to_provider():
    track = _new_track()
    ext_mod = _load_ext(track)
    ext = _make_ext(ext_mod)
    kept = _KeptModel()
    kept.a0_model_conf = SimpleNamespace(provider='keptprov', name='')
    call_data = {'model': kept,
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))
    assert track['instrumented'], 'empty name must still instrument'
    prov, label = track['instrumented'][0][1], track['instrumented'][0][2]
    assert (prov, label) == ('keptprov', 'keptprov')
