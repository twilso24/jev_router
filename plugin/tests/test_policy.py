# Task 4 (TDD): policy resolver + routing log - RED first.
# helpers/policy.py and helpers/telemetry.py do not exist yet.
# Run: /opt/venv-a0/bin/python tests/test_policy.py
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import policy, telemetry
from helpers.pool import PoolEntry
from helpers.signals import Signals


def _sig(cls='coding', comp=1.5, vis=0.05, dele=0.5):
    return Signals(task_class=cls, task_class_confidence=0.9,
                   complexity=comp, vision_needed=vis, delegate_worthy=dele)


def _entries():
    return [
        PoolEntry('Default', 'chat', 'zai_coding', 'glm-5.3-flash', vision=True),
        PoolEntry('Efficiency', 'chat', 'a0_venice', 'deepseek-v4-1-flash', vision=True),
        PoolEntry('Power', 'chat', 'zai_coding', 'glm-5.3', vision=False),
    ]


def test_band_boundaries():
    assert policy.complexity_band(0.0) == 'light'
    assert policy.complexity_band(0.66) == 'light'
    assert policy.complexity_band(0.67) == 'medium'
    assert policy.complexity_band(1.33) == 'medium'
    assert policy.complexity_band(1.34) == 'heavy'
    assert policy.complexity_band(2.0) == 'heavy'


def test_map_lookup_coding_heavy_power():
    d = policy.resolve(_sig(comp=1.8), _entries())
    assert d.entry.preset_name == 'Power'
    assert d.band == 'heavy'
    assert 'coding' in d.reason and 'heavy' in d.reason


def test_chat_light_routes_efficiency():
    d = policy.resolve(_sig(cls='chat', comp=0.2), _entries())
    assert d.entry.preset_name == 'Efficiency'


def test_vision_hard_filter():
    # vision_needed high; Power (vision=False) is the heavy target -> must NOT be used
    d = policy.resolve(_sig(comp=1.8, vis=0.9), _entries())
    assert d.entry.vision is True
    assert d.compromise is True
    assert 'vision' in d.reason.lower()


def test_wanted_preset_unavailable_falls_back_deterministically():
    # only Efficiency left (Default/Power filtered out upstream)
    d = policy.resolve(_sig(comp=1.8), [_entries()[1]])
    assert d.entry.preset_name == 'Efficiency'
    assert 'unavailable' in d.reason


def test_empty_pool_returns_none_entry_with_reason():
    d = policy.resolve(_sig(), [])
    assert d.entry is None
    assert 'empty' in d.reason.lower()


def test_telemetry_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 'telemetry.db'
        conn = telemetry.init_db(db)
        d = policy.resolve(_sig(), _entries())
        telemetry.record_decision(conn, d, signals=_sig(), msg_digest='abc123')
        rows = telemetry.last_decisions(conn, 5)
        assert len(rows) == 1
        r = rows[0]
        assert r['target'] == 'Power'
        assert r['msg_digest'] == 'abc123'
        assert r['band'] == 'heavy'
        assert r['reason']
        conn.close()




SIX = ['Default', 'Efficiency', 'Power', 'Local', 'Unhinged', 'Fast']


def _six_entries():
    return [
        PoolEntry('Default', 'chat', 'zai_coding', 'glm-5.3-flash', vision=True),
        PoolEntry('Efficiency', 'chat', 'a0_venice', 'deepseek-v4-1-flash', vision=True),
        PoolEntry('Power', 'chat', 'zai_coding', 'glm-5.3', vision=False),
        PoolEntry('Local', 'chat', 'lm_studio', 'qwen3.8-27b', vision=False),
        PoolEntry('Unhinged', 'chat', 'a0_venice', 'qwen-3-6-plus', vision=False),
        PoolEntry('Fast', 'chat', 'a0_venice', 'mercury-2-5', vision=False),
    ]


def test_default_band_orders_cover_all_six():
    for band, order in policy.DEFAULT_BAND_ORDERS.items():
        assert sorted(order) == sorted(SIX), (band, order)
        assert len(set(order)) == len(order), band
    assert policy.DEFAULT_BAND_ORDERS['light'][0] == 'Fast'
    assert policy.DEFAULT_BAND_ORDERS['medium'][0] == 'Default'
    assert policy.DEFAULT_BAND_ORDERS['heavy'][0] == 'Power'


def test_all_six_are_first_class_winners():
    entries = _six_entries()
    by = {e.preset_name: e for e in entries}
    d = policy.resolve(_sig(cls='chat', comp=0.2), entries)
    assert d.entry is by['Fast']
    d = policy.resolve(_sig(comp=1.0), entries)
    assert d.entry is by['Default']
    d = policy.resolve(_sig(comp=1.8), entries)
    assert d.entry is by['Power']
    # Preferred winner removed -> next in band order wins (first-class chain).
    rest = [e for e in entries if e.preset_name != 'Power']
    d = policy.resolve(_sig(comp=1.8), rest)
    assert d.entry.preset_name == 'Unhinged', d.reason


def test_band_orders_from_yaml_override_defaults():
    import yaml
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'rp.yaml'
        f.write_text(yaml.safe_dump({'band_orders': {
            'light': ['Unhinged', 'Fast'],
            'heavy': ['Local', 'Power'],
        }}))
        orders = policy.load_band_orders(f)
        assert orders['light'][0] == 'Unhinged'
        assert orders['heavy'][0] == 'Local'
        # missing band filled from defaults
        assert orders['medium'][0] == 'Default'
        d = policy.resolve(_sig(cls='chat', comp=0.2), _six_entries(),
                           band_orders=orders)
        assert d.entry.preset_name == 'Unhinged'
        d = policy.resolve(_sig(comp=1.8), _six_entries(), band_orders=orders)
        assert d.entry.preset_name == 'Local'


def test_band_orders_invalid_yaml_falls_back():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'rp.yaml'
        f.write_text('band_orders: [ this is: not: valid structure !!!')
        orders = policy.load_band_orders(f)
        assert orders['light'] == policy.DEFAULT_BAND_ORDERS['light']
        f2 = Path(td) / 'rp2.yaml'
        f2.write_text('band_orders:\n  light: 42\n')
        orders = policy.load_band_orders(f2)
        assert orders['light'] == policy.DEFAULT_BAND_ORDERS['light']




def test_boost_preferred_reorders_within_band():
    entries = _six_entries()
    orders = {b: list(o) for b, o in policy.DEFAULT_BAND_ORDERS.items()}
    boosted = policy.boost_preferred(orders, entries, ['lm_studio'])
    assert boosted['light'] == ['Local', 'Fast', 'Efficiency', 'Default',
                                'Unhinged', 'Power']
    assert boosted['medium'] == ['Local', 'Default', 'Power', 'Unhinged',
                                 'Efficiency', 'Fast']
    assert boosted['heavy'] == ['Local', 'Power', 'Unhinged', 'Default',
                                'Efficiency', 'Fast']


def test_boost_preferred_stable_for_multiple_providers():
    entries = _six_entries()
    orders = {b: list(o) for b, o in policy.DEFAULT_BAND_ORDERS.items()}
    boosted = policy.boost_preferred(orders, entries,
                                     ['lm_studio', 'a0_venice'])
    assert boosted['light'] == ['Fast', 'Efficiency', 'Unhinged', 'Local',
                                'Default', 'Power']


def test_boost_preferred_noop_without_match():
    entries = _six_entries()
    orders = {b: list(o) for b, o in policy.DEFAULT_BAND_ORDERS.items()}
    boosted = policy.boost_preferred(orders, entries, ['nope'])
    assert boosted == orders


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
