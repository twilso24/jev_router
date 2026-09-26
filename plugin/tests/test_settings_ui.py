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




def test_config_html_fit_settings():
    html = _read(PLUGIN_ROOT / 'webui' / 'config.html')
    assert 'config.fit_enabled' in html, 'fit toggle must be in settings UI'
    assert 'config.fit_min_confidence' in html, 'fit confidence floor must be in settings UI'


def test_config_json_has_fit_defaults():
    data = json.loads(_read(PLUGIN_ROOT / 'config.json'))
    assert isinstance(data.get('fit_enabled'), bool)
    assert 0 < float(data.get('fit_min_confidence')) <= 1

def test_config_json_has_dial_default():
    data = json.loads(_read(PLUGIN_ROOT / 'config.json'))
    assert data.get('performance_dial') == 'balanced'

def test_config_html_binds_dial():
    html = _read(PLUGIN_ROOT / 'webui' / 'config.html')
    assert 'config.performance_dial' in html

def test_config_html_wraps_advanced_knobs():
    html = _read(PLUGIN_ROOT / 'webui' / 'config.html')
    assert 'jev-advanced' in html, 'expert knobs must live in an advanced details block'
    # primary controls stay outside the advanced block
    adv_start = html.index('jev-advanced')
    assert html.index('config.performance_dial') < adv_start
    assert html.index('config.jev_api_key') < adv_start

def test_config_json_has_auto_exec_defaults():
    data = json.loads(_read(PLUGIN_ROOT / 'config.json'))
    assert data.get('delegation_auto_execute') is False
    assert 0 < float(data.get('delegation_auto_execute_floor')) <= 1

def test_config_html_binds_auto_exec():
    html = _read(PLUGIN_ROOT / 'webui' / 'config.html')
    assert 'config.delegation_auto_execute' in html
    assert 'config.delegation_auto_execute_floor' in html
