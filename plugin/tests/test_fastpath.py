# Task 5 (TDD): fast-path heuristic - RED first.
# helpers/fastpath.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_fastpath.py
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import fastpath


def test_short_plain_greeting_is_trivial():
    assert fastpath.is_trivial('hey how are you?') is True


def test_long_message_not_trivial():
    assert fastpath.is_trivial('summarize this: ' + 'blah ' * 120) is False


def test_code_blocks_not_trivial():
    msg = 'fix this:\n```python\ndef f(: pass\n```'
    assert fastpath.is_trivial(msg) is False


def test_question_with_task_verb_not_trivial():
    assert fastpath.is_trivial('please research the best GPU prices') is False


def test_attachments_force_full_routing():
    assert fastpath.is_trivial('hey', attachments=['a.png']) is False


def test_under_50ms():
    start = time.monotonic()
    for i in range(200):
        fastpath.is_trivial('hello there ' + 'x' * (i % 50))
    elapsed = (time.monotonic() - start) / 200 * 1000
    assert elapsed < 50, f'{elapsed:.2f}ms per call'


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
