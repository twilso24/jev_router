import asyncio
import time
from dataclasses import dataclass
from pathlib import Path


DEBUG_LOG = Path('/a0/tmp/jev_router_debug.log')


def _dbg(msg: str) -> None:
    """Best-effort debug-log write; never raises."""
    try:
        from datetime import datetime as _dt
        stamp = _dt.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG, 'a') as f:
            f.write(stamp + ' [signals] ' + msg + chr(10))
    except Exception:
        pass


@dataclass
class Signals:
    task_class: str
    task_class_confidence: float
    complexity: float          # 0..2 score
    vision_needed: float       # noul 0..1
    delegate_worthy: float     # noul 0..1
    preset_fit: str | None = None        # Jev's best-fit preset, if asked
    preset_fit_confidence: float = 0.0   # 0.0 when absent/invalid
    profile_match: float | None = None   # noul: active profile fits the task


TASK_CLASSES = {
    'coding': 'Writing, debugging, refactoring or reviewing code and software architecture',
    'research': 'Information gathering, web research, data analysis, summarizing sources',
    'security': 'Penetration testing, vulnerability analysis, security auditing',
    'testing': 'Designing or writing tests, coverage analysis, verification planning',
    'writing': 'Documents, reports, emails, presentations, copywriting, summarization',
    'ops': 'DevOps, deployment, configuration, infrastructure, system administration',
    'chat': 'Casual conversation, greetings, simple questions with no task',
    'other': 'Anything not matching the above categories',
}


def build_questions(pool_entries: list | None = None,
                    agent_profile: str = '') -> dict:
    questions = {
        'task_class': {
            'type': 'choice',
            'instructions': 'Classify the primary nature of the user message.',
            'criteria': dict(TASK_CLASSES),
        },
        'complexity': {
            'type': 'score',
            'instructions': 'How complex is the task in the message?',
            'criteria': [
                'Trivial: greeting, single-fact question, no multi-step work',
                'Medium: needs a few steps or moderate domain knowledge',
                'Hard: multi-step, multi-file, architectural or high-stakes work',
            ],
        },
        'vision_needed': {
            'type': 'noul',
            'instructions': 'Does the task require understanding images, screenshots or other visual content?',
        },
        'delegate_worthy': {
            'type': 'noul',
            'instructions': 'Would a dedicated specialist agent with a fresh context handle this task better than a generalist continuing this chat?',
        },
    }
    # preset_fit: a choice needs alternatives, so only with 2+ presets.
    try:
        options = []
        seen = set()
        for e in (pool_entries or []):
            name = str(getattr(e, 'preset_name', '') or '')
            if name and name not in seen:
                seen.add(name)
                options.append((name, e))
        if len(options) >= 2:
            questions['preset_fit'] = {
                'type': 'choice',
                'instructions': (
                    'Which available preset fits this message best? '
                    'Consider task type, capability needs and cost tier.'),
                'criteria': {
                    name: (f'provider={getattr(e, "provider", "?")}, '
                           f'model={getattr(e, "model", "?")}, '
                           'vision=' + (
                               'yes' if getattr(e, 'vision', False)
                               else 'no'))
                    for name, e in options
                },
            }
    except Exception:
        pass
    profile = str(agent_profile or '').strip()
    if profile:
        questions['profile_match'] = {
            'type': 'noul',
            'instructions': (
                f'Is the active agent profile {profile!r} a good match for '
                'this message and its task?'),
        }
    return questions


def build_state(message: str, attachments: list,
                pool_entries: list | None = None,
                agent_profile: str = '') -> dict:
    note = ('Routing judgment for one incoming user message in an AI '
            'assistant chat.')
    state = {
        'message': message,
        'attachments': list(attachments or []),
        'note': note,
        'agent_profile': str(agent_profile or ''),
    }
    if pool_entries:
        state['available_models'] = [
            {'preset': e.preset_name, 'provider': e.provider,
             'model': e.model, 'vision': bool(e.vision)}
            for e in pool_entries
        ]
        state['note'] = (note + ' available_models lists the presets '
                         'eligible for this call in real time.')
    return state


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse(result: dict, fit_options: list | None = None) -> Signals | None:
    try:
        answers = result['answers']
        tc = answers['task_class']
        cx = answers['complexity']
        vn = answers['vision_needed']
        dw = answers['delegate_worthy']
        if tc.get('type') != 'choice' or not isinstance(tc.get('choice'), str):
            return None
        conf = _num(tc.get('confidence'))
        comp = _num(cx.get('score'))
        vis = _num(vn.get('noul'))
        dele = _num(dw.get('noul'))
        if conf is None or comp is None or vis is None or dele is None:
            return None
        # Optional answers: absent, malformed or out-of-options values fall
        # back to neutral defaults and never fail the batch.
        fit, fit_conf = None, 0.0
        try:
            fa = answers.get('preset_fit') or {}
            if isinstance(fa, dict) and fa.get('type') == 'choice':
                choice = fa.get('choice')
                opts = [str(o) for o in (fit_options or [])]
                if (isinstance(choice, str) and choice
                        and (not opts or choice in opts)):
                    fit = choice
                    c = _num(fa.get('confidence'))
                    fit_conf = c if c is not None else 0.0
        except Exception:
            fit, fit_conf = None, 0.0
        prof = None
        try:
            pa = answers.get('profile_match') or {}
            if isinstance(pa, dict) and pa.get('type') == 'noul':
                prof = _num(pa.get('noul'))
        except Exception:
            prof = None
        return Signals(
            task_class=tc['choice'],
            task_class_confidence=conf,
            complexity=comp,
            vision_needed=vis,
            delegate_worthy=dele,
            preset_fit=fit,
            preset_fit_confidence=fit_conf,
            profile_match=prof,
        )
    except (KeyError, TypeError, AttributeError):
        return None


async def judge(
    message: str,
    attachments: list,
    query_fn,
    client,
    model: str,
    timeout_s: float = 2.0,
    pool_entries: list | None = None,
    retries: int = 1,
    agent_profile: str = '',
) -> Signals | None:
    """Run the routing batch. Returns Signals or None on any failure.

    A hung Jev request never returns (observed in production), so a
    TimeoutError gets exactly ``retries`` more attempts; all other
    exceptions fail fast without retry.
    """
    start = time.monotonic()
    total = max(int(retries), 0) + 1
    for attempt in range(1, total + 1):
        try:
            result = await asyncio.wait_for(
                query_fn(
                    client,
                    build_state(message, attachments,
                                pool_entries=pool_entries,
                                agent_profile=agent_profile),
                    build_questions(pool_entries=pool_entries,
                                    agent_profile=agent_profile),
                    model,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as exc:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            if attempt < total:
                _dbg(f'judge retry {attempt}/{total - 1} after '
                     f'{type(exc).__name__} elapsed_ms={elapsed_ms} '
                     f'timeout_s={timeout_s}')
                continue
            _dbg(f'judge failed: {type(exc).__name__}: {exc} '
                 f'elapsed_ms={elapsed_ms} timeout_s={timeout_s} '
                 f'attempts={attempt}')
            return None
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            _dbg(f'judge failed: {type(exc).__name__}: {exc} '
                 f'elapsed_ms={elapsed_ms} timeout_s={timeout_s} '
                 f'attempts={attempt}')
            return None
        fit_options = sorted({
            str(getattr(e, 'preset_name', '') or '')
            for e in (pool_entries or [])} - {''})
        return _parse(result, fit_options=fit_options)
