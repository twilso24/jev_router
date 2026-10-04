# jev_router local model tracker: track cold-start latency and context-window pressure
# for local model presets (e.g., lm_studio provider).
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class LocalModelState:
    """Per-provider state for local models."""
    provider: str
    last_success_ts: float = 0.0
    consecutive_failures: int = 0
    cold_start_count: int = 0
    total_cold_start_ms: int = 0
    last_cold_start_ms: int = 0
    # Context window pressure tracking
    context_pressure_events: int = 0
    last_context_pressure_ts: float = 0.0


# Process-local state by design; shared by every routing call in this framework run
_LOCAL_STATES: Dict[str, LocalModelState] = {}

# Providers considered "local" (cold-start capable)
LOCAL_PROVIDERS = {'lm_studio'}

# Cold-start threshold: if last success was more than this many seconds ago,
# the next call is considered a potential cold start.
COLD_START_IDLE_THRESHOLD_SECONDS = 300.0  # 5 minutes

# Context window pressure threshold: fraction of ctx_length used
CONTEXT_PRESSURE_THRESHOLD = 0.85


def is_local_provider(provider: str) -> bool:
    """True when the provider is a local model provider subject to cold starts."""
    return provider in LOCAL_PROVIDERS


def get_state(provider: str) -> LocalModelState:
    """Get or create state for a local provider."""
    if provider not in _LOCAL_STATES:
        _LOCAL_STATES[provider] = LocalModelState(provider=provider)
    return _LOCAL_STATES[provider]


def record_call_start(provider: str) -> Optional[float]:  # returns call_start_ts
    """Record the start of a call to a local provider.

    Returns the call start timestamp for later duration calculation.
    """
    if not is_local_provider(provider):
        return time.time()
    state = get_state(provider)
    now = time.time()
    return now


def record_call_outcome(provider: str, call_start_ts: float, ok: bool,
                         error: Optional[str] = None) -> None:
    """Record the outcome of a call to a local provider.

    Updates cold-start tracking and failure counts.
    """
    if not is_local_provider(provider):
        return
    state = get_state(provider)
    now = time.time()
    duration_ms = int((now - call_start_ts) * 1000)
    if ok:
        # Check if this was a cold start (long duration after idle period)
        if state.last_success_ts > 0 and (call_start_ts - state.last_success_ts) > COLD_START_IDLE_THRESHOLD_SECONDS:
            # This call followed an idle period; if duration is notably long,
            # attribute it as a cold start
            if duration_ms > 10000:  # >10s suggests model loading
                state.total_cold_start_ms += duration_ms
                state.last_cold_start_ms = duration_ms
        state.last_success_ts = now
        state.consecutive_failures = 0
    else:
        state.consecutive_failures += 1


def get_cold_start_stats(provider: str) -> dict:
    """Get cold-start statistics for a local provider."""
    if not is_local_provider(provider):
        return {}
    state = get_state(provider)
    avg_cold_start = 0
    if state.cold_start_count > 0:
        avg_cold_start = state.total_cold_start_ms // state.cold_start_count
    return {
        'provider': provider,
        'cold_start_count': state.cold_start_count,
        'avg_cold_start_ms': avg_cold_start,
        'last_cold_start_ms': state.last_cold_start_ms,
        'consecutive_failures': state.consecutive_failures,
        'idle_since_last_success': time.time() - state.last_success_ts if state.last_success_ts else None,
    }


def record_context_pressure(provider: str, ctx_length: int, estimated_tokens: int) -> bool:
    """Record context window pressure for a local provider.

    Returns True when pressure exceeds threshold (suggests delegation).
    """
    if not is_local_provider(provider) or ctx_length <= 0:
        return False
    state = get_state(provider)
    usage_ratio = estimated_tokens / ctx_length
    if usage_ratio >= CONTEXT_PRESSURE_THRESHOLD:
        state.context_pressure_events += 1
        state.last_context_pressure_ts = time.time()
        return True
    return False


def get_context_pressure_stats(provider: str) -> dict:
    """Get context window pressure statistics for a local provider."""
    if not is_local_provider(provider):
        return {}
    state = get_state(provider)
    return {
        'provider': provider,
        'context_pressure_events': state.context_pressure_events,
        'last_context_pressure_ts': state.last_context_pressure_ts,
    }


def reset_provider(provider: str) -> None:
    """Reset state for a provider (testing/admin)."""
    _LOCAL_STATES.pop(provider, None)


def reset_all() -> None:
    """Reset all local model state (testing/admin)."""
    _LOCAL_STATES.clear()
