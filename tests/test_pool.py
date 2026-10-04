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
    """Structural check against the LIVE presets.yaml (user-editable).

    Names and values change when the user retunes presets; derive all
    expectations from the live file instead of hard-coding them.
    """
    import yaml
    assert PRESETS.exists(), f'live presets.yaml not found: {PRESETS}'
    raw = yaml.safe_load(PRESETS.read_text()) or []
    names = [d.get('name') for d in raw if isinstance(d, dict) and d.get('name')]
    assert len(names) >= 5, f'expected >=5 presets live, got {names}'

    p = pool.load_pool(PRESETS)
    chat = {e.preset_name: e for e in p.entries if e.role == 'chat'}
    # Every live preset with a chat role must appear; preserve its typed fields.
    for name in names:
        entry = chat.get(name)
        if entry is None:
            continue  # preset legitimately defines no chat role
        assert entry.provider, name
        assert entry.model, name
        assert isinstance(entry.vision, bool), name
        if entry.ctx_length:
            assert entry.ctx_length > 0, name



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


# --- RED: plain-language preset descriptions ---

def test_load_pool_reads_optional_description(tmp_path):
    p = tmp_path / 'presets.yaml'
    p.write_text(yaml.safe_dump([
        {'name': 'Storyteller',
         'description': 'Creative writing, persona roleplay, prose polish; slow but expressive',
         'chat': {'provider': 'p', 'name': 'm1', 'vision': False}},
        {'name': 'Speedy',
         'chat': {'provider': 'p', 'name': 'm2', 'vision': True}},
    ]))
    pool_ = pool.load_pool(p)
    by_name = {e.preset_name: e for e in pool_.entries}
    assert by_name['Storyteller'].description.startswith('Creative writing')
    assert by_name['Speedy'].description == ''


def test_description_default_field_absent():
    from helpers.pool import PoolEntry
    e = PoolEntry('X', 'chat', 'p', 'm')
    assert e.description == ''


def test_build_state_includes_description_when_present():
    from helpers.pool import PoolEntry
    from helpers import signals
    e = PoolEntry('Storyteller', 'chat', 'p', 'm',
                  description='creative writing persona')
    st = signals.build_state('hi', [], pool_entries=[e])
    assert st['available_models'][0]['description'] == 'creative writing persona'


def test_preset_fit_criteria_include_description():
    from helpers.pool import PoolEntry
    from helpers import signals
    entries = [
        PoolEntry('Storyteller', 'chat', 'p', 'm1',
                  description='creative writing persona'),
        PoolEntry('Speedy', 'chat', 'p', 'm2'),
    ]
    q = signals.build_questions(pool_entries=entries)
    crit = q['preset_fit']['criteria']
    # description is the ONLY nuance signal (plain-text preset contract)
    assert crit['Storyteller'] == 'creative writing persona'
    # presets without a description get the neutral fallback, never
    # technical facts — criteria must stay description-only
    assert crit['Speedy'] == 'no description provided'
