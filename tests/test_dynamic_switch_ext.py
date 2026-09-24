"""Dynamic profile switching extension (user_message_ui hook).

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

EXT_PATH = Path('/a0/usr/projects/jev_router/plugin/extensions/python/'
                'user_message_ui/_20_jev_dynamic_switch.py')

CFG = {'enabled': True, 'chat_preselect': True, 'delegation_mode': 'auto',
       'dynamic_switch_enabled': True, 'dynamic_switch_threshold': 0.7,
       'dynamic_switch_consecutive': 2, 'dynamic_switch_cooldown_seconds': 30,
       'jev_api_key': 'k', 'jev_model': 'jev-latest', 'jev_timeout_s': 2.0}


class _FakeLog:
    def __init__(self, entries=1):
        self.logs = [object()] * entries


class _FakeContext:
    def __init__(self, agent, log_entries=1):
        self.id = 'ctx-dyn'
        self.log = _FakeLog(log_entries)
        self.config = None
        self.agent0 = agent
        self.data = {}

    def is_running(self):
        return False

    def get_data(self, key, recursive=True):
        return self.data.get(key)

    def set_data(self, key, value, recursive=True):
        self.data[key] = value


class _FakeAgent:
    def __init__(self, profile='agent0'):
        self.number = 0
        self.config = SimpleNamespace(profile=profile)
        self.context = None


def _install_stubs():
    calls = {'initialize': [], 'query': 0, 'saved': 0, 'dirty': [], 'clients': 0}

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

    _client_cache = {}
    def fake_get_client(key, model, timeout):
        k = (str(key), str(model), float(timeout))
        if k not in _client_cache:
            calls['clients'] += 1
            _client_cache[k] = fake_sdk.AsyncTypeSafeClient(
                api_key=key, model=model, timeout=timeout)
        return _client_cache[k]
    fake_jev.get_client = fake_get_client

    fspec = importlib.util.spec_from_file_location(
        'usr.plugins.jev_router.helpers.fastpath',
        Path('/a0/usr/projects/jev_router/plugin/helpers/fastpath.py'))
    fmod = importlib.util.module_from_spec(fspec)
    fspec.loader.exec_module(fmod)
    sys.modules['usr.plugins.jev_router.helpers.fastpath'] = fmod

    mspec = importlib.util.spec_from_file_location(
        'usr.plugins.jev_router.helpers.messages',
        Path('/a0/usr/projects/jev_router/plugin/helpers/messages.py'))
    mmod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mmod)
    sys.modules['usr.plugins.jev_router.helpers.messages'] = mmod
    sys.modules['usr.plugins.jev_router.helpers.jev'] = fake_jev

    spec = importlib.util.spec_from_file_location(
        'usr.plugins.jev_router.helpers.dynamic_switch',
        Path('/a0/usr/projects/jev_router/plugin/helpers/dynamic_switch.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules['usr.plugins.jev_router.helpers.dynamic_switch'] = mod
    return calls


def _load():
    spec = importlib.util.spec_from_file_location('jev_dynamic_switch_test', EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make(mod, profile='agent0', log_entries=1):
    agent = _FakeAgent(profile)
    ctx = _FakeContext(agent, log_entries)
    agent.context = ctx
    ext = mod.JevDynamicSwitch.__new__(mod.JevDynamicSwitch)
    ext.agent = agent
    return agent, ctx, ext


def _run(ext, message='refactor this module now'):
    asyncio.run(ext.execute(agent=ext.agent, data={'message': message, 'attachment_paths': []}))


def _streak_state(mod, task_class='coding', profile='developer', streak=1):
    st = mod.__dict__.get('_STATE_KEY') and None
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, task_class, profile, 0.9)
    for _ in range(streak - 1):
        state = ds.record_match(state, task_class, profile, 0.9)
    return state


def test_second_message_with_streak_switches():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, 'coding', 'developer', 0.9)  # streak=1 from msg N-1
    ctx.set_data('jev_dynamic_switch_state', state)
    _run(ext)
    assert calls['query'] == 1, calls
    assert calls['initialize'] and calls['initialize'][0].get('agent_profile') == 'developer', calls
    assert ctx.agent0.config.profile == 'developer'
    assert calls['saved'] == 1 and calls['dirty'], calls
    saved = ctx.get_data('jev_dynamic_switch_state')
    assert saved.get('last_switch_profile') == 'developer', saved


def test_first_judgment_no_switch_yet():
    """Marker present (message 2+): judged, but one observation never switches."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    ctx.set_data('jev_dynamic_switch_state', ds.new_state())  # marker from msg1
    _run(ext)
    assert calls['query'] == 1
    assert not calls['initialize'], calls
    assert ctx.agent0.config.profile == 'agent0'
    state = ctx.get_data('jev_dynamic_switch_state')
    assert state.get('streak') == 1, state


