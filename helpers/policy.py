# jev_router policy: map signals to a pool entry. Pure code, no LLM.
from dataclasses import dataclass
from pathlib import Path

import yaml

from .pool import PoolEntry
from .signals import Signals

# Preference order per complexity band (preset names). Every preset is
# first-class: each band ranks the full set and the first preset present in
# the live pool wins. Override any band via routing-policy.yaml band_orders.
DEFAULT_BAND_ORDERS = {
    'light': ['Fast', 'Efficiency', 'Default', 'Unhinged', 'Local', 'Power'],
    'medium': ['Default', 'Power', 'Unhinged', 'Local', 'Efficiency', 'Fast'],
    'heavy': ['Power', 'Unhinged', 'Default', 'Local', 'Efficiency', 'Fast'],
}

BANDS = ('light', 'medium', 'heavy')

VISION_THRESHOLD = 0.5


@dataclass
class Decision:
    entry: PoolEntry | None
    band: str
    reason: str
    compromise: bool = False
    wanted: str | None = None
    fit_used: bool = False


def complexity_band(score: float) -> str:
    if score <= 0.66:
        return 'light'
    if score <= 1.33:
        return 'medium'
    return 'heavy'


def load_band_orders(path) -> dict:
    """Merge user band_orders from routing-policy.yaml over the defaults.

    Tolerant of any malformed input: unreadable bands keep their default.
    """
    orders = {band: list(names) for band, names in DEFAULT_BAND_ORDERS.items()}
    try:
        p = Path(path)
        if not p.exists():
            return orders
        data = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return orders
    if not isinstance(data, dict):
        return orders
    raw = data.get('band_orders')
    if not isinstance(raw, dict):
        return orders
    for band in BANDS:
        val = raw.get(band)
        if not isinstance(val, list):
            continue
        names = [str(x).strip() for x in val
                 if isinstance(x, str) and x.strip()]
        if names:
            orders[band] = names
    return orders


def boost_preferred(orders: dict, entries: list[PoolEntry],
                  providers: list) -> dict:
    """Soft-boost presets of preferred providers to band front (stable)."""
    provs = set(providers or [])
    boosts = {e.preset_name for e in entries if e.provider in provs}
    out = {}
    for band, names in orders.items():
        out[band] = ([n for n in names if n in boosts] +
                     [n for n in names if n not in boosts])
    return out


def resolve(sig: Signals, entries: list[PoolEntry],
            band_orders: dict | None = None,
            honor_fit: bool = True,
            fit_min_confidence: float = 0.6) -> Decision:
    band = complexity_band(sig.complexity)
    if not entries:
        return Decision(None, band, 'empty pool: no eligible entries')
    by_preset = {e.preset_name: e for e in entries}
    orders = band_orders or DEFAULT_BAND_ORDERS
    wanted = orders.get(band) or DEFAULT_BAND_ORDERS[band]
    vision_hard = sig.vision_needed > VISION_THRESHOLD

    # Jev's dynamic fit pick: honored only when confident, listed in this
    # band's order, present in the filtered pool, and vision-capable when
    # vision is required. Any other case keeps the legacy decision below.
    if honor_fit and sig.preset_fit:
        try:
            confident = float(sig.preset_fit_confidence) >= float(
                fit_min_confidence)
        except (TypeError, ValueError):
            confident = False
        fit_entry = by_preset.get(sig.preset_fit)
        if (confident and fit_entry is not None
                and sig.preset_fit in wanted
                and not (vision_hard and not fit_entry.vision)):
            chosen = (f'preset {fit_entry.preset_name} '
                      f'({fit_entry.provider}/{fit_entry.model})')
            reason = (f'task_class={sig.task_class} band={band} -> '
                      f'{chosen} [fit]')
            return Decision(fit_entry, band, reason,
                            wanted=wanted[0], fit_used=True)

    deviated_missing = False
    deviated_vision = False
    for name in wanted:
        entry = by_preset.get(name)
        if entry is None:
            deviated_missing = True
            continue
        if vision_hard and not entry.vision:
            deviated_vision = True
            continue
        chosen = f'preset {entry.preset_name} ({entry.provider}/{entry.model})'
        if deviated_vision:
            reason = (f'vision={sig.vision_needed:.2f} required; vision-incapable '
                      f'preferred skipped -> {chosen}')
            return Decision(entry, band, reason, compromise=True, wanted=wanted[0])
        if deviated_missing:
            reason = f'preferred presets unavailable for band={band} -> {chosen}'
            return Decision(entry, band, reason, wanted=wanted[0])
        reason = f'task_class={sig.task_class} band={band} -> {chosen}'
        return Decision(entry, band, reason, wanted=name)

    # No preferred preset usable: deterministic first-fit fallback.
    first = entries[0]
    if vision_hard:
        capable = [e for e in entries if e.vision]
        if not capable:
            return Decision(
                None, band,
                f'empty pool: no vision-capable entry for vision={sig.vision_needed:.2f}')
        first = capable[0]
        reason = (f'vision={sig.vision_needed:.2f} required; preferred unavailable '
                  f'-> vision-capable preset {first.preset_name} '
                  f'({first.provider}/{first.model})')
        return Decision(first, band, reason, compromise=True, wanted=wanted[0])
    reason = (
        f'preferred presets unavailable for band={band} '
        f'-> fallback preset {first.preset_name} ({first.provider}/{first.model})'
    )
    return Decision(first, band, reason, wanted=wanted[0])
