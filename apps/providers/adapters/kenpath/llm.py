"""Kenpath Vistaar LLM Pipecat service (``/api/voice/`` and Voice Bhili)."""

from __future__ import annotations

import codecs
import time
import uuid
from collections.abc import AsyncIterator, Iterator
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

from .call_ending import end_call, response_requests_end_call, strip_goodbye_for_tts


def yield_word_chunks_from_text(text: str) -> Iterator[str]:
    buffer = text
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

    if buffer.strip():
        yield buffer.strip()


def extract_last_user_message(context: LLMContext) -> str:
    for message in reversed(context.get_messages()):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


class KenpathLLMService(LLMService):
    """Kenpath Vistaar LLM — ``/api/voice/`` for Marathi; ``/api/voice-bhili`` for Bhili."""

    def __init__(
        self,
        *,
        private_key: str,
        jwt_sub: str,
        base_url: str,
        model: str,
        source_lang: str = "mr",
        target_lang: str = "mr",
        voice_bhili_url: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not private_key.strip():
            raise ValueError("Kenpath requires private_key")

        self._private_key = private_key
        self._jwt_sub = jwt_sub
        self._base_url = base_url.rstrip("/")
        self._voice_bhili_url = voice_bhili_url.strip()
        self._model = model
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._use_voice_bhili = source_lang == "bhb"
        # Match mono: JWT on Voice Bhili only for Vistaar prod.
        self._is_prod = "vistaar-prod" in model
        self._call_id: str | None = None
        self._client: httpx.AsyncClient | None = None

        if self._use_voice_bhili and not self._voice_bhili_url:
            raise ValueError("Kenpath Voice Bhili requires voice_bhili_url from catalog")

        if self._use_voice_bhili:
            logger.info(
                "KenpathLLMService initialized | model={} | Voice Bhili | url={} | lang={}/{}",
                self._model,
                self._voice_bhili_url,
                self._source_lang,
                self._target_lang,
            )
        else:
            logger.info(
                "KenpathLLMService initialized | model={} | url={} | lang={}/{}",
                self._model,
                self._base_url,
                self._source_lang,
                self._target_lang,
            )

    def set_call_id(self, call_id: str | None) -> None:
        self._call_id = (call_id or "").strip() or None
        if self._call_id:
            logger.info("Kenpath Vistaar session_id set to call_id={}", self._call_id)

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
                    error_msg="Kenpath LLM completion timeout",
                    exception=exc,
                )
            except Exception as exc:
                await self.push_error(
                    error_msg=f"Error during Kenpath completion: {exc}",
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
            logger.warning("Kenpath: no user message found in context")
            return ""

        logger.info("Kenpath processing: '{}...'", user_message[:50])
        await self.start_ttfb_metrics()

        first_chunk = True
        chunk_count = 0
        parts: list[str] = []
        async for chunk in self._iter_completions(user_message):
            if first_chunk:
                first_chunk = False
                await self.stop_ttfb_metrics()
            parts.append(chunk)
            tts_text = strip_goodbye_for_tts(chunk)
            if tts_text:
                await self._push_llm_text(tts_text)
            chunk_count += 1

        logger.info("Kenpath completed — {} chunks streamed", chunk_count)
        return "".join(parts)

    async def _iter_completions(self, query: str) -> AsyncIterator[str]:
        if self._use_voice_bhili:
            async for chunk in self._iter_voice_bhili_text(query):
                yield chunk
        else:
            async for chunk in self._stream_vistaar_completions(query):
                yield chunk

    async def _iter_voice_bhili_text(
        self,
        query: str,
        *,
        source_lang: str | None = None,
        target_lang: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        session_id = session_id or self._session_id()
        source_lang = source_lang or self._source_lang
        target_lang = target_lang or self._target_lang
        params = {
            "query": query,
            "session_id": session_id,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        # Match mono aiohttp behavior: Accept always; JWT only on prod.
        headers = {"Accept": "application/json"}
        if self._is_prod:
            headers["Authorization"] = f"Bearer {self._generate_jwt()}"

        logger.info(
            "Voice Bhili API request | env={} | session_id={} | query={}...",
            "prod" if self._is_prod else "dev",
            session_id,
            query[:50],
        )

        client = await self._get_client()
        # aiohttp follows redirects by default; httpx does not — follow so 307 works.
        response = await client.get(
            self._voice_bhili_url,
            params=params,
            headers=headers,
            follow_redirects=True,
        )
        if response.status_code != 200:
            logger.error(
                "Voice Bhili API error {}: {}",
                response.status_code,
                response.text,
            )
            raise RuntimeError(f"Voice Bhili API Error {response.status_code}")

        data = response.json()
        text = ""
        if isinstance(data, dict):
            text = data.get("response") or ""
        if not str(text).strip():
            logger.warning("Voice Bhili returned empty response")
            return

        for chunk in yield_word_chunks_from_text(str(text)):
            yield chunk

    async def _stream_vistaar_completions(
        self,
        query: str,
        *,
        source_lang: str | None = None,
        target_lang: str | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}/api/voice/"
        session_id = session_id or self._session_id()
        source_lang = source_lang or self._source_lang
        target_lang = target_lang or self._target_lang
        params = {
            "query": query,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "session_id": session_id,
        }
        headers = {"Authorization": f"Bearer {self._generate_jwt()}"}

        logger.info(
            "Vistaar API request | session_id={} | query={}...",
            session_id,
            query[:50],
        )

        client = await self._get_client()
        async with client.stream("GET", url, params=params, headers=headers) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                logger.error(
                    "Vistaar API error {}: {}",
                    response.status_code,
                    error_text.decode("utf-8", errors="replace"),
                )
                raise RuntimeError(f"Vistaar API Error {response.status_code}")

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
        async for chunk in self._iter_completions(user_message):
            parts.append(chunk)
        return "".join(parts) if parts else None

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Kenpath httpx client closed")
