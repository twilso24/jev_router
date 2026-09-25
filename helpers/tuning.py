# jev_router tuning: telemetry-driven band-order suggestions and safe,
# partial policy writes so route tuning is a repeatable one-click step.
from pathlib import Path

import yaml

from .policy import BANDS, DEFAULT_BAND_ORDERS, load_band_orders


MIN_EVIDENCE_CALLS = 10


def _observed_calls(stats: dict) -> int:
    """Total ok+fail observations across presets; malformed entries count 0."""
    total = 0
    for s in (stats or {}).values():
        if not isinstance(s, dict):
            continue
        for k in ('ok', 'fail'):
            try:
                total += int(s.get(k) or 0)
            except Exception:
                pass
    return total


def suggest_band_orders(current: dict, pool_presets: list,
                        preset_stats: dict) -> dict:
    """Suggest band orders from per-preset outcome stats.

    Evidence floor: below MIN_EVIDENCE_CALLS total observed calls the
    current (pool-filtered) orders are returned unchanged - one healthy
    call must not promote a preset over the user's configured orders
    (production: Default with ok=1 jumped to #1 in every band).

    Once evidence is sufficient, ranking per band: healthy presets
    (fail==0) first, most ok first; untouched presets keep their current
    relative order; failing presets last, fewest failures first. Presets
    absent from the live pool are dropped; unknown pool presets are
    appended. Missing bands fall back to DEFAULT_BAND_ORDERS. Pure and
    total: never raises, covers all bands.
    """
    pool = [str(p) for p in (pool_presets or [])]
    stats = preset_stats if isinstance(preset_stats, dict) else {}
    enough = _observed_calls(stats) >= MIN_EVIDENCE_CALLS
    cur_raw = current if isinstance(current, dict) else {}
    defaults = {b: list(names) for b, names in DEFAULT_BAND_ORDERS.items()}
    out = {}
    for band in BANDS:
        base = cur_raw.get(band)
        if not isinstance(base, list) or not base:
            base = defaults[band]
        order = [str(p) for p in base if str(p) in pool]
        for p in pool:
            if p not in order:
                order.append(p)

        def key(p):
            s = stats.get(p) if isinstance(stats.get(p), dict) else {}
            try:
                fail = int(s.get('fail') or 0)
            except Exception:
                fail = 0
            try:
                ok = int(s.get('ok') or 0)
            except Exception:
                ok = 0
            if fail > 0:
                return (1, fail, -ok, 0)
            return (0, -ok, 0, order.index(p))

        if not enough:
            out[band] = order
            continue

        out[band] = sorted(order, key=key)
    return out


def write_band_orders(path, band_orders: dict) -> bool:
    """Merge band_orders into routing-policy.yaml, preserving every other
    key (provider_rules, schedules, ...).

    Rejects unknown bands and empty/non-list orders without touching the
    file. Writes atomically (tmp + replace). Returns True on success.
    """
    try:
        raw = band_orders if isinstance(band_orders, dict) else {}
        if not raw:
            return False
        updates = {}
        for band, val in raw.items():
            if band not in BANDS:
                return False
            if not isinstance(val, list) or not val:
                return False
            names = [str(x).strip() for x in val if str(x).strip()]
            if not names:
                return False
            updates[band] = names
        if not updates:
            return False
        p = Path(path)
        data = {}
        if p.exists():
            loaded = yaml.safe_load(p.read_text())
            if isinstance(loaded, dict):
                data = loaded
        existing = data.get('band_orders')
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(updates)
        data['band_orders'] = merged
        tmp = p.with_suffix('.yaml.tmp')
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp.replace(p)
        return True
    except Exception:
        return False


def read_auto_tune(path) -> bool:
    """True only when routing-policy.yaml holds auto_tune: true."""
    try:
        p = Path(path)
        if not p.exists():
            return False
        data = yaml.safe_load(p.read_text())
        if not isinstance(data, dict):
            return False
        return data.get('auto_tune') is True
    except Exception:
        return False


def write_auto_tune(path, enabled: bool) -> bool:
    """Persist auto_tune flag; preserves all other keys. Atomic."""
    try:
        p = Path(path)
        data = {}
        if p.exists():
            loaded = yaml.safe_load(p.read_text())
            if isinstance(loaded, dict):
                data = loaded
        data['auto_tune'] = bool(enabled)
        tmp = p.with_suffix('.yaml.tmp')
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp.replace(p)
        return True
    except Exception:
        return False


def effective_band_orders(policy_path, telemetry_path=None,
                          pool_presets=None, limit: int = 200) -> tuple:
    """Band orders routing should use right now.

    auto_tune off (or any failure): file orders, applied=False.
    auto_tune on: outcome-ranked orders, applied=True. Never raises.
    """
    try:
        orders = load_band_orders(policy_path)
        if not read_auto_tune(policy_path):
            return orders, False
        stats = {}
        if telemetry_path is not None:
            from . import telemetry as tel_mod
            tp = Path(telemetry_path)
            if tp.exists():
                conn = tel_mod.init_db(tp)
                try:
                    stats = tel_mod.preset_call_stats(conn, limit=limit)
                finally:
                    conn.close()
        suggested = suggest_band_orders(
            orders, list(pool_presets or []), stats)
        return suggested, True
    except Exception:
        try:
            return load_band_orders(policy_path), False
        except Exception:
            return {b: list(n) for b, n in DEFAULT_BAND_ORDERS.items()}, False
