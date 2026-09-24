"""WebUI-path pre-selection extension (user_message_ui hook).

Loads the real extension file with stubbed framework modules.
Run: cd /a0 && /opt/venv-a0/bin/python <this file>
"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

EXT_PATH = Path(__file__).resolve().parents[1] / 'extensions/python/user_message_ui/_10_jev_preselect.py'

CFG = {'enabled': True, 'chat_preselect': True, 'delegation_mode': 'auto',
       'jev_api_key': 'k', 'jev_model': 'jev-latest', 'jev_timeout_s': 2.0}


class _FakeLog:
    def __init__(self):
        self.logs = []


class _FakeContext:
    def __init__(self, agent):
        self.id = 'ctx-test'
        self.log = _FakeLog()
        self.config = None
        self.agent0 = agent
        self._task = None
        self.saved = 0

    def is_running(self):
        return False


class _FakeAgent:
    def __init__(self, profile='agent0'):
        self.number = 0
        self.config = SimpleNamespace(profile=profile)
        self.context = None
        self.data = {}


def _install_stubs():
    calls = {'initialize': [], 'query': 0, 'saved': 0, 'dirty': []}

    fake_plugins = types.ModuleType('helpers.plugins')
    fake_plugins.get_plugin_config = (
        lambda name, agent=None, **kw: dict(CFG) if name == 'jev_router' else {})
    sys.modules['helpers.plugins'] = fake_plugins

    fake_settings = types.ModuleType('helpers.settings')
    fake_settings.get_settings = lambda: {'agent_profile': 'agent0'}
    sys.modules['helpers.settings'] = fake_settings

    fake_subagents = types.ModuleType('helpers.subagents')
    fake_subagents.get_agents_list = lambda project_name=None: [
        SimpleNamespace(name=n) for n in ('default', 'developer', 'researcher', 'hacker', 'agent0')]
    sys.modules['helpers.subagents'] = fake_subagents

    fake_init = types.ModuleType('initialize')
    def fake_initialize_agent(override_settings=None):
        calls['initialize'].append(dict(override_settings or {}))
        return SimpleNamespace(profile=(override_settings or {}).get('agent_profile', 'agent0'))
    fake_init.initialize_agent = fake_initialize_agent
    sys.modules['initialize'] = fake_init

    fake_persist = types.ModuleType('helpers.persist_chat')
    fake_persist.save_tmp_chat = lambda ctx: calls.__setitem__('saved', calls['saved'] + 1)
    sys.modules['helpers.persist_chat'] = fake_persist

    fake_smi = types.ModuleType('helpers.state_monitor_integration')
    fake_smi.mark_dirty_for_context = (
        lambda cid, reason='': calls['dirty'].append((cid, reason)))
    sys.modules['helpers.state_monitor_integration'] = fake_smi

    fake_sdk = types.ModuleType('typesafe_sdk')
    fake_sdk.AsyncTypeSafeClient = lambda **kw: object()
    sys.modules['typesafe_sdk'] = fake_sdk

    fake_jev = types.ModuleType('usr.plugins.jev_router.helpers.jev')
    async def fake_query(client, msg_state, questions, model, **kw):
        calls['query'] += 1
        return {'answers': {'task_class': {'choice': 'coding', 'confidence': 0.9}},
                'model': 'jev-latest', 'usage': {}}
    fake_jev.query = fake_query
    fake_jev.resolve_api_key = lambda cfg, env=None: str((cfg or {}).get('jev_api_key') or '')
    sys.modules['usr.plugins.jev_router.helpers.jev'] = fake_jev

    pspec = importlib.util.spec_from_file_location(
        'usr.plugins.jev_router.helpers.preselect',
        Path(__file__).resolve().parents[1] / 'helpers/preselect.py')
    pmod = importlib.util.module_from_spec(pspec)
    pspec.loader.exec_module(pmod)
    sys.modules['usr.plugins.jev_router.helpers.preselect'] = pmod
    return calls


def _load():
    spec = importlib.util.spec_from_file_location('jev_preselect_ui_test', EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make(mod, profile='agent0'):
    agent = _FakeAgent(profile)
    ctx = _FakeContext(agent)
    agent.context = ctx
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    return agent, ctx


def _run(ext, message='fix this python bug'):
    asyncio.run(ext.execute(agent=ext.agent, data={'message': message, 'attachment_paths': []}))


def test_fresh_chat_swaps_profile():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod)
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 1, calls
    assert calls['initialize'] and calls['initialize'][0].get('agent_profile') == 'developer', calls
    assert ctx.config is not None and ctx.agent0.config.profile == 'developer'
    assert calls['saved'] == 1 and calls['dirty'], calls


def test_busy_chat_skipped():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod)
    ctx.is_running = lambda: True
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_chat_with_history_skipped():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod)
    ctx.log.logs = [object()]
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_explicit_profile_wins():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod, profile='researcher')
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_advise_mode_skipped():
    calls = _install_stubs()
    sys.modules['helpers.plugins'].get_plugin_config = (
        lambda name, agent=None, **kw: dict(CFG, delegation_mode='advise') if name == 'jev_router' else {})
    mod = _load()
    agent, ctx = _make(mod)
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0


def test_no_key_skipped():
    calls = _install_stubs()
    sys.modules['helpers.plugins'].get_plugin_config = (
        lambda name, agent=None, **kw: dict(CFG, jev_api_key='') if name == 'jev_router' else {})
    mod = _load()
    agent, ctx = _make(mod)
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_subordinate_agent_skipped():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod)
    agent.number = 1
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)
    assert calls['query'] == 0


def test_never_raises_on_init_failure():
    calls = _install_stubs()
    mod = _load()
    agent, ctx = _make(mod)
    sys.modules['initialize'].initialize_agent = (
        lambda override_settings=None: (_ for _ in ()).throw(RuntimeError('boom')))
    ext = mod.JevPreselectUi.__new__(mod.JevPreselectUi)
    ext.agent = agent
    _run(ext)  # must not raise
    assert ctx.agent0.config.profile == 'agent0'


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
