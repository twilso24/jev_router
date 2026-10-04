#!/usr/bin/env python3
# jev_router report: view routing decisions from the telemetry DB.
# Usage: python report.py [limit] [db_path]
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path('/a0/tmp/jev_router_telemetry.db')


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = argv
    if args and args[0] == 'dial':
        return _main_dial(args[1:])
    if args and args[0] == 'percentile':
        return _main_percentile(args[1:])
    if args and args[0] == 'fallback':
        return _main_fallback(args[1:])
    if args and args[0] == 'session':
        return _main_session(args[1:])
    if args and args[0] == 'shadow':
        return _main_shadow(args[1:])
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


def evidence_summary(config_path, policy_path, telemetry_path) -> dict:
    """Evidence summary; pure read, never raises. No performance dial.

    Returns {auto_tune, pins, preset_stats, orders} where orders are the
    policy file orders exactly (band orders are the sole ranking truth;
    pins freeze a band against auto-tune, nothing re-ranks it). preset_stats
    are per-preset ok/fail outcomes from the telemetry DB - the evidence
    auto-tune ranks on. Missing or malformed inputs fall back to safe
    defaults (off, empty).
    """
    try:
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
        band_stats = {}
        try:
            from helpers.telemetry import (preset_call_stats,
                                           band_preset_call_stats)
            tp = Path(telemetry_path)
            if tp.exists():
                conn = sqlite3.connect(tp)
                conn.row_factory = sqlite3.Row
                try:
                    stats = preset_call_stats(conn)
                    band_stats = band_preset_call_stats(conn)
                finally:
                    conn.close()
        except Exception:
            stats, band_stats = {}, {}
        return {'auto_tune': bool(auto_tune), 'pins': pins,
                'preset_stats': stats, 'orders': orders,
                'band_stats': band_stats}
    except Exception:
        return {'auto_tune': False, 'pins': {},
                'preset_stats': {}, 'orders': {}, 'band_stats': {}}


def _main_dial(args) -> int:
    here = Path(__file__).resolve().parent
    cfg = Path(args[0]) if len(args) > 0 else here / 'config.json'
    pol = Path(args[1]) if len(args) > 1 else here / 'routing-policy.yaml'
    db = Path(args[2]) if len(args) > 2 else DEFAULT_DB
    s = evidence_summary(cfg, pol, db)
    pins = [b for b, v in s['pins'].items() if v] or 'none'
    print(f"auto_tune={'on' if s['auto_tune'] else 'off'} "
          f"pins={pins} ({db})")
    if s['preset_stats']:
        print('per-preset call outcomes (recent):')
        for name in sorted(s['preset_stats']):
            st = s['preset_stats'][name]
            print(f"  {name}: ok={st['ok']} fail={st['fail']}")
    else:
        print('no call outcomes recorded yet')
    if s.get('band_stats'):
        print('per-band call outcomes (band=' + ',band='.join(
            sorted(s['band_stats'])) + '):')
        for band in sorted(s['band_stats']):
            for name in sorted(s['band_stats'][band]):
                st = s['band_stats'][band][name]
                print(f"  band={band} {name}: ok={st['ok']} fail={st['fail']}")
    if s['orders']:
        print('orders (file, pins honored):')
        for band in sorted(s['orders']):
            print(f"  {band}: {' > '.join(s['orders'][band])}")
    return 0


def _main_percentile(args) -> int:
    here = Path(__file__).resolve().parent
    db = Path(args[0]) if len(args) > 0 else DEFAULT_DB
    if not db.exists():
        print(f'no telemetry db at {db}')
        return 1
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        from helpers.telemetry import preset_duration_stats
        stats = preset_duration_stats(conn)
    finally:
        conn.close()
    if not stats:
        print('no call durations recorded yet')
        return 0
    print(f'Per-preset latency percentiles (p50/p95/p99) over recent successful calls ({db}):')
    for preset in sorted(stats):
        s = stats[preset]
        print(f"  {preset}: p50={s['p50']:.3f}s p95={s['p95']:.3f}s p99={s['p99']:.3f}s (count={s['count']}, avg={s['avg']:.3f}s)")
    return 0