def test_fresh_chat_skipped():
    """Empty log = message 1 = preselect's domain."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod, log_entries=0)
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_busy_chat_skipped():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    ctx.is_running = lambda: True
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_manual_profile_locks():
    """Non-default profile we did not auto-switch to = user intent; never override."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod, profile='researcher')  # != default agent0
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, 'coding', 'developer', 0.9)
    ctx.set_data('jev_dynamic_switch_state', state)
    _run(ext)
    assert calls['query'] == 0, calls
    assert not calls['initialize']
    assert ctx.agent0.config.profile == 'researcher'


def test_own_auto_switch_not_locked():
    """Profile we auto-switched to earlier is not a manual lock."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod, profile='developer')  # we switched here before
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, 'coding', 'developer', 0.9)
    state['last_switch_profile'] = 'developer'
    state['last_switch_time'] = 0.0
    ctx.set_data('jev_dynamic_switch_state', state)
    _run(ext)
    assert calls['query'] == 1, calls


def test_advise_mode_skipped():
    calls = _install_stubs()
    sys.modules['helpers.plugins'].get_plugin_config = (
        lambda name, agent=None, **kw: dict(CFG, delegation_mode='advise') if name == 'jev_router' else {})
    mod = _load()
    agent, ctx, ext = _make(mod)
    _run(ext)
    assert calls['query'] == 0


def test_no_key_skipped():
    calls = _install_stubs()
    sys.modules['helpers.plugins'].get_plugin_config = (
        lambda name, agent=None, **kw: dict(CFG, jev_api_key='') if name == 'jev_router' else {})
    mod = _load()
    agent, ctx, ext = _make(mod)
    _run(ext)
    assert calls['query'] == 0 and not calls['initialize']


def test_subordinate_agent_skipped():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    agent.number = 1
    _run(ext)
    assert calls['query'] == 0


def test_never_raises_on_init_failure():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, 'coding', 'developer', 0.9)
    ctx.set_data('jev_dynamic_switch_state', state)
    sys.modules['initialize'].initialize_agent = (
        lambda override_settings=None: (_ for _ in ()).throw(RuntimeError('boom')))
    _run(ext)  # must not raise
    assert ctx.agent0.config.profile == 'agent0'



def test_first_dynamic_message_records_marker_without_judgment():
    """E2E regression: greeting entries make logs non-empty; message 1 must
    still belong to preselect - dynamic records a marker, no Jev call."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)  # log_entries=1 simulates greeting
    _run(ext)
    assert calls['query'] == 0, calls
    state = ctx.get_data('jev_dynamic_switch_state')
    assert isinstance(state, dict) and state.get('task_class') is None, state


def test_same_profile_after_cooldown_no_reinit():
    """Already on target: no redundant re-init after cooldown (review fix)."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod, profile='developer')  # already switched here
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    state = ds.new_state()
    state = ds.record_match(state, 'coding', 'developer', 0.9)  # streak=1
    state['last_switch_profile'] = 'developer'
    state['last_switch_time'] = 0.0  # now - 0 >> cooldown(30)
    ctx.set_data('jev_dynamic_switch_state', state)
    _run(ext)
    assert calls['query'] == 1, calls
    assert not calls['initialize'], calls
    assert ctx.agent0.config.profile == 'developer'
    assert calls['saved'] == 0 and not calls['dirty'], calls



def test_duplicate_message_fire_judged_once():
    """Same (context, digest) within the dedup window: no second Jev call."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    ctx.set_data('jev_dynamic_switch_state', ds.new_state())
    _run(ext, message='refactor the auth module and add tests')
    assert calls['query'] == 1, calls
    _run(ext, message='refactor the auth module and add tests')
    assert calls['query'] == 1, calls


def test_distinct_messages_judged_separately():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    ctx.set_data('jev_dynamic_switch_state', ds.new_state())
    _run(ext, message='refactor the auth module and add tests')
    _run(ext, message='research quantum computing breakthroughs this week')
    assert calls['query'] == 2, calls


def test_trivial_message_skips_jev():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    ctx.set_data('jev_dynamic_switch_state', ds.new_state())
    _run(ext, message='ok thanks!')
    assert calls['query'] == 0, calls
    assert not calls['initialize'], calls


def test_marker_message_does_not_consume_digest():
    """Message 1 (marker skip) must not eat the digest: same text on msg 2 judges."""
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    _run(ext, message='refactor the auth module and add tests')  # marker skip
    assert calls['query'] == 0, calls
    _run(ext, message='refactor the auth module and add tests')  # now judged
    assert calls['query'] == 1, calls


def test_extension_reuses_client_across_messages():
    calls = _install_stubs()
    mod = _load()
    agent, ctx, ext = _make(mod)
    from usr.plugins.jev_router.helpers import dynamic_switch as ds
    ctx.set_data('jev_dynamic_switch_state', ds.new_state())
    _run(ext, message='refactor the auth module and add tests')
    _run(ext, message='research quantum computing breakthroughs this week')
    assert calls['query'] == 2, calls
    assert calls['clients'] == 1, calls

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
