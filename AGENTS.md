# jev_router project conventions

- plugin/ is the canonical plugin source. Deployed copy: /a0/usr/plugins/jev_router. Sync explicitly only after tests pass.
- Always use /opt/venv-a0/bin/python for this code.
- TDD: write the failing test in plugin/tests/ first, watch it fail, implement, watch it pass.
- Framework restart is REQUIRED after changes to helpers/ modules: the live process caches them in sys.modules. Extension files (extensions/) hot-load per chat; helpers do not.
- Run tests (cwd must be /a0 so plugin imports resolve):
  cd /a0 && for f in /a0/usr/projects/jev_router/plugin/tests/test_*.py; do /opt/venv-a0/bin/python "$f"; done
- Observability: /a0/tmp/jev_router_debug.log (hook trace), /a0/tmp/jev_router_telemetry.db via plugin/report.py.
- Spec: docs/specs/jev-router.md (APPROVED). Plan: docs/plans/jev-router.md.
- Never raise from the router hook; any failure falls back to the active preset and logs.

## WebUI + API conventions

- plugin/api/*.py are thin ApiHandlers at /api/plugins/jev_router/<name>;
  keep logic in helpers/webui_data.py (has tests).
- plugin/webui/jev-router-panel.html is the right-canvas surface fragment;
  it imports callJsonApi from /js/api.js (never window.csrfToken).
- Surface registration: plugin/extensions/webui/right_canvas_register_surfaces/.
- Panel endpoint paths in JS are relative (plugins/jev_router/...), POST only.
- Panel scripts must be timing-safe: never bind DOM at module import time
  (the shell imports inline modules before mounting markup). Use class-scoped
  selectors inside each .jev-panel root, idempotent init, and a
  MutationObserver scan; never throw into the shell.
