# jev_router dial: performance-dial band emphasis. Pure code, no LLM.
#
# Maps a coarse user preference (cost saver / balanced / max quality) onto
# stable band-order re-ranking. Manual control wins: pinned bands and any
# failure keep the incoming orders verbatim.

DIALS = ('cost', 'balanced', 'quality')

# Known preset -> tier rank per non-neutral dial. Unknown presets join the
# neutral middle rank, keeping their relative order (stable sort).
_COST_RANK = {'Fast': 0, 'Efficiency': 0, 'Local': 1, 'Default': 1,
              'Unhinged': 2, 'Power': 2}
_QUALITY_RANK = {'Power': 0, 'Unhinged': 1, 'Default': 1,
                 'Efficiency': 2, 'Fast': 2, 'Local': 2}
_RANKS = {'cost': _COST_RANK, 'quality': _QUALITY_RANK}

# Fuzzy tier detection for verbose preset names (e.g. 'Fast and Free',
# 'High Power and Free'): exact-name maps take precedence, otherwise
# weighted keyword hits decide the tier. Quality words weigh double so
# 'High Power and Free' (power+free) resolves as quality; keyword ties
# land in the neutral middle rank.
_QUALITY_WORDS = ('power', 'max', 'expensive', 'unhinged')
_COST_WORDS = ('fast', 'cheap', 'free', 'local', 'efficiency')


def _fuzzy_rank(name, dial: str) -> int:
    """Tier rank for a preset name via weighted keyword hits.

    Consulted only when the exact-name maps have no entry. Cost-tier
    names rank 0 on the cost dial and 2 on the quality dial (mirroring
    the exact maps); quality names rank 0 when they contain 'power'
    (matching exact 'Power': 0) and 1 otherwise on quality, 2 on cost.
    Keyword ties land neutral (1). Pure and total.
    """
    try:
        n = str(name).lower()
        q = sum(2 for w in _QUALITY_WORDS if w in n)
        c = sum(1 for w in _COST_WORDS if w in n)
        if dial == 'cost':
            if c > q:
                return 0
            if q > c:
                return 2
            return 1
        if q > c:
            return 0 if 'power' in n else 1
        if c > q:
            return 2
        return 1
    except Exception:
        return 1


def apply_dial(orders: dict, dial: str, pinned: dict | None = None) -> dict:
    """Re-rank band orders by dial emphasis. Pure and total: never raises.

    balanced (or any unknown dial): orders returned unchanged. Known preset
    names sort by the dial's tier rank (stable); unknown names join the
    neutral middle group in their original relative order. Bands pinned in
    `pinned` ({band: True}) keep their input order verbatim.
    """
    try:
        src = orders if isinstance(orders, dict) else {}
        out = {b: list(v) for b, v in src.items() if isinstance(v, list)}
        if dial not in _RANKS:
            return out
        ranks = _RANKS[dial]
        pins = {str(b) for b, v in (pinned or {}).items() if v}
        for band, names in out.items():
            if band in pins:
                continue
            keyed = [(ranks.get(str(n), _fuzzy_rank(n, dial)), i, str(n))
                     for i, n in enumerate(names)]
            keyed.sort()
            out[band] = [n for _, _, n in keyed]
        return out
    except Exception:
        try:
            return {b: list(v) for b, v in (orders or {}).items()
                    if isinstance(v, list)}
        except Exception:
            return {}
