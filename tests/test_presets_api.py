# Task 4/5 (TDD): presets API - list / describe (corrected spec: no save/delete)
# Run: /opt/venv-a0/bin/python -m pytest tests/test_presets_api.py -q
import sys
import asyncio
import tempfile
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import yaml

# --- framework helpers.api stub (needed by routing_presets) -----------------
# Only stub helpers.api, NOT the entire helpers package
api_mod = types.ModuleType('helpers.api')


class Request:  # minimal stand-in
    pass


class Response:  # minimal stand-in
    pass


class ApiHandler:
    def __init__(self, *args, **kwargs):
        pass


api_mod.ApiHandler = ApiHandler
api_mod.Request = Request
api_mod.Response = Response
sys.modules['helpers.api'] = api_mod

# --- plugin helpers stub so process() lazy imports resolve ------------------
# Same pattern as test_routing_policy_api.py: register the plugin helpers
# package in sys.modules, then attach the REAL helper modules so the lazy
# imports inside RoutingPresets.process() resolve to genuine code.
pkg = types.ModuleType('usr.plugins.jev_router.helpers')
pkg.__path__ = []
sys.modules.setdefault('usr.plugins', types.ModuleType('usr.plugins'))
sys.modules.setdefault('usr.plugins.jev_router',
                       types.ModuleType('usr.plugins.jev_router'))
sys.modules['usr.plugins.jev_router.helpers'] = pkg

from helpers import auto_wire as _auto_wire
from helpers import presets_editor as _presets_editor
pkg.presets_editor = _presets_editor
pkg.auto_wire = _auto_wire
sys.modules['usr.plugins.jev_router.helpers.presets_editor'] = _presets_editor
sys.modules['usr.plugins.jev_router.helpers.auto_wire'] = _auto_wire

from helpers import presets_editor

try:
    from api import routing_presets
    HAVE_MOD = True
except Exception:
    HAVE_MOD = False


class MockRequest:
    def __init__(self, method='POST', json_body=None):
        self.method = method
        self._json = json_body or {}
    async def json(self):
        return self._json


def _model_preset(name: str) -> dict:
    """A model preset entry with a valid chat block (the runtime source of truth)."""
    return {
        'name': name,
        'description': '',
        'chat': {
            'provider': 'openrouter',
            'name': 'test/model',
            'api_base': '',
            'ctx_length': 128000,
            'ctx_history': 0.5,
            'vision': True,
            'max_embeds': 5,
            'rl_requests': 10,
            'rl_input': 1000,
            'rl_output': 2000
        },
        'utility': {
            'provider': 'openrouter',
            'name': 'test/utility'
        },
        'embedding': {
            'provider': 'huggingface',
            'name': 'sentence-transformers/all-MiniLM-L6-v2'
        },
        'vision': {
            'provider': 'openrouter',
            'name': 'test/vision'
        }
    }


# ============================================================================
# RED tests for inline describe action (attach plain-text definition to an
# existing model preset without creating new presets or using 'from')
# ============================================================================

def test_describe_updates_existing_model_preset():
    """describe: name + description on an existing model preset updates
    only the description field, preserving chat and all other blocks."""
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        data = [_model_preset('Default')]
        presets_path.write_text(yaml.safe_dump(data))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process(
                {'action': 'describe', 'name': 'Default',
                 'description': 'Fast and reliable default model'},
                MockRequest())
            assert result['ok'] is True
            loaded = yaml.safe_load(presets_path.read_text())
            assert loaded[0]['description'] == 'Fast and reliable default model'
            # chat block untouched
            assert loaded[0]['chat']['provider'] == 'openrouter'
            assert loaded[0]['chat']['name'] == 'test/model'
        asyncio.run(run())


def test_describe_missing_preset_fails():
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        presets_path.write_text(yaml.safe_dump([_model_preset('Default')]))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process(
                {'action': 'describe', 'name': 'Nope', 'description': 'x'},
                MockRequest())
            assert result['ok'] is False
        asyncio.run(run())


def test_describe_empty_description_fails():
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        presets_path.write_text(yaml.safe_dump([_model_preset('Default')]))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process(
                {'action': 'describe', 'name': 'Default', 'description': '  '},
                MockRequest())
            assert result['ok'] is False
        asyncio.run(run())


def test_describe_too_long_fails():
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        presets_path.write_text(yaml.safe_dump([_model_preset('Default')]))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process(
                {'action': 'describe', 'name': 'Default',
                 'description': 'x' * 301}, MockRequest())
            assert result['ok'] is False
        asyncio.run(run())


def test_describe_preserves_unknown_keys():
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        entry = _model_preset('Default')
        entry['custom_flag'] = True
        presets_path.write_text(yaml.safe_dump([entry]))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process(
                {'action': 'describe', 'name': 'Default',
                 'description': 'noted'}, MockRequest())
            assert result['ok'] is True
            loaded = yaml.safe_load(presets_path.read_text())
            assert loaded[0]['custom_flag'] is True
            assert loaded[0]['description'] == 'noted'
        asyncio.run(run())


# ============================================================================
# List action tests (corrected spec: only model presets returned)
# ============================================================================

def test_list_action_returns_only_model_presets():
    """List should return ONLY model presets (entries with valid chat block)."""
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        # Mix of model preset and plain-text preset (no chat block)
        data = [
            _model_preset('Default'),
            {'name': 'PlainOnly', 'description': 'no chat block', 'from': 'Default'}
        ]
        presets_path.write_text(yaml.safe_dump(data))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process({'action': 'list'}, MockRequest())
            assert result['ok'] is True
            assert 'presets' in result
            # Only model preset returned
            assert len(result['presets']) == 1
            assert result['presets'][0]['name'] == 'Default'
            assert 'model_presets' in result
            assert result['model_presets'] == ['Default']
        asyncio.run(run())


def test_list_action_empty_when_no_model_presets():
    """List returns empty when no entries have a valid chat block."""
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        data = [{'name': 'PlainOnly', 'description': 'no chat block', 'from': 'Default'}]
        presets_path.write_text(yaml.safe_dump(data))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process({'action': 'list'}, MockRequest())
            assert result['ok'] is True
            assert result['presets'] == []
            assert result['model_presets'] == []
        asyncio.run(run())


def test_list_action_model_presets_field_populated():
    """model_presets list matches the returned presets."""
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        data = [_model_preset('A'), _model_preset('B')]
        presets_path.write_text(yaml.safe_dump(data))
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process({'action': 'list'}, MockRequest())
            assert result['ok'] is True
            assert len(result['presets']) == 2
            names = {p['name'] for p in result['presets']}
            assert names == {'A', 'B'}
            assert set(result['model_presets']) == {'A', 'B'}
        asyncio.run(run())


def test_unknown_action_returns_error():
    """Unknown action returns error."""
    with tempfile.TemporaryDirectory() as td:
        presets_path = Path(td) / 'presets.yaml'
        presets_path.write_text('[]')
        handler = routing_presets.RoutingPresets(presets_path=presets_path)

        async def run():
            result = await handler.process({'action': 'foo'}, MockRequest())
            assert result['ok'] is False
        asyncio.run(run())