def _main_fallback(args) -> int:
    here = Path(__file__).resolve().parent
    db = Path(args[0]) if len(args) > 0 else DEFAULT_DB
    if not db.exists():
        print(f'no telemetry db at {db}')
        return 1
    from helpers.telemetry import init_db, preset_call_stats
    conn = init_db(db)
    try:
        stats = preset_call_stats(conn)
        # Also show fallback info from recent calls
        cur = conn.execute(
            'SELECT provider, preset, ok, error, fallback_from_preset '
            'FROM calls WHERE fallback_from_preset IS NOT NULL '
            'ORDER BY id DESC LIMIT 20')
        rows = cur.fetchall()
    finally:
        conn.close()
    
    if not rows:
        print('no fallback calls recorded yet')
        if stats:
            print('per-preset call outcomes (recent):')
            for name in sorted(stats):
                st = stats[name]
                print(f"  {name}: ok={st['ok']} fail={st['fail']}")
        return 0
    
    print(f'Recent fallback calls ({db}):')
    for r in rows:
        status = 'OK' if r['ok'] else 'FAIL'
        fallback_info = f" <- fallback from {r['fallback_from_preset']}" if r['fallback_from_preset'] else ''
        err = f" | {r['error']}" if r['error'] else ''
        print(f"  {r['provider']}/{r['preset']} {status}{fallback_info}{err}")
    return 0


def _main_session(args) -> int:
    here = Path(__file__).resolve().parent
    db = Path(args[0]) if len(args) > 0 else DEFAULT_DB
    session_id = args[1] if len(args) > 1 else None
    if not db.exists():
        print(f'no telemetry db at {db}')
        return 1
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        from helpers.telemetry import session_decision_stats
        if session_id:
            stats = session_decision_stats(conn, session_id)
            print(f'Session {session_id} stats ({db}):')
            print(f"  Decisions: {stats['decisions']}")
            print(f"  Model switches: {stats['model_switches']}")
            print(f"  Fallback rate: {stats['fallback_rate']:.1%}")
            if stats['band_dist']:
                print('  Band distribution:')
                for band, count in sorted(stats['band_dist'].items()):
                    print(f"    {band}: {count}")
        else:
            # Show all sessions summary
            cur = conn.execute(
                'SELECT session_id, COUNT(*) as cnt, '
                'SUM(CASE WHEN target IS NULL OR target = "" THEN 1 ELSE 0 END) as fallbacks '
                'FROM decisions WHERE session_id != "" '
                'GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 20')
            rows = cur.fetchall()
            if not rows:
                print('no session data recorded yet')
                return 0
            print(f'Recent sessions ({db}):')
            for r in rows:
                fb_rate = r['fallbacks'] / r['cnt'] if r['cnt'] > 0 else 0
                print(f"  {r['session_id']}: {r['cnt']} decisions, {fb_rate:.1%} fallback")
    finally:
        conn.close()
    return 0


def _main_shadow(args) -> int:
    here = Path(__file__).resolve().parent
    db = Path(args[0]) if len(args) > 0 else DEFAULT_DB
    if not db.exists():
        print(f'no telemetry db at {db}')
        return 1
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            'SELECT ts, target, shadow_target, band, reason '
            'FROM decisions WHERE shadow_target IS NOT NULL '
            'ORDER BY id DESC LIMIT 20')
        rows = cur.fetchall()
    finally:
        conn.close()
    
    if not rows:
        print('no shadow mode decisions recorded yet')
        return 0
    
    print(f'Shadow mode decisions (actual vs predicted) ({db}):')
    for r in rows:
        actual = r['target'] or 'KEEP-MODEL'
        predicted = r['shadow_target']
        match = '✓' if actual == predicted else '✗'
        print(f"  {match} actual={actual} predicted={predicted} band={r['band']} | {r['reason'][:60]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
