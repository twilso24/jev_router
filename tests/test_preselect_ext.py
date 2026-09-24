"""Pre-selection extension wrapper: kwargs mutation and skip paths.

Loads the real extension file with stubbed flask/plugins/SDK/jev modules.
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

EXT_PATH = Path(__file__).resolve().parents[1] / 'extensions/python/_functions/initialize/initialize_agent/start/_10_jev_preselect.py'

CFG = {'enabled': True, 'chat_preselect': True, 'delegation_mode': 'auto',
       'jev_api_key': 'k', 'jev_model': 'jev-latest', 'jev_timeout_s': 2.0}


def _install_stubs(request_json):
    state = {'query_calls': 0}

    fake_flask = types.ModuleType('flask')
    fake_flask.request = SimpleNamespace(
        get_json=lambda silent=False: request_json)
    sys.modules['flask'] = fake_flask

    fake_plugins = types.ModuleType('helpers.plugins')
    fake_plugins.get_plugin_config = lambda name, agent=None, **kw: dict(CFG) if name == 'jev_router' else {}
    sys.modules['helpers.plugins'] = fake_plugins

    fake_subagents = types.ModuleType('helpers.subagents')
    fake_subagents.get_agents_list = lambda project_name=None: [
        SimpleNamespace(name=n) for n in ('default', 'developer', 'researcher', 'hacker', 'agent0')]
    sys.modules['helpers.subagents'] = fake_subagents

    fake_sdk = types.ModuleType('typesafe_sdk')
    fake_sdk.AsyncTypeSafeClient = lambda **kw: object()
    sys.modules['typesafe_sdk'] = fake_sdk

    fake_jev = types.ModuleType('usr.plugins.jev_router.helpers.jev')
    async def fake_query(client, msg_state, questions, model, **kw):
        state['query_calls'] += 1
        return {'answers': {'task_class': {'choice': 'coding', 'confidence': 0.9}},
                'model': 'jev-latest', 'usage': {}}
    fake_jev.query = fake_query
    fake_jev.resolve_api_key = lambda cfg, env=None: str((cfg or {}).get('jev_api_key') or '')
    sys.modules['usr.plugins.jev_router.helpers.jev'] = fake_jev

    # Canonical preselect module: the extension imports the deployed path
    # (usr.plugins...), so pre-register the canonical file under that name.
    pspec = importlib.util.spec_from_file_location(
        'usr.plugins.jev_router.helpers.preselect',
        Path(__file__).resolve().parents[1] / 'helpers/preselect.py')
    pmod = importlib.util.module_from_spec(pspec)
    pspec.loader.exec_module(pmod)
    sys.modules['usr.plugins.jev_router.helpers.preselect'] = pmod
    return state


def _load():
    spec = importlib.util.spec_from_file_location('jev_preselect_ext_test', EXT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _data():
    return {'args': (), 'kwargs': {'override_settings': {}}, 'result': None, 'exception': None}


def test_new_chat_sets_profile_in_override_settings():
    _install_stubs({'message': 'fix this python bug fast'})
    mod = _load()
    data = _data()
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert data['kwargs']['override_settings'].get('agent_profile') == 'developer', data


def test_explicit_profile_never_overridden():
    _install_stubs({'message': 'fix bug', 'agent_profile': 'researcher'})
    mod = _load()
    data = _data()
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert 'agent_profile' not in data['kwargs']['override_settings']


def test_existing_context_skipped():
    _install_stubs({'message': 'fix bug', 'context_id': 'abc'})
    mod = _load()
    data = _data()
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert 'agent_profile' not in data['kwargs']['override_settings']


def test_advise_mode_skipped_without_query():
    _install_stubs({'message': 'fix bug'})
    sys.modules['helpers.plugins'].get_plugin_config = lambda name, agent=None, **kw: dict(CFG, delegation_mode='advise')
    mod = _load()
    data = _data()
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert 'agent_profile' not in data['kwargs']['override_settings']


def test_no_api_key_skips_without_query():
    _install_stubs({'message': 'fix bug'})
    sys.modules['helpers.plugins'].get_plugin_config = lambda name, agent=None, **kw: dict(CFG, jev_api_key='')
    mod = _load()
    data = _data()
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert 'agent_profile' not in data['kwargs']['override_settings']


def test_none_override_settings_replaced_not_crashed():
    _install_stubs({'message': 'fix bug'})
    mod = _load()
    data = {'args': (), 'kwargs': {'override_settings': None}, 'result': None, 'exception': None}
    mod.JevPreselectProfile.__new__(mod.JevPreselectProfile).execute(data=data)
    assert data['kwargs']['override_settings'].get('agent_profile') == 'developer'


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
