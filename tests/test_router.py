# Task 6 (TDD): router core - RED first.
# helpers/router.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_router.py
import asyncio
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import router, telemetry
from helpers.signals import Signals


def _cfg(enabled=True):
    return {'enabled': enabled, 'jev_timeout_s': 2.0,
            'delegation_threshold': 0.6}


def _entries():
    # preset_name, role, provider, model, vision
    return [
        ('Default', 'zai_coding', 'glm-5.3-flash', True),
        ('Efficiency', 'a0_venice', 'deepseek-v4-1-flash', True),
        ('Power', 'zai_coding', 'glm-5.3', False),
    ]


def _mk_entries():
    from helpers.pool import PoolEntry
    return [PoolEntry(n, 'chat', p, m, vision=v) for n, p, m, v in _entries()]


def _fake_query(sig):
    async def q(client, state, questions, model):
        if isinstance(sig, Exception):
            raise sig
        return {'answers': {
            'task_class': {'type': 'choice', 'choice': sig.task_class,
                           'confidence': sig.task_class_confidence,
                           'probabilities': {}},
            'complexity': {'type': 'score', 'score': sig.complexity,
                           'legend': {}, 'probabilities': {}},
            'vision_needed': {'type': 'noul', 'noul': sig.vision_needed},
            'delegate_worthy': {'type': 'noul', 'noul': sig.delegate_worthy},
        }}
    return q


MOCK_SENTINEL_MODEL = object()


def test_enabled_routes_coding_heavy_to_power():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'tel.db'
            made = []
            def factory(entry):
                made.append(entry.preset_name)
                return f'MODEL[{entry.preset_name}]'
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(), policy_path=Path(td) / 'p.yaml',
                message='refactor the auth module and add tests', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=factory, telemetry_path=db)
            assert res.model == 'MODEL[Power]', res.reason
            assert made == ['Power']
            assert 'band=heavy' in res.reason
            assert res.fallback is False
            assert telemetry.last_decisions(telemetry.init_db(db))[0]['target'] == 'Power'
    asyncio.run(run())


def test_disabled_passthrough_keeps_model():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def factory(entry):
                calls.append(entry)
                return 'NEW'
            res = await router.route(
                cfg=_cfg(enabled=False), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='anything at all', attachments=[],
                query_fn=_fake_query(Exception('must not be called')),
                client=object(), jev_model='jev-latest',
                model_factory=factory,
                telemetry_path=Path(td) / 'tel.db')
            assert res.model is None
            assert calls == []
            assert res.fallback is False
            assert 'disabled' in res.reason
    asyncio.run(run())


def test_jev_failure_keeps_model_and_logs_fallback():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'tel.db'
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze the quarterly data and build a forecast', attachments=[],
                query_fn=_fake_query(RuntimeError('jev down')),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: 'X', telemetry_path=db)
            assert res.model is None
            assert res.fallback is True
            assert 'jev' in res.reason.lower()
            rows = telemetry.last_decisions(telemetry.init_db(db))
            assert len(rows) == 1 and rows[0]['target'] is None
    asyncio.run(run())


def test_fastpath_trivial_routes_light_without_jev():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'tel.db'
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='hey there!', attachments=[],
                query_fn=_fake_query(Exception('must not be called')),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=db)
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert 'fast-path' in res.reason
    asyncio.run(run())


def test_never_raises_on_total_garbage():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            def factory(entry):
                raise ValueError('factory boom')
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='hello world', attachments=[],
                query_fn=_fake_query(Exception('x')),
                client=object(), jev_model='jev-latest',
                model_factory=factory,
                telemetry_path=Path(td) / 'tel.db')
            assert res.model is None and res.fallback is True
    asyncio.run(run())


def test_advice_present_when_gate_recommends():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files',
                attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.85)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: 'X', telemetry_path=Path(td) / 't.db')
            assert res.advice is not None
            assert 'developer' in res.advice
    asyncio.run(run())


def test_advice_absent_below_threshold():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files',
                attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.2)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: 'X', telemetry_path=Path(td) / 't.db')
            assert res.advice is None
    asyncio.run(run())




def test_fastpath_triggers_through_protocol_wrapper():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            raw = '{"user_message":"hey"}\n[EXTRAS]\n' + '{"padding":"' + 'x' * 300 + '"}'
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message=raw, attachments=[],
                query_fn=_fake_query(Exception('must not be called')),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert 'fast-path' in res.reason, res.reason
    asyncio.run(run())




