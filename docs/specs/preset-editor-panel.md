# Spec: Preset Editor UI + Canvas Panel Enhancement

## Objective

Give users first-class, in-UI management of model presets — the thing they
saw missing ("I don't see input fields for model definitions") — inside the
existing jev_router right-canvas panel. Also uplift the panel's overall
visual quality, using StitchMCP-generated HTML/CSS as the design reference.

Preset data lives in `/a0/usr/plugins/_model_config/presets.yaml` (the
`_model_config` plugin owns the file; jev_router reads it every call). This
feature makes jev_router write-capable for that file with strict validation.

### ASSUMPTIONS (correct me now)
1. The editor lives **inside the existing right-canvas panel** as a new
   "Presets" tab/section — not a separate page, not a modal dialog.
2. jev_router writes directly to `_model_config/presets.yaml` (single shared
   source). The `_model_config` plugin has no WebUI of its own; nothing
   coordinates concurrent edits, so we defend with atomic writes + backup.
3. Edit scope: top-level `name`, `description`, plus the **chat** role block
   (provider, name=model, ctx_length, ctx_history, vision, max_embeds,
   rl_*). Utility/embedding/vision role blocks are shown read-only (copied
   verbatim on save). No rename of the file's other keys is allowed.
4. Validation is local and strict: unique name, required chat
   provider+model, numeric bounds (ctx_length > 0, 0 < ctx_history <= 1,
   rl_* >= 0), description optional (<= 300 chars).
5. StitchMCP output is a **design reference only** (copy guidance, layout,
   spacing, colors). Final code stays self-contained in the panel fragment
   (no external CSS/JS deps, matches existing Alpine.js + panel style).
6. Panel keeps diff-guarded 20s polling; the editor must never clobber a
   field the user is editing (focus-guard), per existing pattern.

## Tech Stack

Existing: Alpine.js single-file fragment (`webui/jev-router-panel.html`),
Flask plugin APIs (`api/*.py`), helpers (`helpers/*.py`), PyYAML, pytest.
StitchMCP (Google Stitch) for HTML/CSS mockups of the design.
No new runtime dependencies.

## Commands

- Focused tests: `/opt/venv-a0/bin/python -m pytest tests/test_presets_api.py tests/test_panel_consistency.py -q`
- Full suite: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Sync to deployed: copy `webui/`, `api/`, `helpers/` per panel-sync
  checklist; runtime files excluded; hard-refresh browser (no restart -
  panel + APIs are request-scoped).

## Project Structure (files touched)

- `webui/jev-router-panel.html` — new Presets section (form + list),
  visual uplift per Stitch design; single canonical copy.
- `extensions/webui/right-canvas-panels/jev-router-panel.html` — deployed
  render-path copy (byte-identical; guarded by test_panel_consistency).
- `api/routing_presets.py` (new) — GET list / POST save (create+update) /
  DELETE preset. All writes: validate -> atomic write -> backup
  `presets.yaml.bak` -> trigger auto-wire sync.
- `helpers/presets_editor.py` (new) — pure validation + serialization
  logic; no Flask imports.
- `tests/test_presets_editor.py` (new) — validation + round-trip.
- `tests/test_presets_api.py` (new) — API contract.

## Code Style

Match existing panel: plain Alpine.js, semantic HTML, container queries,
focus-visible rings, no fixed pixel widths, `container-type: inline-size`.
Validation errors render inline beneath the offending field.

## Testing Strategy

- TDD: failing tests before each slice (form serialization, validation
  matrix, YAML round-trip preserving unknown keys, API happy/sad paths).
- Panel-consistency guard tests stay green (byte-identical copies).
- No e2e browser automation required for merge; manual verification step
  on deployed panel + hard refresh.

## Boundaries

- Always: atomic YAML write with `.bak` backup; preserve unknown keys and
  non-chat role blocks byte-for-byte semantics; keep `name` immutable on
  edit (rename = delete + create) so auto-wire history stays sane.
- Ask first: touching `_model_config` plugin code itself; adding delete
  for a preset that is currently `Default`-referenced in settings.
- Never: write to presets.yaml without validation; include secrets in the
  panel response (api keys are never stored in presets.yaml).

## Success Criteria

1. Panel "Presets" section lists all presets from presets.yaml with name,
   description, provider/model badges; empty state shown when none.
2. Creating a preset via the form appends to presets.yaml, triggers
   auto-wire (appears in band tails), and shows in the list without reload.
3. Editing updates only allowed fields; validation errors (duplicate name,
   missing provider, bad numbers) block save and render inline.
4. Deleting removes the preset (confirm step) and auto-wire prunes it from
   band orders on next call.
5. A save never corrupts the file: post-write `yaml.safe_load` equals the
   intended list; unknown keys survive round-trip.
6. Stitch-generated design reference exists (HTML/CSS mock artifact) and the
   implemented panel visibly follows it; whole suite stays green.

## Open Questions

1. Should preset descriptions feed a "regenerate with Jev" button? (v2)
2. Should we support reordering presets in the file (affects list order)?
   Proposed: no — list sorted alphabetically in UI.

## Design Reference

Linear's DESIGN.md (from VoltAgent/awesome-design-md collection) —
utra-minimal developer-tool aesthetic, single accent color, precise
spacing, keyboard-first. This replaces the StitchMCP mock which failed
auth. The DESIGN.md pattern: plain markdown read by AI agents for
consistent UI generation.
