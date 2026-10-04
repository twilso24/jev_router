"""Dial removal guard: zero dial references in production code.

Production paths only (helpers/, api/, extensions/, webui/, config.json).
tests/ legitimately reference the legacy key to assert it is ignored or
absent, so tests are excluded from the scan.
"""
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

PROD_PATHS = [
    PLUGIN_ROOT / 'helpers',
    PLUGIN_ROOT / 'api',
    PLUGIN_ROOT / 'extensions',
    PLUGIN_ROOT / 'webui',
]

PATTERNS = [
    'apply_dial',
    'performance_dial',
    'from helpers import dial',
    'from helpers.dial',
    'import helpers.dial',
    'jev-dial',
    'config.performance_dial',
]


def test_no_dial_references_in_production_code():
    for pattern in PATTERNS:
        hits = []
        for root in PROD_PATHS:
            if not root.exists():
                continue
            result = subprocess.run(
                ['grep', '-r', '--include=*.py', '--include=*.html',
                 '--include=*.js', pattern, str(root)],
                capture_output=True, text=True,
            )
            hits += [l for l in result.stdout.split('\n') if l]
        assert not hits, f'dial reference {pattern!r} in production code:\n' + '\n'.join(hits)


def test_config_json_has_no_dial_key():
    import json
    data = json.loads((PLUGIN_ROOT / 'config.json').read_text())
    assert 'performance_dial' not in data


def test_helpers_dial_module_absent():
    assert not (PLUGIN_ROOT / 'helpers' / 'dial.py').exists()
    assert not (PLUGIN_ROOT / 'plugin' / 'helpers' / 'dial.py').exists()


def test_test_dial_deleted():
    assert not (PLUGIN_ROOT / 'tests' / 'test_dial.py').exists()
    assert not (PLUGIN_ROOT / 'plugin' / 'tests' / 'test_dial.py').exists()
