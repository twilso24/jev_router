# Spec: Jev Router Right-Canvas Panel UI Isolation

## Objective

The Jev Router panel currently contributes raw panel markup to the shared `right-canvas-panels` extension point. Because it has no surface wrapper, its content remains visible when another surface—observed with Swarm—is active. The fix must make Jev Router participate in the shared single-active-surface visibility contract without changing its panel behavior or modal rendering.

**User story:** As a canvas user, when I switch from Jev Router to Swarm, Editor, Browser, or another surface, Jev Router disappears completely; when I select Jev Router again, its panel appears and remains functional.

### Evidence and current behavior

- The browser page showed Swarm selected while Jev Router content was rendered below it in the same canvas.
- `extensions/webui/right-canvas-panels/jev-router-panel.html` is currently byte-identical to the canonical raw panel fragment and does not contain `data-surface-id`, `is-active`, `is-mounted`, or `aria-hidden` bindings.
- Working canvas contributions, including Swarm and Files, use a `right-canvas-surface-panel` wrapper with shared `$store.rightCanvas` visibility bindings.
- Shared CSS already sets inactive surface panels to `opacity: 0`, `pointer-events: none`, and `z-index: 0`; active panels receive the visible state. No Jev-specific z-index workaround is required.

## Assumptions

1. This is a frontend-only fix. No backend/API, routing-policy, configuration, or shared canvas-store behavior changes are required.
2. `webui/jev-router-panel.html` remains the canonical inner panel fragment and continues to serve the existing `modalPath`.
3. `extensions/webui/right-canvas-panels/jev-router-panel.html` becomes a thin canvas-only wrapper that includes the canonical fragment with `<x-component ... mode="canvas">`.
4. `plugin/webui/jev-router-panel.html` remains the legacy snapshot of the canonical inner fragment and must remain content-identical to `webui/jev-router-panel.html`.
5. The existing Jev Router panel behavior is out of scope: API calls, auto-refresh, focus guards, preset collapsing, localStorage keys, band tuning, provider exclusion, and inline description editing must not change.
6. The registered surface ID is `jev_router`, and the existing registration and modal path remain valid unless implementation verification proves otherwise.

## Tech Stack

Existing Agent Zero WebUI extension HTML, Alpine.js bindings, shared right-canvas CSS/store, and pytest contract tests. No new dependencies.

## Commands

- Focused tests: `/opt/venv-a0/bin/python -m pytest tests/test_panel_consistency.py -q`
- Full suite: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Hash check: `sha256sum webui/jev-router-panel.html plugin/webui/jev-router-panel.html extensions/webui/right-canvas-panels/jev-router-panel.html`
- Runtime sync after tests pass: copy the canonical inner fragment to `/a0/usr/plugins/jev_router/webui/jev-router-panel.html` and the wrapper to the deployed right-canvas extension path. Do not sync `routing-policy.yaml` or `config.json`.
- Browser verification: hard-refresh the WebUI, open Jev Router, switch to Swarm and back, and confirm no Jev Router content or pointer interaction remains while Swarm is active.

## Project Structure

Files expected to change:

- `extensions/webui/right-canvas-panels/jev-router-panel.html` — replace the raw duplicate with the thin visibility-aware wrapper.
- `tests/test_panel_consistency.py` — replace the obsolete assertion that every panel copy is byte-identical; add wrapper and inner-fragment contract tests.
- `docs/specs/panel-ui-isolation.md` — this specification.

Files that must remain behaviorally unchanged:

- `webui/jev-router-panel.html` — canonical inner/modal fragment.
- `plugin/webui/jev-router-panel.html` — canonical snapshot; copy from `webui/` if needed.
- `extensions/webui/right_canvas_register_surfaces/register-jev-router.js` — retain `id: 'jev_router'`, existing `open()` selector, and `modalPath: '/plugins/jev_router/webui/jev-router-panel.html'` unless a focused test demonstrates a required adjustment.

## Code Style

The extension wrapper should follow the existing Files/Swarm wrapper contract:

```html
<div
  class="right-canvas-surface-panel jev-router-canvas-surface"
  data-surface-id="jev_router"
  :class="{
    'is-active': $store.rightCanvas?.isSurfaceVisible('jev_router'),
    'is-mounted': $store.rightCanvas?.isSurfaceRendered('jev_router')
  }"
  :aria-hidden="(!$store.rightCanvas?.isSurfaceVisible('jev_router')).toString()"
>
  <x-component
    path="/plugins/jev_router/webui/jev-router-panel.html"
    mode="canvas"
  ></x-component>
</div>
```

