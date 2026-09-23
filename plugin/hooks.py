"""jev_router lifecycle hooks.

Installs the typesafe-sdk dependency so the plugin works standalone.
"""
import subprocess
import sys


def install():
    """Install typesafe-sdk into the framework runtime."""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "typesafe-sdk==0.6.0"])


def pre_update():
    """No special pre-update action needed."""
    pass


def uninstall():
    """Do not remove typesafe-sdk; it may be used by other plugins."""
    pass
