# Task 1 (TDD): presets editor validation + YAML round-trip - RED first.
# helpers/presets_editor.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python -m pytest tests/test_presets_editor.py -q
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import yaml

# These imports will fail until we implement helpers/presets_editor.py
try:
    from helpers import presets_editor
    HAVE_MOD = True
except Exception:
    HAVE_MOD = False


def _sample_preset():
    return {
        'name': 'TestPreset',
        'description': 'A test preset for validation',
        'chat': {
            'provider': 'openrouter',
            'name': 'test/model',
            'api_base': '',
            'ctx_length': 128000,
            'ctx_history': 0.5,
            'vision': True,
            'max_embeds': 5,
            'rl_requests': 10,
            'rl_input': 1000,
            'rl_output': 2000
        },
        'utility': {
            'provider': 'openrouter',
            'name': 'test/utility'
        },
        'embedding': {
            'provider': 'huggingface',
            'name': 'sentence-transformers/all-MiniLM-L6-v2'
        },
        'vision': {
            'provider': 'openrouter',
            'name': 'test/vision'
        }
    }


def _sample_plain_preset():
    return {
        'name': 'TestPreset',
        'description': 'A test preset for validation',
        'from': 'Default'
    }


def _model_preset_names() -> set[str]:
    """Get available model preset names from the real pool for validation tests."""
    from helpers.pool import load_pool
    pool = load_pool(Path('/a0/usr/plugins/_model_config/presets.yaml'))
    return {e.preset_name for e in pool.entries}


def test_module_exists():
    assert HAVE_MOD, 'helpers.presets_editor not importable'


def test_validate_preset_unique_name():
    existing = {'Default', 'Efficient'}
    data = _sample_preset()
    data['name'] = 'Default'
    errors = presets_editor.validate_preset(data, existing)
    assert 'name' in errors
    assert 'unique' in errors['name'].lower()


def test_validate_preset_missing_chat_provider():
    data = _sample_preset()
    data['chat']['provider'] = ''
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.provider' in errors or 'provider' in str(errors)


def test_validate_preset_missing_chat_model():
    data = _sample_preset()
    data['chat']['name'] = ''
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.name' in errors or 'model' in str(errors) or 'name' in str(errors)


def test_validate_preset_invalid_ctx_length():
    data = _sample_preset()
    data['chat']['ctx_length'] = 0
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.ctx_length' in errors
    data['chat']['ctx_length'] = -1
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.ctx_length' in errors


def test_validate_preset_invalid_ctx_history():
    data = _sample_preset()
    data['chat']['ctx_history'] = 0
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.ctx_history' in errors
    data['chat']['ctx_history'] = 1.5
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.ctx_history' in errors
    data['chat']['ctx_history'] = -0.1
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.ctx_history' in errors


def test_validate_preset_negative_rl():
    data = _sample_preset()
    data['chat']['rl_requests'] = -1
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.rl_requests' in errors
    data['chat']['rl_input'] = -5
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.rl_input' in errors
    data['chat']['rl_output'] = -10
    errors = presets_editor.validate_preset(data, set())
    assert 'chat.rl_output' in errors


def test_validate_preset_description_too_long():
    data = _sample_preset()
    data['description'] = 'x' * 301
    errors = presets_editor.validate_preset(data, set())
    assert 'description' in errors


def test_validate_preset_valid_passes():
    data = _sample_preset()
    errors = presets_editor.validate_preset(data, {'Default'})
    assert errors == {}


def test_serialize_preset_round_trip_preserves_unknown_keys():
    data = _sample_preset()
    # Add an unknown key that should survive
    data['custom_field'] = 'should_not_be_lost'
    data['chat']['custom_chat_key'] = 'also_preserved'
    serialized = presets_editor.serialize_preset(data)
    assert serialized['custom_field'] == 'should_not_be_lost'
    assert serialized['chat']['custom_chat_key'] == 'also_preserved'
    # Core fields still present
    assert serialized['name'] == data['name']
    assert serialized['chat']['provider'] == data['chat']['provider']


