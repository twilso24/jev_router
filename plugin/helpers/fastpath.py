# jev_router fastpath: cheap heuristic to skip Jev for trivial messages.

MAX_CHARS = 240

FENCE_MARKERS = ('```', '~~/~', '<code')
URL_MARKER = 'http'

TASK_HINTS = (
    'write', 'build', 'create', 'make', 'fix', 'debug', 'refactor', 'review',
    'research', 'find', 'search', 'analyze', 'analyse', 'summarize', 'summarise',
    'plan', 'design', 'implement', 'install', 'deploy', 'configure', 'test',
    'classify', 'convert', 'translate', 'generate', 'compare', 'explain how',
    'why does', 'optimize', 'optimise', 'migrate', 'update', 'migrate',
)


def is_trivial(message: str, attachments: list | None = None) -> bool:
    """True for short plain conversational messages with no task markers."""
    if attachments:
        return False
    if not isinstance(message, str):
        return False
    text = message.strip()
    if not text or len(text) > MAX_CHARS:
        return False
    lowered = text.lower()
    for marker in FENCE_MARKERS:
        if marker in lowered:
            return False
    if URL_MARKER in lowered:
        return False
    for hint in TASK_HINTS:
        if hint in lowered:
            return False
    return True
