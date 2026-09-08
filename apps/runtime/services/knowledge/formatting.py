"""Format retrieved knowledge chunks for LLM prompts."""

from __future__ import annotations

from typing import Any


def format_excerpt_lines(chunks: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        source = (
            chunk.get("source_filename")
            or chunk.get("document_id")
            or "knowledge_base"
        )
        lines.append(f"[Excerpt {idx} | {source}]\n{text}")
    return lines


def augment_user_message(user_text: str, chunks: list[dict[str, Any]]) -> str:
    excerpt_lines = format_excerpt_lines(chunks)
    if not excerpt_lines:
        return user_text
    return (
        f"User question:\n{user_text}\n\n"
        "Knowledge Base excerpts:\n"
        f"{chr(10).join(excerpt_lines)}\n\n"
        "Answer using the excerpts when relevant. If excerpts are insufficient, "
        "answer naturally and be transparent."
    )
