# jev_router mentions: ephemeral chat-mention dials parsed per message.
import re
import time
from dataclasses import dataclass, field


@dataclass
class Mentions:
    exclude: list = field(default_factory=list)   # hard provider excludes
    prefer: list = field(default_factory=list)    # soft provider boost
    free: bool = False                            # free-models dial
    ttl_hours: float = 0                          # 0 = this call only


EXCLUDE_VERBS = "stop using|do not use|don't use|no more|without|drop|exclude"
PREFER_VERBS = "use|switch to|prefer|route to"


def _alias_map(providers) -> dict:
    m = {}
    for prov in providers or []:
        name = str(prov).lower().strip()
        if not name:
            continue
        m.setdefault(name, name)
        for tok in re.split(r'[_.\-]+', name):
            if len(tok) >= 3:
                m.setdefault(tok, name)
    return m


def _find(low: str, verbs: str, aliases: dict) -> list:
    found = []
    for alias, prov in aliases.items():
        pat = (r'\b(?:' + verbs + r')\s+(?:the\s+)?'
               + re.escape(alias) + r'\b')
        if re.search(pat, low):
            found.append(prov)
    return sorted(set(found))


def parse(text: str, providers) -> Mentions:
    """Parse provider mentions from one user message. Tolerant, never raises."""
    m = Mentions()
    try:
        if not isinstance(text, str) or not text.strip():
            return m
        low = text.lower()
        aliases = _alias_map(providers)
        m.exclude = _find(low, EXCLUDE_VERBS, aliases)
        m.prefer = [p for p in _find(low, PREFER_VERBS, aliases)
                    if p not in m.exclude]
        if 'free models' in low or 'free model' in low:
            m.free = True
        hm = re.search(r'for\s+(\d+)\s+hours?\b', low)
        if hm:
            m.ttl_hours = float(hm.group(1))
        elif re.search(r'\btonight\b', low):
            m.ttl_hours = 8.0
        elif re.search(r'\btoday\b', low):
            m.ttl_hours = 12.0
        return m
    except Exception:
        return Mentions()


# session_id -> list of (expiry_ts, [providers]); process-local by design.
_SESSIONS: dict = {}


def remember(session_id, providers, ttl_hours, now=None) -> None:
    """Store an exclude set for a chat session until expiry."""
    if not session_id or not providers or not ttl_hours or ttl_hours <= 0:
        return
    now = time.time() if now is None else now
    _SESSIONS.setdefault(str(session_id), []).append(
        (now + float(ttl_hours) * 3600.0, [str(p) for p in providers]))


def session_excludes(session_id, now=None) -> list:
    """Active excludes for the session; expired entries are pruned."""
    now = time.time() if now is None else now
    entries = _SESSIONS.get(str(session_id)) or []
    active = []
    keep = []
    for expiry, provs in entries:
        if expiry > now:
            keep.append((expiry, provs))
            active.extend(provs)
    if keep:
        _SESSIONS[str(session_id)] = keep
    else:
        _SESSIONS.pop(str(session_id), None)
    return sorted(set(active))
