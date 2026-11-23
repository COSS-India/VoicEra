"""Amul voice LLM Pipecat service (GET ``/api/voice/``)."""

from __future__ import annotations

import codecs
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.utils.tracing.service_decorators import traced_llm

from .catalog import VOICE_PATH


def extract_last_user_message(context: LLMContext) -> str:
    """Text for Amul ``query=``: trailing user turns since the last assistant reply."""
    parts: list[str] = []
    for message in reversed(context.get_messages()):
        role = message.get("role")
        if role == "user":
            text = str(message.get("content") or "").strip()
            if text:
                parts.append(text)
        elif role == "assistant":
            break
    parts.reverse()
    return " ".join(parts)


class AmulLLMService(LLMService):
    """Amul farmer voice LLM. ``target_lang`` is always the same as ``source_lang``."""

    def __init__(
        self,
        *,
        bearer_token: str,
        base_url: str,
        model: str,
        source_lang: str = "gu",
        user_id: str = "5550000001",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        token = bearer_token.strip()
        if not token:
            raise ValueError("Amul requires bearer_token")

        self._bearer_token = token
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._source_lang = source_lang
        self._user_id = user_id.strip()
        self._call_id: str | None = None
        self._client: httpx.AsyncClient | None = None
        logger.info(
            "AmulLLMService initialized | model={} | url={} | lang={} | user_id={}",
            self._model,
            self._base_url,
            self._source_lang,
            self._user_id,
        )

    def set_call_id(self, call_id: str | None) -> None:
        self._call_id = (call_id or "").strip() or None
        if self._call_id:
            logger.info("Amul session_id set to call_id={}", self._call_id)

    def _session_id(self) -> str:
        return self._call_id or str(uuid.uuid4())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    def can_generate_metrics(self) -> bool:
        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        context = None
        if isinstance(frame, LLMContextFrame):
            context = frame.context
        else:
            await self.push_frame(frame, direction)

        if context:
            try:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.start_processing_metrics()
                await self._process_context(context)
            except httpx.TimeoutException as exc:
                await self._call_event_handler("on_completion_timeout")
                await self.push_error(
                    error_msg="Amul LLM completion timeout",
                    exception=exc,
                )
            except Exception as exc:
                await self.push_error(
                    error_msg=f"Error during Amul completion: {exc}",
                    exception=exc,
                )
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())

    @traced_llm
    async def _process_context(self, context: LLMContext) -> str:
        user_message = extract_last_user_message(context)
        if not user_message:
            logger.warning("Amul: no user message found in context")
            return ""

        logger.info("Amul processing: '{}...'", user_message[:50])
        await self.start_ttfb_metrics()

        first_chunk = True
        chunk_count = 0
        parts: list[str] = []
        async for chunk in self._stream_voice(user_message):
            if first_chunk:
                first_chunk = False
                await self.stop_ttfb_metrics()
            parts.append(chunk)
            if chunk:
                await self._push_llm_text(chunk)
            chunk_count += 1

        logger.info("Amul completed — {} chunks streamed", chunk_count)
        return "".join(parts)

    async def _stream_voice(
        self,
        query: str,
        *,
        source_lang: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}{VOICE_PATH}"
        session_id = session_id or self._session_id()
        source_lang = source_lang or self._source_lang
        params = {
            "query": query,
            "session_id": session_id,
            "source_lang": source_lang,
            "target_lang": source_lang,
            "user_id": self._user_id,
        }
        headers = {"Authorization": f"Bearer {self._bearer_token}"}

        logger.info(
            "Amul API request | session_id={} | lang={} | user_id={} | query={}...",
            session_id,
            source_lang,
            self._user_id,
            query[:50],
        )

        client = await self._get_client()
        async with client.stream(
            "GET",
            url,
            params=params,
            headers=headers,
            follow_redirects=True,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                logger.error(
                    "Amul API error {}: {}",
                    response.status_code,
                    error_text.decode("utf-8", errors="replace"),
                )
                raise RuntimeError(f"Amul API Error {response.status_code}")

            buffer = ""
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            async for data in response.aiter_bytes():
                buffer += decoder.decode(data, final=False)
                while " " in buffer or "\n" in buffer:
                    space_idx = buffer.find(" ")
                    newline_idx = buffer.find("\n")

                    if space_idx == -1 and newline_idx == -1:
                        break
                    if space_idx == -1:
                        split_idx = newline_idx
                    elif newline_idx == -1:
                        split_idx = space_idx
                    else:
                        split_idx = min(space_idx, newline_idx)

                    word = buffer[:split_idx].strip()
                    buffer = buffer[split_idx + 1 :]
                    if word:
                        yield word + " "

            buffer += decoder.decode(b"", final=True)
            if buffer.strip():
                yield buffer.strip()

    async def run_inference(
        self,
        context: LLMContext,
        max_tokens: Optional[int] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        del max_tokens, system_instruction
        user_message = extract_last_user_message(context)
        if not user_message:
            return None
        parts: list[str] = []
        async for chunk in self._stream_voice(user_message):
            parts.append(chunk)
        return "".join(parts) if parts else None

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Amul httpx client closed")
