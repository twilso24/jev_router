# jev_router pool loader: parse _model_config presets.yaml into typed entries.
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PoolEntry:
    preset_name: str
    role: str          # chat | utility | embedding | vision
    provider: str
    model: str
    api_base: str = ''
    ctx_length: int | None = None
    vision: bool = False


@dataclass
class Pool:
    entries: list[PoolEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_pool(path: Path) -> Pool:
    pool = Pool()
    data = yaml.safe_load(Path(path).read_text()) or []
    if not isinstance(data, list):
        pool.warnings.append('presets.yaml root is not a list')
        return pool
    for item in data:
        if not isinstance(item, dict):
            pool.warnings.append(f'skipping non-dict preset entry: {item!r}')
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            pool.warnings.append('skipping preset without name')
            continue
        for role in ('chat', 'utility', 'embedding', 'vision'):
            cfg = item.get(role)
            if not isinstance(cfg, dict):
                continue
            provider = str(cfg.get('provider') or '').strip()
            model = str(cfg.get('name') or '').strip()
            if not provider or not model:
                pool.warnings.append(
                    f'skipping {name}/{role}: missing provider or model')
                continue
            pool.entries.append(PoolEntry(
                preset_name=name,
                role=role,
                provider=provider,
                model=model,
                api_base=str(cfg.get('api_base') or ''),
                ctx_length=cfg.get('ctx_length'),
                vision=bool(cfg.get('vision', False)),
            ))
    return pool


def pool_fingerprint(entries: list[PoolEntry]) -> str:
    """Stable digest over pool content; changes whenever presets change."""
    import hashlib
    rows = sorted(
        (e.preset_name, e.role, e.provider, e.model, e.api_base,
         str(e.ctx_length), str(e.vision))
        for e in entries
    )
    blob = chr(10).join('|'.join(r) for r in rows)
    return hashlib.sha256(blob.encode('utf-8', 'replace')).hexdigest()[:16]
