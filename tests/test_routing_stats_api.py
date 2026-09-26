# Audit round 2 RED: routing_stats API must not leak internals on error.
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

helpers_pkg = types.ModuleType('helpers')
api_mod = types.ModuleType('helpers.api')


class Request:
    pass


class Response:
    pass


class ApiHandler:
    pass


api_mod.ApiHandler = ApiHandler
api_mod.Request = Request
api_mod.Response = Response
sys.modules.setdefault('helpers', helpers_pkg)
sys.modules['helpers.api'] = api_mod

pkg = types.ModuleType('usr.plugins.jev_router.helpers')
pkg.__path__ = []
sys.modules.setdefault('usr.plugins', types.ModuleType('usr.plugins'))
sys.modules.setdefault('usr.plugins.jev_router',
                       types.ModuleType('usr.plugins.jev_router'))
sys.modules['usr.plugins.jev_router.helpers'] = pkg


def _boom(db, limit=20):
    raise RuntimeError('secret detail /a0/tmp/tele.db')


webui_stub = types.SimpleNamespace(stats_from_db=_boom)
sys.modules['usr.plugins.jev_router.helpers.webui_data'] = webui_stub
pkg.webui_data = webui_stub

spec = importlib.util.spec_from_file_location(
    'jev_routing_stats_test', PLUGIN_ROOT / 'api' / 'routing_stats.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_stats_error_is_generic():
    out = asyncio.run(mod.RoutingStats().process({'limit': 5}, Request()))
    assert out['ok'] is False
    assert 'secret' not in str(out.get('error'))
    assert '/a0' not in str(out.get('error'))
