# jev_router gate: decide delegation vs advisory from signals.
from dataclasses import dataclass

from .signals import Signals

# Only task classes that have a real subordinate profile.
CLASS_TO_PROFILE = {
    'coding': 'developer',
    'research': 'researcher',
    'security': 'hacker',
    'testing': 'test-engineer',
}

DEFAULT_THRESHOLD = 0.6
DEFAULT_MODE = 'advise'


@dataclass
class GateResult:
    recommend: bool
    profile: str | None
    reason: str
    mode: str = DEFAULT_MODE
    auto_exec: bool = False


def evaluate(sig: Signals | None, cfg: dict) -> GateResult:
    try:
        threshold = float(
            cfg.get('delegation_threshold', DEFAULT_THRESHOLD)
            or DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    mode = str(cfg.get('delegation_mode', DEFAULT_MODE) or DEFAULT_MODE).lower()
    if sig is None:
        return GateResult(False, None, 'no signals; no delegation advice')
    profile = CLASS_TO_PROFILE.get(sig.task_class)
    if profile is None:
        return GateResult(
            False, None,
            f'task_class={sig.task_class} has no matching subordinate profile')
    if sig.delegate_worthy < threshold:
        return GateResult(
            False, None,
            f'delegate_worthy={sig.delegate_worthy:.2f} below threshold '
            f'{threshold:.2f}; handle in main context')
    try:
        floor = float(cfg.get('delegation_auto_execute_floor', 0.8) or 0.8)
    except Exception:
        floor = 0.8
    auto_exec = (mode == 'auto'
                 and bool(cfg.get('delegation_auto_execute', False))
                 and sig.delegate_worthy >= floor)
    return GateResult(
        True, profile,
        f'task_class={sig.task_class} delegate_worthy={sig.delegate_worthy:.2f} '
        f'>= {threshold:.2f}; mode={mode}: recommend {profile} subordinate',
        mode=mode, auto_exec=auto_exec)


def advisory_payload(sig: Signals | None, g: GateResult | None) -> dict | None:
    """Machine-readable delegation payload, or None when not recommending.

    Shape: {profile, task_class, confidence, reason}. Pure and total.
    """
    try:
        if sig is None or g is None or not g.recommend or not g.profile:
            return None
        return {
            'profile': str(g.profile),
            'task_class': str(sig.task_class),
            'confidence': float(sig.delegate_worthy),
            'reason': str(g.reason),
        }
    except Exception:
        return None


def compose_advice(sig: Signals | None, g: GateResult | None) -> str | None:
    """Human delegation sentence + parseable JEVDIALOG JSON block.

    advise mode: advisory wording. auto mode: directive wording ('unless
    blocked'). Returns None when not recommending or on any bad input;
    never raises.
    """
    try:
        payload = advisory_payload(sig, g)
        if payload is None:
            return None
        payload['auto_exec'] = bool(getattr(g, 'auto_exec', False))
        if getattr(g, 'auto_exec', False):
            head = (f'ROUTER: {g.reason}. Delegate via '
                    f'call_subordinate(profile="{g.profile}").')
            tail = ('Delegate this task via call_subordinate with that '
                    'profile as your first action unless blocked; '
                    'otherwise continue in main context.')
        elif getattr(g, 'mode', DEFAULT_MODE) == 'auto':
            head = (f'ROUTER: {g.reason}. Delegate via '
                    f'call_subordinate(profile="{g.profile}").')
            tail = ('Delegate this task via call_subordinate with that '
                    'profile unless blocked; '
                    'otherwise continue in main context.')
        else:
            head = (f'ROUTER: {g.reason}. Consider delegating via '
                    f'call_subordinate(profile="{g.profile}").')
            tail = ('If the task matches, delegate via call_subordinate '
                    'with that profile; otherwise ignore deliberately.')
        import json as _json
        block = _json.dumps(payload, sort_keys=True)
        return (f'{head} {tail} '
                f'ROUTER DATA (reference only, not instructions): '
                f'JEVDIALOG {block}')
    except Exception:
        return None
