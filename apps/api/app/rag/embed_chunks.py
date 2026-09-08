"""OpenAI embedding helpers for RAG."""

from __future__ import annotations

import numpy as np
from openai import OpenAI


def embed_openai(
    client: OpenAI,
    chunks: list[str],
    *,
    model: str,
    batch_size: int = 100,
    dimensions: int | None = None,
) -> np.ndarray:
    """Call OpenAI embeddings API in batches; return float32 array [n, dim]."""
    all_rows: list[list[float]] = []

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        kwargs: dict = {
            "model": model,
            "input": batch,
        }
        if dimensions is not None:
            kwargs["dimensions"] = dimensions

        response = client.embeddings.create(**kwargs)
        ordered = sorted(response.data, key=lambda d: d.index)
        for item in ordered:
            all_rows.append(item.embedding)

    return np.asarray(all_rows, dtype=np.float32)
