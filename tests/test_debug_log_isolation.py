"""Debug-log path isolation: test runs must not write the live debug log.

Every module that logs to /a0/tmp/jev_router_debug.log must honor the
JEV_ROUTER_DEBUG_LOG environment variable, so pytest can be redirected to a
throwaway path. Run: cd /a0 && /opt/venv-a0/bin/python <this file>
"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if '/a0' not in sys.path:
    sys.path.insert(0, '/a0')

def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _with_env(value):
    old = os.environ.get('JEV_ROUTER_DEBUG_LOG')
    if value is None:
        os.environ.pop('JEV_ROUTER_DEBUG_LOG', None)
    else:
        os.environ['JEV_ROUTER_DEBUG_LOG'] = value
    return old

def _restore(old):
    if old is None:
        os.environ.pop('JEV_ROUTER_DEBUG_LOG', None)
    else:
        os.environ['JEV_ROUTER_DEBUG_LOG'] = old


def test_preselect_debug_log_honors_env():
    old = _with_env('/tmp/jev_test_debug.log')
    try:
        mod = _load('preselect_env_test', 'helpers/preselect.py')
        assert str(mod.DEBUG_LOG) == '/tmp/jev_test_debug.log'
    finally:
        _restore(old)


def test_preselect_debug_log_defaults_live_path():
    old = _with_env(None)
    try:
        mod = _load('preselect_default_test', 'helpers/preselect.py')
        assert str(mod.DEBUG_LOG) == '/a0/tmp/jev_router_debug.log'
    finally:
        _restore(old)


def test_all_logging_modules_honor_env():
    old = _with_env('/tmp/jev_test_debug.log')
    try:
        for name, rel in (
            ('preselect_all', 'helpers/preselect.py'),
            ('jev_all', 'helpers/jev.py'),
            ('signals_all', 'helpers/signals.py'),
        ):
            mod = _load(name, rel)
            assert str(mod.DEBUG_LOG) == '/tmp/jev_test_debug.log', rel
    finally:
        _restore(old)


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
