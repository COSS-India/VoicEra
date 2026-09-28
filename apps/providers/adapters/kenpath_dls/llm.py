"""Kenpath DLS LLM Pipecat service (``/api/voice-dls/``)."""

from __future__ import annotations

import codecs
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx
import jwt
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

from apps.providers.adapters.kenpath.call_ending import (
    end_call,
    response_requests_end_call,
    strip_goodbye_for_tts,
)
from apps.providers.adapters.kenpath_dls.catalog import VOICE_DLS_PATH
from apps.providers.adapters.kenpath_dls.language_markers import (
    extract_lang_marker,
    flush_speakable,
    strip_lang_marker_for_tts,
    wire_to_canonical,
)
from apps.runtime.services.language_switch.frames import LanguageSwitchFrame


def extract_last_user_message(context: LLMContext) -> str:
    for message in reversed(context.get_messages()):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


class KenpathDlsLLMService(LLMService):
    """Vistaar DLS voice LLM — single endpoint; language via ``<lang:…>`` markers."""

    def __init__(
        self,
        *,
        private_key: str,
        jwt_sub: str,
        base_url: str,
        model: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not private_key.strip():
            raise ValueError("Kenpath DLS requires private_key")

        self._private_key = private_key
        self._jwt_sub = jwt_sub
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._call_id: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._active_lang: str | None = None
        self._stream_hold = ""

        logger.info(
            "KenpathDlsLLMService initialized | model={} | url={}",
            self._model,
            self._base_url,
        )

    def set_call_id(self, call_id: str | None) -> None:
        self._call_id = (call_id or "").strip() or None
        if self._call_id:
            logger.info("Kenpath DLS session_id set to call_id={}", self._call_id)

    def _session_id(self) -> str:
        return self._call_id or str(uuid.uuid4())

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "sub": self._jwt_sub,
            "iss": "voice-provider",
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    def can_generate_metrics(self) -> bool:
        return True

    async def _emit_language_switch_if_needed(self, raw_text: str) -> None:
        wire = extract_lang_marker(raw_text)
        if not wire:
            return
        canonical = wire_to_canonical(wire)
        if self._active_lang == canonical:
            return
        if wire == "mr":
            logger.info("Kenpath DLS received Marathi language code (<lang:mr>)")
        elif wire in ("bhb", "bh"):
            logger.info(
                "Kenpath DLS received Bhili language code (<lang:{}>)",
                wire,
            )
        self._active_lang = canonical
        frame = LanguageSwitchFrame(language=canonical)
        await self.pipeline_worker.queue_frame(frame, FrameDirection.DOWNSTREAM)
        logger.info("Kenpath DLS queued LanguageSwitchFrame language={}", canonical)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        context = None
        if isinstance(frame, LLMContextFrame):
            context = frame.context
        else:
            await self.push_frame(frame, direction)

        if context:
            spoken_text = ""
            try:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.start_processing_metrics()
                spoken_text = await self._process_context(context)
            except httpx.TimeoutException as exc:
                await self._call_event_handler("on_completion_timeout")
                await self.push_error(
                    error_msg="Kenpath DLS LLM completion timeout",
                    exception=exc,
                )
            except Exception as exc:
                await self.push_error(
                    error_msg=f"Error during Kenpath DLS completion: {exc}",
                    exception=exc,
                )
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())
                if response_requests_end_call(spoken_text):
                    await end_call(self)

    @traced_llm
    async def _process_context(self, context: LLMContext) -> str:
        user_message = extract_last_user_message(context)
        if not user_message:
            logger.warning("Kenpath DLS: no user message found in context")
            return ""

        logger.info("Kenpath DLS processing: '{}...'", user_message[:50])
        await self.start_ttfb_metrics()

        first_chunk = True
        chunk_count = 0
        parts: list[str] = []
        self._stream_hold = ""
        async for chunk in self._stream_voice_dls(user_message):
            if first_chunk:
                first_chunk = False
                await self.stop_ttfb_metrics()
            parts.append(chunk)
            await self._emit_language_switch_if_needed("".join(parts))

            self._stream_hold += chunk
            speakable, self._stream_hold = flush_speakable(self._stream_hold)
            tts_text = strip_goodbye_for_tts(strip_lang_marker_for_tts(speakable))
            if tts_text:
                await self._push_llm_text(tts_text)
            chunk_count += 1

        if self._stream_hold:
            tts_text = strip_goodbye_for_tts(
                strip_lang_marker_for_tts(self._stream_hold)
            )
            self._stream_hold = ""
            if tts_text:
                await self._push_llm_text(tts_text)

        logger.info("Kenpath DLS completed — {} chunks streamed", chunk_count)
        return "".join(parts)

    async def _stream_voice_dls(
        self,
        query: str,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}{VOICE_DLS_PATH}"
        session_id = session_id or self._session_id()
        params = {
            "query": query,
            "session_id": session_id,
        }
        headers = {"Authorization": f"Bearer {self._generate_jwt()}"}

        logger.info(
            "Kenpath DLS API request | session_id={} | query={}...",
            session_id,
            query[:50],
        )

        client = await self._get_client()
        async with client.stream(
            "GET", url, params=params, headers=headers, follow_redirects=True
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                logger.error(
                    "Kenpath DLS API error {}: {}",
                    response.status_code,
                    error_text.decode("utf-8", errors="replace"),
                )
                raise RuntimeError(f"Kenpath DLS API Error {response.status_code}")

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
        async for chunk in self._stream_voice_dls(user_message):
            parts.append(chunk)
        return "".join(parts) if parts else None

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Kenpath DLS httpx client closed")
