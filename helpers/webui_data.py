import time
from pathlib import Path

import yaml

from . import telemetry as tel_mod
from . import circuit_breaker as breaker_mod


def stats_from_db(db_path: Path, limit: int = 20) -> dict:
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
        with open(path, 'w') as f:
            yaml.safe_dump(data, f)
        return True
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
    try:
        if db_path.exists():
            conn = tel_mod.init_db(db_path)
            stats = tel_mod.preset_call_stats(conn, limit=limit)
            prov_stats = tel_mod.provider_call_stats(conn, limit=limit)
            conn.close()
    except Exception:
        stats, prov_stats = {}, {}

    suggested = tuning_mod.suggest_band_orders(current, pool_presets, stats)
    auto_tune = tuning_mod.read_auto_tune(policy_path)

    excludes = [str(x) for x in (
        ((policy_data.get('provider_rules') or {}).get('exclude')) or [])]
    providers = sorted(set(
        [str(x) for x in (pool_providers or [])]
        + excludes + list(prov_stats.keys())))
    tripped = set(breaker_mod.excluded_providers(providers)) if providers else set()
    eset = set(excludes)
    provider_states = [{
        'provider': pr,
        'excluded': pr in eset,
        'tripped': pr in tripped,
        'ok': (prov_stats.get(pr) or {}).get('ok', 0),
        'fail': (prov_stats.get(pr) or {}).get('fail', 0),
    } for pr in providers]

    # Auto-wire visibility: presets missing from all band orders + last
    # wire report (sidecar next to the policy file).
    from . import auto_wire as auto_wire_mod
    unwired = auto_wire_mod.unwired_presets(policy_path, pool_presets)
    wire_state = auto_wire_mod.read_wire_state(
        Path(policy_path).parent / 'wire-state.json')

    return {'current': current, 'suggested': suggested, 'stats': stats,
            'auto_tune': auto_tune, 'excludes': excludes,
            'provider_states': provider_states,
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
