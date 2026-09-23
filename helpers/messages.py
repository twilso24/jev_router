# jev_router messages: robust last-human-message text extraction.


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                t = part.get('text')
                if isinstance(t, str):
                    parts.append(t)
                # image/file parts intentionally contribute no text;
                # presence is enough for the vision signal.
        return ' '.join(parts)
    if isinstance(content, dict):
        t = content.get('text')
        return t if isinstance(t, str) else ''
    return ''


def last_human_text(messages) -> str:
    """Return text of the last human message; '' when none found."""
    if not messages:
        return ''
    last = ''
    for msg in messages:
        if msg is None:
            continue
        mtype = getattr(msg, 'type', None)
        if mtype != 'human':
            continue
        text = _text_of(getattr(msg, 'content', ''))
        if text:
            last = text
    return last


def has_image_parts(messages) -> bool:
    """True when any human message carries image parts (multipart content)."""
    for msg in messages or []:
        if msg is None:
            continue
        if getattr(msg, 'type', None) != 'human':
            continue
        content = getattr(msg, 'content', '')
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') in (
                        'image_url', 'image', 'media'):
                    return True
    return False


import json as _json
import re as _re


def extract_user_text(raw: str) -> str:
    """Extract the human-authored text from a framework-wrapped message.

    Framework messages may arrive as JSON ({"user_message": ...}) with
    trailing protocol/extras blocks, or plain text. Returns the clean user
    text for triviality checks and digests.
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw if isinstance(raw, str) else ''
    text = raw.strip()
    # strip leading voice marker
    if text.lower().startswith('(voice)'):
        text = text[len('(voice)'):].strip()
    candidate = text.split('[PROTOCOL]', 1)[0].split('[EXTRAS]', 1)[0].strip()
    # try JSON object with user_message
    if candidate.startswith('{'):
        try:
            data = _json.loads(candidate)
            if isinstance(data, dict) and isinstance(data.get('user_message'), str):
                return data['user_message'].strip()
        except Exception:
            pass
    # regex fallback: works for malformed or truncated wrappers too
    m = _re.search(r'"user_message"\s*:\s*"((?:[^"\\]|\\.)*)"', candidate)
    if m is None:
        # truncated value with no closing quote: capture to end of string
        m = _re.search(r'"user_message"\s*:\s*"(.*)\s*$', candidate)
    if m:
        try:
            return _json.loads('"' + m.group(1) + '"')
        except Exception:
            return m.group(1)
    return candidate
