"""Self-contained Jev query helper for jev_router.

Replaces the typesafe_ai dependency. Uses the typesafe_sdk package directly.
"""
import json
import math
import time

from pathlib import Path

DEBUG_LOG = Path('/a0/tmp/jev_router_debug.log')


def _dbg(msg: str) -> None:
    """Best-effort debug-log write; never raises."""
    try:
        from datetime import datetime as _dt
        stamp = _dt.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG, 'a') as f:
            f.write(stamp + ' [jev] ' + msg + chr(10))
    except Exception:
        pass


def validate_request(state, questions):
    """Validate the shape of a Jev system_one request."""
    if not isinstance(state, (str, dict, list)):
        raise ValueError("state must be text, an object, or an array.")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a nonempty object keyed by question ID.")
    json.dumps({"state": state, "questions": questions}, allow_nan=False)
    for name, question in questions.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each question needs a nonempty string ID.")
        if not isinstance(question, dict) or question.get("type") not in {"choice", "noul", "score"}:
            raise ValueError(f"Question {name!r} needs type choice, noul, or score.")
        if set(question) - {"type", "instructions", "criteria"}:
            raise ValueError(f"Question {name!r} accepts only type, instructions, and criteria.")
        instructions = question.get("instructions")
        if not isinstance(instructions, (str, dict, list)) or not instructions:
            raise ValueError(f"Question {name!r} needs instructions as text, an object, or an array.")
        kind, criteria = question["type"], question.get("criteria")
        if kind == "choice" and (not isinstance(criteria, dict) or len(criteria) < 2):
            raise ValueError(f"Choice {name!r} needs at least two named criteria.")
        if kind == "score" and (not isinstance(criteria, list) or len(criteria) < 2):
            raise ValueError(f"Score {name!r} needs at least two ordered criteria.")
        if kind == "noul" and criteria is not None and (
            not isinstance(criteria, dict) or set(criteria) - {"true", "false"}
        ):
            raise ValueError(f"Noul {name!r} criteria may only describe true and false.")
        if isinstance(criteria, dict) and any(not isinstance(k, str) or not k.strip() for k in criteria):
            raise ValueError(f"Question {name!r} has an empty or non-string criterion name.")
        values = criteria.values() if isinstance(criteria, dict) else criteria or []
        if any(not isinstance(v, (str, dict, list)) and not (v is None and kind != "score") for v in values):
            raise ValueError(f"Question {name!r} criteria must be descriptions, not numbers or booleans.")


def resolve_api_key(config, environ=None):
    """Return the TypeSafe API key: config wins, else TYPESAFE_API_KEY env."""
    import os
    env = environ if environ is not None else os.environ
    key = str((config or {}).get('jev_api_key') or '').strip()
    if key:
        return key
    return str(env.get('TYPESAFE_API_KEY') or '').strip()


def validate_config(config):
    """Validate jev_router Jev config; returns (model, timeout)."""
    api_key = config.get("api_key", "")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("TypeSafe API key must be a non-empty string.")
    model = config.get("model", "jev-latest")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Set a nonempty model name in TypeSafe AI settings.")
    timeout = config.get("timeout", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 300:
        raise ValueError("TypeSafe timeout must be between 1 and 300 seconds.")
    return model.strip(), timeout


async def query(client, state, questions, model, timeout_s=2.0, on_error=None):
    """Run one Jev system_one call. Returns result dict or None on any failure.

    Failures are logged with their concrete reason (type + message, no
    secrets). When on_error is provided it receives the same detail string.
    """
    try:
        import msgspec
        validate_request(state, questions)
        start = time.monotonic()
        response = await client.system_one(state=state, questions=questions, model=model)
        result = msgspec.to_builtins(response)
        if set(result["answers"]) != set(questions):
            raise ValueError("TypeSafe returned an incomplete set of answers; do not act on this result.")
        result["elapsed_ms"] = round((time.monotonic() - start) * 1000)
        return result
    except Exception as exc:
        detail = f'{type(exc).__name__}: {exc}'
        _dbg('query failed: ' + detail[:300])
        if on_error is not None:
            try:
                on_error(detail)
            except Exception:
                pass
        return None


def result_cards(result, questions):
    """Format a Jev result into visual card data for the WebUI."""
    cards = []
    for name, answer in result["answers"].items():
        card = {"id": name, "instructions": questions[name]["instructions"], **answer}
        legend = answer.get("legend", {})
        card["distribution"] = [
            {"label": str(label), "probability": probability,
             "description": legend.get(label, legend.get(str(label)))}
            for label, probability in answer.get("probabilities", {}).items()
        ]
        card.pop("probabilities", None)
        card.pop("legend", None)
        cards.append(card)
    return {"model": result["model"], "usage": result["usage"],
            "elapsed_ms": result["elapsed_ms"], "cards": cards}
