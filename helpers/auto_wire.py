# jev_router auto-wire: keep band orders in sync with the live pool.
#
# New chat presets (any name) are appended to the tail of every band order;
# names removed from presets.yaml are pruned. Writes happen only on change
# (atomic, via tuning.write_band_orders) and a JSON sidecar records the last
# report for the WebUI panel. Never raises.
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import tuning
from .policy import load_band_orders


@dataclass
class WireReport:
    added: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    ts: float = 0.0


def unwired_presets(policy_path, pool_presets) -> list:
    """Pool presets missing from every band order (steady state: [])."""
    try:
        orders = load_band_orders(policy_path)
        listed = set()
        for names in orders.values():
            listed.update(str(n) for n in names)
        pool = [str(p) for p in (pool_presets or [])]
        seen, out = set(), []
        for p in pool:
            if p not in listed and p not in seen:
                seen.add(p)
                out.append(p)
        return out
    except Exception:
        return []


def read_wire_state(state_path) -> dict | None:
    """Last persisted wire report, or None when absent/unreadable."""
    try:
        p = Path(state_path)
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def sync_band_orders(policy_path, pool_presets, state_path=None) -> WireReport:
    """Sync band orders with the live pool. Pure filesystem effect:
    append missing presets to each band tail, prune dead names, write only
    on change, persist report only on real change. Never raises."""
    empty = WireReport()
    try:
        pool = []
        seen = set()
        for p in (pool_presets or []):
            sp = str(p)
            if sp and sp not in seen:
                seen.add(sp)
                pool.append(sp)
        orders = load_band_orders(policy_path)

        listed = set()
        for names in orders.values():
            listed.update(str(n) for n in names)
        added = [p for p in pool if p not in listed]

        pruned: list = []
        pruned_seen = set()
        new_orders = {}
        for band, names in orders.items():
            kept = []
            for n in names:
                sn = str(n)
                if sn in pool:
                    kept.append(sn)
                elif sn not in pruned_seen:
                    pruned_seen.add(sn)
                    pruned.append(sn)
            new_orders[band] = kept

        if added or pruned:
            for band in new_orders:
                new_orders[band] = new_orders[band] + [
                    p for p in added if p not in new_orders[band]]
            ok = tuning.write_band_orders(policy_path, new_orders)
            if not ok:
                return empty
            report = WireReport(added=added, pruned=pruned, ts=time.time())
            if state_path is not None:
                try:
                    sp = Path(state_path)
                    sp.parent.mkdir(parents=True, exist_ok=True)
                    sp.write_text(json.dumps({
                        'added': report.added,
                        'pruned': report.pruned,
                        'ts': report.ts,
                    }))
                except Exception:
                    pass
            return report
        return empty
    except Exception:
        return empty
