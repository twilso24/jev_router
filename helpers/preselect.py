"""jev_router preselect: one-shot task-class judgment for new-chat profiles.

Pure logic lives here; the implicit-hook extension at
extensions/python/_functions/initialize/initialize_agent/start/ calls into it.
Spec decision #5B: pre-select the agent profile for NEW chats from a Jev
task-class judgment; explicit user choice always wins; never raises.
"""
import asyncio
from pathlib import Path

DEBUG_LOG = Path('/a0/tmp/jev_router_debug.log')

CONFIDENCE_THRESHOLD = 0.5
# Only classes that have a real subordinate profile.
TASK_TO_PROFILE = {
    'coding': 'developer',
    'research': 'researcher',
    'security': 'hacker',
    'testing': 'test-engineer',
}


def _dbg(msg: str) -> None:
    """Best-effort debug-log write; never raises."""
    try:
        from datetime import datetime as _dt
        stamp = _dt.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG, 'a') as f:
            f.write(stamp + ' [preselect] ' + msg + chr(10))
    except Exception:
        pass


def should_preselect(cfg: dict) -> bool:
    """True when auto pre-selection is enabled for new chats."""
    try:
        return (bool(cfg.get('enabled'))
                and bool(cfg.get('chat_preselect'))
                and str(cfg.get('delegation_mode') or '').lower() == 'auto')
    except Exception:
        return False


def parse_request(input: dict | None) -> tuple[str, str | None]:
    """Return (message, explicit_profile) from an api_message input body.

    Empty message means skip: existing chats and empty bodies are never
    pre-selected. An explicit agent_profile is reported so callers can
    refuse to override user intent.
    """
    if not isinstance(input, dict):
        return '', None
    explicit = input.get('agent_profile') or None
    if input.get('context_id'):
        return '', explicit
    return input.get('message', '') or '', explicit


def profile_for(task_class: str, profiles: list) -> str | None:
    """Map task_class to a profile that actually exists; else None."""
    target = TASK_TO_PROFILE.get(task_class)
    if target and target in (profiles or []):
        return target
    return None


def decide(task_class: str, confidence: float, profiles: list,
           cfg: dict) -> tuple[str | None, str]:
    """Decide a profile from task class + confidence. Returns (profile, reason)."""
    if task_class in ('chat', 'other'):
        return None, 'task_class=chat/other; no profile pre-selection'
    if confidence < CONFIDENCE_THRESHOLD:
        return None, (f'confidence={confidence:.2f} below threshold '
                      f'{CONFIDENCE_THRESHOLD:.2f}')
    profile = profile_for(task_class, profiles)
    if profile:
        return profile, (f'task_class={task_class} '
                         f'confidence={confidence:.2f} -> profile={profile}')
    return None, f'task_class={task_class} has no matching subordinate profile'


def _questions() -> dict:
    return {
        'task_class': {
            'type': 'choice',
            'instructions': ('Classify the primary nature of the first user '
                             'message of a new chat.'),
            'criteria': {
                'coding': 'Writing, debugging, refactoring or reviewing code',
                'research': 'Information gathering, analysis, summarizing sources',
                'security': 'Penetration testing, vulnerability analysis',
                'testing': 'Designing or writing tests, verification planning',
                'other': 'Anything else (chat, writing, ops, unclear)',
            },
        },
    }


async def run(message: str, cfg: dict, query_fn, client, model: str,
              profiles: list, budget: float) -> tuple[str | None, str]:
    """One Jev judgment for a new chat. Returns (profile, reason); never raises."""
    try:
        result = await asyncio.wait_for(
            query_fn(client, {'message': message}, _questions(), model),
            timeout=max(float(budget or 0), 0.1))
    except Exception as exc:
        return None, f'jev query failed ({type(exc).__name__}: {str(exc)[:120]}); keeping default profile'
    answers = (result or {}).get('answers') or {}
    tc = answers.get('task_class')
    if not isinstance(tc, dict):
        return None, 'jev returned malformed task_class; keeping default profile'
    choice = tc.get('choice')
    try:
        conf = float(tc.get('confidence') or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return decide(choice, conf, profiles, cfg)
