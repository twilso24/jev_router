# TDD RED: api wire_sync action for auto-wire (spec: auto-wire-presets.md).
# Run: /opt/venv-a0/bin/python tests/test_routing_policy_api.py
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

# --- framework stub -------------------------------------------------------
helpers_pkg = types.ModuleType('helpers')
api_mod = types.ModuleType('helpers.api')


class Request:  # minimal stand-in
    pass


class Response:  # minimal stand-in
    pass


class ApiHandler:
    pass


api_mod.ApiHandler = ApiHandler
api_mod.Request = Request
api_mod.Response = Response
sys.modules.setdefault('helpers', helpers_pkg)
sys.modules['helpers.api'] = api_mod

# --- plugin helper stubs --------------------------------------------------
pkg = types.ModuleType('usr.plugins.jev_router.helpers')
pkg.__path__ = []
sys.modules.setdefault('usr.plugins', types.ModuleType('usr.plugins'))
sys.modules.setdefault('usr.plugins.jev_router',
                       types.ModuleType('usr.plugins.jev_router'))
sys.modules['usr.plugins.jev_router.helpers'] = pkg

webui_stub = types.SimpleNamespace(
    pool_preset_names=lambda p: ['Default', 'Fast', 'Storyteller'],
    pool_providers=lambda p: ['prov_a'],
)
sys.modules['usr.plugins.jev_router.helpers.webui_data'] = webui_stub
pkg.webui_data = webui_stub

calls = {}


def _sync(policy_path, pool, state_path=None):
    calls['sync'] = (policy_path, list(pool), state_path)
    return types.SimpleNamespace(added=['Storyteller'], pruned=[], ts=1.5)


auto_wire_stub = types.SimpleNamespace(
    sync_band_orders=_sync,
    unwired_presets=lambda policy_path, pool: [],
)
sys.modules['usr.plugins.jev_router.helpers.auto_wire'] = auto_wire_stub
pkg.auto_wire = auto_wire_stub

tuning_stub = types.SimpleNamespace(
    write_pin=lambda path, band, pinned: (
        calls.__setitem__('pin', (path, str(band), bool(pinned))) or True),
)
sys.modules['usr.plugins.jev_router.helpers.tuning'] = tuning_stub
pkg.tuning = tuning_stub

# --- load handler module --------------------------------------------------
spec = importlib.util.spec_from_file_location(
    'jev_routing_policy_test', PLUGIN_ROOT / 'api' / 'routing_policy.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _run(input):
    return asyncio.run(mod.RoutingPolicy().process(input, Request()))


def test_wire_sync_runs_and_returns_report(tmp_path):
    out = _run({'action': 'wire_sync'})
    assert out['ok'] is True
    assert out['report'] == {'added': ['Storyteller'], 'pruned': [],
                             'pinned': [], 'ts': 1.5}
    assert out['unwired'] == []
    policy_path, pool, state_path = calls['sync']
    assert policy_path == mod.POLICY_PATH
    assert pool == ['Default', 'Fast', 'Storyteller']
    assert state_path == mod.POLICY_PATH.parent / 'wire-state.json'


def test_unknown_action_still_rejected():
    out = _run({'action': 'bogus'})
    assert out['ok'] is False


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))


# --- S4 (TDD) RED: set_pin api action ---
def test_set_pin_action_calls_tuning(tmp_path):
    pol = tmp_path / 'rp.yaml'
    orig = mod.POLICY_PATH
    mod.POLICY_PATH = pol  # never touch the live deployed policy in tests
    try:
        out = _run({'action': 'set_pin', 'band': 'heavy', 'pinned': True})
        assert out['ok'] is True
        assert calls['pin'] == (pol, 'heavy', True)
    finally:
        mod.POLICY_PATH = orig


# --- Audit round 2: API errors must not leak internals ---


def test_api_error_is_generic():
    def boom(path, band, pinned):
        raise RuntimeError('secret detail /a0/tmp/x')

    orig = tuning_stub.write_pin
    tuning_stub.write_pin = boom
    try:
        out = _run({'action': 'set_pin', 'band': 'heavy', 'pinned': True})
    finally:
        tuning_stub.write_pin = orig
    assert out['ok'] is False
    assert 'secret' not in str(out.get('error'))
    assert '/a0' not in str(out.get('error'))
