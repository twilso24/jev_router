"""jev_router: WebUI-path new-chat profile pre-selection (spec decision #5B).

The WebUI creates chats via /chat_create (no message yet) and then POSTs
the first message to /message_async, which fires the framework's
``user_message_ui`` hook BEFORE ``context.communicate()`` starts the loop.
This extension runs one bounded Jev task-class judgment on that first
message and swaps the agent profile with the sanctioned pattern from
api/agent_profile_set.py (initialize_agent -> assign config -> persist).

Guards: main agent only; fresh chat only (idle + empty log + profile still
the instance default, so an explicit user choice — or an earlier
pre-selection via the API path — always wins); plugin gates (enabled +
chat_preselect + delegation_mode=auto + API key); never raises.
"""
import os
import traceback

from helpers.extension import Extension


def _dbg(msg: str) -> None:
    try:
        from usr.plugins.jev_router.helpers.preselect import _dbg as _pdbg
        _pdbg(msg)
    except Exception:
        pass


class JevPreselectUi(Extension):

    async def execute(self, data: dict = None, **kwargs) -> None:
        try:
            agent = self.agent
            if not agent or getattr(agent, "number", 1) != 0:
                return  # main agent only
            context = getattr(agent, "context", None)
            if context is None:
                return
            if not isinstance(data, dict):
                return
            message = str(data.get("message") or "").strip()
            if not message:
                return

            # Fresh chat only: idle and no log entries yet (the greeting and
            # the first user message are logged AFTER this hook fires).
            try:
                if context.is_running():
                    return
            except Exception:
                return
            log = getattr(context, "log", None)
            if log is not None and getattr(log, "logs", None):
                return

            # Explicit profile (or already pre-selected via API path) wins.
            try:
                from helpers import settings as settings_mod
                default_profile = str(
                    settings_mod.get_settings().get("agent_profile") or "")
            except Exception:
                default_profile = ""
            current_profile = str(
                getattr(getattr(agent, "config", None), "profile", "") or "")
            if not default_profile or current_profile != default_profile:
                return

            # Plugin gates.
            try:
                from helpers import plugins
                cfg = plugins.get_plugin_config("jev_router", agent) or {}
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
                _dbg("ui skip: no TypeSafe API key configured")
                return

            # Validate against actually available profiles.
            try:
                from helpers import subagents
                profiles = [a.name for a in subagents.get_agents_list()]
            except Exception:
                profiles = []
            if not profiles:
                _dbg("ui skip: no agent profiles available")
                return

            # One bounded Jev judgment. We are inside the live event loop
            # (async hook), so await directly — never asyncio.run here.
            from typesafe_sdk import AsyncTypeSafeClient
            model = str(cfg.get("jev_model") or "jev-latest")
            client = AsyncTypeSafeClient(
                api_key=key, model=model,
                timeout=float(cfg.get("jev_timeout") or 30))

            async def _query_fn(c, state, questions, m):
                return await jev_mod.query(c, state, questions, m)

            profile, reason = await preselect.run(
                message, cfg, _query_fn, client, model, profiles,
                float(cfg.get("jev_timeout_s") or 2.0))
            _dbg("ui decision: " + reason)
            if not profile or profile == current_profile:
                return

            # Sanctioned swap pattern (api/agent_profile_set.py): rebuild
            # config before the loop starts, assign, persist.
            from initialize import initialize_agent
            config = initialize_agent(override_settings={"agent_profile": profile})
            context.config = config
            agent.config = config
            try:
                from helpers.persist_chat import save_tmp_chat
                save_tmp_chat(context)
            except Exception:
                pass
            try:
                from helpers.state_monitor_integration import mark_dirty_for_context
                mark_dirty_for_context(context.id, reason="jev_preselect")
            except Exception:
                pass
            _dbg("ui pre-selected agent_profile=" + profile)
        except Exception:
            _dbg("ui ERROR " + traceback.format_exc()[:300])
            return