def test_router_passes_pool_snapshot_to_jev():
    async def run():
        # isolate from process-local breaker state left by earlier tests
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        captured = {}

        async def q(client, state, questions, model):
            captured['state'] = state
            return {'answers': {
                'task_class': {'type': 'choice', 'choice': 'coding',
                               'confidence': 0.9, 'probabilities': {}},
                'complexity': {'type': 'score', 'score': 1.8,
                               'legend': {}, 'probabilities': {}},
                'vision_needed': {'type': 'noul', 'noul': 0.05},
                'delegate_worthy': {'type': 'noul', 'noul': 0.2},
            }}

        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files',
                attachments=[], query_fn=q, client=object(),
                jev_model='jev-latest', model_factory=lambda e: 'X',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'X'
            snap = captured['state'].get('available_models')
            assert snap and len(snap) == 3, snap
            assert snap[0]['preset'] == 'Default'
            assert snap[2]['model'] == 'glm-5.3'
            assert snap[0]['vision'] is True
    asyncio.run(run())




def test_router_respects_yaml_band_orders():
    async def run():
        # isolate from process-local breaker state left by earlier tests
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        import yaml
        from helpers.pool import PoolEntry
        entries = _mk_entries() + [
            PoolEntry('Local', 'chat', 'lm_studio', 'qwen3.8-27b'),
            PoolEntry('Unhinged', 'chat', 'a0_venice', 'qwen-3-6-plus'),
            PoolEntry('Fast', 'chat', 'a0_venice', 'mercury-2-5'),
        ]
        with tempfile.TemporaryDirectory() as td:
            rp = Path(td) / 'rp.yaml'
            rp.write_text(yaml.safe_dump({'band_orders': {
                'heavy': ['Local', 'Power'],
                'light': ['Fast', 'Efficiency'],
            }}))
            res = await router.route(
                cfg=_cfg(), entries=entries, policy_path=rp,
                message='please analyze and refactor the authentication module across files',
                attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Local]', res.reason
    asyncio.run(run())




def test_router_applies_schedule_exclude():
    async def run():
        import yaml
        with tempfile.TemporaryDirectory() as td:
            rp = Path(td) / 'rp.yaml'
            rp.write_text(yaml.safe_dump({'schedules': [
                {'name': 'no-zai', 'exclude': ['zai_coding']},
            ]}))
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(), policy_path=rp,
                message='please analyze and refactor the authentication module across files',
                attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert 'unavailable' in res.reason
            assert '[schedule:no-zai]' in res.reason, res.reason
    asyncio.run(run())


def test_router_applies_schedule_prefer():
    async def run():
        import yaml
        with tempfile.TemporaryDirectory() as td:
            rp = Path(td) / 'rp.yaml'
            rp.write_text(yaml.safe_dump({'schedules': [
                {'name': 'prefer-zai', 'prefer': ['zai_coding']},
            ]}))
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(), policy_path=rp,
                message='hey!', attachments=[],
                query_fn=_fake_query(Exception('must not be called')),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Default]', res.reason
            assert '[schedule:prefer-zai]' in res.reason, res.reason
            assert 'unavailable' not in res.reason
    asyncio.run(run())




def test_router_applies_mention_exclude():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='stop using zai for this task, please analyze and refactor the authentication module across files',
                attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert '[mention]' in res.reason, res.reason
    asyncio.run(run())


def test_router_mention_free_dial_tags_fastpath():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='hey there! use free models', attachments=[],
                query_fn=_fake_query(Exception('must not be called')),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert 'fast-path' in res.reason
            assert '[mention]' in res.reason, res.reason
    asyncio.run(run())





def test_router_excludes_trippped_providers():
    async def run():
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        for _ in range(circuit_breaker.DEFAULT_THRESHOLD + 1):
            circuit_breaker.record_fail('zai_coding')
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert '[circuit-breaker]' in res.reason, res.reason
    asyncio.run(run())


def test_router_success_resets_circuit():
    async def run():
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        for _ in range(circuit_breaker.DEFAULT_THRESHOLD + 1):
            circuit_breaker.record_fail('zai_coding')
        circuit_breaker.record_success('zai_coding')
        with tempfile.TemporaryDirectory() as td:
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Power]', res.reason
    asyncio.run(run())


