"""TDD: hooks.py must preserve runtime files across plugin updates.

pre_update() snapshots config.json/routing-policy.yaml and resets them to HEAD
so git.update_repo()'s stash-pop cannot conflict; install() restores them.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_hooks(path: Path):
    spec = importlib.util.spec_from_file_location("jev_hooks_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def plugin_repo(tmp_path):
    """A git repo shaped like a deployed plugin with committed runtime files."""
    repo = tmp_path / "plugin"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-q", "-m", "base"], cwd=repo, check=True)
    (repo / "config.json").write_text('{"enabled": true}\n')
    (repo / "routing-policy.yaml").write_text("band_orders:\n  light: [Default]\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "runtime files"], cwd=repo, check=True)
    # user's live edits
    (repo / "config.json").write_text('{"enabled": true, "jev_api_key": "secret"}\n')
    (repo / "routing-policy.yaml").write_text(
        "band_orders:\n  light: [Efficient, Default]\n")
    # hooks.py under test lives beside the runtime files
    (repo / "hooks.py").write_text(
        (ROOT / "hooks.py").read_text(encoding="utf-8"), encoding="utf-8")
    return repo


def _dirty(repo: Path) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--",
                          "config.json", "routing-policy.yaml"],
                         cwd=repo, capture_output=True, text=True, check=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def test_pre_update_backs_up_and_resets_runtime_files(plugin_repo):
    hooks = _load_hooks(plugin_repo / "hooks.py")
    hooks.pre_update()
    backup = plugin_repo / ".update-backup"
    assert (backup / "config.json").exists(), "pre_update must snapshot config.json"
    assert (backup / "routing-policy.yaml").exists(), "pre_update must snapshot policy"
    # snapshot holds the USER's live content, not HEAD
    assert "secret" in (backup / "config.json").read_text()
    # runtime files back at HEAD -> stash-pop cannot conflict
    assert _dirty(plugin_repo) == [], "runtime files must be clean after pre_update"


def test_install_restores_live_files_and_cleans_backup(plugin_repo):
    hooks = _load_hooks(plugin_repo / "hooks.py")
    hooks.pre_update()
    # simulate the update checking out new upstream versions
    (plugin_repo / "config.json").write_text('{"enabled": false, "upstream": 1}\n')
    hooks.install()
    live = (plugin_repo / "config.json").read_text()
    assert "secret" in live, "install must restore the user's live config"
    policy = (plugin_repo / "routing-policy.yaml").read_text()
    assert "Efficient" in policy, "install must restore the live band orders"
    assert not (plugin_repo / ".update-backup").exists(), "backup must be cleaned up"


def test_backup_survives_aborted_update(plugin_repo):
    """A second pre_update after an aborted update must not clobber the snapshot."""
    hooks = _load_hooks(plugin_repo / "hooks.py")
    hooks.pre_update()          # backup created with user content
    # update aborts -> runtime files stay reset at HEAD, install() never ran
    hooks.pre_update()          # user retries the update
    backup = plugin_repo / ".update-backup" / "config.json"
    assert "secret" in backup.read_text(), (
        "repeat pre_update must keep the first snapshot, not the reset content")


def test_install_without_backup_is_noop(plugin_repo):
    """Fresh install (no pre_update) must not fail or fabricate files."""
    subprocess.run(["git", "checkout", "HEAD", "--", "config.json"],
                   cwd=plugin_repo, check=True)
    hooks = _load_hooks(plugin_repo / "hooks.py")
    hooks.install()  # pip step runs; must not raise on missing backup
    assert (plugin_repo / "config.json").exists()
