# P2 (TDD): chat-mention dials - RED first. helpers/mentions.py missing yet.
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import mentions

PROVIDERS = ['zai_coding', 'a0_venice', 'openrouter', 'lm_studio']


def test_exclude_stop_using():
    m = mentions.parse('stop using zai for this task', PROVIDERS)
    assert m.exclude == ['zai_coding'], m
    assert m.ttl_hours == 0


def test_exclude_do_not_and_alias():
    m = mentions.parse('do not use venice here', PROVIDERS)
    assert m.exclude == ['a0_venice'], m


def test_exclude_no_more_with_today_ttl():
    m = mentions.parse('no more openrouter today', PROVIDERS)
    assert m.exclude == ['openrouter'], m
    assert m.ttl_hours == 12


def test_tonight_ttl():
    m = mentions.parse('stop using zai tonight', PROVIDERS)
    assert m.exclude == ['zai_coding']
    assert m.ttl_hours == 8


def test_explicit_hours_ttl():
    m = mentions.parse('drop zai for 2 hours please', PROVIDERS)
    assert m.exclude == ['zai_coding']
    assert m.ttl_hours == 2


def test_prefer_use():
    m = mentions.parse('use zai for this one', PROVIDERS)
    assert m.prefer == ['zai_coding'], m
    assert m.exclude == []


def test_prefer_switch_to():
    m = mentions.parse('switch to venice for this', PROVIDERS)
    assert m.prefer == ['a0_venice'], m


def test_free_dial():
    m = mentions.parse('use free models for this one', PROVIDERS)
    assert m.free is True
    assert m.exclude == []


def test_no_mentions():
    m = mentions.parse('hello world, how are you?', PROVIDERS)
    assert m.exclude == [] and m.prefer == [] and m.free is False
    assert m.ttl_hours == 0


def test_unknown_provider_ignored():
    m = mentions.parse('stop using nonexistent_provider now', PROVIDERS)
    assert m.exclude == []


def test_session_remember_and_expiry():
    mentions.remember('s1', ['zai_coding'], ttl_hours=1, now=1000.0)
    assert mentions.session_excludes('s1', now=1500.0) == ['zai_coding']
    assert mentions.session_excludes('s1', now=5000.0) == []  # pruned


def test_session_multiple_providers_merged():
    mentions.remember('s2', ['zai_coding'], ttl_hours=1, now=100.0)
    mentions.remember('s2', ['openrouter'], ttl_hours=2, now=150.0)
    assert mentions.session_excludes('s2', now=200.0) == ['openrouter', 'zai_coding']




def test_exclude_with_the_article():
    m = mentions.parse('stop using the zai now', PROVIDERS)
    assert m.exclude == ['zai_coding'], m


def test_prefer_with_the_article():
    m = mentions.parse('use the venice provider here', PROVIDERS)
    assert m.prefer == ['a0_venice'], m


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
