"""jev_router: dynamic main-agent profile switching (user_message_ui hook).

Spec: docs/specs/dynamic-profile-switch.md (user-approved policy):
- Evaluates EVERY user message while the chat is idle, before the loop starts.
- Fresh chats (message 1) belong to _10_jev_preselect; this extension acts
  from message 2 onward (non-empty log guard).
- Manual profile choice wins: a non-default profile that we did NOT auto-
  switch to earlier is treated as a user lock and never overridden.
- Conservative policy: confidence >= threshold, two consecutive matching
  judgments of the same task class, and a same-profile cooldown.
- Swap uses the sanctioned pattern from api/agent_profile_set.py:
  initialize_agent -> assign config -> persist -> mark dirty.
- Never raises; any failure keeps the current profile.
"""
import hashlib
import os
import time
import traceback

from helpers.extension import Extension

_STATE_KEY = 'jev_dynamic_switch_state'
_FIRED = {}  # per-context digest cache
_FIRED_MAX = 512
DEBUG_LOG = '/a0/tmp/jev_router_debug.log'


def _dbg(msg: str) -> None:
    """Best-effort debug-log write with the dynamic-switch tag; never raises."""
    try:
        from datetime import datetime as _dt
        stamp = _dt.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG, 'a') as f:
            f.write(stamp + ' [dynamic-switch] ' + msg + chr(10))
    except Exception:
        pass


def _questions() -> dict:
    """Shared task-class taxonomy; reuses preselect's question when available."""
    try:
        from usr.plugins.jev_router.helpers import preselect
        return preselect._questions()
    except Exception:
        pass
    return {
        'task_class': {
            'type': 'choice',
            'instructions': ('Classify the primary nature of the latest user '
                             'message.'),
            'criteria': {
                'coding': 'Writing, debugging, refactoring or reviewing code',
                'research': 'Information gathering, analysis, summarizing sources',
                'security': 'Penetration testing, vulnerability analysis',
                'testing': 'Designing or writing tests, verification planning',
                'other': 'Anything else (chat, writing, ops, unclear)',
            },
        },
    }


