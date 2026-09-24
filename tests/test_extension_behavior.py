"""Extension behavior: no-key guard, failure caching, success caching.

Loads the real extension file and stubs its plugin-helper imports, so the
executed code path is the deployed one while the test stays hermetic.
Run with cwd=/a0 using /opt/venv-a0/bin/python (framework helpers required).
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

# Framework root first: the extension imports `helpers.extension` (framework),
# and `usr.plugins.*` namespace packages live under /a0 too. The plugin's own
# helpers/ dir must NOT precede it or it would shadow the framework package.
if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

EXT_PATH = Path(__file__).resolve().parents[1] / 'extensions/python/chat_model_call_before/_10_jev_route.py'


def _load_ext():
    # seed fake plugin-helper modules BEFORE the extension imports them
    fake_messages = types.ModuleType('usr.plugins.jev_router.helpers.messages')
    fake_messages.last_human_text = lambda msgs: msgs
    fake_messages.extract_user_text = lambda raw: 'hello world please route this message'
    fake_messages.has_image_parts = lambda msgs: False

    fake_mentions = types.ModuleType('usr.plugins.jev_router.helpers.mentions')
    fake_mentions.parse = lambda text, providers: SimpleNamespace(
        exclude=[], prefer=[], free=False, ttl_hours=0)
    fake_mentions.session_excludes = lambda sid: []
    fake_mentions.remember = lambda *a, **k: None

    fake_pool = types.ModuleType('usr.plugins.jev_router.helpers.pool')
    fake_pool.pool_fingerprint = lambda entries: 'fp1'

    state = {'result': None, 'kwargs': None, 'calls': 0}

    fake_router = types.ModuleType('usr.plugins.jev_router.helpers.router')

    async def fake_route(**kwargs):
        state['calls'] += 1
        state['kwargs'] = kwargs
        return state['result']

    fake_router.route = fake_route

    for name, mod in [
        ('usr.plugins.jev_router.helpers.messages', fake_messages),
        ('usr.plugins.jev_router.helpers.mentions', fake_mentions),
        ('usr.plugins.jev_router.helpers.pool', fake_pool),
        ('usr.plugins.jev_router.helpers.router', fake_router),
    ]:
        sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location('jev_route_ext_test', EXT_PATH)
    ext_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ext_mod)
    return ext_mod, state


def _make_ext(ext_mod, cfg):
    ext = ext_mod.JevRouteChatCall.__new__(ext_mod.JevRouteChatCall)
    ext.agent = SimpleNamespace(context=SimpleNamespace(id='sess-test'))
    ext_mod._plugin_cfg = lambda agent: cfg
    ext_mod._pool_entries = lambda: [SimpleNamespace(role='chat')]
    ext_mod._make_model_factory = lambda e=None: (lambda entry: 'FAKE_MODEL')
    ext._jev_client = lambda: object()
    ext._jev_model = lambda: 'jev-latest'
    ext._telemetry_path = lambda: Path('/tmp/jev_test_telemetry.db')
    return ext


def _run(ext, model='ORIGINAL'):
    call_data = {'model': model, 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))
    return call_data


def _cache_keys(ext_mod):
    return set(ext_mod.DECISION_CACHE.keys())


def test_no_key_skips_jev_and_keeps_model():
    ext_mod, state = _load_ext()
    saved = os.environ.pop('TYPESAFE_API_KEY', None)
    try:
        ext = _make_ext(ext_mod, {'enabled': True})
        call_data = _run(ext)
        assert state['calls'] == 0, 'route() must not be called without an API key'
        assert call_data['model'] == 'ORIGINAL'
        assert not _cache_keys(ext_mod), 'no-key skip must not be cached'
    finally:
        if saved is not None:
            os.environ['TYPESAFE_API_KEY'] = saved


def test_failed_judgment_is_not_cached():
    ext_mod, state = _load_ext()
    ext = _make_ext(ext_mod, {'enabled': True, 'jev_api_key': 'k'})
    state['result'] = SimpleNamespace(
        model=None, reason='jev query failed; keeping active preset model',
        fallback=True, advice=None)
    call_data = _run(ext)
    assert state['calls'] == 1
    assert call_data['model'] == 'ORIGINAL', 'failed judgment must keep framework model'
    assert not _cache_keys(ext_mod), 'failed judgments must not be cached'


def test_successful_judgment_is_cached_and_applied():
    ext_mod, state = _load_ext()
    ext = _make_ext(ext_mod, {'enabled': True, 'jev_api_key': 'k'})
    state['result'] = SimpleNamespace(
        model='FAKE_MODEL', reason='task_class=chat band=light -> preset Fast',
        fallback=False, advice=None)
    call_data = _run(ext)
    assert call_data['model'] == 'FAKE_MODEL'
    assert len(_cache_keys(ext_mod)) == 1


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
