"""jev_router: per-chat routing kill-switch API.

get/set the routing-enabled flag for one chat context.
Spec: docs/specs/per-chat-kill-switch.md
"""
from helpers.api import ApiHandler, Request, Response

JEV_KILL_KEY = 'jev_router_kill'


class RoutingKill(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        from agent import AgentContext
        from helpers import plugins as plugins_mod
        from helpers.persist_chat import save_tmp_chat
        from helpers.state_monitor_integration import mark_dirty_for_context
        from usr.plugins.jev_router.helpers.gate import routing_allowed

        context_id = str(input.get('context_id') or '').strip()
        action = str(input.get('action') or 'get').strip().lower()
        if not context_id:
            return Response(status=400, response='Missing context_id')

        context = AgentContext.get(context_id)
        if not context:
            return Response(status=404, response='Context not found')

        agent = getattr(request, 'agent', None)
        cfg = plugins_mod.get_plugin_config('jev_router', agent) or {}

        if action == 'get':
            return self._state(context, cfg, routing_allowed)
        if action != 'set':
            return Response(status=400, response=f'Unknown action: {action}')
        if context.is_running():
            return Response(
                status=409,
                response=('Chat is running; routing can be toggled after '
                          'the current run finishes.'),
            )

        enabled = input.get('enabled')
        if not isinstance(enabled, bool):
            return Response(status=400, response='enabled must be a boolean')

        context.set_data(JEV_KILL_KEY, {'enabled': enabled})
        save_tmp_chat(context)
        mark_dirty_for_context(context.id, reason='jev_kill_switch')
        return self._state(context, cfg, routing_allowed)

    @staticmethod
    def _state(context, cfg, routing_allowed) -> dict:
        chat_state = context.get_data(JEV_KILL_KEY)
        if not isinstance(chat_state, dict):
            chat_state = None
        stored = (chat_state or {}).get('enabled')
        return {
            'ok': True,
            # unset chat switch defaults to on (follows the global flag)
            'enabled': stored if isinstance(stored, bool) else True,
            'global_enabled': bool(cfg.get('enabled', True)),
            'effective': routing_allowed(cfg, chat_state),
        }