"""Settings UI wiring: plugin.yaml sections + config.html bindings."""
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _read(p):
    return Path(p).read_text(encoding='utf-8')


def test_plugin_yaml_declares_settings_section():
    text = _read(PLUGIN_ROOT / 'plugin.yaml')
    assert 'settings_sections' in text
    assert 'external' in text

def test_plugin_yaml_enables_scope_config():
    text = _read(PLUGIN_ROOT / 'plugin.yaml')
    assert 'per_project_config: true' in text
    assert 'per_agent_config: true' in text

def test_config_html_exists():
    assert (PLUGIN_ROOT / 'webui' / 'config.html').exists()

def test_config_html_binds_required_fields():
    html = _read(PLUGIN_ROOT / 'webui' / 'config.html')
    for key in ['jev_api_key', 'jev_model', 'jev_timeout', 'jev_timeout_s',
                'enabled', 'delegation_threshold', 'delegation_mode',
                'chat_preselect', 'breaker_threshold', 'breaker_cooldown_hours',
                'dynamic_switch_enabled', 'dynamic_switch_threshold',
                'dynamic_switch_consecutive', 'dynamic_switch_cooldown_seconds']:
        assert f'config.{key}' in html, key

def test_config_json_has_setting_keys():
    cfg = json.loads(_read(PLUGIN_ROOT / 'config.json'))
    for key in ['jev_api_key', 'jev_model', 'jev_timeout', 'jev_timeout_s',
                'dynamic_switch_enabled', 'dynamic_switch_threshold',
                'dynamic_switch_consecutive', 'dynamic_switch_cooldown_seconds']:
        assert key in cfg, key


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS {t.__name__}')
        except Exception as exc:
            failed += 1
            print(f'FAIL {t.__name__}: {type(exc).__name__}: {exc}')
    print(f'--- {len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)
