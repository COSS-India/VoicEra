"""Parse agent knowledge-base config for runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class KnowledgeRuntimeConfig:
    mode: Literal["tool", "context"]
    document_ids: list[str]
    top_k: int


def parse_knowledge_config(agent: dict[str, Any]) -> KnowledgeRuntimeConfig | None:
    """Return KB runtime settings when enabled with valid document IDs."""
    config = agent.get("config") or {}
    kb = config.get("knowledge_base") or {}
    if not kb.get("enabled"):
        return None

    document_ids = [d for d in (kb.get("document_ids") or []) if d]
    if not document_ids:
        return None

    mode = kb.get("mode") or "context"
    if mode not in ("tool", "context"):
        mode = "context"

    top_k = max(1, min(int(kb.get("top_k") or 5), 10))
    return KnowledgeRuntimeConfig(
        mode=mode,
        document_ids=document_ids,
        top_k=top_k,
    )
