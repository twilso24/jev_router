# jev_router schedules: time-based provider availability and preference.
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

DAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DAY_ALIASES = {
    'monday': 'mon', 'tuesday': 'tue', 'wednesday': 'wed',
    'thursday': 'thu', 'friday': 'fri', 'saturday': 'sat', 'sunday': 'sun',
}


@dataclass
class Schedule:
    name: str
    window: str = ''                 # '' = all day; 'HH:MM-HH:MM', wrap ok
    days: list = field(default_factory=list)   # [] = every day
    timezone: str = 'instance'       # informational; matching is instance-local
    prefer: list = field(default_factory=list)  # soft provider boost
    exclude: list = field(default_factory=list)  # hard provider block


def load_schedules(path) -> list[Schedule]:
    """Parse schedules from routing-policy.yaml; tolerant of any junk."""
    try:
        p = Path(path)
        if not p.exists():
            return []
        data = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get('schedules')
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        out.append(Schedule(
            name=name,
            window=str(item.get('window') or ''),
            days=[str(d).lower() for d in (item.get('days') or [])],
            timezone=str(item.get('timezone') or 'instance'),
            prefer=[str(x) for x in (item.get('prefer') or [])],
            exclude=[str(x) for x in (item.get('exclude') or [])],
        ))
    return out


def _parse_hhmm(text: str) -> int | None:
    try:
        h, m = text.strip().split(':', 1)
        hh, mm = int(h), int(m)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh * 60 + mm
    except Exception:
        pass
    return None


def window_matches(window: str, minutes: int) -> bool:
    """True when minutes-of-day falls inside window. Wrap supported."""
    if not window:
        return True
    try:
        lo_s, hi_s = window.split('-', 1)
    except Exception:
        return False
    lo = _parse_hhmm(lo_s)
    hi = _parse_hhmm(hi_s)
    if lo is None or hi is None:
        return False
    if lo <= hi:
        return lo <= minutes < hi
    return minutes >= lo or minutes < hi  # e.g. 22:00-06:00


def day_matches(days: list, weekday: int) -> bool:
    """True when weekday (0=mon) is allowed. Empty list = every day."""
    if not days:
        return True
    wanted = {DAY_ALIASES.get(d, d) for d in days}
    return DAY_NAMES[weekday % 7] in wanted


def active_schedule(items: list[Schedule],
                    now: datetime | None = None) -> Schedule | None:
    """First schedule matching day + window wins (spec decision #9)."""
    now = now or datetime.now()
    minutes = now.hour * 60 + now.minute
    for s in items:
        if not day_matches(s.days, now.weekday()):
            continue
        if window_matches(s.window, minutes):
            return s
    return None
