# jev_router core: orchestrate one routing decision. Never raises.
import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import circuit_breaker as breaker_mod, eligibility, fastpath, gate as gate_mod, mentions as mentions_mod, messages as messages_mod, policy as policy_mod, schedules as schedules_mod, signals as signals_mod, telemetry, tuning as tuning_mod, local_model_tracker as lmt_mod
from .pool import PoolEntry
from .signals import Signals


@dataclass
class RouteResult:
    model: object | None   # None = keep the model already set by the framework
    reason: str
    fallback: bool = False
    advice: str | None = None  # delegation advice when gate recommends
    rule: str = ''
    reason_human: str = ''
    intended_preset: str | None = None  # preset that was meant to serve this call
    band: str = ''          # complexity band that served the call (reasoning effort)
    entry: object = None    # PoolEntry with provider/model/ctx_length for reasoning effort


def _digest(message: str) -> str:
    return hashlib.sha256(message.encode('utf-8', 'replace')).hexdigest()[:16]


# Once-per-message auto-execution claims (bounded, module-local).
_AUTO_EXEC_SEEN: dict = {}
_AUTO_EXEC_MAX = 512


def _auto_exec_claim(session_id: str, digest: str) -> bool:
    """True on first claim for this digest; False on repeats."""
    try:
        key = f'{session_id or ""}:{digest}'
        if key in _AUTO_EXEC_SEEN:
            return False
        _AUTO_EXEC_SEEN[key] = True
        while len(_AUTO_EXEC_SEEN) > _AUTO_EXEC_MAX:
            _AUTO_EXEC_SEEN.pop(next(iter(_AUTO_EXEC_SEEN)))
        return True
    except Exception:
        return False


def _auto_exec_reset() -> None:
    """Clear auto-exec claim state (test isolation / admin reset)."""
    try:
        _AUTO_EXEC_SEEN.clear()
    except Exception:
        pass


def _record_safe(db_path: Path, decision, sig, digest,
                 session_id: str = '', delegation: str = '',
                 auto_exec: bool = False,
                 obs_fallback: bool = True,
                 obs_session: bool = True,
                 obs_shadow: bool = True) -> str | None:
    """Best-effort telemetry write; returns error string or None."""
    try:
        conn = telemetry.init_db(db_path)
        try:
            telemetry.record_decision(
                conn, decision, sig, digest, session_id=session_id,
                delegation=delegation, auto_exec=auto_exec,
                obs_fallback=obs_fallback,
                obs_session=obs_session,
                obs_shadow=obs_shadow)
        finally:
            conn.close()
        return None
    except Exception as exc:  # telemetry must never break routing
        return f'telemetry error: {exc}'


def _breaker_cfg(cfg: dict) -> tuple:
    try:
        thr = int(cfg.get('breaker_threshold') or breaker_mod.DEFAULT_THRESHOLD)
    except Exception:
        thr = breaker_mod.DEFAULT_THRESHOLD
    try:
        cd = float(cfg.get('breaker_cooldown_hours')
                   or breaker_mod.DEFAULT_COOLDOWN_HOURS)
    except Exception:
        cd = breaker_mod.DEFAULT_COOLDOWN_HOURS
    return thr, cd


