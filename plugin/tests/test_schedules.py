# P2 (TDD): schedules - RED first. helpers/schedules.py does not exist yet.
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import schedules


def _write(td, data):
    f = Path(td) / 'rp.yaml'
    f.write_text(yaml.safe_dump(data))
    return f


def test_parse_schedules_fields():
    with tempfile.TemporaryDirectory() as td:
        f = _write(td, {'schedules': [
            {'name': 'night-free', 'window': '22:00-06:00',
             'timezone': 'instance',
             'prefer': ['openrouter', 'a0_venice']},
            {'name': 'weekend-no-paid', 'days': ['sat', 'sun'],
             'exclude': ['zai_coding']},
        ]})
        s = schedules.load_schedules(f)
        assert len(s) == 2
        assert s[0].name == 'night-free'
        assert s[0].window == '22:00-06:00'
        assert s[0].prefer == ['openrouter', 'a0_venice']
        assert s[0].timezone == 'instance'
        assert s[1].days == ['sat', 'sun']
        assert s[1].exclude == ['zai_coding']


def test_no_schedules_key_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        f = _write(td, {'provider_rules': {'include': [], 'exclude': []}})
        assert schedules.load_schedules(f) == []


def test_malformed_yaml_tolerated():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / 'rp.yaml'
        f.write_text('schedules: [ oops: ::: ]')
        assert schedules.load_schedules(f) == []
        f2 = Path(td) / 'rp2.yaml'
        f2.write_text('schedules:\n  - name: ok\n  - 42\n')
        assert [x.name for x in schedules.load_schedules(f2)] == ['ok']


def test_entry_without_name_skipped():
    with tempfile.TemporaryDirectory() as td:
        f = _write(td, {'schedules': [
            {'prefer': ['x']},
            {'name': 'kept'},
        ]})
        assert [x.name for x in schedules.load_schedules(f)] == ['kept']


def test_window_normal_match():
    assert schedules.window_matches('08:00-20:00', 12 * 60)
    assert not schedules.window_matches('08:00-20:00', 21 * 60)
    assert not schedules.window_matches('08:00-20:00', 7 * 60)


def test_window_midnight_wrap():
    assert schedules.window_matches('22:00-06:00', 23 * 60)
    assert schedules.window_matches('22:00-06:00', 5 * 60)
    assert not schedules.window_matches('22:00-06:00', 12 * 60)


def test_window_empty_or_invalid():
    assert schedules.window_matches('', 0)
    assert not schedules.window_matches('junk', 0)


def test_days_match():
    assert schedules.day_matches(['mon'], 0)
    assert not schedules.day_matches(['sat', 'sun'], 0)
    assert schedules.day_matches([], 5)
    assert schedules.day_matches(['saturday'], 5)


def test_active_first_match_wins():
    a = schedules.Schedule('a', window='00:00-23:59')
    b = schedules.Schedule('b', window='00:00-23:59')
    assert schedules.active_schedule(
        [a, b], now=datetime(2026, 9, 22, 12, 0)).name == 'a'


def test_active_none_when_no_match():
    a = schedules.Schedule('a', window='01:00-02:00', days=['sun'])
    assert schedules.active_schedule(
        [a], now=datetime(2026, 9, 22, 12, 0)) is None  # tuesday


def test_active_uses_injected_now():
    s = [schedules.Schedule('day', window='08:00-20:00')]
    assert schedules.active_schedule(
        s, now=datetime(2026, 9, 22, 12, 0)).name == 'day'
    assert schedules.active_schedule(
        s, now=datetime(2026, 9, 22, 23, 0)) is None


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
