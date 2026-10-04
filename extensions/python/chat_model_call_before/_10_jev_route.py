"""jev_router: per-call model routing on the chat_model_call_before hook.

Fires once per chat LLM call with a mutable ``call_data`` dict. When the
plugin is enabled, replaces ``call_data["model"]`` with the routed model.
Any failure keeps the framework model (never raises). A digest cache
avoids re-running Jev for repeated loop iterations of one user message.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from helpers.extension import Extension

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DECISION_CACHE: Dict[str, tuple] = {}
DECISION_CACHE_MAX = 32
_LAST_WIRE_FP = None  # last pool fingerprint auto-wire synced against
DEBUG_LOG = Path('/a0/tmp/jev_router_debug.log')


def _dbg(msg: str) -> None:
    """Best-effort file log; makes hook execution observable."""
    try:
        from datetime import datetime as _dt
        stamp = _dt.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG, 'a') as f:
            f.write(stamp + ' ' + msg + chr(10))
    except Exception:
        pass


_dbg('module imported')


def _plugin_cfg(agent) -> dict:
    try:
        from helpers import plugins
        cfg = plugins.get_plugin_config("jev_router", agent) or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def _has_api_key(cfg: dict) -> bool:
    """True when a TypeSafe key is configured in settings or environment."""
    import os
    from usr.plugins.jev_router.helpers import jev as jev_mod
    return bool(jev_mod.resolve_api_key(cfg or {}, os.environ))


def _pool_entries():
    from usr.plugins.jev_router.helpers import pool as pool_mod
    presets = Path('/a0/usr/plugins/_model_config/presets.yaml')
    if not presets.exists():
        presets = PLUGIN_ROOT.parent / '_model_config' / 'presets.yaml'
    data = pool_mod.load_pool(presets)
    return [e for e in data.entries if e.role == 'chat']


def _make_model_factory(ext=None):
    from plugins._model_config.helpers import model_config
    import models

    def factory(entry):
        cfg = {
            'provider': entry.provider,
            'name': entry.model,
            'api_base': entry.api_base,
            'ctx_length': entry.ctx_length or 0,
            'vision': entry.vision,
        }
        mc = model_config.build_model_config(cfg, models.ModelType.CHAT)
        model = models.get_chat_model(
            mc.provider, mc.name, model_config=mc, **mc.build_kwargs())
        _instrument(ext, model, entry)
        return model

    return factory


def _instrument(ext, model, entry, fallback_from_preset: str | None = None,
                band: str | None = None):
    # Track real API-call outcomes: breaker feedback + tuning telemetry.
    try:
        from usr.plugins.jev_router.helpers import call_tracker

        def on_outcome(provider, preset, ok, duration, error, usage=None, fallback=None):
            _on_call_outcome(ext, provider, preset, ok, duration, error, fallback,
                             band=band)

        call_tracker.instrument(
            model, entry.provider, entry.preset_name, on_outcome,
            fallback_from_preset=fallback_from_preset)
    except Exception as exc:
        _dbg('instrument failed: ' + str(exc))


def _instrument_kept_model(ext, model, fallback_from_preset: str | None = None):
    # Keep-model fallback: the framework's cached model still serves the
    # turn, so its real outcomes must reach telemetry + breaker too.
    # Attribution comes from the framework model config; without a provider
    # we stay silent rather than guess. Never raises.
    try:
        if model is None:
            return
        from usr.plugins.jev_router.helpers import call_tracker
        if call_tracker.is_wrapped(model):
            # keeps first-wrap attribution (breaker is provider-scoped so
            # unaffected; telemetry preset label stays from the original wrap)
            return
        conf = getattr(model, 'a0_model_conf', None)
        provider = str(getattr(conf, 'provider', '') or '')
        if not provider:
            return
        name = str(getattr(conf, 'name', '') or provider)

        def on_outcome(prov, preset, ok, duration, error, usage=None, fallback=None):
            _on_call_outcome(ext, prov, preset, ok, duration, error, fallback)

        call_tracker.instrument(model, provider, name, on_outcome,
                                fallback_from_preset=fallback_from_preset)
    except Exception as exc:
        _dbg('kept-model instrument failed: ' + str(exc))


def _on_call_outcome(ext, provider, preset, ok, duration, error,
                     fallback_from_preset: str | None = None,
                     band: str | None = None):
    # breaker feedback from real outcomes (config thresholds)
    try:
        from usr.plugins.jev_router.helpers import circuit_breaker as cb_mod
        cfg = ext._jev_config() if ext is not None else {}
        if ok:
            cb_mod.record_success(provider)
        else:
            threshold = cfg.get('breaker_threshold')
            cooldown = cfg.get('breaker_cooldown_hours')
            tripped = cb_mod.record_fail(
                provider,
                threshold=int(threshold) if threshold else None,
                cooldown_hours=float(cooldown) if cooldown else None,
            )
            _dbg('provider fail provider=' + str(provider)
                 + ' tripped=' + str(tripped)
                 + ' err=' + str(error)[:80])
    except Exception:
        pass
    # persist the outcome for tuning suggestions
    try:
        if ext is not None:
            from usr.plugins.jev_router.helpers import telemetry as tel_mod
            conn = tel_mod.init_db(ext._telemetry_path())
            tel_mod.record_call(conn, provider, preset, ok, duration, error,
                                fallback_from_preset=fallback_from_preset,
                                band=band)
            conn.close()
    except Exception:
        pass


async def _jev_query_fn(client, state, questions, model, timeout_s=2.0):
    from usr.plugins.jev_router.helpers import jev
    return await jev.query(client, state, questions, model, timeout_s=timeout_s)


class JevRouteChatCall(Extension):
    """Route the chat model per jev_router policy; fall back silently."""

    async def execute(self, call_data: Dict[str, Any] = None, **kwargs: Any) -> None:
        if call_data is None:
            return
        _dbg('execute entry')
        try:
            cfg = _plugin_cfg(self.agent)
            _dbg(f'cfg keys={sorted(cfg.keys())}')
            from usr.plugins.jev_router.helpers.gate import routing_allowed_agent
            if not routing_allowed_agent(self.agent, cfg):
                _dbg('early return: routing disabled (global or per-chat)')
                return  # global off OR per-chat off → no routing
            if not _has_api_key(cfg):
                _dbg('early return: no TypeSafe API key configured; keeping framework model')
                return  # never build a keyless Jev client; skip routing entirely

            from usr.plugins.jev_router.helpers import messages as msg_mod
            from usr.plugins.jev_router.helpers import mentions as mentions_mod
            from usr.plugins.jev_router.helpers import pool as pool_mod
            from usr.plugins.jev_router.helpers import router as router_mod

            msgs = call_data.get('messages') or []
            text = msg_mod.extract_user_text(msg_mod.last_human_text(msgs))
            import hashlib
            digest = hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:16]

            entries = _pool_entries()
            fingerprint = pool_mod.pool_fingerprint(entries)
            # Auto-wire: re-sync band orders with the live pool on every
            # chat-model call. The sync itself only writes on real changes
            # (adds/prunes), retries are cheap, and running every turn heals
            # hand-edited or externally modified band orders that a pool
            # fingerprint guard would miss. Sync failures never affect
            # routing.
            try:
                from usr.plugins.jev_router.helpers import auto_wire
                auto_wire.sync_band_orders(
                    PLUGIN_ROOT / 'routing-policy.yaml',
                    [e.preset_name for e in entries],
                    PLUGIN_ROOT / 'wire-state.json')
            except Exception as exc:
                _dbg('auto-wire sync failed: ' + str(exc))
            global _LAST_WIRE_FP
            _LAST_WIRE_FP = fingerprint
            _ctx = getattr(self, 'agent', None)
            session_id = str(
                getattr(getattr(_ctx, 'context', None), 'id', '')
                or getattr(_ctx, 'context_id', '') or '')
            sess_sig = hashlib.sha256(','.join(
                mentions_mod.session_excludes(session_id)).encode(
                'utf-8', 'replace')).hexdigest()[:8]
            agent_profile = str(
                getattr(getattr(_ctx, 'config', None), 'profile', '') or '')
            cache_key = f'{digest}:{fingerprint}:{sess_sig}:{agent_profile}'
            cached = DECISION_CACHE.get(cache_key)
            if cached is not None:
                model, reason = cached
                _dbg(f'cache hit key={cache_key} model={model is not None}')
                if model is not None:
                    call_data['model'] = model
                return

            advice_pending = {'text': None}

            # Read observability settings from plugin config
            obs_fallback = cfg.get('obs_fallback_enabled', True)
            obs_session = cfg.get('obs_session_enabled', True)
            obs_shadow = cfg.get('obs_shadow_enabled', True)

            attachments = ['image'] if msg_mod.has_image_parts(msgs) else []
            result = await router_mod.route(
                cfg=cfg,
                entries=entries,
                policy_path=PLUGIN_ROOT / 'routing-policy.yaml',
                message=text,
                attachments=attachments,
                query_fn=_jev_query_fn,
                client=self._jev_client(),
                jev_model=self._jev_model(),
                model_factory=_make_model_factory(self),
                telemetry_path=self._telemetry_path(),
                session_id=session_id,
                agent_profile=agent_profile,
                obs_fallback=obs_fallback,
                obs_session=obs_session,
                obs_shadow=obs_shadow,
            )

            advice_pending['text'] = getattr(result, 'advice', None)
            _dbg(f'routed fallback={result.fallback} reason={result.reason[:80]}')
            fallback_preset = getattr(result, 'intended_preset', None)
            if result.model is not None:
                call_data['model'] = result.model
                # Cache successful judgments only: fallbacks (Jev failure,
                # empty pool, compromise) must retry on the next message.
                if len(DECISION_CACHE) >= DECISION_CACHE_MAX:
                    DECISION_CACHE.pop(next(iter(DECISION_CACHE)))
                DECISION_CACHE[cache_key] = (result.model, result.reason)
                # Refresh attribution on the routed model when the router
                # exposes the entry (the model factory already instruments
                # models it creates; this covers externally provided models).
                _entry = getattr(result, 'entry', None)
                if _entry is not None:
                    _instrument(self, result.model, _entry,
                                fallback_from_preset=fallback_preset,
                                band=getattr(result, 'band', None))
            else:
                # keep-model fallback: still track the framework model's
                # real outcomes (telemetry + breaker feedback)
                _instrument_kept_model(self, call_data.get('model'),
                                      fallback_from_preset=fallback_preset)

            if advice_pending['text']:
                try:
                    from python.helpers.message import SystemMessage
                    msgs = call_data.get('messages')
                    if isinstance(msgs, list):
                        msgs.append(SystemMessage(content=advice_pending['text']))
                except Exception:
                    pass  # advisory only; never break routing
        except Exception:
            import traceback
            _dbg('EXECUTE ERROR: ' + traceback.format_exc())
            # never break the LLM call; keep framework model
            return

    def _jev_config(self) -> dict:
        try:
            from helpers import plugins
            cfg = plugins.get_plugin_config('jev_router', self.agent) or {}
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
        return {}

    def _jev_model(self) -> str:
        return str(self._jev_config().get('jev_model') or 'jev-latest')

    def _jev_client(self):
        import os
        from usr.plugins.jev_router.helpers import jev as jev_mod
        cfg = self._jev_config()
        key = jev_mod.resolve_api_key(cfg, os.environ)
        timeout = float(cfg.get('jev_timeout') or 30)
        return jev_mod.get_client(key, self._jev_model(), timeout)

    def _telemetry_path(self) -> Path:
        try:
            from helpers import files
            base = Path(files.get_abs_path('tmp'))
        except Exception:
            base = PLUGIN_ROOT
        base.mkdir(parents=True, exist_ok=True)
        return base / 'jev_router_telemetry.db'
