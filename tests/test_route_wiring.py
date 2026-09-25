# TDD RED: route extension triggers auto-wire sync on pool fingerprint
# change (spec: auto-wire-presets.md, decision 1A).
# Run: /opt/venv-a0/bin/python tests/test_route_wiring.py
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

EXT_PATH = Path(__file__).resolve().parents[1] / 'extensions/python/chat_model_call_before/_10_jev_route.py'


def _load_ext(fingerprint, sync_calls):
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
    fake_pool.pool_fingerprint = lambda entries: fingerprint

    def _sync(policy_path, pool, state_path=None):
        sync_calls.append((policy_path, list(pool), state_path))
        return SimpleNamespace(added=['X'], pruned=[], ts=1.0)

    fake_auto_wire = types.ModuleType('usr.plugins.jev_router.helpers.auto_wire')
    fake_auto_wire.sync_band_orders = _sync

    fake_jev = types.ModuleType('usr.plugins.jev_router.helpers.jev')
    fake_jev.resolve_api_key = lambda cfg, env: 'test-key'
    fake_jev.get_client = lambda key, model, timeout: object()

    fake_router = types.ModuleType('usr.plugins.jev_router.helpers.router')

    async def fake_route(**kwargs):
        return SimpleNamespace(
            model='FAKE_MODEL',
            reason='task_class=chat band=light -> preset Fast',
            fallback=False, advice=None)

    fake_router.route = fake_route

    for name, mod in [
        ('usr.plugins.jev_router.helpers.messages', fake_messages),
        ('usr.plugins.jev_router.helpers.mentions', fake_mentions),
        ('usr.plugins.jev_router.helpers.pool', fake_pool),
        ('usr.plugins.jev_router.helpers.auto_wire', fake_auto_wire),
        ('usr.plugins.jev_router.helpers.jev', fake_jev),
        ('usr.plugins.jev_router.helpers.router', fake_router),
    ]:
        sys.modules[name] = mod

    # Order independence: other test files may have cached the PLUGIN's
    # `helpers` package (same name as the framework's). Pop `helpers*` so
    # `from helpers.extension import Extension` resolves to /a0 framework
    # code, then restore the previous cache state after loading.
    saved_helpers = {k: v for k, v in sys.modules.items()
                     if k == 'helpers' or k.startswith('helpers.')}
    for k in list(saved_helpers):
        del sys.modules[k]
    if '/a0' not in sys.path:
        sys.path.insert(0, '/a0')

    spec = importlib.util.spec_from_file_location(
        'jev_route_ext_wiring_test', EXT_PATH)
    ext_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ext_mod)

    # Restore cache state so this file leaves no helpers pollution behind.
    for k in [k for k in sys.modules if k == 'helpers' or k.startswith('helpers.')]:
        if k not in saved_helpers:
            del sys.modules[k]
    sys.modules.update(saved_helpers)
    return ext_mod


def _make_ext(ext_mod, cfg):
    ext = ext_mod.JevRouteChatCall.__new__(ext_mod.JevRouteChatCall)
    ext.agent = SimpleNamespace(context=SimpleNamespace(id='sess-wire'))
    ext_mod._plugin_cfg = lambda agent: cfg
    ext_mod._pool_entries = lambda: [SimpleNamespace(preset_name='P', role='chat')]
    ext_mod._make_model_factory = lambda e=None: (lambda entry: 'FAKE_MODEL')
    ext._jev_client = lambda: object()
    ext._jev_model = lambda: 'jev-latest'
    ext._telemetry_path = lambda: Path('/tmp/jev_wire_test_telemetry.db')
    return ext


def _run(ext):
    call_data = {'model': 'ORIGINAL',
                 'messages': [{'role': 'user', 'content': 'hi'}]}
    asyncio.run(ext.execute(call_data=call_data))
    return call_data


def test_sync_runs_once_per_fingerprint_change():
    sync_calls = []
    ext_mod = _load_ext('fp1', sync_calls)
    ext = _make_ext(ext_mod, {'enabled': True, 'jev_api_key': 'k'})
    _run(ext)  # first call: fp1 -> sync (new fingerprint)
    _run(ext)  # same fingerprint -> no re-sync
    assert len(sync_calls) == 1, 'sync must run exactly once per fingerprint'
    assert sync_calls[0][1] == ['P'], 'sync receives chat preset names'


def test_fingerprint_change_triggers_new_sync():
    sync_calls = []
    ext_mod = _load_ext('fp1', sync_calls)
    ext = _make_ext(ext_mod, {'enabled': True, 'jev_api_key': 'k'})
    _run(ext)
    # pool changed: same module, new fingerprint via stubbed pool module
    fp_mod = sys.modules['usr.plugins.jev_router.helpers.pool']
    fp_mod.pool_fingerprint = lambda entries: 'fp2'
    _run(ext)
    assert len(sync_calls) == 2, 'changed fingerprint must re-run sync'


def test_sync_failure_never_breaks_routing():
    sync_calls = []
    ext_mod = _load_ext('fp1', sync_calls)

    def _boom(*a, **k):
        raise RuntimeError('sync exploded')

    sys.modules['usr.plugins.jev_router.helpers.auto_wire'].sync_band_orders = _boom
    ext = _make_ext(ext_mod, {'enabled': True, 'jev_api_key': 'k'})
    call_data = _run(ext)
    assert call_data['model'] == 'FAKE_MODEL', 'routing must survive sync failure'


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
