# Implementation Plan: Preset Editor UI + Canvas Panel Enhancement

## Overview

Implement the approved spec `docs/specs/preset-editor-panel.md`: an in-panel
Preset Editor (create/edit/delete model presets with strict validation and
atomic YAML write-back to `_model_config/presets.yaml`) plus a visual uplift
of the jev_router canvas panel following Linear's DESIGN.md aesthetic.
Sliced vertically per the user's directive: form, validation, YAML
write-back, panel integration.

## Architecture Decisions

- **Pure validation core** (`helpers/presets_editor.py`, no Flask imports):
  validation matrix + YAML round-trip are unit-testable in isolation and
  reusable by the API layer. Mirrors the existing helpers pattern.
- **One API file** (`api/routing_presets.py`): list/save/delete actions in a
  single ApiHandler, same error envelope shape as `routing_policy.py`
  (`{ok, error}`), atomic write + `.bak` backup, auto-wire triggered after
  every successful write.
- **Panel fragment stays self-contained**: Alpine.js + inline CSS only;
  focus-guard prevents diff-guarded polling from clobbering fields being
  edited (existing pattern); name immutable on edit (rename = delete+
  create) so auto-wire history stays sane.
- **Design**: Linear DESIGN.md aesthetic (ultra-minimal, single indigo
  accent, precise spacing, keyboard-first) — replaces the StitchMCP mock
  that failed auth.

## Task List

### Phase 1: Foundation (validation + write-back core)

- [ ] **Task 1: Validation + YAML round-trip core**
  - Acceptance: `validate_preset(data, existing_names)` returns per-field
    errors (unique name, required chat provider+model, ctx_length > 0,
    0 < ctx_history <= 1, rl_* >= 0, description <= 300 chars);
    `serialize_preset` / `apply_edit` preserve unknown keys and non-chat
    role blocks; `save_presets` writes atomically with `.bak` backup and
    post-write `yaml.safe_load` equals the intended list.
  - Verify: `/opt/venv-a0/bin/python -m pytest tests/test_presets_editor.py -q`
  - Dependencies: None
  - Files: `helpers/presets_editor.py` (new), `tests/test_presets_editor.py` (new)
  - Estimated scope: S (2 files)

### Checkpoint: Foundation
- [ ] Focused tests green; full suite still green

### Phase 2: API layer

- [ ] **Task 2: Presets API (list / save / delete)**
  - Acceptance: GET lists all presets with name/description/chat fields;
    POST save validates (invalid input -> `ok: false` + field errors, no
    write); POST delete requires confirm name; every successful write:
    atomic + `.bak` + auto-wire sync; never raises.
  - Verify: `/opt/venv-a0/bin/python -m pytest tests/test_presets_api.py -q`
  - Dependencies: Task 1
  - Files: `api/routing_presets.py` (new), `tests/test_presets_api.py` (new)
  - Estimated scope: S (2 files)

### Checkpoint: API layer
- [ ] API contract tests green; write path proven against a temp copy of presets.yaml

### Phase 3: Panel integration + polish

- [ ] **Task 3: Panel Presets section (list + form)**
  - Acceptance: Presets section lists all presets (name bold, provider/model
    badges, description line, edit/delete icons, vision dot); empty state;
    collapsible form with labeled fields (Name disabled on edit,
    Description with 300-char counter, Provider, Model, ctx_length,
    ctx_history slider, vision switch, rl_* inputs); Save/Cancel; inline
    field errors from the API; focus-guard keeps polling from clobbering
    edits; list refreshes after save without reload.
  - Verify: full suite + `tests/test_panel_consistency.py` green; manual
    check on deployed panel after hard refresh
  - Dependencies: Task 2
  - Files: `webui/jev-router-panel.html`
  - Estimated scope: M (1 file, large single-file edit)

- [ ] **Task 4: Visual uplift per Linear DESIGN.md + deploy**
  - Acceptance: Panel styling matches Linear aesthetic (indigo accent
    #5e6ad2 family, hairline borders, 8px radii, precise spacing,
    keyboard-first focus-visible); canonical + deployed render-path copies
    byte-identical (guard test); deployed panel verified with hard refresh.
  - Verify: full suite green; deployed syntax + md5 inventory; manual check
  - Dependencies: Task 3
  - Files: `webui/jev-router-panel.html`, deployed copies, `CHANGELOG.md`, `plugin.yaml`
  - Estimated scope: S (4 files)

### Checkpoint: Complete
- [ ] All 6 spec success criteria met
- [ ] Full suite green; DOX/CHANGELOG updated; deployed + verified

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Concurrent writes to presets.yaml (no owning UI) | High | Atomic write + `.bak` backup + post-write re-parse check |
| Unknown keys lost on round-trip | High | `apply_edit` mutates only allowed fields; round-trip test asserts unknown keys survive |
| Polling clobbers form while editing | Med | Focus-guard: skip field refresh while an editor field has focus (existing pattern) |
| Panel fragment drift between repo and deployed | Med | Byte-identity guard test + explicit deploy checklist |
| Large single-file HTML edit breaks existing sections | Med | Section-scoped edits; full-suite + panel-consistency tests after each slice |

## Open Questions

- None blocking. (v2 candidates from spec: Jev-powered description
  regeneration, in-UI preset reordering.)
