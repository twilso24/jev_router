# Contract tests for the per-chat routing kill-switch gate.
# Spec: docs/specs/per-chat-kill-switch.md
# Truth table (spec assumption 3/4):
#   global off -> off everywhere; global on -> chat switch decides;
#   chat unset -> follows global; chat on -> on.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from helpers.gate import routing_allowed


def test_routing_allowed_truth_table():
    # global off -> off, regardless of chat state
    assert routing_allowed({'enabled': False}, None) is False
    assert routing_allowed({'enabled': False}, {'enabled': True}) is False
    assert routing_allowed({'enabled': False}, {'enabled': False}) is False
    # global on + chat off -> off
    assert routing_allowed({'enabled': True}, {'enabled': False}) is False
    # global on + chat unset -> on (default follows global)
    assert routing_allowed({'enabled': True}, None) is True
    assert routing_allowed({'enabled': True}, {}) is True
    # global on + chat on -> on
    assert routing_allowed({'enabled': True}, {'enabled': True}) is True
    # missing key defaults to enabled (matches cfg.get('enabled', True))
    assert routing_allowed({}, None) is True
    assert routing_allowed({}, {'enabled': False}) is False


def test_routing_allowed_bad_input_never_raises():
    # robust: non-dict chat state treated as unset
    assert routing_allowed({'enabled': True}, 'garbage') is True
    assert routing_allowed(None, None) is True


def test_hooks_use_gate_helper():
    "Routing/preselect hooks must consult routing_allowed, not raw cfg."""
    hook_files = [
        ROOT / 'extensions/python/chat_model_call_before/_10_jev_route.py',
        ROOT / 'extensions/python/user_message_ui/_10_jev_preselect.py',
        ROOT / 'extensions/python/user_message_ui/_20_jev_dynamic_switch.py',
    ]
    for path in hook_files:
        if not path.exists():
            continue
        src = path.read_text()
        assert 'routing_allowed' in src, f'{path.name} must use routing_allowed()'
        assert "cfg.get('enabled'" not in src, (
            f'{path.name} still reads raw cfg enabled flag')


def test_strip_extension_contract():
    "Context-strip toggle extension exists and wires the store + endpoint."""
    html = ROOT / 'extensions/webui/model-context-strip-end/jev-kill-switch.html'
    store = ROOT / 'webui/jev-kill-switch-store.js'
    assert html.exists(), 'strip extension html missing'
    assert store.exists(), 'kill-switch store missing'
    src = html.read_text()
    assert 'jevKillSwitch' in src
    assert 'routing_kill' in src
    assert 'route' in src  # chip label
