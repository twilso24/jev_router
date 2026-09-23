"""jev_router: policy read/write, provider rules, and band tuning."""
from pathlib import Path

from helpers.api import ApiHandler, Request, Response

POLICY_PATH = Path('/a0/usr/plugins/jev_router/routing-policy.yaml')
PRESETS_PATH = Path('/a0/usr/plugins/_model_config/presets.yaml')
TELEMETRY_PATH = Path('/a0/tmp/jev_router_telemetry.db')


class RoutingPolicy(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.jev_router.helpers import webui_data
            action = str(input.get('action') or 'read')
            if action == 'read':
                return {'ok': True, 'policy': webui_data.read_policy(POLICY_PATH)}
            if action == 'write':
                raw = input.get('exclude')
                exclude = ([str(x).strip() for x in raw if str(x).strip()]
                           if isinstance(raw, list) else [])
                ok = webui_data.write_provider_rules(POLICY_PATH, exclude=exclude)
                return {'ok': ok, 'error': None if ok else 'write failed'}
            if action == 'tuning':
                presets = webui_data.pool_preset_names(PRESETS_PATH)
                providers = webui_data.pool_providers(PRESETS_PATH)
                return {'ok': True,
                        'providers': providers,
                        **webui_data.tuning_report(
                            TELEMETRY_PATH, POLICY_PATH, presets,
                            pool_providers=providers)}
            if action == 'set_auto_tune':
                from usr.plugins.jev_router.helpers import tuning
                ok = tuning.write_auto_tune(
                    POLICY_PATH, bool(input.get('enabled')))
                return {'ok': ok, 'error': None if ok else 'write failed'}
            if action == 'write_band_orders':
                from usr.plugins.jev_router.helpers import tuning
                raw = input.get('band_orders')
                ok = tuning.write_band_orders(
                    POLICY_PATH, raw if isinstance(raw, dict) else {})
                return {'ok': ok,
                        'error': None if ok else 'invalid band_orders'}
            return {'ok': False, 'error': 'unknown action'}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}
