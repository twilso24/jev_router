import time
from pathlib import Path

import yaml

from . import telemetry as tel_mod
from . import circuit_breaker as breaker_mod


def stats_from_db(db_path: Path, limit: int = 20) -> dict:
    # Clamp client-supplied limits (review finding): SQLite LIMIT -1 means
    # unbounded; keep responses to a sane page size.
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 20
    try:
        if not db_path.exists():
            raise FileNotFoundError(f'db not found: {db_path}')
        conn = tel_mod.init_db(db_path)
        rows = tel_mod.last_decisions(conn, limit=limit)
        conn.close()
    except Exception:
        rows = []

    recent = [{
        'ts': r['ts'],
        'task_class': r['task_class'],
        'band': r['band'],
        'target': r['target'],
        'reason': r['reason'],
        'compromise': bool(r['compromise']),
        'preset_fit': r['preset_fit'] if 'preset_fit' in r.keys() else None,
        'profile_match': (r['profile_match']
                          if 'profile_match' in r.keys() else None),
        'fit_used': bool(r['fit_used']) if 'fit_used' in r.keys() else False,
        'rule': r['rule'] if 'rule' in r.keys() else None,
        'reason_human': (r['reason_human']
                         if 'reason_human' in r.keys() else None),
        'delegation': (r['delegation'] if 'delegation' in r.keys() else None),
        'auto_exec': (bool(r['auto_exec']) if 'auto_exec' in r.keys() else False),
    } for r in rows]

    by_preset: dict = {}
    for r in rows:
        target = r['target']
        if target not in by_preset:
            by_preset[target] = {'count': 0, 'compromises': 0}
        by_preset[target]['count'] += 1
        if r['compromise']:
            by_preset[target]['compromises'] += 1

    return {'recent': recent, 'totals': {'decisions': len(rows)},
            'by_preset': by_preset}


def breaker_snapshot() -> list:
    now = time.time()
    return [{
        'provider': p,
        'failures': s.failures,
        'trip_until': s.trip_until,
        'excluded': s.trip_until > now if s.trip_until else False,
    } for p, s in breaker_mod._STATES.items()]


def read_policy(path: Path) -> dict:
    defaults = {'provider_rules': {'include': [], 'exclude': []}}
    try:
        if not path.exists():
            return defaults
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else defaults
    except Exception:
        return defaults


def write_provider_rules(path: Path, exclude: list | None = None) -> bool:
    try:
        data = read_policy(path)
        if exclude is not None:
            dedup: list = []
            for x in exclude:
                sx = str(x).strip()
                if sx and sx not in dedup:
                    dedup.append(sx)
            data['provider_rules']['exclude'] = dedup
        from .tuning import _POLICY_LOCK, _atomic_yaml_write
        with _POLICY_LOCK:
            return _atomic_yaml_write(Path(path), data)
    except Exception:
        return False

