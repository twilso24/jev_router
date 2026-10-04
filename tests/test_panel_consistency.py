# Guard (Panel Copy Consistency from memory): the canvas panel renders only
# when there is exactly ONE byte-identical fragment and nothing stale shadows
# it. This test pins the canonical bodies; deployment-side checks live in
# the sync checklist (deployed copies are outside this repo).
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PANEL = ROOT / 'webui' / 'jev-router-panel.html'
CANONICAL_CONFIG = ROOT / 'webui' / 'config.html'
# The nested plugin/ tree is a legacy one-time sync snapshot, not canonical;
# only copies under the real webui/ render source are asserted identical.


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_canonical_panel_and_config_exist_and_nonempty():
    assert CANONICAL_PANEL.exists() and CANONICAL_PANEL.stat().st_size > 1000
    assert CANONICAL_CONFIG.exists() and CANONICAL_CONFIG.stat().st_size > 100


def test_no_duplicate_panel_bodies_outside_plugin_snapshot():
    "Every jev-router-panel.html outside the plugin/ snapshot must be byte-identical."
    copies = [p for p in ROOT.glob('**/jev-router-panel.html')
              if 'plugin' not in p.relative_to(ROOT).parts
              and 'node_modules' not in p.parts]
    assert copies, 'no canonical panel copy found'
    assert {_sha(p) for p in copies} == {_sha(CANONICAL_PANEL)}


def test_plugin_snapshot_panel_matches_canonical():
    snap = ROOT / 'plugin' / 'webui' / 'jev-router-panel.html'
    if snap.exists():
        assert _sha(snap) == _sha(CANONICAL_PANEL), 'plugin/ snapshot panel drifted - resync or prune'


def test_plugin_snapshot_config_matches_canonical():
    snap = ROOT / 'plugin' / 'webui' / 'config.html'
    if snap.exists():
        assert _sha(snap) == _sha(CANONICAL_CONFIG), 'plugin/ snapshot config drifted - resync or prune'


# --- Inline plain-text description UI contract (corrected UX) -------------
# The presets section lets users define EXISTING model presets with plain
# text, inline with each row. No create-new flow, no add/edit/delete buttons.


def test_panel_uses_inline_describe_flow():
    html = CANONICAL_PANEL.read_text()
    # Each preset row exposes an inline description editor saved via describe
    assert "action: 'describe'" in html or 'action: \'describe\'' in html
    assert 'jev-preset-desc-input' in html, 'inline description input missing'


def test_panel_has_no_create_or_delete_controls():
    html = CANONICAL_PANEL.read_text()
    assert 'jev-preset-add' not in html, 'Add preset button should be removed'
    # no delete button wiring in the presets section
    assert "deletePreset" not in html, 'delete flow should be removed'
    assert "action: 'delete'" not in html, 'delete action should be removed'


def test_panel_has_no_standalone_preset_form():
    html = CANONICAL_PANEL.read_text()
    assert 'jev-preset-form' not in html, 'standalone form should be removed'
    assert 'openPresetForm' not in html, 'form opener should be removed'


# --- Collapsible Model Presets Section contract -------------------------
# The presets card header gets a collapse toggle (chevron) that hides
# .jev-preset-hint, .jev-presets-list, .jev-preset-status via CSS.
# State persists in localStorage under 'jev_router_presets_collapsed'.
# Default is collapsed (no stored key -> collapsed).


def test_panel_has_collapsible_presets_section():
    html = CANONICAL_PANEL.read_text()
    # Collapse button with chevron in the presets card head
    assert 'jev-collapse-btn' in html, 'collapse button class missing'
    assert 'jev-chevron' in html, 'chevron element missing'
    # aria-expanded binding on the button
    assert 'aria-expanded' in html, 'aria-expanded attribute missing'
    # Body elements guarded by visibility (CSS/JS hide, not remove)
    assert 'x-show' in html or 'hidden' in html or 'display: none' in html or 'collapsed' in html.lower(), 'body visibility guard missing'
    # localStorage persistence key
    assert 'jev_router_presets_collapsed' in html, 'localStorage persistence key missing'
    # Default state is collapsed (user decision: open question 1 resolved)
    assert 'presetsOpen = false' in html, 'default must be collapsed'
    # Chevron lives on the header button
    assert 'jev-chevron' in html and 'jev-collapse-btn' in html
    # Toggle button must be type=button (not submit) and toggle body class
    assert "presetsBody.classList.toggle('collapsed'" in html, 'body collapse class toggle missing'


def test_collapse_does_not_remove_preset_content():
    html = CANONICAL_PANEL.read_text()
    # All preset content must remain in markup when collapsed (hide only)
    assert 'jev-preset-hint' in html, 'hint removed instead of hidden'
    assert 'jev-presets-list' in html, 'list removed instead of hidden'
    assert 'jev-preset-status' in html, 'status removed instead of hidden'
    assert 'jev-preset-desc-input' in html, 'description input missing'
    assert "action: 'describe'" in html or "action: \"describe\"" in html, 'describe action missing'
    assert 'jev-preset-save' in html, 'save button missing'
