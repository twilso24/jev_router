# jev_router tuning: telemetry-driven band-order suggestions and safe,
# partial policy writes so route tuning is a repeatable one-click step.
from pathlib import Path

import yaml

from .policy import BANDS, DEFAULT_BAND_ORDERS, load_band_orders


MIN_EVIDENCE_CALLS = 10


def suggest_band_orders(current: dict, pool_presets: list,
                        preset_stats: dict) -> dict:
    """Suggest band orders from per-preset outcome stats.

    Per-preset evidence floor: a preset needs at least
    MIN_EVIDENCE_CALLS own ok+fail observations to be ranked at all.
    Qualified presets rank healthy-first (most ok first), failing-last
    (fewest failures first); unqualified presets - no or sparse own
    evidence - keep their current relative order after the qualified
    group, so one healthy call can never promote a preset over the
    user's configured orders (production: Default with ok=1 jumped to
    #1 in every band). Presets
    absent from the live pool are dropped; unknown pool presets are
    appended. Missing bands fall back to DEFAULT_BAND_ORDERS. Pure and
    total: never raises, covers all bands.
    """
    pool = [str(p) for p in (pool_presets or [])]
    stats = preset_stats if isinstance(preset_stats, dict) else {}
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

        def qualified(p):
            s = stats.get(p) if isinstance(stats.get(p), dict) else {}
            try:
                n = int(s.get('ok') or 0) + int(s.get('fail') or 0)
            except Exception:
                n = 0
            return n >= MIN_EVIDENCE_CALLS

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

        qual = [p for p in order if qualified(p)]
        unqual = [p for p in order if not qualified(p)]
        out[band] = sorted(qual, key=key) + unqual
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
    """Auto-tune flag from routing-policy.yaml.

    Explicit value wins (non-bool falls back to off). A keyless but
    readable policy file defaults ON: auto-tune is the product default,
    while missing or malformed files fail safe to off. Never raises.
    """
    try:
        p = Path(path)
        if not p.exists():
            return False
        data = yaml.safe_load(p.read_text())
        if not isinstance(data, dict):
            return False
        if 'auto_tune' not in data:
            return True
        val = data['auto_tune']
        return val if isinstance(val, bool) else False
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


def read_pinned_bands(path) -> dict:
    """Pinned bands from routing-policy.yaml; {} on absence or failure.

    A pinned band keeps its file order verbatim: auto-tune and auto-wire
    must never reorder it (manual wins). Unknown bands are dropped.
    """
    try:
        p = Path(path)
        if not p.exists():
            return {}
        data = yaml.safe_load(p.read_text())
        if not isinstance(data, dict):
            return {}
        raw = data.get('pinned_bands')
        if not isinstance(raw, dict):
            return {}
        return {str(b): bool(v) for b, v in raw.items() if b in BANDS}
    except Exception:
        return {}


def write_pin(path, band: str, pinned: bool) -> bool:
    """Set pinned_bands[band]; rejects unknown bands; preserves all other
    keys. Atomic tmp+replace. Returns True on success.
    """
    try:
        if band not in BANDS:
            return False
        p = Path(path)
        data = {}
        if p.exists():
            loaded = yaml.safe_load(p.read_text())
            if isinstance(loaded, dict):
                data = loaded
        pins = data.get('pinned_bands')
        pins = dict(pins) if isinstance(pins, dict) else {}
        pins[str(band)] = bool(pinned)
        data['pinned_bands'] = pins
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
    auto_tune on: outcome-ranked orders, applied=True; pinned bands keep
    their file order verbatim. Never raises.
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
        pins = read_pinned_bands(policy_path)
        for band, pin in pins.items():
            if pin and band in suggested:
                suggested[band] = orders.get(band) or suggested[band]
        return suggested, True
    except Exception:
        try:
            return load_band_orders(policy_path), False
        except Exception:
            return {b: list(n) for b, n in DEFAULT_BAND_ORDERS.items()}, False
