"""jev_router: recent decisions + per-preset aggregates for the WebUI panel."""
from pathlib import Path

from helpers.api import ApiHandler, Request, Response


class RoutingStats(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.jev_router.helpers import webui_data
            db = Path('/a0/tmp/jev_router_telemetry.db')
            limit = input.get('limit') if isinstance(input.get('limit'), int) else 20
            return {'ok': True, **webui_data.stats_from_db(db, limit=limit)}
        except Exception as exc:
            return {'ok': False, 'error': str(exc),
                    'recent': [], 'totals': {'decisions': 0}, 'by_preset': {}}
