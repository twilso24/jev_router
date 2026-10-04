# Spec: Inline Plain-Text Model Definitions

## Objective

Let users define the meaning of the model presets that already exist in `/a0/usr/plugins/_model_config/presets.yaml` using plain language, for example `Very fast model that's not very smart` or `Local model best for private inference`. The description is authoritative semantic metadata for Jev; the existing provider/model configuration remains the runtime source of truth.

## Confirmed UX

- The Presets panel lists the existing model presets.
- Each row contains an inline plain-text description field and its own Save action.
- There is no Add preset action.
- There are no Edit or Delete actions.
- Users do not enter provider, model ID, context, rate-limit, or vision fields here.
- Saving updates only the selected existing model preset's `description` key and preserves all other YAML keys.

## Data and routing

```yaml
- name: Speedy
  description: Very fast model that's not very smart
  chat:
    provider: openrouter
    name: vendor/model-id
```

The existing `chat`, `utility`, `embedding`, `vision`, and unknown keys remain unchanged. When auto-tune is enabled, Jev receives the descriptions as the semantic criteria for `preset_fit` and can choose the best-fit existing model preset per turn. Technical model fields are not used as the plain-language definition.

## API contract

`POST plugins/jev_router/routing_presets` with:

```json
{"action":"list"}
```

returns existing rows as `{name, description, from}` plus `model_presets` for compatibility with older clients.

`POST plugins/jev_router/routing_presets` with:

```json
{"action":"describe","name":"Speedy","description":"Very fast model that's not very smart"}
```

updates an existing model preset only. Descriptions must be non-empty and at most 300 characters. Unknown names, blank values, and overlong values are rejected without writing.

## Testing strategy

- TDD API tests cover successful inline description updates, missing names, unknown presets, blank descriptions, length limits, atomic writes, and preservation of chat/unknown keys.
- Panel contract tests require the inline description input and `describe` action, and forbid Add, Edit, Delete, and standalone-form controls.
- Full verification uses `/opt/venv-a0/bin/python -m pytest tests/ -q`.
- Canonical, plugin snapshot, deployed WebUI, and render-fragment panel copies must remain byte-identical.

## Boundaries

- **Always:** preserve runtime model configuration and unknown YAML keys; write atomically with backup; validate before writing; keep Jev descriptions separate from technical model fields.
- **Ask first:** changing the shared `_model_config` schema beyond adding/updating `description`; changing routing policy semantics.
- **Never:** create or delete model presets from this panel; silently overwrite provider/model configuration; silently discard user descriptions.

## Success criteria

1. Every existing model preset is visible in the panel.
2. Every row provides an inline plain-text description editor and Save action.
3. Add preset, Edit, Delete, and standalone structured form controls are absent.
4. A successful save updates only the matching preset description and survives restart.
5. Auto-tune uses the descriptions as Jev's semantic fit criteria.
6. Focused and full tests pass, and all shipped panel/API copies are synchronized.
