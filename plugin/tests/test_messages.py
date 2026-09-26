# Task 6b (TDD): extract last human message text - RED first.
# helpers/messages.py does not exist yet; expect ImportError.
# Run: /opt/venv-a0/bin/python tests/test_messages.py
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from helpers import messages


class FakeHuman:
    def __init__(self, content):
        self.content = content
        self.type = 'human'


class FakeAI:
    def __init__(self, content):
        self.content = content
        self.type = 'ai'


def test_plain_string_content():
    msgs = [FakeHuman('hello'), FakeAI('hi'), FakeHuman('do the task')]
    assert messages.last_human_text(msgs) == 'do the task'


def test_multipart_content_extracts_text_parts():
    human = FakeHuman([
        {'type': 'text', 'text': 'look at '},
        {'type': 'image_url', 'image_url': {'url': 'x'}},
        {'type': 'text', 'text': 'this image'},
    ])
    assert messages.last_human_text([human]) == 'look at  this image'


def test_no_human_message_returns_empty():
    assert messages.last_human_text([FakeAI('only ai')]) == ''


def test_empty_list_safe():
    assert messages.last_human_text([]) == ''


def test_none_items_ignored():
    msgs = [FakeHuman('first'), None, 'garbage-string', FakeHuman('second')]
    assert messages.last_human_text(msgs) == 'second'



def test_extract_json_wrapper_with_extras():
    raw = '{"user_message":"hey"}\n[EXTRAS]\n{"agent_info":"padding padding padding"}'
    assert messages.extract_user_text(raw) == 'hey'


def test_extract_plain_passthrough():
    assert messages.extract_user_text('hello world') == 'hello world'


def test_extract_cuts_protocol_marker():
    assert messages.extract_user_text('do the task [PROTOCOL] more stuff') == 'do the task'


def test_extract_voice_prefix():
    assert messages.extract_user_text('(voice) hello there') == 'hello there'


def test_extract_invalid_json_kept():
    assert messages.extract_user_text('{not json') == '{not json'


def test_extract_regex_fallback():
    raw = 'prefix "user_message":"ping tail'
    assert messages.extract_user_text(raw) == 'ping tail'


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