def test_apply_edit_preserves_non_chat_roles():
    original = _sample_preset()
    original['utility']['provider'] = 'original_utility_provider'
    original['embedding']['name'] = 'original_embedding_model'
    original['vision']['provider'] = 'original_vision_provider'
    
    # New incoming data with only chat fields changed
    incoming = _sample_preset()
    incoming['name'] = 'EditedName'
    incoming['description'] = 'New description'
    incoming['chat']['provider'] = 'new_provider'
    incoming['chat']['name'] = 'new/model'
    
    merged = presets_editor.apply_edit(original, incoming)
    # Chat fields updated
    assert merged['name'] == 'EditedName'
    assert merged['description'] == 'New description'
    assert merged['chat']['provider'] == 'new_provider'
    assert merged['chat']['name'] == 'new/model'
    # Non-chat roles preserved exactly
    assert merged['utility']['provider'] == 'original_utility_provider'
    assert merged['embedding']['name'] == 'original_embedding_model'
    assert merged['vision']['provider'] == 'original_vision_provider'
    # Unknown keys on original preserved
    original['custom_top'] = 'kept'
    original['chat']['custom_chat'] = 'kept'
    merged2 = presets_editor.apply_edit(original, incoming)
    assert merged2['custom_top'] == 'kept'
    assert merged2['chat']['custom_chat'] == 'kept'


def test_save_presets_atomic_write_with_bak():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'presets.yaml'
        original = [_sample_preset(), _sample_preset()]
        original[1]['name'] = 'Another'
        
        presets_editor.save_presets(path, original)
        
        # File exists
        assert path.exists()
        # Backup exists
        bak = Path(td) / 'presets.yaml.bak'
        # Backup may or may not exist depending on whether it was pre-existing
        # But after write, we should be able to load and it matches
        loaded = yaml.safe_load(path.read_text())
        assert loaded == original
        # Post-write re-parse equals intended list
        assert yaml.safe_load(path.read_text()) == original


def test_save_presets_creates_bak_when_file_exists():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'presets.yaml'
        original = [_sample_preset()]
        presets_editor.save_presets(path, original)
        # Now write again - should create .bak
        presets_editor.save_presets(path, original)
        bak = Path(td) / 'presets.yaml.bak'
        assert bak.exists(), 'Backup should exist after second write'
        # Backup content should match original
        assert yaml.safe_load(bak.read_text()) == original


# ============================================================================
# RED tests for plain-text preset validation (Task: plain-text presets)
# ============================================================================


def _model_preset_names() -> set[str]:
    """Get available model preset names from the real pool for validation tests."""
    from helpers.pool import load_pool
    pool = load_pool(Path('/a0/usr/plugins/_model_config/presets.yaml'))
    return {e.preset_name for e in pool.entries}



def test_validate_plain_preset_valid():
    """Valid plain-text preset: name, description, from (resolvable)."""
    existing = {'Default', 'Efficient'}
    data = _sample_plain_preset()
    data['from'] = 'Default'
    errors = presets_editor.validate_preset(data, existing, _model_preset_names())
    assert errors == {}, f'Expected valid, got errors: {errors}'


def test_validate_plain_preset_missing_description():
    """Description is required."""
    data = _sample_plain_preset()
    del data['description']
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    assert 'description' in errors
    assert 'required' in errors['description'].lower()


def test_validate_plain_preset_empty_description():
    """Description cannot be empty."""
    data = _sample_plain_preset()
    data['description'] = ''
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    assert 'description' in errors


def test_validate_plain_preset_description_too_long():
    """Description must be <= 300 characters."""
    data = _sample_plain_preset()
    data['description'] = 'x' * 301
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    assert 'description' in errors
    assert '300' in errors['description']