The wrapper must be thin: no duplicated `.jev-panel` markup, styles, scripts, API calls, or lifecycle logic. The canonical fragment remains responsible for finding `.jev-panel` and initializing its existing behavior.

## Testing Strategy

Use TDD: add failing contract tests before changing the wrapper.

### Wrapper contract

Add `test_canvas_panel_has_surface_wrapper` to assert that the extension file contains:

- `right-canvas-surface-panel`;
- `data-surface-id="jev_router"`;
- `is-active` bound through `$store.rightCanvas?.isSurfaceVisible('jev_router')`;
- `is-mounted` bound through `$store.rightCanvas?.isSurfaceRendered('jev_router')`;
- `:aria-hidden` bound to the inverse visibility;
- an `x-component` include for `/plugins/jev_router/webui/jev-router-panel.html` with `mode="canvas"`.

Add `test_canvas_panel_is_thin_wrapper` to assert that the extension file does not duplicate the inner implementation markers such as `.jev-header`, `callJsonApi`, or `<script type="module">`. Prefer structural checks over fragile full-file snapshots.

### Inner-fragment and registration contracts

Retain or add tests that assert:

- `webui/jev-router-panel.html` exists and is non-empty;
- `plugin/webui/jev-router-panel.html` has the same SHA-256 as the canonical inner fragment;
- the canonical fragment still contains existing panel contracts, including `action: 'describe'`, `jev-preset-desc-input`, `jev-preset-save`, and the collapsible presets controls;
- `register-jev-router.js` keeps `modalPath` set to `/plugins/jev_router/webui/jev-router-panel.html` and waits for `[data-surface-id="jev_router"] .jev-panel`.

Update the existing duplicate-copy test so it no longer requires the canvas wrapper to match the canonical inner fragment. It should compare only the two inner-fragment copies and validate the wrapper separately.

### Runtime/browser verification

After focused and full tests pass:

1. Open Jev Router and confirm its content renders once.
2. Select Swarm and confirm the Jev Router content is not visible, not clickable, and does not appear behind Swarm.
3. Select Editor, Browser, and Desktop and repeat the isolation check.
4. Return to Jev Router and confirm recent decisions, circuit breaker, band tuning, excluded providers, model presets, auto-refresh, and inline description editing still work.
5. Verify that the modal path still renders the canonical panel fragment without the canvas wrapper being nested incorrectly.
6. Verify deployed source hashes for the canonical inner fragment and snapshot after sync.

If the live browser endpoint is unavailable, record browser verification as not run rather than inferring success from static tests. The prior remote-debugging failure must be resolved before claiming visual verification.

## Boundaries

- **Always:** use the shared `right-canvas-surface-panel` semantics; keep inactive surfaces hidden and non-interactive; preserve the canonical fragment and all existing panel behavior; keep the canonical and plugin snapshot fragments byte-identical; use `mode="canvas"` for the wrapper include.
- **Ask first:** changing `right-canvas-store.js`, shared right-canvas CSS, the surface registration lifecycle, `modalPath` semantics, or the panel's API/state behavior.
- **Never:** fix this with a Jev-specific z-index override; duplicate the panel implementation in the wrapper; remove `data-surface-id` or visibility bindings; change backend APIs, routing policy, `config.json`, or `routing-policy.yaml`; claim browser verification without a successful live check.

## Success Criteria

1. The extension contribution has exactly one `jev_router` surface wrapper compatible with the shared canvas CSS/store contract.
2. Jev Router is fully hidden and non-interactive whenever another canvas surface is active.
3. Selecting Jev Router shows exactly one panel instance, with no duplicate or nested Jev Router content.
4. The canonical modal path still renders the existing inner panel correctly.
5. The canonical and plugin snapshot inner fragments remain byte-identical; the wrapper is tested as a wrapper, not as an identical content copy.
6. All existing panel features and state persistence continue to work.
7. `/opt/venv-a0/bin/python -m pytest tests/ -q` passes.
8. Manual browser verification passes after a hard refresh, or is explicitly reported as blocked if the browser remote-debugging endpoint is unavailable.

## Open Questions

1. Should the wrapper use an absolute plugin path or a repository-relative path in `x-component`? Proposed: use the absolute `/plugins/jev_router/webui/jev-router-panel.html` path, matching the existing Swarm convention and deployed plugin routing.
2. Should the extension wrapper also be copied into a plugin snapshot directory? Proposed: sync the wrapper to the deployed extension render path only; retain `plugin/webui/jev-router-panel.html` as the inner-fragment snapshot and document the two distinct roles in the consistency tests.
