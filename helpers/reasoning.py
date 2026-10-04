# jev_router reasoning: complexity-band reasoning effort + chat override precedence.
#
# Option B from reasoning-effort design discussion: effort follows the band
# Jev already judged (light->low, medium->medium, heavy->high), and the
# a0_reasoning_effort chat-level override always wins. Never raises; unsupported
# models get no effort param at all (some providers reject unknown params).

BAND_EFFORT = {
    'light': 'low',
    'medium': 'medium',
    'heavy': 'high',
}

# Same context key the a0_reasoning_effort plugin uses; we only *read* it.
_OVERRIDE_CONTEXT_KEY = 'a0_reasoning_effort_override'


def effort_for_band(band) -> str | None:
    """Map a complexity band to a reasoning effort; unknown band -> None."""
    try:
        if not isinstance(band, str):
            return None
        return BAND_EFFORT.get(band.strip().lower())
    except Exception:
        return None


def supports_reasoning(provider, model) -> bool:
    """True when the model exposes reasoning_effort support.

    Reuses the a0_reasoning_effort plugin's cached LiteLLM capability
    discovery when the plugin is installed; absent plugin or any failure
    means 'unsupported' (conservative: never send a param the provider
    may reject). Never raises.
    """
    try:
        p = str(provider or '').strip()
        m = str(model or '').strip()
        if not p or not m:
            return False
        from usr.plugins.a0_reasoning_effort.helpers.reasoning_effort import (
            get_state as _re_state,
        )
        # get_state resolves litellm provider + model capabilities via a
        # cached registry lookup; 'available' is True only when the model
        # advertises reasoning_effort options.
        class _Agent:
            context = None
        # get_state reads config from get_chat_model_config(agent); we pass a
        # stub so it skips the context lookup and reports capabilities only.
        # If the plugin's get_state can't handle a stub, we fall through to
        # the registry probe below.
        st = _re_state(_Agent())
        # The stub reports the *configured* model, not ours; ignore it and
        # probe the registry directly instead.
        import litellm as _litellm
        from .providers import get_provider_config as _gpc
        cfg = _gpc('chat', p) or {}
        litellm_provider = str(cfg.get('litellm_provider') or p).strip().lower()
        if litellm_provider == 'other':
            litellm_provider = 'openai'
        params = _litellm.get_supported_openai_params(
            model=m, custom_llm_provider=litellm_provider)
        info = _litellm.get_model_info(
            model=m, custom_llm_provider=litellm_provider)
        if ('reasoning_effort' not in (params or ())
                or info.get('supports_reasoning') is not True):
            return False
        return True
    except Exception:
        return False


def chat_override(agent, model_key: str) -> str:
    """Read the a0_reasoning_effort chat-level override for this model key.

    model_key is 'provider/model'. Returns '' when absent, mismatched, or
    any failure. Read-only; never writes context. Never raises.
    """
    try:
        context = getattr(agent, 'context', None)
        if context is None or not model_key:
            return ''
        stored = context.get_data(_OVERRIDE_CONTEXT_KEY)
        if not isinstance(stored, dict):
            return ''
        if str(stored.get('model') or '') != str(model_key):
            return ''
        effort = str(stored.get('effort') or '').strip().lower()
        return effort if effort else ''
    except Exception:
        return ''


def resolve_effort(band, supported: bool, chat_override: str = '',
                   enabled: bool = True) -> str | None:
    """Decide the reasoning_effort for one routed call.

    Precedence: chat override > band effort; unsupported or disabled always
    None. Pure and total.
    """
    try:
        if not enabled or not supported:
            return None
        override = str(chat_override or '').strip().lower()
        if override:
            return override
        return effort_for_band(band)
    except Exception:
        return None


# GLM-5.3 effort ladder and providers (parity with a0_reasoning_effort).
_GLM53_EFFORTS = ('low', 'high', 'max')
_GLM53_PROVIDERS = frozenset({'zai', 'zai_coding', 'a0_venice', 'venice'})
_GLM53_MODEL_IDS = frozenset(
    {'glm-5.3', 'z-ai-glm-5-3', 'z-ai-glm-5-3-flash'})


def apply_to_model_kwargs(provider, model, kwargs, effort) -> dict:
    """Write an effective effort into model kwargs; returns a new dict.

    Parity with a0_reasoning_effort: plain models get
    kwargs['reasoning_effort']; GLM-5.3 moves a valid effort into
    extra_body (plus thinking:{type:enabled} for zai providers) because
    that ladder differs. Always returns a dict; never raises.
    """
    try:
        out = dict(kwargs) if isinstance(kwargs, dict) else {}
        eff = str(effort or '').strip().lower()
        if not eff:
            return out
        p = str(provider or '').strip().lower()
        m = str(model or '').strip().lower()
        if p in _GLM53_PROVIDERS and m in _GLM53_MODEL_IDS:
            if eff not in _GLM53_EFFORTS:
                return out  # GLM-5.3 only accepts low/high/max
            extra = dict(out.get('extra_body')
                         if isinstance(out.get('extra_body'), dict)
                         else {})
            extra['reasoning_effort'] = eff
            if p in {'zai', 'zai_coding'}:
                extra['thinking'] = {'type': 'enabled'}
            out['extra_body'] = extra
            return out
        out['reasoning_effort'] = eff
        return out
    except Exception:
        return dict(kwargs) if isinstance(kwargs, dict) else {}


def apply_for_route(agent, result) -> str | None:
    """Apply reasoning effort to a routed model from a RouteResult.

    Precedence: chat override > band effort; unsupported models are
    untouched. Writes into result.model.kwargs in place (the LiteLLM
    wrapper's kwargs are merged at call time). Returns the applied effort,
    or None when nothing was applied. Never raises.
    """
    try:
        entry = getattr(result, 'entry', None)
        model = getattr(result, 'model', None)
        if entry is None or model is None:
            return None
        provider = str(getattr(entry, 'provider', '') or '').strip()
        model_name = str(getattr(entry, 'model', '') or '').strip()
        if not provider or not model_name:
            return None
        model_kwargs = getattr(model, 'kwargs', None)
        if not isinstance(model_kwargs, dict):
            return None
        if not supports_reasoning(provider, model_name):
            return None
        effort = resolve_effort(
            getattr(result, 'band', ''),
            supported=True,
            chat_override=chat_override(
                agent, f'{provider}/{model_name}'))
        if not effort:
            return None
        model.kwargs = apply_to_model_kwargs(
            provider, model_name, model_kwargs, effort)
        return effort
    except Exception:
        return None
