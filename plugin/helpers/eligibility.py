# jev_router eligibility: deterministic provider filter chain.
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .pool import PoolEntry


@dataclass
class Policy:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class FilterResult:
    kept: list[PoolEntry] = field(default_factory=list)
    removals: list[tuple[PoolEntry, str, str]] = field(default_factory=list)
    fallback_reason: str | None = None


def load_policy(path: Path) -> Policy:
    p = Path(path)
    if not p.exists():
        return Policy()
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        return Policy()
    rules = data.get('provider_rules') or {}
    return Policy(
        include=[str(x) for x in (rules.get('include') or [])],
        exclude=[str(x) for x in (rules.get('exclude') or [])],
    )


def filter_pool(entries: list[PoolEntry], policy: Policy) -> FilterResult:
    res = FilterResult()
    for entry in entries:
        if entry.provider in policy.exclude:
            res.removals.append((entry, 'static_exclude',
                f'provider {entry.provider} excluded by static rule'))
            continue
        if policy.include and entry.provider not in policy.include:
            res.removals.append((entry, 'static_include',
                f'provider {entry.provider} not in include list'))
            continue
        res.kept.append(entry)
    if not res.kept:
        res.fallback_reason = 'fallback:empty_pool'
    return res
