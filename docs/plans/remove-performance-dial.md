# Implementation Plan: Remove Performance Dial

Spec: `docs/specs/remove-performance-dial.md` (approved).
Goal: delete the cost/balanced/quality dial layer; band orders + pins +
signals + Jev fit + circuit breaker remain the only routing authorities.
Legacy `performance_dial` key already deleted from both live and repo
`config.json`.

## Architecture Decisions

- Remove the mechanic at its roots: `helpers/dial.py` (module) and every
  call site, not a config-level disable.
- `report.py` keeps its evidence summary but never applies a dial:
  printed orders are the policy file orders exactly; output fields drop
  `dial=` (renamed `evidence` summary).
- Pin semantics move to existing suites: `test_router.py` keeps a
  pin-freeze test (pinned bands skip auto-tune), `test_policy.py`
  covers order loading.
- Settings UI removes the dial `<select>`; the "advanced knobs wraps"
  assertion re-targets a surviving control (`config.jev_api_key`).

## Task List

### Phase 1: Evidence surface

- [x] Task 0: Delete legacy `performance_dial` from live + repo config.json — DONE.

- [ ] Task 1: report.py dial removal (RED -> GREEN)
  - Acceptance: `dial_summary` (renamed `evidence_summary`) returns
    `{auto_tune, pins, preset_stats, orders}` with orders == file
    orders; no `dial` key; `_main_dial` (renamed `_main_evidence`)
    prints orders without dial text; `report.py dial` CLI stays as the
    entrypoint name for muscle memory but output has no dial column.
  - Verify: updated `tests/test_report.py` — file-orders-exact test,
    never-raises test, no-dial-field test. Watch old tests fail first.
  - Files: report.py, tests/test_report.py  (S)

### Phase 2: Router core

- [ ] Task 2: helpers/router.py dial removal (RED -> GREEN)
  - Acceptance: no `dial` import; band_orders flow:
    tuning (auto-tune or file) -> schedules -> done. No
    `performance_dial` read. Decision reasons contain no dial text.
  - Verify: `test_router.py` — delete `test_dial_quality_promotes_...`
    and rewrite `test_pinned_band_skips_dial` as
    `test_pinned_band_skips_auto_tune` (pin freezes even with
    auto-tune on). `test_router_mention_free_dial_tags_fastpath` stays
    (mentions mechanic, unrelated).
  - Files: helpers/router.py, tests/test_router.py  (S)

### Phase 3: Module + settings UI

- [ ] Task 3: delete helpers/dial.py + tests/test_dial.py; settings UI (RED -> GREEN)
  - Acceptance: `helpers/dial.py` gone; zero `from helpers import dial`
    / `from helpers.dial` / `apply_dial` references repo-wide
    (guard test); `webui/config.html` has no `jev-dial` select or
    `config.performance_dial` binding; advanced-block test re-targeted.
  - Verify: `tests/test_settings_ui.py` updated (remove
    `test_config_json_has_dial_default`, `test_config_html_binds_dial`;
    `test_config_html_wraps_advanced_knobs` asserts `jev_api_key` is a
    primary control only). New guard test in test_dial_removal.py (or
    folded into test_settings_ui) asserts no dial references.
  - Files: helpers/dial.py (delete), tests/test_dial.py (delete),
    webui/config.html, tests/test_settings_ui.py  (S)

### Checkpoint: after Tasks 1-3
- Full suite green: `/opt/venv-a0/bin/python -m pytest tests/ -q`

### Phase 4: Deploy

- [ ] Task 4: sync + versioning
  - Acceptance: helpers/router.py, report.py, webui/config.html synced
    to `/a0/usr/plugins/jev_router/` (all copies: helpers/, plugin/,
    webui/); deployed helpers/dial.py + plugin/helpers/dial.py +
    plugin/tests/test_dial.py removed; CHANGELOG entry; plugin.yaml
    version bump.
  - Verify: byte-identical sha256 across copies; full suite green;
    `python report.py dial` runs with no dial field.
  - Files: deployed plugin, CHANGELOG.md, plugin.yaml  (S)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Stale import of removed helpers/dial.py | Live framework crash after restart | grep guard test asserts zero references before deploy; sync deletes deployed copy |
| `report.py dial` external script callers | command name kept; output drops one column | keep CLI subcommand name `dial` -> prints evidence summary |
| Old `performance_dial` key in a chat-session cfg dict | cfg.get() default covers it | all reads removed anyway; toleration is the point |
| Pin semantics lost coverage | regression risk | pin-freeze test migrated to test_router.py before deleting test_dial.py |

## Open Questions

- None. Spec assumption locked: mentions (free/prefer) stay; only the
  performance dial is removed.
