# jev_router telemetry: SQLite routing log, one row per decision.
import sqlite3
import time
from pathlib import Path

from .policy import Decision
from .signals import Signals

SCHEMA = '''
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    msg_digest TEXT NOT NULL,
    task_class TEXT,
    complexity REAL,
    band TEXT,
    vision REAL,
    delegate REAL,
    target TEXT,
    reason TEXT,
    compromise INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    provider TEXT NOT NULL,
    preset TEXT NOT NULL,
    ok INTEGER NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    error TEXT
);
'''


def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_decision(
    conn: sqlite3.Connection,
    decision: Decision,
    signals: Signals | None,
    msg_digest: str,
) -> None:
    conn.execute(
        'INSERT INTO decisions (ts, msg_digest, task_class, complexity, band, '
        'vision, delegate, target, reason, compromise) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (
            time.time(),
            msg_digest,
            signals.task_class if signals else None,
            signals.complexity if signals else None,
            decision.band,
            signals.vision_needed if signals else None,
            signals.delegate_worthy if signals else None,
            decision.entry.preset_name if decision.entry else None,
            decision.reason,
            1 if decision.compromise else 0,
        ),
    )
    conn.commit()


def last_decisions(conn: sqlite3.Connection, limit: int = 20):
    cur = conn.execute(
        'SELECT * FROM decisions ORDER BY id DESC LIMIT ?', (int(limit),))
    return cur.fetchall()


def record_call(
    conn: sqlite3.Connection,
    provider: str,
    preset: str,
    ok: bool,
    duration: float,
    error: str | None,
) -> None:
    conn.execute(
        'INSERT INTO calls (ts, provider, preset, ok, duration, error) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (time.time(), str(provider or ''), str(preset or ''),
         1 if ok else 0, float(duration), error),
    )
    conn.commit()


def preset_call_stats(conn: sqlite3.Connection, limit: int = 200) -> dict:
    """Aggregate ok/fail counts per preset over the most recent calls."""
    cur = conn.execute(
        'SELECT preset, ok FROM calls ORDER BY id DESC LIMIT ?',
        (int(limit),))
    stats: dict = {}
    for row in cur.fetchall():
        slot = stats.setdefault(row['preset'], {'ok': 0, 'fail': 0})
        if row['ok']:
            slot['ok'] += 1
        else:
            slot['fail'] += 1
    return stats


def provider_call_stats(conn: sqlite3.Connection, limit: int = 200) -> dict:
    """Aggregate ok/fail counts per provider over the most recent calls."""
    cur = conn.execute(
        'SELECT provider, ok FROM calls ORDER BY id DESC LIMIT ?',
        (int(limit),))
    stats: dict = {}
    for row in cur.fetchall():
        slot = stats.setdefault(row['provider'], {'ok': 0, 'fail': 0})
        if row['ok']:
            slot['ok'] += 1
        else:
            slot['fail'] += 1
    return stats
