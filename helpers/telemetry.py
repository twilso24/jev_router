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
    compromise INTEGER NOT NULL DEFAULT 0,
    session_id TEXT,
    preset_fit TEXT,
    profile_match TEXT,
    fit_used INTEGER NOT NULL DEFAULT 0,
    fit_confidence REAL
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    provider TEXT NOT NULL,
    preset TEXT NOT NULL,
    ok INTEGER NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    error TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    fallback_from_preset TEXT,
    cold_start BOOLEAN NOT NULL DEFAULT 0,
    cold_start_ms INTEGER,
    context_pressure BOOLEAN NOT NULL DEFAULT 0,
    ctx_length INTEGER,
    estimated_tokens INTEGER
);
'''


def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_column(conn, 'decisions', 'session_id', 'TEXT')
    _ensure_column(conn, 'decisions', 'preset_fit', 'TEXT')
    _ensure_column(conn, 'decisions', 'profile_match', 'TEXT')
    _ensure_column(conn, 'decisions', 'fit_used',
                   'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'decisions', 'fit_confidence', 'REAL')
    _ensure_column(conn, 'decisions', 'rule', 'TEXT')
    _ensure_column(conn, 'decisions', 'reason_human', 'TEXT')
    _ensure_column(conn, 'decisions', 'delegation', 'TEXT')
    _ensure_column(conn, 'decisions', 'auto_exec', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'decisions', 'shadow_target', 'TEXT')
    _ensure_column(conn, 'calls', 'fallback_from_preset', 'TEXT')
    _ensure_column(conn, 'calls', 'band', 'TEXT')
    _ensure_column(conn, 'calls', 'cold_start', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'calls', 'cold_start_ms', 'INTEGER')
    _ensure_column(conn, 'calls', 'context_pressure', 'INTEGER NOT NULL DEFAULT 0')
    _ensure_column(conn, 'calls', 'ctx_length', 'INTEGER')
    _ensure_column(conn, 'calls', 'estimated_tokens', 'INTEGER')
    conn.commit()
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str,
                   decl: str) -> None:
    """Legacy-DB migration: add a column when an existing table lacks it."""
    cols = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')


def record_decision(
    conn: sqlite3.Connection,
    decision: Decision,
    signals: Signals | None,
    msg_digest: str,
    session_id: str = '',
    delegation: str = '',
    auto_exec: bool = False,
    shadow_target: str | None = None,
    obs_fallback: bool = True,
    obs_session: bool = True,
    obs_shadow: bool = True,
) -> None:
    # Only record shadow_target if shadow mode is enabled
    record_shadow = shadow_target if obs_shadow else None
    conn.execute(
        'INSERT INTO decisions (ts, msg_digest, task_class, complexity, band, '
        'vision, delegate, target, reason, compromise, session_id, '
        'preset_fit, profile_match, fit_used, fit_confidence, '
        'rule, reason_human, delegation, auto_exec, shadow_target) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
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
            str(session_id or ''),
            signals.preset_fit if signals else None,
            signals.profile_match if signals else None,
            1 if decision.fit_used else 0,
            float(signals.preset_fit_confidence) if signals else None,
            decision.rule,
            decision.reason_human,
            str(delegation or ''),
            1 if auto_exec else 0,
            str(record_shadow) if record_shadow else None,
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
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    fallback_from_preset: str | None = None,
    band: str | None = None,
    cold_start: bool = False,
    cold_start_ms: int | None = None,
    context_pressure: bool = False,
    ctx_length: int | None = None,
    estimated_tokens: int | None = None,
) -> None:
    conn.execute(
        'INSERT INTO calls (ts, provider, preset, ok, duration, error, '
        'input_tokens, output_tokens, cost_usd, fallback_from_preset, band, '
        'cold_start, cold_start_ms, context_pressure, ctx_length, estimated_tokens) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (time.time(), str(provider or ''), str(preset or ''),
         1 if ok else 0, float(duration), error,
         _int_or_none(input_tokens), _int_or_none(output_tokens),
         _float_or_none(cost_usd),
         str(fallback_from_preset) if fallback_from_preset else None,
         band,
         1 if cold_start else 0,
         _int_or_none(cold_start_ms),
         1 if context_pressure else 0,
         _int_or_none(ctx_length),
         _int_or_none(estimated_tokens)),
    )
    conn.commit()


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def usage_fields(result) -> dict:
    """Extract input/output tokens and cost_usd from a framework result.

    Reads LLMResult.usage (LiteLLM dict: prompt_tokens/completion_tokens
    or input_tokens/output_tokens, cost from response_cost). Never raises;
    missing or malformed values become None.
    """
    out = {'input_tokens': None, 'output_tokens': None, 'cost_usd': None}
    try:
        usage = getattr(result, 'usage', None)
        if not isinstance(usage, dict):
            return out
        inp = usage.get('input_tokens', usage.get('prompt_tokens'))
        outp = usage.get('output_tokens', usage.get('completion_tokens'))
        cost = usage.get('cost')
        out['input_tokens'] = _int_or_none(inp)
        out['output_tokens'] = _int_or_none(outp)
        out['cost_usd'] = _float_or_none(cost)
    except Exception:
        pass
    return out


def resolve_fallback(intended: str | None,
                     called: str | None) -> str | None:
    """Blame for a failing call: the preset that was *meant* to serve it.

    Returns intended when it differs from the preset actually called;
    None when identical or unavailable (non-fallback paths)."""
    i = str(intended or '').strip()
    c = str(called or '').strip()
    if i and i != c:
        return i
    return None


def _percentile_nearest_rank(sorted_vals: list, pct: float) -> float:
    """Nearest-rank percentile over an ascending list (pct in 0..1)."""
    if not sorted_vals:
        return 0.0
    import math
    rank = max(1, math.ceil(pct * len(sorted_vals)))
    return float(sorted_vals[rank - 1])


def preset_duration_stats(conn: sqlite3.Connection,
                          limit: int = 200) -> dict:
    """Per-preset latency percentiles over successful calls only.

    Returns {preset: {p50, p95, p99, count, avg}} using nearest-rank."""
    cur = conn.execute(
        'SELECT preset, duration FROM calls '
        'WHERE ok = 1 ORDER BY id DESC LIMIT ?', (int(limit),))
    groups: dict = {}
    for row in cur.fetchall():
        groups.setdefault(row['preset'], []).append(float(row['duration']))
    stats: dict = {}
    for preset, durations in groups.items():
        durations.sort()
        stats[preset] = {
            'p50': _percentile_nearest_rank(durations, 0.50),
            'p95': _percentile_nearest_rank(durations, 0.95),
            'p99': _percentile_nearest_rank(durations, 0.99),
            'count': len(durations),
            'avg': sum(durations) / len(durations),
        }
    return stats


def session_decision_stats(conn: sqlite3.Connection, session_id: str,
                           limit: int = 200) -> dict:
    """Session-level aggregates from the decisions table.

    model_switches counts sequential target changes in chronological order.
    band_dist maps band -> decision count. Missing session returns zeroes."""
    empty = {'decisions': 0, 'model_switches': 0,
             'fallback_rate': 0.0, 'band_dist': {}}
    try:
        cur = conn.execute(
            'SELECT target, band FROM decisions '
            'WHERE session_id = ? ORDER BY id DESC LIMIT ?',
            (str(session_id or ''), int(limit)))
        rows = cur.fetchall()  # newest-first; reverse to chronological
        if not rows:
            return empty
        chron = list(reversed(rows))
        switches = 0
        prev = None
        band_dist: dict = {}
        for row in chron:
            band = row['band'] or 'unknown'
            band_dist[band] = band_dist.get(band, 0) + 1
            target = row['target'] or ''
            # keep-model rows are not switches and do not move the chain
            if not target:
                continue
            if prev is not None and target != prev:
                switches += 1
            prev = target
        # fallback_rate: share of keep-model (empty target) decisions
        keep = sum(1 for r in chron if not (r['target'] or ''))
        return {
            'decisions': len(chron),
            'model_switches': switches,
            'fallback_rate': keep / len(chron),
            'band_dist': band_dist,
        }
    except Exception:
        return empty


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


def band_preset_call_stats(conn: sqlite3.Connection, limit: int = 200) -> dict:
    """Aggregate ok/fail counts per (band, preset) over the most recent calls.

    Rows without a band (legacy calls, kept-model fallbacks) are excluded:
    per-band ranking must only see evidence actually measured in a band.
    Returns {band: {preset: {'ok': n, 'fail': n}}}.
    """
    cur = conn.execute(
        "SELECT band, preset, ok FROM calls WHERE band IS NOT NULL "
        'ORDER BY id DESC LIMIT ?',
        (int(limit),))
    stats: dict = {}
    for row in cur.fetchall():
        band_slot = stats.setdefault(row['band'], {})
        slot = band_slot.setdefault(row['preset'], {'ok': 0, 'fail': 0})
        if row['ok']:
            slot['ok'] += 1
        else:
            slot['fail'] += 1
    return stats


def provider_call_stats(conn: sqlite3.Connection, limit: int = 200) -> dict:
    """Aggregate ok/fail counts per provider over the most recent calls.

    last_ok mirrors each provider's most recent outcome in the window so
    the UI can tell a recovered provider (old failures, latest call ok)
    from one that is still failing. Rows arrive newest-first, so the first
    row seen per provider fixes last_ok.
    """
    cur = conn.execute(
        'SELECT provider, ok FROM calls ORDER BY id DESC LIMIT ?',
        (int(limit),))
    stats: dict = {}
    for row in cur.fetchall():
        # rows arrive newest-first: the first row seen per provider pins
        # last_ok; reordering this query would invert recovery semantics
        slot = stats.setdefault(
            row['provider'],
            {'ok': 0, 'fail': 0, 'last_ok': bool(row['ok'])})
        if row['ok']:
            slot['ok'] += 1
        else:
            slot['fail'] += 1
    return stats
