"""jev_router: circuit breaker snapshot + reset for the WebUI panel."""
from helpers.api import ApiHandler, Request, Response


class RoutingBreaker(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.jev_router.helpers import circuit_breaker, webui_data
            action = str(input.get('action') or '')
            if action == 'reset':
                circuit_breaker.reset(
                    str(input['provider']) if input.get('provider') else None)
            return {'ok': True, 'snapshot': webui_data.breaker_snapshot()}
        except Exception as exc:
            return {'ok': False, 'error': str(exc), 'snapshot': []}
