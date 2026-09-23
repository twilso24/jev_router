# jev_router circuit breaker: auto-exclude failing providers for health.
import time
from dataclasses import dataclass


@dataclass
class ProviderState:
    failures: int = 0
    trip_until: float = 0.0  # epoch ts while provider is excluded


# process-local by design; shared by every routing call in this framework run
_STATES: dict = {}
DEFAULT_THRESHOLD = 3
DEFAULT_COOLDOWN_HOURS = 1.0


def record_fail(provider: str, failures_to_add: int = 1,
                threshold: int | None = None,
                cooldown_hours: float | None = None) -> bool:
    """Count failures; trips (starts cooldown) at the threshold.

    Returns True when this call tripped the breaker.
    """
    s = _STATES.setdefault(provider, ProviderState())
    s.failures += failures_to_add
    lim = int(threshold) if threshold else DEFAULT_THRESHOLD
    if s.failures >= lim:
        ch = float(cooldown_hours) if cooldown_hours else DEFAULT_COOLDOWN_HOURS
        s.trip_until = time.time() + ch * 3600.0
        return True
    return False


def record_success(provider: str) -> None:
    """Healthy call: reset the failure counter and any active trip."""
    s = _STATES.get(provider)
    if s:
        s.failures = 0
        s.trip_until = 0.0


def excluded_providers(providers: list, now: float | None = None) -> list:
    """Providers currently tripped; fully-expired states are pruned."""
    now = time.time() if now is None else now
    out = [p for p in providers
           if (s := _STATES.get(p)) is not None and s.trip_until > now]
    expired = [k for k, s in _STATES.items()
               if s.trip_until and s.trip_until <= now]
    for k in expired:
        _STATES.pop(k, None)
    return out


def reset(provider: str | None = None) -> None:
    """Clear breaker state (one provider or all); for the WebUI panel."""
    if provider is None:
        _STATES.clear()
    else:
        _STATES.pop(provider, None)
