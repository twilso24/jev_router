"""jev_router: shadow mode statistics for the WebUI panel."""
from pathlib import Path

from helpers.api import ApiHandler, Request, Response


class RoutingShadow(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.jev_router.helpers import webui_data
            from helpers import plugins as plugins_mod
            
            # Check if shadow mode is enabled in plugin config
            agent = getattr(request, 'agent', None)
            if agent is not None:
                cfg = plugins_mod.get_plugin_config('jev_router', agent) or {}
                if not cfg.get('obs_shadow_enabled', True):
                    return {'ok': True, 'shadow': [], 'total': 0, 'matches': 0, 'match_rate': 0}
            
            db = Path('/a0/tmp/jev_router_telemetry.db')
            limit = input.get('limit') if isinstance(input.get('limit'), int) else 200
            return {'ok': True, **webui_data.shadow_mode_stats(db, limit=limit)}
        except Exception:
            return {'ok': False, 'error': 'internal error',
                    'shadow': [], 'total': 0, 'matches': 0, 'match_rate': 0}
