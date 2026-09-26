#!/usr/bin/env python3
# jev_router report: view routing decisions from the telemetry DB.
# Usage: python report.py [limit] [db_path]
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path('/a0/tmp/jev_router_telemetry.db')


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == 'dial':
        return _main_dial(args[1:])
    limit = int(args[0]) if args else 20
    db = Path(args[1]) if len(args) > 1 else DEFAULT_DB
    if not db.exists():
        print(f'no telemetry db at {db}')
        return 1
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT ts, task_class, complexity, band, vision, delegate, '
        'target, reason, compromise FROM decisions '
        'ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    if not rows:
        print('no decisions logged yet')
        return 0
    print(f'{len(rows)} most recent decisions ({db}):')
    for r in rows:
        comp = ' [COMPROMISE]' if r['compromise'] else ''
        vis = f' vis={r["vision"]:.2f}' if r['vision'] is not None else ''
        print(f"- {r['target'] or 'KEEP-MODEL'}{comp} | {r['task_class'] or '-'} "
              f"cx={r['complexity'] if r['complexity'] is not None else '-'} "
              f"band={r['band']}{vis} | {r['reason']}")
    conn.close()
    return 0


def dial_summary(config_path, policy_path, telemetry_path) -> dict:
    """Dial-aware evidence summary; pure read, never raises.

    Returns {dial, auto_tune, pins, preset_stats, orders} where orders are
    the policy file orders with the performance dial applied (pinned bands
    keep file order). preset_stats are per-preset ok/fail outcomes from the
    telemetry DB - the evidence auto-tune ranks on. Missing or malformed
    inputs fall back to safe defaults (balanced, off, empty).
    """
    try:
        dial = 'balanced'
        try:
            data = json.loads(Path(config_path).read_text())
            dial = str(data.get('performance_dial') or 'balanced')
        except Exception:
            dial = 'balanced'
        auto_tune = False
        pins = {}
        orders = {}
        try:
            from helpers import tuning as tuning_mod
            from helpers.policy import load_band_orders
            auto_tune = bool(tuning_mod.read_auto_tune(policy_path))
            pins = tuning_mod.read_pinned_bands(policy_path)
            if Path(policy_path).exists():
                orders = load_band_orders(policy_path) or {}
        except Exception:
            auto_tune, pins, orders = False, {}, {}
        stats = {}
        try:
            from helpers.telemetry import preset_call_stats
            tp = Path(telemetry_path)
            if tp.exists():
                conn = sqlite3.connect(tp)
                conn.row_factory = sqlite3.Row
                try:
                    stats = preset_call_stats(conn)
                finally:
                    conn.close()
        except Exception:
            stats = {}
        out_orders = orders
        if dial != 'balanced':
            try:
                from helpers.dial import apply_dial
                out_orders = apply_dial(orders, dial, pins)
            except Exception:
                out_orders = orders
        return {'dial': dial, 'auto_tune': bool(auto_tune), 'pins': pins,
                'preset_stats': stats, 'orders': out_orders}
    except Exception:
        return {'dial': 'balanced', 'auto_tune': False, 'pins': {},
                'preset_stats': {}, 'orders': {}}


def _main_dial(args) -> int:
    here = Path(__file__).resolve().parent
    cfg = Path(args[0]) if len(args) > 0 else here / 'config.json'
    pol = Path(args[1]) if len(args) > 1 else here / 'routing-policy.yaml'
    db = Path(args[2]) if len(args) > 2 else DEFAULT_DB
    s = dial_summary(cfg, pol, db)
    pins = [b for b, v in s['pins'].items() if v] or 'none'
    print(f"dial={s['dial']} auto_tune={'on' if s['auto_tune'] else 'off'} "
          f"pins={pins} ({db})")
    if s['preset_stats']:
        print('per-preset call outcomes (recent):')
        for name in sorted(s['preset_stats']):
            st = s['preset_stats'][name]
            print(f"  {name}: ok={st['ok']} fail={st['fail']}")
    else:
        print('no call outcomes recorded yet')
    if s['orders']:
        print('orders (file + dial, pins honored):')
        for band in sorted(s['orders']):
            print(f"  {band}: {' > '.join(s['orders'][band])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
