"""jev_router lifecycle hooks.

Installs the typesafe-sdk dependency so the plugin works standalone.
Around plugin updates, snapshots the user-editable runtime files
(config.json, routing-policy.yaml), resets them to HEAD so the updater's
auto-stash cannot conflict, and restores the live copies afterwards.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / ".update-backup"
RUNTIME_FILES = ("config.json", "routing-policy.yaml")


def _backup_runtime_files() -> None:
    """Snapshot the live runtime files before an update.

    Never overwrites an existing snapshot: a previous update attempt may have
    aborted after pre_update() reset the files to HEAD, and that first
    snapshot still holds the user's live content.
    """
    BACKUP_DIR.mkdir(exist_ok=True)
    for name in RUNTIME_FILES:
        src = ROOT / name
        dst = BACKUP_DIR / name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)


def _reset_runtime_files() -> None:
    """Reset runtime files to HEAD so the update stash cannot conflict."""
    for name in RUNTIME_FILES:
        src = ROOT / name
        if src.is_file():
            try:
                subprocess.run(
                    ["git", "checkout", "HEAD", "--", name],
                    cwd=ROOT, capture_output=True, check=False,
                )
            except OSError:
                pass


def _restore_runtime_files() -> None:
    """Restore the user's live runtime files after the update, then clean up."""
    for name in RUNTIME_FILES:
        snapshot = BACKUP_DIR / name
        if snapshot.is_file():
            shutil.copy2(snapshot, ROOT / name)
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)


def install():
    """Install typesafe-sdk and restore live runtime files after an update."""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "typesafe-sdk==0.6.0"]
    )
    _restore_runtime_files()


def pre_update():
    """Snapshot live runtime files and reset them before the repo update."""
    _backup_runtime_files()
    _reset_runtime_files()


def uninstall():
    """Do not remove typesafe-sdk; it may be used by other plugins."""
    pass
