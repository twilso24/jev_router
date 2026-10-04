"""jev_router: presets list/save/delete API."""
from pathlib import Path

from helpers.api import ApiHandler, Request, Response

PRESETS_PATH = Path('/a0/usr/plugins/_model_config/presets.yaml')


class RoutingPresets(ApiHandler):
    def __init__(self, app=None, lock=None, presets_path: Path | None = None):
        # The framework instantiates handlers as handler_cls(app, lock).
        # Optional app/lock params keep direct test construction working.
        # For tests, create a dummy lock if not provided.
        if app is not None:
            super().__init__(app, lock)
        else:
            # Test mode: create a no-op lock
            import threading
            self.thread_lock = threading.Lock()
        self.presets_path = presets_path or PRESETS_PATH
    
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            # Lazy imports to avoid framework namespace conflicts at module load time
            from usr.plugins.jev_router.helpers import presets_editor
            from usr.plugins.jev_router.helpers import auto_wire
            
            action = str(input.get('action') or 'list')
            
            if action == 'list':
                return await self._handle_list()
            
            if action == 'save':
                return await self._handle_save(input, presets_editor, auto_wire)
            
            if action == 'describe':
                return await self._handle_describe(input, presets_editor, auto_wire)
            
            return {'ok': False, 'error': 'unknown action'}
        except Exception as e:
            return {'ok': False, 'error': 'internal error'}
    
    async def _handle_list(self) -> dict:
        """List model presets (entries with a valid chat block) as plain-text rows."""
        if not self.presets_path.exists():
            return {'ok': True, 'presets': []}
        
        try:
            import yaml
            presets = yaml.safe_load(self.presets_path.read_text()) or []
            # Only return entries that have a valid chat block (model presets).
            # Plain-text presets (with 'from' but no 'chat') are not returned.
            result = []
            model_names = []
            for p in presets:
                if not isinstance(p, dict):
                    continue
                chat = p.get('chat')
                if not (isinstance(chat, dict)
                        and str(chat.get('provider') or '').strip()
                        and str(chat.get('name') or '').strip()):
                    continue
                name = p.get('name', '')
                result.append({
                    'name': name,
                    'description': p.get('description', ''),
                    'from': p.get('from', '')
                })
                model_names.append(name)
            return {'ok': True, 'presets': result, 'model_presets': model_names}
        except Exception:
            return {'ok': False, 'error': 'failed to read presets'}
    
    async def _handle_save(self, input: dict, presets_editor, auto_wire) -> dict:
        """Save (create or update) a preset with validation.
        Serialized via thread_lock to prevent lost updates under concurrent saves.
        """
        preset_data = input.get('preset')
        if not isinstance(preset_data, dict):
            return {'ok': False, 'error': 'preset data required', 'errors': {'preset': 'invalid data'}}
        
        # Serialize read-modify-write with the framework's thread lock
        with self.thread_lock:
            # Load existing presets
            existing = []
            if self.presets_path.exists():
                try:
                    import yaml
                    existing = yaml.safe_load(self.presets_path.read_text()) or []
                except Exception:
                    existing = []
            
            # Check if updating existing preset
            name = str(preset_data.get('name') or '').strip()
            existing_names = {str(p.get('name') or '').strip() for p in existing if isinstance(p, dict)}
            
            is_update = name in existing_names
            
            # For validation, exclude the current preset's name if updating
            validation_names = existing_names - {name} if is_update else existing_names
            
            # Model preset names: entries in the same file with a real chat block.
            # 'from' must resolve against one of these (plain-text contract).
            model_names = {
                str(p.get('name') or '').strip()
                for p in existing
                if isinstance(p, dict)
                and isinstance(p.get('chat'), dict)
                and str(p.get('chat', {}).get('provider') or '').strip()
                and str(p.get('chat', {}).get('name') or '').strip()
            }
            
            # Validate
            errors = presets_editor.validate_preset(preset_data, validation_names, model_names)
            if errors:
                return {'ok': False, 'error': 'validation failed', 'errors': errors}
            
            # Apply edit or create new
            if is_update:
                # Find and update existing preset
                new_list = []
                for p in existing:
                    if isinstance(p, dict) and str(p.get('name') or '').strip() == name:
                        new_list.append(presets_editor.apply_edit(p, preset_data))
                    else:
                        new_list.append(p)
            else:
                # Create new preset - normalize via serialize_preset
                new_list = existing + [presets_editor.serialize_preset(preset_data)]
            
            # Atomic write with backup and auto-wire sync
            try:
                presets_editor.save_presets(self.presets_path, new_list)
                
                # Trigger auto-wire sync
                try:
                    auto_wire.sync_band_orders(
                        Path('/a0/usr/plugins/jev_router/routing-policy.yaml'),
                        [str(p.get('name') or '').strip() for p in new_list if isinstance(p, dict) and p.get('name')],
                        Path('/a0/usr/plugins/jev_router/wire-state.json')
                    )
                except Exception:
                    pass  # auto-wire is best-effort
                
                return {'ok': True}
            except Exception as e:
                return {'ok': False, 'error': f'write failed: {e}'}
    
    async def _handle_describe(self, input: dict, presets_editor, auto_wire) -> dict:
        """Attach a plain-text definition to an existing model preset.
        Serialized via thread_lock to prevent lost updates under concurrent saves.
        """
        name = str(input.get('name') or '').strip()
        description = input.get('description')
        if not name:
            return {'ok': False, 'error': 'name required', 'errors': {'name': 'Name is required'}}
        if description is None or not str(description).strip():
            return {'ok': False, 'error': 'validation failed', 'errors': {'description': 'Description cannot be empty'}}
        description = str(description)
        if len(description) > 300:
            return {'ok': False, 'error': 'validation failed', 'errors': {'description': 'Description must be <= 300 characters'}}

        # Serialize read-modify-write with the framework's thread lock
        with self.thread_lock:
            existing = []
            if self.presets_path.exists():
                try:
                    import yaml
                    existing = yaml.safe_load(self.presets_path.read_text()) or []
                except Exception:
                    return {'ok': False, 'error': 'failed to read presets'}

            found = False
            updated = []
            for preset in existing:
                if isinstance(preset, dict) and str(preset.get('name') or '').strip() == name:
                    if not isinstance(preset.get('chat'), dict):
                        return {'ok': False, 'error': 'model preset required'}
                    changed = presets_editor._deep_copy(preset)
                    changed['description'] = description
                    updated.append(changed)
                    found = True
                else:
                    updated.append(preset)

            if not found:
                return {'ok': False, 'error': 'preset not found'}

            try:
                presets_editor.save_presets(self.presets_path, updated)
                return {'ok': True, 'name': name, 'description': description}
            except Exception as exc:
                return {'ok': False, 'error': f'write failed: {exc}'}