# P2 (TDD): circuit breaker - RED first. helpers/circuit_breaker.py missing yet.
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import circuit_breaker


def test_no_state_no_exclude():
    assert circuit_breaker.excluded_providers(['p']) == []


def test_record_fail_trips_at_threshold():
    circuit_breaker._STATES.clear()
    for i in range(circuit_breaker.DEFAULT_THRESHOLD - 1):
        assert not circuit_breaker.record_fail('p1')
    assert circuit_breaker.record_fail('p1')
    assert circuit_breaker.excluded_providers(['p1']) == ['p1']


def test_trip_cooldown_expires():
    circuit_breaker._STATES.clear()
    t = time.time()
    for i in range(circuit_breaker.DEFAULT_THRESHOLD):
        circuit_breaker.record_fail('p2')
    assert circuit_breaker.excluded_providers(['p2'], now=t) == ['p2']
    future = t + (circuit_breaker.DEFAULT_COOLDOWN_HOURS * 3600) + 10
    assert circuit_breaker.excluded_providers(['p2'], now=future) == []


def test_success_resets_failures():
    circuit_breaker._STATES.clear()
    for i in range(circuit_breaker.DEFAULT_THRESHOLD - 1):
        circuit_breaker.record_fail('p3')
    circuit_breaker.record_success('p3')
    assert circuit_breaker.excluded_providers(['p3']) == []


def test_multiple_providers_independent():
    circuit_breaker._STATES.clear()
    for i in range(circuit_breaker.DEFAULT_THRESHOLD):
        circuit_breaker.record_fail('p4')
        circuit_breaker.record_fail('p5')
    assert set(circuit_breaker.excluded_providers(['p4', 'p5'])) == {'p4', 'p5'}


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
