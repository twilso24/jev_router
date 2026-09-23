#!/usr/bin/env python3
# jev_router report: view routing decisions from the telemetry DB.
# Usage: python report.py [limit] [db_path]
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path('/a0/tmp/jev_router_telemetry.db')


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    db = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
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


if __name__ == '__main__':
    sys.exit(main())