def tuning_report(db_path: Path, policy_path: Path,
                  pool_presets: list, limit: int = 200,
                  pool_providers: list | None = None) -> dict:
    """Everything the panel Band Tuning card needs: current orders, suggested
    orders, per-preset stats, auto_tune flag, and per-provider live state."""
    from .policy import DEFAULT_BAND_ORDERS
    from . import tuning as tuning_mod

    policy_data = read_policy(policy_path)
    raw_orders = policy_data.get('band_orders')
    current = {b: list(names) for b, names in DEFAULT_BAND_ORDERS.items()}
    if isinstance(raw_orders, dict):
        for band in current:
            val = raw_orders.get(band)
            if isinstance(val, list) and val:
                current[band] = [str(x) for x in val]

    stats = {}
    prov_stats = {}
    band_stats = {}
    try:
        if db_path.exists():
            conn = tel_mod.init_db(db_path)
            stats = tel_mod.preset_call_stats(conn, limit=limit)
            prov_stats = tel_mod.provider_call_stats(conn, limit=limit)
            band_stats = tel_mod.band_preset_call_stats(conn, limit=limit)
            conn.close()
    except Exception:
        stats, prov_stats, band_stats = {}, {}, {}

    # band-only ranking: bands without own evidence keep the user's file
    # order - never re-ranked from global stats (Default-everywhere fix).
    # Always pass a dict (band mode): an empty {} means no banded rows yet,
    # which must keep file orders, NOT degrade to global ranking via None.
    suggested = tuning_mod.suggest_band_orders(
        current, pool_presets, stats, band_preset_stats=band_stats)
    # pinned bands freeze in suggested too - the panel displays and Applies
    # `suggested`, so unpinned suggestions would overwrite pinned content.
    # Mirrors effective_band_orders (router contract). Pins > suggestion.
    for band, pin in tuning_mod.read_pinned_bands(policy_path).items():
        if pin and band in suggested and current.get(band):
            suggested[band] = list(current[band])
    auto_tune = tuning_mod.read_auto_tune(policy_path)

    excludes = [str(x) for x in (
        ((policy_data.get('provider_rules') or {}).get('exclude')) or [])]
    providers = sorted(set(
        [str(x) for x in (pool_providers or [])]
        + excludes + list(prov_stats.keys())))
    tripped = set(breaker_mod.excluded_providers(providers)) if providers else set()
    eset = set(excludes)
    def _pstate(pr):
        st = prov_stats.get(pr) or {}
        last_ok = st.get('last_ok')
        # failing only while the latest recorded outcome is a failure:
        # old failures with a newer success mean the provider recovered.
        return {
            'provider': pr,
            'excluded': pr in eset,
            'tripped': pr in tripped,
            'ok': st.get('ok', 0),
            'fail': st.get('fail', 0),
            'last_ok': last_ok,
            'failing': bool(st.get('fail', 0)) and last_ok is False,
        }

    provider_states = [_pstate(pr) for pr in providers]

    # Auto-wire visibility: presets missing from all band orders + last
    # wire report (sidecar next to the policy file).
    from . import auto_wire as auto_wire_mod
    unwired = auto_wire_mod.unwired_presets(policy_path, pool_presets)
    wire_state = auto_wire_mod.read_wire_state(
        Path(policy_path).parent / 'wire-state.json')

    return {'current': current, 'suggested': suggested, 'stats': stats,
            'auto_tune': auto_tune, 'excludes': excludes,
            'provider_states': provider_states,
            'pinned_bands': tuning_mod.read_pinned_bands(policy_path),
            'unwired': unwired, 'wire_state': wire_state}

def pool_preset_names(presets_path: Path) -> list:
    """Live chat preset names from presets.yaml (pool source of truth)."""
    try:
        from . import pool as pool_mod
        entries = [e for e in pool_mod.load_pool(presets_path).entries
                   if e.role == 'chat']
        seen, out = set(), []
        for e in entries:
            if e.preset_name not in seen:
                seen.add(e.preset_name)
                out.append(e.preset_name)
        return out
    except Exception:
        return []


def pool_providers(presets_path: Path) -> list:
    """Distinct chat provider names from presets.yaml, sorted."""
    try:
        from . import pool as pool_mod
        entries = [e for e in pool_mod.load_pool(presets_path).entries
                   if e.role == 'chat']
        seen = set()
        for e in entries:
            seen.add(str(e.provider))
        return sorted(seen)
    except Exception:
        return []


