# Task 1 (TDD): pool loader tests - RED first.
# helpers/pool.py does not exist yet; this must fail with ModuleNotFoundError.
# Plain-script runner (framework convention, no pytest dependency).
# Run: /opt/venv-a0/bin/python tests/test_pool.py
import os
import sys
import tempfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import pool

PRESETS = Path(os.environ.get(
    'JEV_ROUTER_PRESETS',
    '/a0/usr/plugins/_model_config/presets.yaml',
))


def test_loads_real_presets_chat_role():
    assert PRESETS.exists(), f'live presets.yaml not found: {PRESETS}'
    p = pool.load_pool(PRESETS)
    chat = {e.preset_name: e for e in p.entries if e.role == 'chat'}
    assert len(chat) >= 5, f'expected >=5 chat presets, got {len(chat)}'
    assert chat['Default'].provider == 'zai_coding'
    assert chat['Default'].model == 'glm-5.3-flash'
    assert chat['Default'].vision is True
    assert chat['Power'].vision is False
    assert chat['Local'].ctx_length == 56000
    assert chat['Unhinged'].provider == 'a0_venice'


def test_malformed_entry_skipped_with_warning():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'presets.yaml'
        data = [
            {'name': 'Good', 'chat': {'provider': 'p1', 'name': 'm1', 'ctx_length': 1000}},
            {'name': 'Bad', 'chat': {'name': 'no-provider-here'}},
        ]
        f.write_text(yaml.safe_dump(data))
        p = pool.load_pool(f)
        assert [e.preset_name for e in p.entries] == ['Good']
        assert any('Bad' in w for w in p.warnings), p.warnings


def test_unknown_fields_tolerated():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'presets.yaml'
        data = [{'name': 'Future', 'chat': {
            'provider': 'p', 'name': 'm', 'future_field': 42,
            'another_new_thing': {'deep': True}}}]
        f.write_text(yaml.safe_dump(data))
        p = pool.load_pool(f)
        assert len(p.entries) == 1
        assert p.warnings == []


def test_missing_optional_fields_default():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'presets.yaml'
        data = [{'name': 'Sparse', 'chat': {'provider': 'p', 'name': 'm'}}]
        f.write_text(yaml.safe_dump(data))
        p = pool.load_pool(f)
        e = p.entries[0]
        assert e.ctx_length is None
        assert e.vision is False
        assert e.api_base == ''




def test_pool_fingerprint_stable_and_sensitive():
    a = pool.PoolEntry('A', 'chat', 'p', 'm1')
    a2 = pool.PoolEntry('A', 'chat', 'p', 'm1')
    b = pool.PoolEntry('A', 'chat', 'p', 'm2')
    c = pool.PoolEntry('B', 'chat', 'p', 'm1')
    assert pool.pool_fingerprint([a]) == pool.pool_fingerprint([a2])
    assert pool.pool_fingerprint([a]) != pool.pool_fingerprint([b])
    assert pool.pool_fingerprint([a]) != pool.pool_fingerprint([c])
    assert pool.pool_fingerprint([a]) != pool.pool_fingerprint([a, b])


def test_pool_fingerprint_live_presets_deterministic():
    assert PRESETS.exists()
    p1 = pool.load_pool(PRESETS)
    p2 = pool.load_pool(PRESETS)
    assert pool.pool_fingerprint(p1.entries) == pool.pool_fingerprint(p2.entries)


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
