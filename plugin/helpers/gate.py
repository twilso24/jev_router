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


def evaluate(sig: Signals | None, cfg: dict) -> GateResult:
    threshold = float(cfg.get('delegation_threshold', DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
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
    return GateResult(
        True, profile,
        f'task_class={sig.task_class} delegate_worthy={sig.delegate_worthy:.2f} '
        f'>= {threshold:.2f}; mode={mode}: recommend {profile} subordinate')