def fallback_chain_stats(db_path: Path, limit: int = 200) -> dict:
    """Fallback chain statistics: which presets fell back to which."""
    try:
        if not db_path.exists():
            raise FileNotFoundError(f'db not found: {db_path}')
        conn = tel_mod.init_db(db_path)
        cur = conn.execute(
            'SELECT preset, fallback_from_preset, ok, error, duration '
            'FROM calls WHERE fallback_from_preset IS NOT NULL '
            'ORDER BY id DESC LIMIT ?', (int(limit),))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        rows = []

    fallback_map: dict = {}
    fallback_calls = []
    for r in rows:
        preset = r['preset']
        fallback_from = r['fallback_from_preset']
        if preset and fallback_from:
            key = f'{fallback_from}->{preset}'
            if key not in fallback_map:
                fallback_map[key] = {'count': 0, 'failures': 0, 'avg_duration': 0.0}
            fallback_map[key]['count'] += 1
            if not r['ok']:
                fallback_map[key]['failures'] += 1
            fallback_calls.append({
                'preset': preset,
                'fallback_from_preset': fallback_from,
                'ok': bool(r['ok']),
                'error': r['error'],
                'duration': float(r['duration'] or 0),
            })
    
    # Calculate avg duration per fallback chain
    for key, data in fallback_map.items():
        chain_calls = [c for c in fallback_calls if f"{c['fallback_from_preset']}->{c['preset']}" == key]
        if chain_calls:
            data['avg_duration'] = sum(c['duration'] for c in chain_calls) / len(chain_calls)

    return {'fallback_map': fallback_map, 'fallback_calls': fallback_calls[:50]}


def session_aggregates(db_path: Path, limit: int = 200) -> dict:
    """Session-level aggregates from the decisions table."""
    try:
        if not db_path.exists():
            raise FileNotFoundError(f'db not found: {db_path}')
        conn = tel_mod.init_db(db_path)
        cur = conn.execute(
            'SELECT session_id, COUNT(*) as cnt, '
            'SUM(CASE WHEN target IS NULL OR target = "" THEN 1 ELSE 0 END) as fallbacks, '
            'MIN(id) as first_id, MAX(id) as last_id '
            'FROM decisions WHERE session_id != "" '
            'GROUP BY session_id ORDER BY last_id DESC LIMIT ?', (int(limit),))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        rows = []

    sessions = []
    for r in rows:
        sid = r['session_id']
        cnt = r['cnt']
        fallbacks = r['fallbacks']
        # Get model switches for this session
        switches = 0
        band_dist = {}
        try:
            conn = tel_mod.init_db(db_path)
            cur2 = conn.execute(
                'SELECT target, band FROM decisions '
                'WHERE session_id = ? ORDER BY id ASC', (str(sid),))
            chron = cur2.fetchall()
            conn.close()
            prev = None
            for row in chron:
                band = row['band'] or 'unknown'
                band_dist[band] = band_dist.get(band, 0) + 1
                target = row['target'] or ''
                if not target:
                    continue
                if prev is not None and target != prev:
                    switches += 1
                prev = target
        except Exception:
            pass
        
        sessions.append({
            'session_id': sid,
            'decisions': cnt,
            'fallbacks': fallbacks,
            'fallback_rate': fallbacks / cnt if cnt > 0 else 0,
            'model_switches': switches,
            'band_dist': band_dist,
        })
    
    return {'sessions': sessions}


def shadow_mode_stats(db_path: Path, limit: int = 200) -> dict:
    """Shadow mode: actual vs predicted preset decisions."""
    try:
        if not db_path.exists():
            raise FileNotFoundError(f'db not found: {db_path}')
        conn = tel_mod.init_db(db_path)
        cur = conn.execute(
            'SELECT ts, target, shadow_target, band, reason '
            'FROM decisions WHERE shadow_target IS NOT NULL '
            'ORDER BY id DESC LIMIT ?', (int(limit),))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        rows = []

    shadow = []
    matches = 0
    for r in rows:
        actual = r['target'] or 'KEEP-MODEL'
        predicted = r['shadow_target']
        match = actual == predicted
        if match:
            matches += 1
        shadow.append({
            'ts': r['ts'],
            'actual': actual,
            'predicted': predicted,
            'match': match,
            'band': r['band'],
            'reason': r['reason'],
        })
    
    total = len(shadow)
    return {
        'shadow': shadow,
        'total': total,
        'matches': matches,
        'match_rate': matches / total if total > 0 else 0,
    }
