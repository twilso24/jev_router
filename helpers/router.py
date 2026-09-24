# jev_router core: orchestrate one routing decision. Never raises.
import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import circuit_breaker as breaker_mod, eligibility, fastpath, gate as gate_mod, mentions as mentions_mod, messages as messages_mod, policy as policy_mod, schedules as schedules_mod, signals as signals_mod, telemetry, tuning as tuning_mod
from .pool import PoolEntry
from .signals import Signals


@dataclass
class RouteResult:
    model: object | None   # None = keep the model already set by the framework
    reason: str
    fallback: bool = False
    advice: str | None = None  # delegation advice when gate recommends


def _digest(message: str) -> str:
    return hashlib.sha256(message.encode('utf-8', 'replace')).hexdigest()[:16]


def _record_safe(db_path: Path, decision, sig, digest,
                 session_id: str = '') -> str | None:
    """Best-effort telemetry write; returns error string or None."""
    try:
        conn = telemetry.init_db(db_path)
        try:
            telemetry.record_decision(
                conn, decision, sig, digest, session_id=session_id)
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
) -> RouteResult:
    digest = _digest(message or '')
    try:
        if not cfg.get('enabled', False):
            return RouteResult(None, 'jev_router disabled', False)

        pol = eligibility.load_policy(policy_path)
        band_orders = policy_mod.load_band_orders(policy_path)
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

        if fastpath.is_trivial(clean, attachments):
            pseudo = Signals(task_class='chat', task_class_confidence=1.0,
                             complexity=0.0, vision_needed=0.0,
                             delegate_worthy=0.0)
            decision = policy_mod.resolve(pseudo, pool_entries, band_orders=band_orders)
            decision.reason += sched_tag + mention_tag + breaker_tag + auto_tag
            if decision.entry is None:
                return RouteResult(
                    None, f'fast-path: {decision.reason}', True)
            try:
                model = model_factory(decision.entry)
            except Exception as exc:
                breaker_mod.record_fail(
                    decision.entry.provider, threshold=thr,
                    cooldown_hours=cd)
                return RouteResult(
                    None,
                    f'fast-path: model factory failed ({exc}); keeping model',
                    True)
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, pseudo, digest, session_id=session_id)
            return RouteResult(
                model, f'fast-path: trivial message; {decision.reason}', False)

        # Full path: Jev batch.
        sig = await signals_mod.judge(
            message=clean,
            attachments=attachments,
            query_fn=query_fn,
            client=client,
            model=jev_model,
            timeout_s=float(cfg.get('jev_timeout_s', 2.0)),
            pool_entries=pool_entries,
        )
        if sig is None:
            decision = policy_mod.Decision(
                None, 'unknown',
                'jev query failed; keeping active preset model')
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, None, digest, session_id=session_id)
            return RouteResult(None, decision.reason, True)

        decision = policy_mod.resolve(sig, pool_entries, band_orders=band_orders)
        decision.reason += sched_tag + mention_tag + breaker_tag + auto_tag
        advice = None
        gate_res = gate_mod.evaluate(sig, cfg)
        if gate_res.recommend:
            advice = (f'ROUTER: {gate_res.reason}. Consider delegating via '
                      f'call_subordinate(profile=\"{gate_res.profile}\").')

        if decision.entry is None:
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, sig, digest, session_id=session_id)
            return RouteResult(None, decision.reason, True, advice=advice)

        try:
            model = model_factory(decision.entry)
        except Exception as exc:
            breaker_mod.record_fail(
                decision.entry.provider, threshold=thr, cooldown_hours=cd)
            reason = f'model factory failed for {decision.entry.preset_name} ({exc}); keeping model'
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, sig, digest, session_id=session_id)
            return RouteResult(None, reason, True, advice=advice)

        if telemetry_path is not None:
            _record_safe(telemetry_path, decision, sig, digest, session_id=session_id)
        return RouteResult(model, decision.reason, False, advice=advice)

    except Exception as exc:  # never raise out of the router
        try:
            decision = policy_mod.Decision(
                None, 'unknown', f'router error: {exc}; keeping model')
            if telemetry_path is not None:
                _record_safe(telemetry_path, decision, None, digest, session_id=session_id)
        except Exception:
            pass
        return RouteResult(None, f'router error: {exc}; keeping model', True)
