"""jev_router: fallback chain statistics for the WebUI panel."""
from pathlib import Path

from helpers.api import ApiHandler, Request, Response


class RoutingFallback(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.jev_router.helpers import webui_data
            from helpers import plugins as plugins_mod
            
            # Check if fallback chain tracking is enabled in plugin config
            agent = getattr(request, 'agent', None)
            if agent is not None:
                cfg = plugins_mod.get_plugin_config('jev_router', agent) or {}
                if not cfg.get('obs_fallback_enabled', True):
                    return {'ok': True, 'fallback_map': {}, 'fallback_calls': []}
            
            db = Path('/a0/tmp/jev_router_telemetry.db')
            limit = input.get('limit') if isinstance(input.get('limit'), int) else 200
            return {'ok': True, **webui_data.fallback_chain_stats(db, limit=limit)}
        except Exception:
            return {'ok': False, 'error': 'internal error',
                    'fallback_map': {}, 'fallback_calls': []}