def test_router_factory_failures_trip_provider():
    async def run():
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()

        def boom(entry):
            raise ValueError('provider down')

        with tempfile.TemporaryDirectory() as td:
            for _ in range(circuit_breaker.DEFAULT_THRESHOLD):
                res = await router.route(
                    cfg=_cfg(), entries=_mk_entries(),
                    policy_path=Path(td) / 'p.yaml',
                    message='please analyze and refactor the authentication module across files', attachments=[],
                    query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                    client=object(), jev_model='jev-latest',
                    model_factory=boom,
                    telemetry_path=Path(td) / 't.db')
                assert res.model is None and res.fallback is True
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert '[circuit-breaker]' in res.reason, res.reason
    asyncio.run(run())


def test_router_custom_breaker_threshold():
    async def run():
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        cfg = _cfg()
        cfg['breaker_threshold'] = 2

        def boom(entry):
            raise ValueError('down')

        with tempfile.TemporaryDirectory() as td:
            for _ in range(2):
                await router.route(
                    cfg=cfg, entries=_mk_entries(),
                    policy_path=Path(td) / 'p.yaml',
                    message='please analyze and refactor the authentication module across files', attachments=[],
                    query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                    client=object(), jev_model='jev-latest',
                    model_factory=boom,
                    telemetry_path=Path(td) / 't.db')
            res = await router.route(
                cfg=cfg, entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='please analyze and refactor the authentication module across files', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: f'MODEL[{e.preset_name}]',
                telemetry_path=Path(td) / 't.db')
            assert res.model == 'MODEL[Efficiency]', res.reason
            assert '[circuit-breaker]' in res.reason, res.reason
    asyncio.run(run())

def test_auto_tune_routes_away_from_failing_preset():
    async def run():
        from helpers import circuit_breaker
        circuit_breaker._STATES.clear()
        import yaml
        from helpers.pool import PoolEntry
        entries = _mk_entries() + [
            PoolEntry('Local', 'chat', 'lm_studio', 'qwen3.8-27b'),
            PoolEntry('Unhinged', 'chat', 'a0_venice', 'qwen-3-6-plus'),
            PoolEntry('Fast', 'chat', 'a0_venice', 'mercury-2-5'),
        ]
        with tempfile.TemporaryDirectory() as td:
            rp = Path(td) / 'rp.yaml'
            rp.write_text(yaml.safe_dump({
                'auto_tune': True,
                'band_orders': {'heavy': ['Power', 'Unhinged', 'Default',
                                          'Local', 'Efficiency', 'Fast']},
            }))
            db = Path(td) / 'tel.db'
            conn = telemetry.init_db(db)
            # Power failing (below breaker threshold 3 -> not tripped)
            telemetry.record_call(conn, 'zai_coding', 'Power', False, 0.1, 'e1')
            telemetry.record_call(conn, 'zai_coding', 'Power', False, 0.1, 'e2')
            for _ in range(3):
                telemetry.record_call(conn, 'a0_venice', 'Unhinged', True, 0.1, None)
            conn.close()
            res = await router.route(
                cfg=_cfg(), entries=entries, policy_path=rp,
                message='debug this crash in the auth module and fix it',
                attachments=[],
                query_fn=_fake_query(Signals(
                    task_class='coding', task_class_confidence=0.9,
                    complexity=1.6, vision_needed=0.0, delegate_worthy=0.1)),
                client=object(), jev_model='jev',
                model_factory=lambda e: MOCK_SENTINEL_MODEL,
                telemetry_path=db, session_id='')
            assert res.model is MOCK_SENTINEL_MODEL
            assert res.fallback is False
            assert 'auto-tune' in res.reason
            conn2 = telemetry.init_db(db)
            rows = telemetry.last_decisions(conn2, limit=1)
            conn2.close()
            # Unhinged healthy+most-ok outranks failing Power in heavy
            assert rows[0]['target'] == 'Unhinged', rows[0]['reason']

    asyncio.run(run())



def test_route_records_session_id():
    async def run():
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'tel.db'
            res = await router.route(
                cfg=_cfg(), entries=_mk_entries(),
                policy_path=Path(td) / 'p.yaml',
                message='refactor the auth module and add tests', attachments=[],
                query_fn=_fake_query(Signals('coding', 0.9, 1.8, 0.05, 0.5)),
                client=object(), jev_model='jev-latest',
                model_factory=lambda e: 'M[' + e.preset_name + ']',
                telemetry_path=db, session_id='ctx-sess-1')
            assert res.fallback is False, res.reason
            conn = telemetry.init_db(db)
            row = telemetry.last_decisions(conn, limit=1)[0]
            conn.close()
            assert row['session_id'] == 'ctx-sess-1', dict(row)
    asyncio.run(run())

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
    sys.exit(1 if failed else 0)
