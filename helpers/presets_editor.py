# jev_router presets editor: validation, serialization, and atomic YAML writes.
# Pure helpers — no Flask, no framework deps.
import tempfile
import os
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml


# Validation rules
REQUIRED_CHAT_FIELDS = ('provider', 'name')


def validate_preset(data: Dict[str, Any], existing_names: Set[str], model_preset_names: Set[str] | None = None) -> Dict[str, str]:
    """Validate a preset dict; return {field_path: error_message}.

    Empty dict means valid. Supports two formats:
    
    1. Plain-text format (new, authoritative):
       - name: unique among existing_names
       - description: required, non-empty, max 300 chars
       - from: required, must resolve to a model preset name from model_preset_names
    
    2. Legacy structured format (deprecated, for backward compat):
       - name: unique among existing_names
       - chat.provider and chat.name: required non-empty strings
       - chat.ctx_length: int > 0
       - chat.ctx_history: float in (0, 1]
       - chat.rl_*: int >= 0
       - description: optional, max 300 chars
    
    The format is detected by presence of 'from' field (plain-text) vs 'chat' field (legacy).
    """
    errors = {}

    # name uniqueness
    name = str(data.get('name') or '').strip()
    if not name:
        errors['name'] = 'Name is required'
    elif name in existing_names:
        errors['name'] = 'Name must be unique (already exists)'

    # Detect format:
    # - Plain-text (authoritative): has 'from' field (even if 'chat' also present, 'from' wins)
    # - Legacy: has 'chat' but NO 'from'
    # - Ambiguous: has 'description' but neither 'from' nor 'chat' → plain-text (will require 'from')
    has_from = 'from' in data
    has_chat = 'chat' in data
    has_description = 'description' in data and data.get('description') is not None
    
    is_plain_text = has_from or (has_description and not has_chat and not has_from)

    if is_plain_text:
        # Plain-text format validation
        # description: required, non-empty, <= 300 chars
        desc = data.get('description')
        if desc is None:
            errors['description'] = 'Description is required'
        else:
            d = str(desc)
            if not d.strip():
                errors['description'] = 'Description cannot be empty'
            elif len(d) > 300:
                errors['description'] = 'Description must be <= 300 characters'

        # from: required, must resolve to existing model preset
        from_ref = data.get('from')
        if from_ref is None:
            errors['from'] = 'Field "from" is required (must reference a model preset)'
        else:
            from_str = str(from_ref).strip()
            if not from_str:
                errors['from'] = 'Field "from" cannot be empty'
            elif model_preset_names is not None and from_str not in model_preset_names:
                errors['from'] = f'Model preset "{from_str}" does not exist'
        
        # Do NOT validate old structured fields (chat, vision, utility, embedding)
        # They come from the referenced model preset at runtime
    else:
        # Legacy structured format validation (backward compat)
        # chat role required fields
        chat = data.get('chat')
        if not isinstance(chat, dict):
            errors['chat'] = 'Chat role block is required and must be an object'
        else:
            for field in REQUIRED_CHAT_FIELDS:
                val = str(chat.get(field) or '').strip()
                if not val:
                    errors[f'chat.{field}'] = f'Chat {field} is required'

            # numeric validations
            ctx_len = chat.get('ctx_length')
            if ctx_len is not None:
                try:
                    if int(ctx_len) <= 0:
                        errors['chat.ctx_length'] = 'Context length must be > 0'
                except (ValueError, TypeError):
                    errors['chat.ctx_length'] = 'Context length must be an integer'

            ctx_hist = chat.get('ctx_history')
            if ctx_hist is not None:
                try:
                    f = float(ctx_hist)
                    if not (0 < f <= 1):
                        errors['chat.ctx_history'] = 'Context history must be in (0, 1]'
                except (ValueError, TypeError):
                    errors['chat.ctx_history'] = 'Context history must be a number'

            for rl_field in ('rl_requests', 'rl_input', 'rl_output'):
                val = chat.get(rl_field)
                if val is not None:
                    try:
                        if int(val) < 0:
                            errors[f'chat.{rl_field}'] = f'{rl_field} must be >= 0'
                    except (ValueError, TypeError):
                        errors[f'chat.{rl_field}'] = f'{rl_field} must be an integer'

        # description length (optional in legacy)
        desc = data.get('description')
        if desc is not None:
            d = str(desc)
            if len(d) > 300:
                errors['description'] = 'Description must be <= 300 characters'

    return errors


