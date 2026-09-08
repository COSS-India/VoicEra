"""Pipecat tool for on-demand knowledge-base retrieval."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.services.llm_service import FunctionCallParams

from apps.runtime.services.backend import backend_client
from apps.runtime.services.knowledge.formatting import format_excerpt_lines


def build_knowledge_tool(
    *,
    org_id: str,
    document_ids: list[str],
    top_k: int,
):
    """Return a Pipecat direct function for KB search."""

    async def search_knowledge_base(params: FunctionCallParams, query: str) -> None:
        """Search attached knowledge-base documents for relevant information.

        Args:
            query: Natural-language search query.
        """
        chunks = await backend_client.retrieve_knowledge_chunks(
            org_id=org_id,
            question=query,
            document_ids=document_ids,
            top_k=top_k,
        )
        excerpts = format_excerpt_lines(chunks)
        logger.debug(
            "KB tool retrieval org_id={} query_len={} excerpts={}",
            org_id,
            len(query or ""),
            len(excerpts),
        )
        await params.result_callback(
            {
                "query": query,
                "excerpts": excerpts,
                "total_results": len(excerpts),
            }
        )

    return search_knowledge_base
