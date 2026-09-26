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


def test_tuning_report_unwired_and_wire_state():
    with tempfile.TemporaryDirectory() as td:
        policy = Path(td) / 'routing-policy.yaml'
        policy.write_text(yaml.safe_dump({
            'band_orders': {'light': ['Fast'], 'medium': ['Fast'],
                            'heavy': ['Fast']},
        }))
        db = _mk_db(td, 1)
        # sidecar absent -> wire_state None, unwired lists pool-missing name
        rep = webui_data.tuning_report(db, policy, ['Fast', 'Storyteller'])
        assert rep['unwired'] == ['Storyteller']
        assert rep['wire_state'] is None
        # sidecar present -> surfaced verbatim
        state = {
            'added': ['Storyteller'], 'pruned': ['Ghost'], 'ts': 123.456,
        }
        (Path(td) / 'wire-state.json').write_text(
            __import__('json').dumps(state))
        rep = webui_data.tuning_report(db, policy, ['Fast', 'Storyteller'])
        assert rep['wire_state'] == state
        assert rep['unwired'] == ['Storyteller']


def test_tuning_report_auto_tune_off():
    with tempfile.TemporaryDirectory() as td:
        rep = webui_data.tuning_report(
            Path(td) / 'none.db', Path(td) / 'none.yaml', ['Fast'],
            pool_providers=['p1'])
        assert rep['auto_tune'] is False
        assert rep['provider_states'][0]['provider'] == 'p1'


# --- T6: panel data exposes fit/profile judgment fields ---
import tempfile
from pathlib import Path

from helpers import telemetry, webui_data
from helpers.policy import Decision
from helpers.signals import Signals


def _fit_db(td):
    db = Path(td) / 't.db'
    conn = telemetry.init_db(db)
    sig = Signals(task_class='coding', task_class_confidence=0.9,
                  complexity=1.5, vision_needed=0.0, delegate_worthy=0.1,
                  preset_fit='Efficiency', preset_fit_confidence=0.9,
                  profile_match='developer')
    d = Decision(None, 'heavy', 'reason text')
    d.fit_used = True
    telemetry.record_decision(conn, d, sig, 'dig')
    conn.close()
    return db


def test_stats_recent_includes_fit_fields():
    with tempfile.TemporaryDirectory() as td:
        out = webui_data.stats_from_db(_fit_db(td))
        row = out['recent'][0]
        assert row['preset_fit'] == 'Efficiency'
        assert row['profile_match'] == 'developer'
        assert row['fit_used'] is True


def test_stats_recent_fit_fields_absent_when_no_signals():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = telemetry.init_db(db)
        d = Decision(None, 'unknown', 'jev query failed')
        telemetry.record_decision(conn, d, None, 'dig')
        conn.close()
        out = webui_data.stats_from_db(db)
        row = out['recent'][0]
        assert row['preset_fit'] is None
        assert row['profile_match'] is None
        assert row['fit_used'] is False


# --- S2 (TDD) RED: decision card fields rule + reason_human ---

def test_record_decision_stores_rule_and_human_reason():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = tel_mod.init_db(db)
        d = Decision(_entry('Power'), 'heavy', 'row x',
                     rule='fit',
                     reason_human='Best match: Power')
        tel_mod.record_decision(conn, d, Signals('coding', 0.9, 1.8, 0.05, 0.5), 'dx')
        rows = tel_mod.last_decisions(conn, limit=1)
        conn.close()
        assert rows[0]['rule'] == 'fit'
        assert rows[0]['reason_human'] == 'Best match: Power'


def test_stats_recent_includes_rule_and_human_reason():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = tel_mod.init_db(db)
        d = Decision(_entry('Power'), 'heavy', 'row x',
                     rule='band',
                     reason_human='Routed to Power: heavy coding task')
        tel_mod.record_decision(conn, d, Signals('coding', 0.9, 1.8, 0.05, 0.5), 'dx')
        conn.close()
        s = webui_data.stats_from_db(db, limit=5)
        row = s['recent'][0]
        assert row['rule'] == 'band'
        assert row['reason_human'] == 'Routed to Power: heavy coding task'


# --- S4 (TDD) RED: tuning_report exposes pinned_bands ---
def test_tuning_report_includes_pinned_bands():
    with tempfile.TemporaryDirectory() as td:
        pol = Path(td) / 'policy.yaml'
        pol.write_text(yaml.safe_dump({'pinned_bands': {'light': True}}))
        rep = webui_data.tuning_report(
            Path(td) / 't.db', pol, ['Fast'])
        assert rep['pinned_bands'] == {'light': True}

def test_stats_recent_includes_delegation():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = tel_mod.init_db(db)
        d = Decision(_entry('Power'), 'heavy', 'row x')
        tel_mod.record_decision(conn, d, Signals('coding', 0.9, 1.8, 0.05, 0.9),
                                'dx', delegation='advised')
        conn.close()
        s = webui_data.stats_from_db(db, limit=5)
        assert s['recent'][0]['delegation'] == 'advised'

def test_record_and_stats_expose_auto_exec():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = tel_mod.init_db(db)
        d = Decision(_entry('Power'), 'heavy', 'row x')
        tel_mod.record_decision(conn, d, Signals('coding', 0.9, 1.8, 0.05, 0.9),
                                'dx', delegation='directed', auto_exec=True)
        conn.close()
        s = webui_data.stats_from_db(db, limit=5)
        assert s['recent'][0]['auto_exec'] is True


# --- FIX F7 (review fan-out): stats limit must be clamped ---

def test_stats_from_db_clamps_negative_limit():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 't.db'
        conn = tel_mod.init_db(db)
        for i in range(3):
            d = Decision(_entry('Power'), 'heavy', f'row {i}')
            tel_mod.record_decision(conn, d,
                                    Signals('coding', 0.9, 1.8, 0.05, 0.5),
                                    f'd{i}')
        conn.close()
        s = webui_data.stats_from_db(db, limit=-1)
        assert len(s['recent']) == 1


# --- Audit round 2: write_provider_rules must be atomic ---


def test_write_provider_rules_torn_dump_leaves_original(tmp_path, monkeypatch):
    p = tmp_path / 'rp.yaml'
    p.write_text('provider_rules:\n  exclude: [keep_me]\n')

    def partial_dump(data, stream, **kw):
        stream.write('provider_rul')
        raise RuntimeError('dump crashed mid-write')

    monkeypatch.setattr(webui_data.yaml, 'safe_dump', partial_dump)
    ok = webui_data.write_provider_rules(p, exclude=['x'])
    assert ok is False
    import yaml as _yaml
    loaded = _yaml.safe_load(p.read_text())
    assert loaded['provider_rules']['exclude'] == ['keep_me'], \
        'a torn dump must never corrupt the live policy'
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != 'rp.yaml']
    assert leftovers == [], leftovers
