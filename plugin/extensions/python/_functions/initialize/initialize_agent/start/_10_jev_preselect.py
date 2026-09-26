"""jev_router: new-chat agent-profile pre-selection (spec decision #5B).

Implicit start-hook on ``initialize.initialize_agent``: WebUI and API both
create chats through ``/api/message`` -> ``initialize_agent``, so this is the
single shared interception point BEFORE ``AgentConfig(profile=...)`` is built.

Behavior:
- Only for NEW chats (no context_id in the pending request body).
- NEVER overrides an explicit ``agent_profile`` (user intent wins).
- Gates: plugin enabled + chat_preselect + delegation_mode=auto + API key.
- One bounded Jev task-class judgment; maps to an existing profile.
- Never raises; any failure leaves override_settings untouched.
"""
import asyncio
import os
import traceback

from helpers.extension import Extension


def _dbg(msg: str) -> None:
    try:
        from usr.plugins.jev_router.helpers.preselect import _dbg as _pdbg
        _pdbg(msg)
    except Exception:
        pass


class JevPreselectProfile(Extension):

    def execute(self, data: dict = None, **kwargs) -> None:
        if not isinstance(data, dict):
            return
        try:
            # 1. Request-context guard: outside an HTTP request (CLI, boot,
            #    programmatic initialize_agent) there is no first message.
            try:
                from flask import request
                body = request.get_json(silent=True)
            except Exception:
                return
            if not isinstance(body, dict):
                return

            # 2. Config gates.
            try:
                from helpers import plugins
                cfg = plugins.get_plugin_config("jev_router") or {}
            except Exception:
                cfg = {}
            if not isinstance(cfg, dict):
                cfg = {}

            from usr.plugins.jev_router.helpers import preselect
            if not preselect.should_preselect(cfg):
                return

            from usr.plugins.jev_router.helpers import jev as jev_mod
            key = jev_mod.resolve_api_key(cfg, os.environ)
            if not key:
                _dbg('skip: no TypeSafe API key configured')
                return

            # 3. New chat only; explicit profile always wins.
            message, explicit = preselect.parse_request(body)
            if not message:
                return
            if explicit:
                _dbg('skip: explicit agent_profile in request wins')
                return

            # 4. Validate against actually available profiles.
            try:
                from helpers import subagents
                profiles = [a.name for a in subagents.get_agents_list()]
            except Exception:
                profiles = []
            if not profiles:
                _dbg('skip: no agent profiles available')
                return

            # 5. One bounded Jev judgment.
            from typesafe_sdk import AsyncTypeSafeClient
            model = str(cfg.get('jev_model') or 'jev-latest')
            client = AsyncTypeSafeClient(
                api_key=key, model=model,
                timeout=float(cfg.get('jev_timeout') or 30))

            async def _query_fn(c, state, questions, m):
                return await jev_mod.query(c, state, questions, m)

            profile, reason = asyncio.run(preselect.run(
                message, cfg, _query_fn, client, model, profiles,
                float(cfg.get('jev_timeout_s') or 2.0)))
            _dbg('decision: ' + reason)

            # 6. Inject into initialize_agent kwargs (start-hook contract:
            #    mutating data['kwargs'] reaches the wrapped function).
            if profile:
                kw = data.get('kwargs')
                if not isinstance(kw, dict):
                    kw = {}
                    data['kwargs'] = kw
                ov = kw.get('override_settings')
                if not isinstance(ov, dict):
                    ov = {}
                    kw['override_settings'] = ov
                ov['agent_profile'] = profile
                _dbg('pre-selected agent_profile=' + profile)
        except Exception:
            _dbg('ERROR ' + traceback.format_exc()[:300])
            return
