# Spec: Collapsible Model Presets Section

## Objective

The Model Presets card in the jev_router right-canvas panel is the noisiest
section of the panel: it renders a hint plus one row per preset with an inline
description editor, pushing the higher-value sections (Recent Decisions,
Circuit Breaker, Band Tuning) out of view. This feature lets the user collapse
the whole Model Presets section down to its header row, so the panel default
read stays focused on routing decisions.

User story: *As a panel user, I can collapse the Model Presets card to just its
title bar with one click, and expand it again when I want to edit preset
descriptions — and my choice sticks across panel reloads.*

### ASSUMPTIONS (correct me now)
1. Scope is **only** the Model Presets card. Other cards (Recent Decisions,
   Circuit Breaker, Band Tuning, Excluded Providers) keep their current
   always-expanded behavior in this pass.
2. The toggle lives in the existing `.jev-card-head` of the presets card,
   mirroring the `.jev-toggles` pattern already used by Recent Decisions and
   Band Tuning (plain Alpine state, no new dependencies).
3. Collapsing hides `.jev-preset-hint`, `.jev-presets-list`, and
   `.jev-preset-status` — the header row with the section title stays visible
   as the affordance to re-expand.
4. State persists in `localStorage` under a `jev_router_` namespaced key so
   the choice survives reloads and panel re-opens. Storage failure (private
   mode, disabled storage) must degrade to in-memory state only.
5. **Default state is collapsed** for first-time users, to focus panel reads
   on routing decisions; expandable on demand.
6. Collapsed state must not break the focus guard or the diff-guarded 20s
   polling: the list keeps loading in the background, and a description input
   that is focused while the user collapses is not silently edited — existing
   focus-guard behavior is preserved, not redefined here.
7. Panel copies stay byte-identical across the three render paths
   (canonical `webui/`, `extensions/webui/right-canvas-panels/`, plugin
   `plugin/webui/` snapshot), guarded by `test_panel_consistency.py`.

## Tech Stack

Existing only: Alpine.js single-file fragment (`webui/jev-router-panel.html`),
CSS custom properties with light/dark `prefers-color-scheme` variants, pytest.
No new runtime dependencies, no backend/API changes — this is a pure
client-side presentation change.

## Commands

- Focused tests: `/opt/venv-a0/bin/python -m pytest tests/test_panel_consistency.py -q`
- Full suite: `/opt/venv-a0/bin/python -m pytest tests/ -q`
- Sync to deployed: copy panel byte-identically to `extensions/webui/right-canvas-panels/`
  and `/a0/usr/plugins/jev_router/webui/`; runtime files (`routing-policy.yaml`,
  `config.json`) excluded from sync; hard-refresh browser (panel is request-scoped,
  no framework restart needed for webui-only changes).

## Project Structure (files touched)

- `webui/jev-router-panel.html` — add collapse toggle button in the presets
  `.jev-card-head`, Alpine boolean state, `hidden`/conditional binding on the
  three body elements, localStorage read/write, and collapse CSS
  (rotating chevron, focus-visible ring).
- `extensions/webui/right-canvas-panels/jev-router-panel.html` — byte-identical
  copy (render path).
- `plugin/webui/jev-router-panel.html` — byte-identical snapshot copy.
- `tests/test_panel_consistency.py` — new contract test pinning the collapse
  control (see Testing Strategy); existing byte-identity guards stay green.

## Code Style

Match the existing panel fragment: semantic HTML, plain Alpine state on the
panel root, CSS variables only (`var(--text-secondary)`, `var(--border-panel)`),
no fixed pixel widths, `container-type: inline-size` respected. Example of the
expected shape:

```html
<div class="jev-card-head">
  <button type="button" class="jev-collapse-btn"
          :aria-expanded="presetsOpen"
          @click="togglePresets()">
    <h2 class="jev-card-title">Model presets</h2>
    <span class="jev-chevron" :class="{ 'is-open': presetsOpen }"></span>
  </button>
</div>
<div class="jev-preset-hint" x-show="presetsOpen">...</div>
```

The whole header row is clickable (large hit target), `aria-expanded` mirrors
state, and the chevron rotates via CSS transition (~150ms).

## Testing Strategy

- TDD mandatory: write the failing test first in `tests/test_panel_consistency.py`:
  - `test_panel_has_collapsible_presets_section` — canonical HTML contains the
    collapse control (`jev-collapse-btn` or equivalent), an `aria-expanded`
    binding, Alpine state guarding the presets body (`x-show`/`x-collapse` on
    `jev-presets-list`), and a localStorage persistence call
    (`localStorage.setItem` / `jev_router_` key).
  - `test_collapse_does_not_remove_preset_content` — the collapsed markup still
    contains `jev-preset-hint`, `jev-presets-list`, `jev-preset-status`,
    `jev-preset-desc-input`, and `action: 'describe'` (hiding only, never
    removing — existing inline-describe contract stays intact).
- Existing guards stay green: no add/delete controls, byte-identical copies.
- No e2e browser automation required for merge; manual verification on the
  deployed panel with hard refresh: click header, body hides, reload, state
  sticks, expand restores full list.

## Boundaries

- Always: keep all three panel copies byte-identical; keep `aria-expanded`
  accurate; preserve the focus guard and diff-guarded polling; degrade
  gracefully when localStorage is unavailable.
- Ask first: flipping the default to collapsed; collapsing any card other than
  Model Presets; any change to the describe API or preset row markup beyond
  visibility bindings.
- Never: remove preset DOM/content (hide only); add external JS/CSS deps;
  touch `routing-policy.yaml` or `config.json` in this change.

## Success Criteria

1. One click on the Model Presets header hides hint + list + status; only the
   header row remains; chevron indicates state and `aria-expanded` is correct.
2. Clicking again restores the full section with all preset rows and inline
   description editors intact and functional (describe save still works).
3. Collapsed/expanded choice persists across panel reloads via localStorage;
   with storage unavailable the toggle still works for the session.
4. Default state on a fresh profile (no stored key) is expanded.
5. Collapsing does not disturb other cards, polling, or the focus guard; the
   20s auto-refresh continues without errors while collapsed.
6. `pytest tests/` fully green, including byte-identity guards and the two new
   contract tests; deployed copies hash-identical after sync.

## Open Questions

1. Default state: expanded (this spec) or collapsed once users confirm the
   section is mostly read-only for them? — measure before flipping.
2. Should the collapse toggle state be shared with a future "collapse all
   cards" preference? Proposed: keep a per-card namespaced key now so a global
   preference can aggregate later without migration.
3. Persist per-card or one shared key for all cards? Proposed: per-card
   (`jev_router_presets_collapsed`) now, per assumption 4.
