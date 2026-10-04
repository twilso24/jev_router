# jev_router tuning: telemetry-driven band-order suggestions and safe,
# partial policy writes so route tuning is a repeatable one-click step.
import os
import tempfile
import threading
from pathlib import Path

import yaml

from .policy import BANDS, DEFAULT_BAND_ORDERS, load_band_orders

_POLICY_LOCK = threading.Lock()


def _atomic_yaml_write(p: Path, data: dict) -> bool:
    """Write YAML via unique tmp file + os.replace; clean up on failure."""
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), suffix='.yaml.tmp')
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.safe_dump(data, f, sort_keys=False)
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


MIN_EVIDENCE_CALLS = 10


def suggest_band_orders(current: dict, pool_presets: list,
                        preset_stats: dict,
                        band_preset_stats: dict | None = None) -> dict:
    """Suggest band orders from per-band outcome stats (global mode opt-in).

    Two modes:
    - band_preset_stats is a dict (even empty {}): BAND MODE. Each band is
      qualified/ranked ONLY from its own band's stats; a band with no own
      evidence keeps the user's file order. Never re-ranks from global
      stats - that was the Default-everywhere flattening regression
      (global health headed every band regardless of band semantics).
    - band_preset_stats omitted (None): GLOBAL MODE. Legacy callers pass
      aggregate preset_stats and every band ranks from them.

    Per-band evidence: when band_preset_stats provides data for a band,
    qualification and ranking use ONLY that band's stats, so a preset
    that succeeds on light calls can head the light band while another
    heads heavy - no global flattening (production: Default with the most
    global ok calls headed every band).

    Per-band evidence floor: a preset needs at least MIN_EVIDENCE_CALLS
    own ok+fail observations IN THAT BAND to be ranked at all.
    Qualified presets rank healthy-first (most ok first), failing-last
    (fewest failures first); unqualified presets - no or sparse own
    evidence - keep their current relative order after the qualified
    group. Presets absent from the live pool are dropped; unknown pool
    presets are appended. Missing bands fall back to DEFAULT_BAND_ORDERS.
    Pure and total: never raises, covers all bands.
    """
    pool = [str(p) for p in (pool_presets or [])]
    stats = preset_stats if isinstance(preset_stats, dict) else {}
    # None = global mode (omitted kwarg); dict (even {}) = band mode.
    # Do NOT coerce None here - that would make global mode unreachable.
    band_stats = band_preset_stats if isinstance(band_preset_stats, dict) \
        else None
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

        # Band-mode contract: a band with no own evidence keeps the user's
        # file order. Falling back to GLOBAL stats here would re-rank every
        # band from aggregate health (the Default-everywhere flattening the
        # per-band feature exists to remove). Only when band_stats is None
        # (caller explicitly wants global ranking) does global apply.
        if band_stats is not None:
            bdata = band_stats.get(band)
            eff = bdata if isinstance(bdata, dict) and bdata else None
        else:
            eff = stats
        if eff is None:
            # no measured evidence in this band: preserve relative file order
            # (unqualified split still applies - everything is unqualified)
            out[band] = list(order)
            continue

        def qualified(p, eff=eff):
            s = eff.get(p) if isinstance(eff.get(p), dict) else {}
            try:
                n = int(s.get('ok') or 0) + int(s.get('fail') or 0)
            except Exception:
                n = 0
            return n >= MIN_EVIDENCE_CALLS

        def key(p, eff=eff, order=order):
            s = eff.get(p) if isinstance(eff.get(p), dict) else {}
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
        with _POLICY_LOCK:
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
            return _atomic_yaml_write(p, data)
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
        with _POLICY_LOCK:
            p = Path(path)
            data = {}
            if p.exists():
                loaded = yaml.safe_load(p.read_text())
                if isinstance(loaded, dict):
                    data = loaded
            data['auto_tune'] = bool(enabled)
            return _atomic_yaml_write(p, data)
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
        with _POLICY_LOCK:
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
            return _atomic_yaml_write(p, data)
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
        band_stats = None
        if telemetry_path is not None:
            from . import telemetry as tel_mod
            tp = Path(telemetry_path)
            if tp.exists():
                conn = tel_mod.init_db(tp)
                try:
                    stats = tel_mod.preset_call_stats(conn, limit=limit)
                    band_stats = tel_mod.band_preset_call_stats(conn,
                                                                limit=limit)
                finally:
                    conn.close()
        # Band-mode ALWAYS when a telemetry DB was opened - even an empty
        # band_stats ({}: no banded rows yet) must keep file orders, never
        # degrade to global ranking (that was the Default-everywhere bug).
        # Global mode only when the kwarg is omitted (band_stats stays None
        # because no telemetry path was provided).
        suggested = suggest_band_orders(
            orders, list(pool_presets or []), stats,
            band_preset_stats=band_stats)
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