def serialize_preset(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized copy of the preset dict, preserving all keys.

    This is a passthrough that ensures the structure is clean for YAML output
    while preserving unknown keys at any nesting level.
    """
    # Deep copy preserving all keys
    return _deep_copy(data)


def _deep_copy(obj: Any) -> Any:
    """Recursively copy dicts/lists, preserving all other types as-is."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


def apply_edit(original: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge incoming edit into original, preserving non-chat roles and unknown keys.

    Rules:
    - Top-level scalar fields (name, description) are replaced if present in incoming
    - chat role block: fields from incoming replace original; unknown keys in original.chat preserved
    - utility, embedding, vision, and any other role blocks: preserved entirely from original
    - Unknown top-level keys on original are preserved
    """
    result = _deep_copy(original)

    # Top-level scalar fields that can be edited
    for field in ('name', 'description'):
        if field in incoming:
            result[field] = incoming[field]

    # chat role: merge fields, preserve original's unknown keys
    if 'chat' in incoming and isinstance(incoming['chat'], dict):
        if 'chat' not in result or not isinstance(result['chat'], dict):
            result['chat'] = {}
        for k, v in incoming['chat'].items():
            result['chat'][k] = v
    # Note: original's chat keys not in incoming are kept (already in result)

    # Non-chat role blocks: DO NOT TOUCH - keep original entirely
    # (utility, embedding, vision, and any other roles)
    # Unknown top-level keys on original are also kept (already in result)

    return result


def save_presets(path: Path, presets_list: List[Dict[str, Any]]) -> None:
    """Atomically write presets list to YAML file with .bak backup.

    - Writes to a temp file first, then atomic rename
    - Creates .bak backup of previous file if it existed
    - Post-write: re-reads and verifies content matches intended list
    - Never raises on failure; logs error and re-raises
    """
    path = Path(path)
    bak_path = path.with_suffix(path.suffix + '.bak')

    # Serialize to YAML string first (to catch serialization errors before any FS ops)
    yaml_str = yaml.safe_dump(presets_list, sort_keys=False, allow_unicode=True)

    # Create backup if original exists
    if path.exists():
        try:
            # Copy current file to .bak
            bak_path.write_bytes(path.read_bytes())
        except Exception:
            pass  # backup is best-effort

    # Atomic write via temp file + rename
    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=path.parent,
        prefix=path.name + '.tmp',
        delete=False,
        encoding='utf-8',
    ) as tmp:
        tmp.write(yaml_str)
        tmp_path = Path(tmp.name)

    try:
        # Atomic rename
        tmp_path.replace(path)
    except Exception:
        # Clean up temp file on failure
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    # Post-write verification
    loaded = yaml.safe_load(path.read_text())
    if loaded != presets_list:
        raise RuntimeError(
            'Post-write verification failed: written YAML does not match intended list')


# ============================================================================
# Migration: legacy structured -> plain-text authoritative
# ============================================================================

def _derive_description(preset: Dict[str, Any]) -> str:
    """Derive a plain-text description from a legacy preset's technical facts."""
    parts = []
    chat = preset.get('chat')
    if isinstance(chat, dict):
        provider = chat.get('provider')
        model = chat.get('name')
        if provider and model:
            parts.append(f'{provider} · {model}')
        elif model:
            parts.append(model)
        elif provider:
            parts.append(provider)
        # Add vision if present
        if chat.get('vision'):
            parts.append('vision')
    # Fallback if no chat info
    if not parts:
        parts.append('model preset')
    return ', '.join(parts)


def migrate_to_plain_text(presets: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    """Migrate legacy structured presets to plain-text authoritative format.

    Rules:
    - Presets with 'from' field are already plain-text → untouched
    - Presets with non-empty description → untouched (user-authored)
    - Presets with empty/missing description → derive from technical facts
    - All unknown keys and role blocks preserved untouched
    - Returns (migrated_list, changed_count)

    Idempotent: second run returns same list with changed_count=0.
    """
    if not presets:
        return [], 0

    migrated = []
    changed = 0
    for p in presets:
        new_p = _deep_copy(p)
        
        # Already plain-text (has 'from') → skip
        if 'from' in new_p:
            migrated.append(new_p)
            continue

        # Has non-empty user-authored description → skip
        desc = new_p.get('description')
        if desc is not None and str(desc).strip():
            migrated.append(new_p)
            continue

        # Legacy: derive description from technical facts
        derived = _derive_description(new_p)
        new_p['description'] = derived
        changed += 1
        migrated.append(new_p)

    return migrated, changed