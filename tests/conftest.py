# Per-file import isolation for the combined pytest run.
#
# Root cause of cross-file pollution: the framework's /a0/helpers is a
# NAMESPACE package (no __init__.py) while the plugin's helpers/ is a
# REGULAR package. A regular package shadows a namespace package across
# every sys.path entry regardless of order, so once the project root is on
# sys.path, every fresh `import helpers` binds the plugin package and
# `from helpers.extension import Extension` fails. `python -m pytest` puts
# the CWD (project root) on sys.path at startup — that alone reproduces the
# historic combined-run failures.
#
# Fix: give each test file its own import environment, mirroring standalone
# (fresh-process) semantics inside one run. We wrap the module-level
# _pytest.python.importtestmodule that default Module._getobj calls (pytest
# 9): reset polluted namespaces + sys.path to a clean baseline before each
# file's import, then snapshot the environment the file produced; a setup
# hook reapplies that snapshot per test. The baseline sys.path EXCLUDES the
# project root (helper test files re-insert it themselves; extension files
# insert /a0), so the framework namespace package stays reachable. Only
# test-fought namespaces (helpers*, usr*, plugins*, python*) are managed —
# pytest/stdlib machinery is never evicted and fixtures like tmp_path keep
# working.
import sys
from pathlib import Path

import pytest
import _pytest.python as _pp


def _polluted(name: str) -> bool:
    """Namespaces test files fight over: `helpers` (plugin regular pkg vs
    framework namespace pkg), `usr`/`plugins`/`python` (stubbed modules)."""
    return name.split('.', 1)[0] in {'helpers', 'usr', 'plugins', 'python'}


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# sys.path minus the project root: `python -m pytest` adds CWD there and the
# plugin's regular `helpers` package would otherwise shadow /a0/helpers for
# every later import in the process. Files re-add what they need.
BASE_PATH = [p for p in sys.path
             if p and Path(p).resolve() != _PROJECT_ROOT]
BASE_MODS = {k: v for k, v in sys.modules.items() if _polluted(k)}


def _apply(mods: dict, path: list) -> None:
    for k in [k for k in sys.modules if _polluted(k) and k not in mods]:
        del sys.modules[k]
    sys.modules.update(mods)
    sys.path[:] = list(path)


_SNAPSHOTS: dict = {}
_ORIG_IMPORT = _pp.importtestmodule


def _isolated_importtestmodule(path, config):
    _apply(dict(BASE_MODS), BASE_PATH)
    mod = _ORIG_IMPORT(path, config)
    _SNAPSHOTS[str(path)] = (
        {k: v for k, v in sys.modules.items() if _polluted(k)},
        list(sys.path))
    return mod


_pp.importtestmodule = _isolated_importtestmodule


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    yield  # regular fixture setup first; env lands right before call phase
    snap = _SNAPSHOTS.get(str(getattr(item, 'path', '')))
    if snap is not None:
        _apply(snap[0], snap[1])


def pytest_sessionfinish(session, exitstatus):
    # Leave the interpreter as we found it.
    _apply(dict(BASE_MODS), BASE_PATH)
