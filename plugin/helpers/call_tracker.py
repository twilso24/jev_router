# jev_router call tracker: wraps routed chat models to record real API-call
# outcomes (success/failure, duration, error text) and feed the circuit
# breaker with live evidence instead of build-time failures only.
import time

_MARK = '_jev_tracked'
_CB = '_jev_on_outcome'
_PROVIDER = '_jev_provider'
_PRESET = '_jev_preset'


def instrument(model, provider: str, preset: str, on_outcome) -> bool:
    """Wrap model.unified_call so each call reports an outcome tuple
    (provider, preset, ok, duration_s, error_or_None) via on_outcome.

    Idempotent per model instance: a second instrument() on the same object
    is a no-op returning False. Never raises; a broken on_outcome can never
    affect the model call itself.
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
        except Exception:
            pass
        return False
    try:
        orig = model.unified_call
        setattr(model, _CB, on_outcome)
        setattr(model, _PROVIDER, str(provider or ''))
        setattr(model, _PRESET, str(preset or ''))

        async def tracked(*args, **kwargs):
            start = time.time()
            try:
                resp = await orig(*args, **kwargs)
            except Exception as exc:
                _report(model, False, time.time() - start, str(exc))
                raise
            _report(model, True, time.time() - start, None)
            return resp

        model.unified_call = tracked
        setattr(model, _MARK, True)
        return True
    except Exception:
        return False


def _report(model, ok: bool, duration: float, error: str | None) -> None:
    try:
        cb = getattr(model, _CB, None)
        if callable(cb):
            cb(
                getattr(model, _PROVIDER, ''),
                getattr(model, _PRESET, ''),
                ok,
                duration,
                error,
            )
    except Exception:
        pass  # observability must never break the call


def is_wrapped(model) -> bool:
    return bool(getattr(model, _MARK, False))
