# Task 2 (TDD): eligibility filter chain - RED first.
# helpers/eligibility.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_eligibility.py
import sys
import tempfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import eligibility
from helpers.pool import PoolEntry


def _entry(preset, provider, role='chat'):
    return PoolEntry(preset_name=preset, role=role, provider=provider, model='m')


def _policy_file(tmp, rules):
    f = Path(tmp) / 'routing-policy.yaml'
    f.write_text(yaml.safe_dump(rules))
    return f


def test_exclude_removes_and_records_reason():
    with tempfile.TemporaryDirectory() as td:
        f = _policy_file(td, {'provider_rules': {'exclude': ['zai_coding']}})
        pol = eligibility.load_policy(f)
        res = eligibility.filter_pool(
            [_entry('Default', 'zai_coding'), _entry('Eff', 'a0_venice')], pol)
        assert [e.preset_name for e in res.kept] == ['Eff']
        assert len(res.removals) == 1
        entry, fname, reason = res.removals[0]
        assert entry.preset_name == 'Default'
        assert fname == 'static_exclude'
        assert 'zai_coding' in reason


def test_include_only_keeps_listed():
    with tempfile.TemporaryDirectory() as td:
        f = _policy_file(td, {'provider_rules': {'include': ['a0_venice']}})
        pol = eligibility.load_policy(f)
        res = eligibility.filter_pool(
            [_entry('Default', 'zai_coding'), _entry('Eff', 'a0_venice'),
             _entry('Loc', 'lm_studio')], pol)
        assert [e.preset_name for e in res.kept] == ['Eff']
        assert len(res.removals) == 2
        assert all(fn == 'static_include' for _, fn, _ in res.removals)


def test_empty_rules_keep_everything():
    with tempfile.TemporaryDirectory() as td:
        f = _policy_file(td, {})
        pol = eligibility.load_policy(f)
        res = eligibility.filter_pool([_entry('A', 'x'), _entry('B', 'y')], pol)
        assert len(res.kept) == 2
        assert res.removals == []


def test_empty_result_marks_fallback():
    with tempfile.TemporaryDirectory() as td:
        f = _policy_file(td, {'provider_rules': {'exclude': ['x', 'y']}})
        pol = eligibility.load_policy(f)
        res = eligibility.filter_pool([_entry('A', 'x'), _entry('B', 'y')], pol)
        assert res.kept == []
        assert res.fallback_reason == 'fallback:empty_pool'


def test_missing_policy_file_safe_default():
    pol = eligibility.load_policy(Path('/nonexistent/policy.yaml'))
    assert pol.exclude == [] and pol.include == []


def test_garbage_policy_yaml_safe_default():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = _policy_file(td, None) if False else None
        from pathlib import Path as P
        fp = P(td) / 'policy.yaml'
        fp.write_text('provider_rules: [ this is: not: valid: yaml: {{{')
        pol = eligibility.load_policy(fp)
        assert pol.exclude == [] and pol.include == []



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
