"""Inject retrieved KB excerpts into LLM context before inference."""

from __future__ import annotations

from loguru import logger
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.aggregators.llm_context import LLMContext

from apps.runtime.services.backend import backend_client
from apps.runtime.services.knowledge.formatting import augment_user_message


class KnowledgeContextProcessor(FrameProcessor):
    """Augment the latest user turn with KB excerpts on each LLM run."""

    def __init__(
        self,
        *,
        org_id: str,
        document_ids: list[str],
        top_k: int,
        context: LLMContext,
        retrieval_timeout: float = 0.8,
    ) -> None:
        super().__init__()
        self._org_id = org_id
        self._document_ids = document_ids
        self._top_k = top_k
        self._context = context
        self._retrieval_timeout = retrieval_timeout
        self._pending_restore_index: int | None = None
        self._pending_restore_content: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, LLMContextFrame)
        ):
            await self._maybe_augment_context()

        await self.push_frame(frame, direction)

    async def restore_user_message(self) -> None:
        """Restore the original user message after the LLM turn completes."""
        if self._pending_restore_index is None or self._pending_restore_content is None:
            return
        messages = self._context.messages
        if 0 <= self._pending_restore_index < len(messages):
            messages[self._pending_restore_index]["content"] = (
                self._pending_restore_content
            )
        self._pending_restore_index = None
        self._pending_restore_content = None

    async def _maybe_augment_context(self) -> None:
        messages = self._context.messages
        user_index = None
        user_text = ""
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") == "user":
                user_index = i
                user_text = (msg.get("content") or "").strip()
                break

        if user_index is None or not user_text:
            return

        chunks = await backend_client.retrieve_knowledge_chunks(
            org_id=self._org_id,
            question=user_text,
            document_ids=self._document_ids,
            top_k=self._top_k,
            timeout=self._retrieval_timeout,
        )
        if not chunks:
            logger.debug("KB context retrieval returned 0 excerpts; using raw user text")
            return

        augmented = augment_user_message(user_text, chunks)
        self._pending_restore_index = user_index
        self._pending_restore_content = messages[user_index].get("content")
        messages[user_index]["content"] = augmented
        logger.debug("KB context retrieval injected {} excerpts", len(chunks))