def test_validate_plain_preset_missing_from():
    """'from' field is required."""
    data = _sample_plain_preset()
    del data['from']
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    assert 'from' in errors
    assert 'required' in errors['from'].lower()


def test_validate_plain_preset_invalid_from():
    """'from' must reference an existing model preset."""
    data = _sample_plain_preset()
    data['from'] = 'NonExistentModelPreset'
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    assert 'from' in errors
    assert 'exist' in errors['from'].lower() or 'resolve' in errors['from'].lower()


def test_validate_plain_preset_ignores_old_structured_fields():
    """Old structured fields (chat, vision, etc.) are NOT validated."""
    data = _sample_plain_preset()
    data['from'] = 'Default'
    # Add old structured fields with invalid data
    data['chat'] = {'provider': '', 'name': ''}  # invalid
    data['vision'] = {'provider': '', 'name': ''}  # invalid
    errors = presets_editor.validate_preset(data, set(), _model_preset_names())
    # Should NOT have chat.* or vision.* errors
    chat_errors = [k for k in errors if k.startswith('chat.')]
    vision_errors = [k for k in errors if k.startswith('vision.')]
    assert not chat_errors, f'Old chat fields should not be validated: {chat_errors}'
    assert not vision_errors, f'Old vision fields should not be validated: {vision_errors}'


def test_validate_plain_preset_unique_name():
    """Name must be unique among existing presets."""
    existing = {'Default', 'Efficient'}
    data = _sample_plain_preset()
    data['name'] = 'Default'
    data['from'] = 'Efficient'
    errors = presets_editor.validate_preset(data, existing, _model_preset_names())
    assert 'name' in errors
    assert 'unique' in errors['name'].lower()


# ============================================================================
# RED tests for migrate_to_plain_text (Task 2: migration)
# ============================================================================


def test_migrate_derives_missing_description():
    """Presets without description get a derived one from technical facts."""
    legacy = _sample_preset()
    legacy['description'] = ''
    migrated, changed = presets_editor.migrate_to_plain_text([legacy])
    assert changed == 1
    desc = migrated[0]['description']
    assert desc, 'derived description must not be empty'
    # Derived from chat provider/model
    assert 'test/model' in desc
    assert 'openrouter' in desc


def test_migrate_keeps_existing_description():
    """Presets that already have a description are left untouched."""
    legacy = _sample_preset()
    legacy['description'] = 'My hand-written nuance text'
    migrated, changed = presets_editor.migrate_to_plain_text([legacy])
    assert changed == 0
    assert migrated[0]['description'] == 'My hand-written nuance text'


def test_migrate_leaves_plain_text_entries_untouched():
    """Entries already in plain-text form (have 'from') are never modified."""
    plain = _sample_plain_preset()
    plain['description'] = 'Very fast model that is not very smart'
    migrated, changed = presets_editor.migrate_to_plain_text([plain])
    assert changed == 0
    assert migrated[0] == plain


def test_migrate_preserves_unknown_keys():
    """Unknown top-level keys survive migration untouched."""
    legacy = _sample_preset()
    legacy['description'] = ''
    legacy['custom_flag'] = {'nested': [1, 2, 3]}
    migrated, changed = presets_editor.migrate_to_plain_text([legacy])
    assert changed == 1
    assert migrated[0]['custom_flag'] == {'nested': [1, 2, 3]}
    # role blocks untouched
    assert migrated[0]['utility'] == legacy['utility']


def test_migrate_is_idempotent():
    """Second run reports zero changes."""
    legacy = _sample_preset()
    legacy['description'] = ''
    migrated, changed = presets_editor.migrate_to_plain_text([legacy])
    assert changed == 1
    again, changed2 = presets_editor.migrate_to_plain_text(migrated)
    assert changed2 == 0
    assert again == migrated


def test_migrate_empty_list():
    """Empty input -> empty output, no changes."""
    migrated, changed = presets_editor.migrate_to_plain_text([])
    assert migrated == []
    assert changed == 0
