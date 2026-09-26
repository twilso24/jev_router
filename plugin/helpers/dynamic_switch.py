"""jev_router dynamic_switch: mid-chat main-profile switching policy.

Pure logic lives here; the extension at
extensions/python/user_message_ui/_20_jev_dynamic_switch.py calls into it.

Policy (user-approved): evaluate every user message, switch only the main
chat profile, manual profile choice always wins, and switching is
conservative - confidence threshold, consecutive matching judgments, and a
same-profile cooldown. Never raises; any failure keeps the current profile.
"""
import math

DEFAULT_THRESHOLD = 0.7
DEFAULT_CONSECUTIVE = 2
DEFAULT_COOLDOWN_SECONDS = 30.0

# Only classes that have a real subordinate profile (mirrors preselect).
TASK_TO_PROFILE = {
    'coding': 'developer',
    'research': 'researcher',
    'security': 'hacker',
    'testing': 'test-engineer',
}


def _finite(value, fallback: float) -> float:
    """Coerce to a finite float; any malformed/NaN/inf value falls back."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(number) or math.isinf(number):
        return fallback
    return number


def should_dynamic_switch(cfg: dict) -> bool:
    """True when automatic dynamic switching is enabled and configured.

    A missing threshold defers to decide()'s default; an explicitly
    malformed threshold keeps the feature safely off.
    """
    try:
        if not (bool(cfg.get('enabled'))
                and bool(cfg.get('dynamic_switch_enabled'))
                and str(cfg.get('delegation_mode') or '').lower() == 'auto'):
            return False
        if cfg.get('dynamic_switch_threshold') is not None:
            float(cfg.get('dynamic_switch_threshold'))
        return True
    except (TypeError, ValueError):
        return False


def profile_for(task_class: str, profiles: list) -> str | None:
    """Map task_class to a profile that actually exists; else None."""
    target = TASK_TO_PROFILE.get(task_class)
    if target and target in (profiles or []):
        return target
    return None


def decide(task_class: str, confidence: float, profiles: list,
           cfg: dict) -> tuple[str | None, str]:
    """Decide a candidate profile from task class + confidence."""
    threshold = _finite(cfg.get('dynamic_switch_threshold', DEFAULT_THRESHOLD),
                        DEFAULT_THRESHOLD)
    conf = _finite(confidence, 0.0)
    if conf < threshold:
        return None, (f'confidence={conf:.2f} below dynamic threshold '
                      f'{threshold:.2f}')
    if task_class in ('chat', 'other'):
        return None, f'task_class={task_class}; no profile switch'
    profile = profile_for(task_class, profiles)
    if profile:
        return profile, (f'task_class={task_class} '
                         f'confidence={conf:.2f} -> profile={profile}')
    return None, f'task_class={task_class} has no matching profile'


def new_state() -> dict:
    """Fresh per-chat switching state (stored in context data)."""
    return {
        'streak': 0,
        'task_class': None,
        'profile': None,
        'last_switch_time': 0.0,
        'last_switch_profile': None,
    }


def record_match(state: dict, task_class: str, profile: str | None,
                 confidence: float) -> dict:
    """Record one Jev judgment into the state and return it.

    Same task class extends the streak; any new class (first observation or
    change) starts a fresh run at 1, so two consecutive judgments of a new
    class complete the approved policy before any switch.
    """
    prev = state.get('task_class')
    if prev == task_class:
        state['streak'] = int(state.get('streak') or 0) + 1
    else:
        state['streak'] = 1
    state['task_class'] = task_class
    state['profile'] = profile
    return state


def should_switch(state: dict, task_class: str, profile: str | None,
                  confidence: float, now: float | None = None,
                  cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
                  consecutive: int = DEFAULT_CONSECUTIVE) -> bool:
    """Whether this judgment completes the policy and may switch.

    The judgment calling this function is the newest observation; it counts
    toward the streak. `consecutive` is configurable via the
    dynamic_switch_consecutive tunable. The same-profile cooldown applies
    only when the target equals the profile we last switched to; a different
    target bypasses it.
    """
    if not profile:
        return False
    if state.get('task_class') != task_class:
        return False
    need = max(1, int(_finite(consecutive, DEFAULT_CONSECUTIVE)))
    streak = int(state.get('streak') or 0) + 1
    if streak < need:
        return False
    if (now is not None
            and state.get('last_switch_profile') == profile
            and (float(now) - float(state.get('last_switch_time') or 0.0))
            < float(_finite(cooldown_seconds, DEFAULT_COOLDOWN_SECONDS))):
        return False
    return True