class JevDynamicSwitch(Extension):

    async def execute(self, data: dict = None, **kwargs) -> None:
        try:
            agent = self.agent
            if not agent or getattr(agent, 'number', 1) != 0:
                return  # main agent only
            context = getattr(agent, 'context', None)
            if context is None or not isinstance(data, dict):
                return
            message = str(data.get('message') or '').strip()
            if not message:
                return

            # Idle only: never swap while a loop is active.
            try:
                if context.is_running():
                    return
            except Exception:
                return

            # Message 2+ only: fresh chats are preselect's domain.
            log = getattr(context, 'log', None)
            if log is not None and not getattr(log, 'logs', None):
                return

            # Manual lock: a non-default profile that we did not auto-switch
            # to earlier is user intent; never override it.
            state = None
            try:
                state = context.get_data(_STATE_KEY)
            except Exception:
                state = None
            if not isinstance(state, dict):
                state = None
            try:
                from helpers import settings as settings_mod
                default_profile = str(
                    settings_mod.get_settings().get('agent_profile') or '')
            except Exception:
                default_profile = ''
            current_profile = str(
                getattr(getattr(agent, 'config', None), 'profile', '') or '')
            if not default_profile or current_profile != default_profile:
                auto_target = str((state or {}).get('last_switch_profile') or '')
                if current_profile != auto_target:
                    _dbg('skip: manual profile lock at '
                         + (current_profile or '?'))
                    return

            # Fresh-chat split: message 1 belongs to preselect. This runtime
            # logs a greeting entry at context creation, so the empty-log
            # guard cannot detect freshness; the state marker records whether
            # dynamic switching has acted in this chat before.
            if state is None:
                try:
                    from usr.plugins.jev_router.helpers import (
                        dynamic_switch as _ds_marker)
                    context.set_data(_STATE_KEY, _ds_marker.new_state())
                except Exception:
                    pass
                _dbg('skip: first dynamic message (marker recorded); '
                     'preselect owns message 1')
                return

            # Plugin gates.
            try:
                from helpers import plugins
                cfg = plugins.get_plugin_config('jev_router', agent) or {}
            except Exception:
                cfg = {}
            if not isinstance(cfg, dict):
                cfg = {}

            from usr.plugins.jev_router.helpers import dynamic_switch as ds
            if not ds.should_dynamic_switch(cfg):
                return

            from usr.plugins.jev_router.helpers import jev as jev_mod
            key = jev_mod.resolve_api_key(cfg, os.environ)
            if not key:
                _dbg('skip: no TypeSafe API key configured')
                return

            # Trivial message: skip Jev entirely (mirrors the router fast path).
            try:
                from usr.plugins.jev_router.helpers import (
                    fastpath as _fastpath, messages as _messages)
                _clean = _messages.extract_user_text(message)
                _trivial = _fastpath.is_trivial(_clean)
            except Exception:
                _clean = message
                _trivial = False
            if _trivial:
                _dbg('skip: trivial message (fast path)')
                return

            # Dedup: one judgment per (context, digest) within this process;
            # collapses concurrent duplicate fires of the same message.
            _digest = hashlib.sha256(
                _clean.encode('utf-8', 'replace')).hexdigest()[:16]
            _fkey = (str(getattr(context, 'id', '') or ''), _digest)
            if _FIRED.get(_fkey):
                _dbg('skip: duplicate fire digest=' + _digest)
                return
            _FIRED[_fkey] = True
            while len(_FIRED) > _FIRED_MAX:
                _FIRED.pop(next(iter(_FIRED)))

            # Validate against actually available profiles.
            try:
                from helpers import subagents
                profiles = [a.name for a in subagents.get_agents_list()]
            except Exception:
                profiles = []
            if not profiles:
                _dbg('skip: no agent profiles available')
                return

            # One bounded Jev judgment. We are inside the live event loop
            # (async hook), so await directly - never asyncio.run here.
            model = str(cfg.get('jev_model') or 'jev-latest')
            client = jev_mod.get_client(
                key, model, float(cfg.get('jev_timeout') or 30))

            async def _query_fn(c, s, questions, m):
                return await jev_mod.query(c, s, questions, m)

            import asyncio
            try:
                result = await asyncio.wait_for(
                    _query_fn(client, {'message': message}, _questions(), model),
                    timeout=max(float(cfg.get('jev_timeout_s') or 2.0), 0.1))
            except Exception as exc:
                _dbg(f'jev query failed ({type(exc).__name__}: '
                     f'{str(exc)[:120]}); keeping current profile')
                return

            answers = (result or {}).get('answers') or {}
            tc = answers.get('task_class')
            if not isinstance(tc, dict):
                _dbg('jev returned malformed task_class; keeping current profile')
                return
            choice = tc.get('choice')
            try:
                conf = float(tc.get('confidence') or 0.0)
            except (TypeError, ValueError):
                conf = 0.0

            profile, reason = ds.decide(choice, conf, profiles, cfg)
            if not isinstance(state, dict):
                state = ds.new_state()

            now = time.time()
            cooldown = float(cfg.get('dynamic_switch_cooldown_seconds') or 30.0)
            consecutive = cfg.get('dynamic_switch_consecutive') or 2
            do_switch = ds.should_switch(
                state, choice, profile, conf,
                now=now, cooldown_seconds=cooldown, consecutive=consecutive)
            state = ds.record_match(state, choice, profile, conf)

            _dbg('decision: ' + reason
                 + ' streak=' + str(state.get('streak')))

            if do_switch and profile and profile != current_profile:
                _dbg('switching agent_profile=' + profile)
                from initialize import initialize_agent
                config = initialize_agent(
                    override_settings={'agent_profile': profile})
                context.config = config
                agent.config = config
                try:
                    from helpers.persist_chat import save_tmp_chat
                    save_tmp_chat(context)
                except Exception:
                    _dbg('save_tmp_chat failed:\n'
                         + traceback.format_exc()[:300])
                try:
                    from helpers.state_monitor_integration import (
                        mark_dirty_for_context)
                    mark_dirty_for_context(
                        context.id, reason='jev_dynamic_switch')
                except Exception:
                    _dbg('mark_dirty failed:\n' + traceback.format_exc()[:300])
                state['last_switch_time'] = now
                state['last_switch_profile'] = profile

            try:
                context.set_data(_STATE_KEY, state)
            except Exception:
                _dbg('state save failed:\n' + traceback.format_exc()[:300])
        except Exception:
            _dbg('ERROR ' + traceback.format_exc()[:300])
            return
