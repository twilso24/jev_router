# TDD RED: persisted call outcomes + tuning report composition.
# telemetry.calls table and webui_data.tuning_report do not exist yet.
# Run: /opt/venv-a0/bin/python tests/test_telemetry_calls.py
import sqlite3
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import telemetry, webui_data


def test_record_call_and_preset_stats():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = telemetry.init_db(db)
        telemetry.record_call(conn, 'prov1', 'Fast', True, 0.5, None)
        telemetry.record_call(conn, 'prov1', 'Fast', False, 1.0, 'boom')
        telemetry.record_call(conn, 'prov2', 'Default', True, 0.2, None)
        stats = telemetry.preset_call_stats(conn, limit=100)
        assert stats['Fast'] == {'ok': 1, 'fail': 1}
        assert stats['Default'] == {'ok': 1, 'fail': 0}
        conn.close()


def test_preset_stats_limit_only_recent():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = telemetry.init_db(db)
        for _ in range(5):
            telemetry.record_call(conn, 'p', 'Old', True, 0.1, None)
        telemetry.record_call(conn, 'p', 'New', False, 0.1, 'x')
        stats = telemetry.preset_call_stats(conn, limit=1)
        assert 'Old' not in stats
        assert stats['New'] == {'ok': 0, 'fail': 1}
        conn.close()


def test_tuning_report_shape():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        pol = Path(td) / 'policy.yaml'
        pol.write_text(
            'band_orders:\n  light: [Fast, Default]\n')
        conn = telemetry.init_db(db)
        telemetry.record_call(conn, 'p', 'Fast', True, 0.1, None)
        conn.close()
        rep = webui_data.tuning_report(db, pol, ['Fast', 'Default', 'Power'])
        assert rep['current']['light'] == ['Fast', 'Default']
        assert sorted(rep['suggested'].keys()) == ['heavy', 'light', 'medium']
        # Fast is healthy, Default untouched: Fast stays first in light
        assert rep['suggested']['light'][0] == 'Fast'
        assert 'Default' in rep['suggested']['light']
        assert rep['stats'].get('Fast', {}).get('ok') == 1


def test_tuning_report_missing_db_is_empty_stats():
    with tempfile.TemporaryDirectory() as td:
        rep = webui_data.tuning_report(
            Path(td) / 'none.db', Path(td) / 'none.yaml', ['Fast'])
        assert rep['stats'] == {}
        assert rep['suggested']['light'] == ['Fast']


def _main():
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith('test_') and callable(v)]
    passed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print(f'PASS {name}')
        except Exception as exc:
            print(f'FAIL {name}: {exc}')
    print(f'--- {passed}/{len(fns)} passed')
    if passed != len(fns):
        raise SystemExit(1)


def test_provider_call_stats():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = telemetry.init_db(db)
        telemetry.record_call(conn, 'prov1', 'Fast', True, 0.1, None)
        telemetry.record_call(conn, 'prov1', 'Default', False, 0.2, 'e')
        telemetry.record_call(conn, 'prov2', 'Fast', True, 0.1, None)
        stats = telemetry.provider_call_stats(conn, limit=100)
        assert stats['prov1'] == {'ok': 1, 'fail': 1}
        assert stats['prov2'] == {'ok': 1, 'fail': 0}
        conn.close()



def test_record_decision_persists_session_id():
    from helpers.policy import Decision
    from helpers.signals import Signals
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = telemetry.init_db(db)
        d = Decision(None, 'light', 'test reason')
        sig = Signals('chat', 1.0, 0.0, 0.0, 0.0)
        telemetry.record_decision(conn, d, sig, 'dig1', session_id='ctx-1')
        row = telemetry.last_decisions(conn, limit=1)[0]
        assert row['session_id'] == 'ctx-1', dict(row)
        conn.close()


def test_init_db_migrates_legacy_schema_without_session_id():
    import sqlite3
    from helpers.policy import Decision
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 'old.db'
        conn = sqlite3.connect(db)
        conn.execute('''CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            msg_digest TEXT NOT NULL,
            task_class TEXT,
            complexity REAL,
            band TEXT,
            vision REAL,
            delegate REAL,
            target TEXT,
            reason TEXT,
            compromise INTEGER NOT NULL DEFAULT 0
        )''')
        conn.commit()
        conn.close()
        conn = telemetry.init_db(db)
        telemetry.record_decision(
            conn, Decision(None, 'light', 'r'), None, 'd2', session_id='s2')
        row = telemetry.last_decisions(conn, limit=1)[0]
        assert row['session_id'] == 's2', dict(row)
        conn.close()


# --- T3: fit/profile telemetry columns + legacy migration ---
from helpers.policy import Decision
from helpers.signals import Signals


def test_decisions_fit_columns_exist_after_init():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(decisions)')}
        conn.close()
        assert {'preset_fit', 'profile_match', 'fit_used'} <= cols


def test_record_decision_persists_fit_fields():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        sig = Signals(task_class='coding', task_class_confidence=0.9,
                      complexity=1.5, vision_needed=0.0, delegate_worthy=0.1,
                      preset_fit='Efficiency', preset_fit_confidence=0.9,
                      profile_match='developer')
        d = Decision(None, 'heavy', 'reason text')
        d.fit_used = True
        telemetry.record_decision(conn, d, sig, 'dig')
        row = telemetry.last_decisions(conn, 1)[0]
        conn.close()
        assert row['preset_fit'] == 'Efficiency'
        assert row['profile_match'] == 'developer'
        assert row['fit_used'] == 1


def test_record_decision_none_signals_nulls_fit_fields():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        d = Decision(None, 'unknown', 'jev query failed')
        telemetry.record_decision(conn, d, None, 'dig')
        row = telemetry.last_decisions(conn, 1)[0]
        conn.close()
        assert row['preset_fit'] is None
        assert row['profile_match'] is None
        assert row['fit_used'] == 0


def test_legacy_db_migration_idempotent():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        raw = sqlite3.connect(db)
        raw.executescript('''
            CREATE TABLE decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                msg_digest TEXT NOT NULL,
                task_class TEXT,
                complexity REAL,
                band TEXT,
                vision REAL,
                delegate REAL,
                target TEXT,
                reason TEXT,
                compromise INTEGER NOT NULL DEFAULT 0
            );
        ''')
        raw.commit()
        raw.close()
        telemetry.init_db(db)
        conn = telemetry.init_db(db)  # second init: no-op, must not raise
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(decisions)')}
        conn.close()
        assert {'session_id', 'preset_fit', 'profile_match', 'fit_used'} <= cols


def test_record_decision_persists_fit_confidence():
    with tempfile.TemporaryDirectory() as td:
        conn = telemetry.init_db(Path(td) / 't.db')
        sig = Signals(task_class='coding', task_class_confidence=0.9,
                      complexity=1.5, vision_needed=0.0, delegate_worthy=0.1,
                      preset_fit='Efficiency', preset_fit_confidence=0.92,
                      profile_match='developer')
        d = Decision(None, 'heavy', 'r')
        telemetry.record_decision(conn, d, sig, 'dig')
        row = telemetry.last_decisions(conn, 1)[0]
        conn.close()
        assert row['fit_confidence'] == 0.92
