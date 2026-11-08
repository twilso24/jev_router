# Implementation Plan: Jev Router Right-Canvas Panel UI Isolation

## Overview

Fix the Jev Router right-canvas panel to participate in the shared single-active-surface visibility contract by replacing the extension contribution with a thin wrapper that includes the canonical inner fragment via `<x-component mode="canvas">`.

## Architecture Decisions

- Keep `webui/jev-router-panel.html` as the canonical inner/modal fragment unchanged.
- Replace `extensions/webui/right-canvas-panels/jev-router-panel.html` with a visibility-aware wrapper.
- Update `tests/test_panel_consistency.py` to test the wrapper separately and keep canonical/plugin inner fragments byte-identical.
- Retain existing registration and modal path; no backend changes.

## Task List

### Phase 1: Tests (RED)

- [ ] **Task 1: Add wrapper contract tests**
  - **Description:** Add failing tests asserting the extension wrapper contains the required surface bindings and x-component include.
  - **Acceptance criteria:**
    - [ ] `test_canvas_panel_has_surface_wrapper` fails (extension file lacks wrapper structure)
    - [ ] `test_canvas_panel_is_thin_wrapper` fails (extension file currently duplicates inner markup)
  - **Verification:** `/opt/venv-a0/bin/python -m pytest tests/test_panel_consistency.py::test_canvas_panel_has_surface_wrapper tests/test_panel_consistency.py::test_canvas_panel_is_thin_wrapper -v`
  - **Dependencies:** None
  - **Files:** `tests/test_panel_consistency.py`
  - **Estimated scope:** S

- [ ] **Task 2: Update duplicate-copy test to separate wrapper from inner fragment**
  - **Description:** Modify `test_no_duplicate_panel_bodies_outside_plugin_snapshot` to compare only inner-fragment copies (`webui/` and `plugin/`) while excluding the extension wrapper.
  - **Acceptance criteria:**
    - [ ] Test passes when inner fragments are byte-identical
    - [ ] Test ignores the extension wrapper file
  - **Verification:** Run the updated test
  - **Dependencies:** Task 1
  - **Files:** `tests/test_panel_consistency.py`
  - **Estimated scope:** XS

### Checkpoint: Tests Written

- [ ] New tests fail as expected (RED)
- [ ] Existing tests still pass

### Phase 2: Implementation (GREEN)

- [ ] **Task 3: Replace extension panel with thin wrapper**
  - **Description:** Write the visibility-aware wrapper to `extensions/webui/right-canvas-panels/jev-router-panel.html` using the exact structure from the spec.
  - **Acceptance criteria:**
    - [ ] File contains `right-canvas-surface-panel` class
    - [ ] File contains `data-surface-id="jev_router"`
    - [ ] File contains `:class` binding with `is-active`/`is-mounted` via `$store.rightCanvas`
    - [ ] File contains `:aria-hidden` binding
    - [ ] File contains `<x-component path="/plugins/jev_router/webui/jev-router-panel.html" mode="canvas">`
    - [ ] File does NOT contain `.jev-header`, `callJsonApi`, or `<script type="module">`
  - **Verification:** `/opt/venv-a0/bin/python -m pytest tests/test_panel_consistency.py::test_canvas_panel_has_surface_wrapper tests/test_panel_consistency.py::test_canvas_panel_is_thin_wrapper -v`
  - **Dependencies:** Task 1, Task 2
  - **Files:** `extensions/webui/right-canvas-panels/jev-router-panel.html`
  - **Estimated scope:** S

### Checkpoint: Wrapper Implemented

- [ ] New wrapper tests pass (GREEN)
- [ ] All existing panel contract tests pass

### Phase 3: Verification & Sync

- [ ] **Task 4: Full test suite verification**
  - **Description:** Run complete test suite to ensure no regressions.
  - **Acceptance criteria:**
    - [ ] `/opt/venv-a0/bin/python -m pytest tests/ -q` passes
  - **Verification:** Full test run
  - **Dependencies:** Task 3
  - **Files:** None (verification only)
  - **Estimated scope:** XS

- [ ] **Task 5: Sync to deployed copy**
  - **Description:** Copy the canonical inner fragment to `/a0/usr/plugins/jev_router/webui/jev-router-panel.html` and the wrapper to the deployed right-canvas extension path.
  - **Acceptance criteria:**
    - [ ] Deployed inner fragment hash matches canonical
    - [ ] Deployed wrapper is in place
    - [ ] Runtime files (`routing-policy.yaml`, `config.json`) NOT synced
  - **Verification:** `sha256sum` comparison; hard-refresh browser check
  - **Dependencies:** Task 4
  - **Files:** Deployment sync (external)
  - **Estimated scope:** XS

### Checkpoint: Complete

- [ ] All tests pass
- [ ] Browser verification passes (or documented as blocked)
- [ ] Ready for review

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Modal path breaks if wrapper used incorrectly | Medium | Retain `modalPath` pointing to canonical inner fragment; wrapper only used by canvas extension point |
| Canvas store API changes | Low | Use existing `$store.rightCanvas?.isSurfaceVisible/Rendered` pattern matching other panels |
| Tests become brittle with structural checks | Low | Test for presence of key attributes/bindings, not exact byte-for-byte wrapper content |

## Open Questions

- None at this time; spec assumptions validated against repository evidence.