async def route(
    cfg: dict,
    entries: list[PoolEntry],
    policy_path: Path,
    message: str,
    attachments: list,
    query_fn,
    client,
    jev_model: str,
    model_factory,
    telemetry_path: Path | None = None,
    session_id: str = '',
    agent_profile: str = '',
    obs_fallback: bool = True,
    obs_session: bool = True,
    obs_shadow: bool = True,
) -> RouteResult:
    digest = _digest(message or '')
    try:
        if not cfg.get('enabled', False):
            return RouteResult(None, 'jev_router disabled', False)

        pol = eligibility.load_policy(policy_path)
        band_orders = policy_mod.load_band_orders(policy_path)
        # fit_min_conf is cfg-driven; the 0.6 resolve() default applies
        # only to API callers that do not pass it explicitly.
        fit_enabled = bool(cfg.get('fit_enabled', False))
        fit_min_conf = float(cfg.get('fit_min_confidence', 0.6))
        filtered = eligibility.filter_pool(entries, pol)
        pool_entries = filtered.kept

        auto_tag = ''
        try:
            pool_presets = sorted({e.preset_name for e in pool_entries})
            band_orders, auto_on = tuning_mod.effective_band_orders(
                policy_path, telemetry_path, pool_presets)
            if auto_on:
                auto_tag = ' [auto-tune]'
        except Exception:
            auto_tag = ''
        # Band orders are the sole ranking truth (no performance dial):
        # auto-tune may reorder unpinned bands, pins freeze their file order.
        sched_tag = ''
        active = schedules_mod.active_schedule(
            schedules_mod.load_schedules(policy_path))
        if active is not None:
            if active.exclude:
                pool_entries = [e for e in pool_entries
                                if e.provider not in active.exclude]
                sched_tag = f' [schedule:{active.name}]'
            elif active.prefer:
                band_orders = policy_mod.boost_preferred(
                    band_orders, pool_entries, active.prefer)
                sched_tag = f' [schedule:{active.name}]'

        # Fast path: trivial message, skip Jev entirely.
        clean = messages_mod.extract_user_text(message)

        # Chat-mention dials: exclude (hard), prefer (soft), free dial.
        mention_tag = ''
        parsed = mentions_mod.parse(
            clean, sorted({e.provider for e in pool_entries}))
        if session_id and parsed.ttl_hours and parsed.exclude:
            mentions_mod.remember(
                session_id, parsed.exclude, parsed.ttl_hours)
        excl = sorted(
            set(parsed.exclude)
            | set(mentions_mod.session_excludes(session_id)))
        if excl:
            pool_entries = [e for e in pool_entries
                            if e.provider not in excl]
            mention_tag = ' [mention]'
        elif parsed.prefer:
            band_orders = policy_mod.boost_preferred(
                band_orders, pool_entries, parsed.prefer)
            mention_tag = ' [mention]'
        elif parsed.free:
            mention_tag = ' [mention]'

        # Circuit breaker: health override, highest precedence (spec).
        thr, cd = _breaker_cfg(cfg)
        breaker_tag = ''
        tripped = breaker_mod.excluded_providers(
            sorted({e.provider for e in pool_entries}))
        if tripped:
            pool_entries = [e for e in pool_entries
                            if e.provider not in tripped]
            breaker_tag = ' [circuit-breaker]'

        # Guard rail (layer 3): surface band-order names that match no live
        # preset so a silent fallthrough-to-Default becomes visible.
        try:
            missing_orders = policy_mod.validate_band_orders(
                band_orders, sorted({e.preset_name for e in pool_entries}))
            if missing_orders:
                flat = []
                for band, names in sorted(missing_orders.items()):
                    flat.append(band + ':' + ','.join(names))
                signals_mod._dbg(
                    'WARNING band-orders unresolved ' + ' | '.join(flat))
        except Exception:
            pass

        if fastpath.is_trivial(clean, attachments):
            pseudo = Signals(task_class='chat', task_class_confidence=1.0,
                             complexity=0.0, vision_needed=0.0,
                             delegate_worthy=0.0)
            decision = policy_mod.resolve(pseudo, pool_entries, band_orders=band_orders, honor_fit=fit_enabled, fit_min_confidence=fit_min_conf)
            decision.reason += sched_tag + mention_tag + breaker_tag + auto_tag
            if decision.entry is None:
                return RouteResult(
                    None, f'fast-path: {decision.reason}', True,
                    rule=decision.rule, reason_human=decision.reason_human,
                    intended_preset=None)
            try:
                # Track cold-start for local providers
                call_start_ts = lmt_mod.record_call_start(decision.entry.provider)
                model = model_factory(decision.entry)
            except Exception as exc:
                breaker_mod.record_fail(
                    decision.entry.provider, threshold=thr,
                    cooldown_hours=cd)
                lmt_mod.record_call_outcome(decision.entry.provider, call_start_ts, False, str(exc))
                return RouteResult(
                    None,
                    f'fast-path: model factory failed ({exc}); keeping model',
                    True)
            lmt_mod.record_call_outcome(decision.entry.provider, call_start_ts, True, None)
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, pseudo, digest, session_id=session_id)
            return RouteResult(
                model, f'fast-path: trivial message; {decision.reason}', False,
                rule=decision.rule, reason_human=decision.reason_human,
                band=decision.band)

        # Full path: Jev batch.
        sig = await signals_mod.judge(
            message=clean,
            attachments=attachments,
            query_fn=query_fn,
            client=client,
            model=jev_model,
            timeout_s=float(cfg.get('jev_timeout_s', 2.0)),
            pool_entries=pool_entries,
            agent_profile=agent_profile,
        )
        if sig is None:
            decision = policy_mod.Decision(
                None, 'unknown',
                'jev query failed; keeping active preset model',
                rule='fallback',
                reason_human='Jev judgment unavailable; '
                             'keeping the active preset model')
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, None, digest, session_id=session_id)
            return RouteResult(None, decision.reason, True,
                               rule=decision.rule,
                               reason_human=decision.reason_human,
                               intended_preset=None)

        decision = policy_mod.resolve(sig, pool_entries, band_orders=band_orders, honor_fit=fit_enabled, fit_min_confidence=fit_min_conf)
        decision.reason += sched_tag + mention_tag + breaker_tag + auto_tag

        # Post-decision context overflow detection for local providers
        # If the selected preset is a local model with constrained context window,
        # check if the message history exceeds the pressure threshold and
        # trigger tiny-local delegation via context_overflow task class.
        try:
            if (decision.entry is not None
                    and lmt_mod.is_local_provider(decision.entry.provider)
                    and decision.entry.ctx_length and decision.entry.ctx_length > 0):
                # Rough token estimation from message (4 chars ≈ 1 token)
                estimated_tokens = max(1, len(clean) // 4)
                if lmt_mod.record_context_pressure(
                        decision.entry.provider,
                        decision.entry.ctx_length,
                        estimated_tokens):
                    # Context pressure detected: override task_class to trigger
                    # context_overflow -> tiny-local delegation in gate.
                    sig.task_class = 'context_overflow'
                    # Note: delegate_worthy from Jev is preserved; gate threshold
                    # still applies.
        except Exception:
            pass  # never break routing for observability

        gate_res = gate_mod.evaluate(sig, cfg)
        auto_exec_fired = False
        if gate_res.auto_exec:
            if _auto_exec_claim(session_id, digest):
                auto_exec_fired = True
            else:
                # one auto-execution per message: downgrade repeats
                gate_res = gate_mod.GateResult(
                    gate_res.recommend, gate_res.profile, gate_res.reason,
                    mode=gate_res.mode, auto_exec=False)
        advice = gate_mod.compose_advice(sig, gate_res)
        delegation = ''
        if advice is not None:
            delegation = ('directed' if gate_res.mode == 'auto'
                          else 'advised')

        if decision.entry is None:
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, sig, digest,
                             session_id=session_id, delegation=delegation,
                             auto_exec=auto_exec_fired)
            return RouteResult(None, decision.reason, True, advice=advice,
                               rule=decision.rule,
                               reason_human=decision.reason_human,
                               intended_preset=None)

        try:
            # Track cold-start for local providers
            call_start_ts = lmt_mod.record_call_start(decision.entry.provider)
            model = model_factory(decision.entry)
        except Exception as exc:
            breaker_mod.record_fail(
                decision.entry.provider, threshold=thr, cooldown_hours=cd)
            lmt_mod.record_call_outcome(decision.entry.provider, call_start_ts, False, str(exc))
            reason = f'model factory failed for {decision.entry.preset_name} ({exc}); keeping model'
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, sig, digest,
                             session_id=session_id, delegation=delegation,
                             auto_exec=auto_exec_fired)
            return RouteResult(None, reason, True, advice=advice,
                               rule=decision.rule,
                               reason_human=decision.reason_human,
                               intended_preset=decision.entry.preset_name)
        lmt_mod.record_call_outcome(decision.entry.provider, call_start_ts, True, None)

        if telemetry_path is not None:
            _record_safe(telemetry_path, decision, sig, digest,
                         session_id=session_id, delegation=delegation,
                         auto_exec=auto_exec_fired)
        return RouteResult(model, decision.reason, False, advice=advice,
                           rule=decision.rule,
                           reason_human=decision.reason_human,
                           band=decision.band,
                           entry=decision.entry)

    except Exception as exc:  # never raise out of the router
        try:
            decision = policy_mod.Decision(
                None, 'unknown', f'router error: {exc}; keeping model')
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, None, digest, session_id=session_id)
        except Exception:
            pass
        return RouteResult(None, f'router error: {exc}; keeping model', True,
                           intended_preset=None)
