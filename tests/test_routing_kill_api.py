# TDD: routing_kill API contract tests.
# Spec: docs/specs/per-chat-kill-switch.md
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

# --- minimal framework stubs -------------------------------------------
helpers_pkg = types.ModuleType('helpers')
# real directory on __path__ so helpers.gate / helpers.signals resolve to the
# genuine files; explicit sys.modules stubs below still win for framework mods
helpers_pkg.__path__ = [str(PLUGIN_ROOT / 'helpers')]


class Request:
    def __init__(self):
        self.agent = None


class Response:
    def __init__(self, response=None, status=200):
        self.response = response
        self.status = status


class ApiHandler:
    pass


api_mod = types.ModuleType('helpers.api')
api_mod.ApiHandler = ApiHandler
api_mod.Request = Request
api_mod.Response = Response
sys.modules['helpers'] = helpers_pkg
sys.modules['helpers.api'] = api_mod
helpers_pkg.api = api_mod

plugins_mod = types.ModuleType('helpers.plugins')
plugins_mod.get_plugin_config = lambda name, agent=None: {'enabled': True}
sys.modules['helpers.plugins'] = plugins_mod
helpers_pkg.plugins = plugins_mod

persist_mod = types.ModuleType('helpers.persist_chat')
persist_mod.save_tmp_chat = lambda context: None
sys.modules['helpers.persist_chat'] = persist_mod
helpers_pkg.persist_chat = persist_mod

monitor_mod = types.ModuleType('helpers.state_monitor_integration')
monitor_mod.mark_dirty_for_context = lambda context_id, reason='': None
sys.modules['helpers.state_monitor_integration'] = monitor_mod
helpers_pkg.state_monitor_integration = monitor_mod

# --- agent stub ---------------------------------------------------------
agent_mod = types.ModuleType('agent')


class AgentContext:
    _instances = {}

    def __init__(self, context_id, running=False):
        self.id = context_id
        self._running = running
        self._data = {}
        AgentContext._instances[context_id] = self

    def is_running(self):
        return self._running

    def get_data(self, key, recursive=True):
        return self._data.get(key)

    def set_data(self, key, value, recursive=True):
        if value is None:
            self._data.pop(key, None)
        else:
            self._data[key] = value

    @staticmethod
    def get(context_id):
        return AgentContext._instances.get(context_id)

    @classmethod
    def clear(cls):
        cls._instances.clear()


agent_mod.AgentContext = AgentContext
sys.modules['agent'] = agent_mod

# helpers.__path__ points at the real helpers/ dir, so this resolves to
# the genuine gate.py (with its relative .signals import intact)
from helpers.gate import routing_allowed  # noqa: E402

# --- usr.plugins.jev_router.helpers.gate stub ---------------------------
gate_mod = types.ModuleType('usr.plugins.jev_router.helpers.gate')
gate_mod.routing_allowed = routing_allowed
sys.modules.setdefault('usr', types.ModuleType('usr'))
sys.modules.setdefault('usr.plugins', types.ModuleType('usr.plugins'))
sys.modules.setdefault(
    'usr.plugins.jev_router', types.ModuleType('usr.plugins.jev_router'))
usr_helpers = types.ModuleType('usr.plugins.jev_router.helpers')
usr_helpers.__path__ = []
sys.modules['usr.plugins.jev_router.helpers'] = usr_helpers
sys.modules['usr.plugins.jev_router.helpers.gate'] = gate_mod
usr_helpers.gate = gate_mod

# --- import module under test -------------------------------------------
spec = importlib.util.spec_from_file_location(
    'jev_routing_kill_test', PLUGIN_ROOT / 'api' / 'routing_kill.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


async def call(input_data, context_id='ctx', running=False, create=True,
               reset=True):
    """Run handler; unwrap Response into {ok: False, status, response}.

    reset=False keeps the existing AgentContext so set -> get roundtrips
    against the same context (mirrors one live chat).
    """
    if reset:
        AgentContext.clear()
    if create and context_id not in AgentContext._instances:
        AgentContext(context_id, running=running)
    req = Request()
    out = await mod.RoutingKill().process(input_data, req)
    if isinstance(out, Response):
        return {'ok': False, 'status': out.status, 'response': out.response}
    return out


def test_get_returns_enabled_and_effective():
    out = asyncio.run(call({'action': 'get', 'context_id': 'ctx-1'},
                            context_id='ctx-1'))
    assert out['ok'] is True
    assert isinstance(out['enabled'], bool)
    assert isinstance(out['effective'], bool)
    # fresh chat, global on -> enabled + effective
    assert out['enabled'] is True
    assert out['effective'] is True


def test_set_false_persists_and_roundtrips():
    out = asyncio.run(call({'action': 'set', 'context_id': 'ctx-2',
                             'enabled': False}, context_id='ctx-2'))
    assert out['ok'] is True
    assert out['enabled'] is False
    assert out['effective'] is False
    out = asyncio.run(call({'action': 'get', 'context_id': 'ctx-2'},
                            context_id='ctx-2', reset=False))
    assert out['ok'] is True
    assert out['enabled'] is False
    assert out['effective'] is False


def test_set_true_roundtrip():
    out = asyncio.run(call({'action': 'set', 'context_id': 'ctx-5',
                             'enabled': True}, context_id='ctx-5'))
    assert out['ok'] is True
    assert out['enabled'] is True
    assert out['effective'] is True
    out = asyncio.run(call({'action': 'get', 'context_id': 'ctx-5'},
                            context_id='ctx-5', reset=False))
    assert out['enabled'] is True
    assert out['effective'] is True


def test_set_409_while_running():
    out = asyncio.run(call({'action': 'set', 'context_id': 'ctx-3',
                             'enabled': False},
                            context_id='ctx-3', running=True))
    assert out['ok'] is False
    assert out['status'] == 409
    assert 'running' in str(out['response']).lower()
    # state unchanged while running
    out = asyncio.run(call({'action': 'get', 'context_id': 'ctx-3'},
                            context_id='ctx-3', reset=False))
    assert out['enabled'] is True


def test_missing_context_id_400():
    out = asyncio.run(call({'action': 'set', 'enabled': False},
                            context_id='ctx-x'))
    assert out['ok'] is False
    assert out['status'] == 400


def test_unknown_context_404():
    out = asyncio.run(call({'action': 'get', 'context_id': 'ghost'},
                            context_id='ghost', create=False))
    assert out['ok'] is False
    assert out['status'] == 404


def test_invalid_action_400():
    out = asyncio.run(call({'action': 'nonsense', 'context_id': 'ctx-4'},
                            context_id='ctx-4'))
    assert out['ok'] is False
    assert out['status'] == 400


def test_non_bool_enabled_400():
    out = asyncio.run(call({'action': 'set', 'context_id': 'ctx-6',
                             'enabled': 'yes'}, context_id='ctx-6'))
    assert out['ok'] is False
    assert out['status'] == 400