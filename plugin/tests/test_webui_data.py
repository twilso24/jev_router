import tempfile
import time
import yaml
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import webui_data
from helpers import telemetry as tel_mod
from helpers.pool import PoolEntry
from helpers.policy import Decision
from helpers.signals import Signals


def _entry(name):
    return PoolEntry(name, 'chat', 'prov_' + name, 'model-' + name.lower())


def _mk_db(td, n=3):
    db = Path(td) / 't.db'
    conn = tel_mod.init_db(db)
    for i in range(n):
        target = None if i == 2 else ('Power' if i % 2 else 'Efficiency')
        d = Decision(_entry(target) if target else None,
                     'heavy' if i % 2 else 'light',
                     f'row {i}', compromise=(i == 0))
        sig = Signals('coding', 0.9, 1.8, 0.05, 0.5)
        tel_mod.record_decision(conn, d, sig, f'd{i}')
    conn.close()
    return db


def test_stats_recent_and_aggregates():
    with tempfile.TemporaryDirectory() as td:
        db = _mk_db(td, 3)
        s = webui_data.stats_from_db(db, limit=10)
        assert len(s['recent']) == 3
        assert s['totals']['decisions'] == 3
        by = s['by_preset']
        assert by['Efficiency']['count'] == 1
        assert by['Power']['count'] == 1
        assert by[None]['count'] == 1


def test_stats_empty_db_ok():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        tel_mod.init_db(db).close()
        s = webui_data.stats_from_db(db, limit=5)
        assert s['recent'] == []
        assert s['totals']['decisions'] == 0


def test_breaker_snapshot_shape():
    from helpers import circuit_breaker as cb
    cb._STATES.clear()
    cb.record_fail('p1')
    cb.record_fail('p2', 5)
    snap = webui_data.breaker_snapshot()
    names = {x['provider']: x for x in snap}
    assert names['p1']['failures'] == 1
    assert names['p2']['failures'] == 5
    assert names['p2']['excluded'] is True
    cb._STATES.clear()


def test_policy_read_and_write():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'rp.yaml'
        f.write_text('provider_rules:\n  include: []\n  exclude: []\n')
        pol = webui_data.read_policy(f)
        assert pol['provider_rules']['exclude'] == []
        webui_data.write_provider_rules(f, exclude=['zai_coding'])
        pol2 = webui_data.read_policy(f)
        assert pol2['provider_rules']['exclude'] == ['zai_coding']


def test_write_provider_rules_dedupes_exclude():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'rp.yaml'
        f.write_text('provider_rules:\n  include: []\n  exclude: []\n')
        ok = webui_data.write_provider_rules(
            f, exclude=['zai_coding', 'zai_coding', '', ' a0_venice ', 'zai_coding'])
        assert ok is True
        assert webui_data.read_policy(f)['provider_rules']['exclude'] == ['zai_coding', 'a0_venice']


def test_pool_providers_distinct_sorted():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'presets.yaml'
        f.write_text(
            '- name: A\n  chat:\n    provider: prov2\n    name: m1\n'
            '- name: B\n  chat:\n    provider: prov1\n    name: m2\n'
            '- name: C\n  chat:\n    provider: prov1\n    name: m3\n')
        assert webui_data.pool_providers(f) == ['prov1', 'prov2']


def test_tuning_report_auto_tune_and_provider_states():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        pol = Path(td) / 'policy.yaml'
        pol.write_text(yaml.safe_dump({
            'auto_tune': True,
            'provider_rules': {'include': [], 'exclude': ['prov1']},
        }))
        conn = tel_mod.init_db(db)
        tel_mod.record_call(conn, 'prov1', 'Fast', True, 0.1, None)
        tel_mod.record_call(conn, 'prov2', 'Fast', False, 0.1, 'e')
        conn.close()
        rep = webui_data.tuning_report(
            db, pol, ['Fast'], pool_providers=['prov1', 'prov2'])
        assert rep['auto_tune'] is True
        ps = {p2['provider']: p2 for p2 in rep['provider_states']}
        assert ps['prov1']['excluded'] is True
        assert ps['prov1']['tripped'] is False
        assert ps['prov1']['ok'] == 1
        assert ps['prov2']['fail'] == 1


def test_tuning_report_auto_tune_off():
    with tempfile.TemporaryDirectory() as td:
        rep = webui_data.tuning_report(
            Path(td) / 'none.db', Path(td) / 'none.yaml', ['Fast'],
            pool_providers=['p1'])
        assert rep['auto_tune'] is False
        assert rep['provider_states'][0]['provider'] == 'p1'


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS {t.__name__}')
        except Exception as exc:
            failed += 1
            print(f'FAIL {t.__name__}: {type(exc).__name__}: {exc}')
    print(f'--- {len(tests) - failed}/{len(tests)} passed')
