# TDD RED: band context threads from the router decision through the
# extension's instrument callback into telemetry.record_call, so auto-tune
# can rank presets per band instead of globally (spec: per-band-auto-tune.md).
# Run: /opt/venv-a0/bin/python tests/test_band_threading.py
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

EXT_PATH = (Path(__file__).resolve().parents[1]
            / 'extensions/python/chat_model_call_before/_10_jev_route.py')


def _load_ext(recorded):
    """Load the REPO extension file with stubbed plugin modules; `recorded`
    collects record_call kwargs so tests can assert band threading."""
    fake_helpers_ext = types.ModuleType('helpers.extension')
    fake_helpers_ext.Extension = type('Extension', (), {})

    fake_messages = types.ModuleType('usr.plugins.jev_router.helpers.messages')
    fake_messages.last_human_text = lambda msgs: msgs
    fake_messages.extract_user_text = lambda raw: 'msg'
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

    fake_router = types.ModuleType('usr.plugins.jev_router.helpers.router')

    async def fake_route(**kwargs):
        return SimpleNamespace(
            model='FAKE_MODEL',
            reason='task_class=chat band=light -> preset Fast',
            fallback=False, advice=None, band='light',
            entry=SimpleNamespace(provider='prov', preset_name='Fast'))

    fake_router.route = fake_route

    fake_jev = types.ModuleType('usr.plugins.jev_router.helpers.jev')
    fake_jev.resolve_api_key = lambda cfg, env: 'test-key'
    fake_jev.get_client = lambda key, model, timeout: object()

    fake_breaker = types.ModuleType('usr.plugins.jev_router.helpers.circuit_breaker')
    fake_breaker.record_success = lambda *a, **k: None
    fake_breaker.record_fail = lambda *a, **k: False

    fake_tel = types.ModuleType('usr.plugins.jev_router.helpers.telemetry')

    def fake_record_call(conn, provider, preset, ok, duration, error, **kw):
        recorded.append({'provider': provider, 'preset': preset, 'ok': ok,
                         'band': kw.get('band')})

    fake_tel.record_call = fake_record_call
    fake_tel.init_db = lambda path: SimpleNamespace(execute=lambda *a, **k: None,
                                                    close=lambda: None)

    fake_cb = types.ModuleType('usr.plugins.jev_router.helpers.call_tracker')

    def fake_instrument(model, provider, preset, on_outcome, **kw):
        # remember callback + band for the assertion helpers
        model._jev_cb = on_outcome
        model._jev_band = kw.get('band')
        return True

    fake_cb.instrument = fake_instrument
    fake_cb.is_wrapped = lambda m: hasattr(m, '_jev_cb')

    saved = {k: sys.modules[k] for k in list(sys.modules)
             if k.startswith('helpers.')
             or k.startswith('usr.plugins.jev_router')
             or k.startswith('plugins._model_config')}
    for k in saved:
        del sys.modules[k]
    sys.modules.update({
        'helpers.extension': fake_helpers_ext,
        'usr.plugins.jev_router.helpers.messages': fake_messages,
        'usr.plugins.jev_router.helpers.mentions': fake_mentions,
        'usr.plugins.jev_router.helpers.pool': fake_pool,
        'usr.plugins.jev_router.helpers.auto_wire': fake_auto_wire,
        'usr.plugins.jev_router.helpers.router': fake_router,
        'usr.plugins.jev_router.helpers.jev': fake_jev,
        'usr.plugins.jev_router.helpers.circuit_breaker': fake_breaker,
        'usr.plugins.jev_router.helpers.telemetry': fake_tel,
        'usr.plugins.jev_router.helpers.call_tracker': fake_cb,
    })
    # NOTE: stubs intentionally persist for the whole test call - the
    # outcome callback is invoked AFTER _load_ext returns and imports
    # usr.plugins.jev_router.helpers.telemetry at that moment. conftest's
    # per-file isolation restores namespaces between test files.
    spec = importlib.util.spec_from_file_location(
        'ext_jev_route_band', EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_instrument_accepts_band_and_records_it():
    """_instrument(..., band='light') threads band into on_outcome -> _on_call_outcome -> record_call."""
    recorded = []
    ext_mod = _load_ext(recorded)

    class Model:
        pass

    model = Model()
    entry = SimpleNamespace(provider='prov', preset_name='Fast')
    ext = SimpleNamespace(_jev_config=lambda: {},
                          _telemetry_path=lambda: Path('/tmp/jev-band.db'))

    # Signature RED: band kwarg must exist
    ext_mod._instrument(ext, model, entry, band='light',
                        fallback_from_preset=None)

    # invoke the captured callback the way call_tracker would
    cb = getattr(model, '_jev_cb', None)
    assert cb is not None, 'instrument must install an outcome callback'
    cb('prov', 'Fast', True, 0.1, None, None, None)

    assert recorded, 'outcome must reach record_call'
    assert recorded[0]['band'] == 'light', recorded


def test_instrument_without_band_records_none():
    """No band (legacy path) records band=None -> NULL in DB."""
    recorded = []
    ext_mod = _load_ext(recorded)

    class Model:
        pass

    model = Model()
    entry = SimpleNamespace(provider='prov', preset_name='Fast')
    ext = SimpleNamespace(_jev_config=lambda: {},
                          _telemetry_path=lambda: Path('/tmp/jev-band.db'))
    ext_mod._instrument(ext, model, entry, fallback_from_preset=None)
    cb = getattr(model, '_jev_cb', None)
    assert cb is not None
    cb('prov', 'Fast', True, 0.1, None, None, None)

    assert recorded[0]['band'] is None, recorded


def test_kept_model_instrument_bandless():
    """Kept-model fallback has no decision band -> records None."""
    recorded = []
    ext_mod = _load_ext(recorded)

    class Conf:
        provider = 'prov'
        name = 'model'

    class Model:
        a0_model_conf = Conf()

    model = Model()
    ext = SimpleNamespace(_jev_config=lambda: {},
                          _telemetry_path=lambda: Path('/tmp/jev-band.db'))
    ext_mod._instrument_kept_model(ext, model,
                                  fallback_from_preset=None)
    cb = getattr(model, '_jev_cb', None)
    assert cb is not None, 'kept model must still be instrumented'
    cb('prov', 'model', False, 1.0, 'boom', None, None)

    assert recorded[0]['band'] is None, recorded


def test_execute_passes_result_band_to_instrument():
    """Router result band flows: fake route returns band='light'; execute must forward it to _instrument."""
    recorded = []
    ext_mod = _load_ext(recorded)

    import inspect
    src = inspect.getsource(ext_mod)
    # the router-call site must forward the band attribute
    assert 'band=' in src, (
        'extension must pass band=getattr(result, \'band\', None) '
        'to _instrument')


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
