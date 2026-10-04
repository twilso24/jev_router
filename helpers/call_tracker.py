# jev_router call tracker: wraps routed chat models to record real API-call
# outcomes (success/failure, duration, error text) and feed the circuit
# breaker with live evidence instead of build-time failures only.
import asyncio
import time

_MARK = '_jev_tracked'
_CB = '_jev_on_outcome'
_PROVIDER = '_jev_provider'
_PRESET = '_jev_preset'
_FALLBACK = '_jev_fallback'
_COLD_START = '_jev_cold_start'
_COLD_START_MS = '_jev_cold_start_ms'
_CONTEXT_PRESSURE = '_jev_context_pressure'
_CTX_LENGTH = '_jev_ctx_length'
_ESTIMATED_TOKENS = '_jev_estimated_tokens'
# framework entry points that reach the provider: the chat turn path uses
# unified_turn, legacy/utility paths use unified_call
_METHODS = ('unified_call', 'unified_turn')


def instrument(model, provider: str, preset: str, on_outcome,
                fallback_from_preset: str | None = None,
                cold_start: bool = False,
                cold_start_ms: int | None = None,
                context_pressure: bool = False,
                ctx_length: int | None = None,
                estimated_tokens: int | None = None) -> bool:
    """Wrap the model's unified entry points so each call reports an outcome
    tuple (provider, preset, ok, duration_s, error_or_None) via on_outcome.

    When the callback declares nine positional params (usage, fallback, cold_start,
    cold_start_ms, context_pressure, ctx_length, estimated_tokens are appended),
    it also receives the normalized usage dict extracted from a successful
    response and the preset this call fell back from. Callbacks with fewer
    params or varargs keep the legacy five-tuple.

    Idempotent per model instance: a second instrument() on the same object
    refreshes attribution/callback and never double-wraps. Wrapping both
    entry points stays safe when one delegates to the other: the in-flight
    guard reports exactly one outcome per outermost call. Never raises; a
    broken on_outcome can never affect the model call itself.
    """
    if model is None:
        return False
    if getattr(model, _MARK, False):
        # already wrapped (e.g. cached model): refresh attribution/callback
        # only, never double-wrap the call itself.
        try:
            setattr(model, _CB, on_outcome)
            setattr(model, _PROVIDER, str(provider or ''))
            setattr(model, _PRESET, str(preset or ''))
            setattr(model, _FALLBACK,
                    str(fallback_from_preset) if fallback_from_preset else None)
            setattr(model, _COLD_START, cold_start)
            setattr(model, _COLD_START_MS, cold_start_ms)
            setattr(model, _CONTEXT_PRESSURE, context_pressure)
            setattr(model, _CTX_LENGTH, ctx_length)
            setattr(model, _ESTIMATED_TOKENS, estimated_tokens)
        except Exception:
            pass
        return False
    try:
        # per-model in-flight set keyed by asyncio Task: same-task delegation
        # (unified_call -> unified_turn) reports once, while concurrent calls
        # on the same (cached) instance each report their own outcome
        inflight: set = set()
        for name in _METHODS:
            _wrap_method(model, name, inflight)
        setattr(model, _CB, on_outcome)
        setattr(model, _PROVIDER, str(provider or ''))
        setattr(model, _PRESET, str(preset or ''))
        setattr(model, _FALLBACK,
                str(fallback_from_preset) if fallback_from_preset else None)
        setattr(model, _COLD_START, cold_start)
        setattr(model, _COLD_START_MS, cold_start_ms)
        setattr(model, _CONTEXT_PRESSURE, context_pressure)
        setattr(model, _CTX_LENGTH, ctx_length)
        setattr(model, _ESTIMATED_TOKENS, estimated_tokens)
        setattr(model, _MARK, True)
        return True
    except Exception:
        return False


def _wrap_method(model, name: str, inflight: set) -> None:
    orig = getattr(model, name, None)
    if not callable(orig):
        return

    async def tracked(*args, **kwargs):
        # an outer tracked method in this task already owns the call (e.g.
        # unified_call delegating to unified_turn): pass through silently
        task = asyncio.current_task()
        # outside a running loop (task is None) the guard cannot correlate
        # entries, so every entry point reports: conservative, never drops
        if task is not None and task in inflight:
            return await orig(*args, **kwargs)
        start = time.time()
        if task is not None:
            inflight.add(task)
        # CancelledError bypasses `except Exception` by design: a cancelled
        # call is not a provider failure; finally still clears the guard
        try:
            resp = await orig(*args, **kwargs)
        except Exception as exc:
            _report(model, False, time.time() - start, str(exc), None)
            raise
        finally:
            if task is not None:
                inflight.discard(task)
        _report(model, True, time.time() - start, None, resp)
        return resp

    setattr(model, name, tracked)


def _report(model, ok: bool, duration: float, error: str | None,
            resp=None) -> None:
    try:
        cb = getattr(model, _CB, None)
        if not callable(cb):
            return
        args = [
            getattr(model, _PROVIDER, ''),
            getattr(model, _PRESET, ''),
            ok,
            duration,
            error,
        ]
        if _accepts_wide(cb):
            usage = {
                'input_tokens': None, 'output_tokens': None,
                'cost_usd': None,
            }
            if ok and resp is not None:
                try:
                    from .telemetry import usage_fields
                    usage = usage_fields(resp)
                except Exception:
                    pass
            args.extend([
                usage,
                getattr(model, _FALLBACK, None),
                getattr(model, _COLD_START, False),
                getattr(model, _COLD_START_MS, None),
                getattr(model, _CONTEXT_PRESSURE, False),
                getattr(model, _CTX_LENGTH, None),
                getattr(model, _ESTIMATED_TOKENS, None),
            ])
        cb(*args)
    except Exception:
        pass  # observability must never break the call


def _accepts_wide(cb) -> bool:
    """True when cb declares nine positional params (usage, fallback, cold_start,
    cold_start_ms, context_pressure, ctx_length, estimated_tokens)."""
    try:
        import inspect
        params = inspect.signature(cb).parameters
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL
               for p in params.values()):
            return False
        positional = [p for p in params.values()
                      if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                    inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        return len(positional) >= 9
    except Exception:
        return False


def is_wrapped(model) -> bool:
    return bool(getattr(model, _MARK, False))