"""Bharat Vistaar chat-completions LLM Pipecat service."""

from __future__ import annotations

import json
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

from .call_ending import end_call, response_requests_end_call, strip_goodbye_for_tts
from .catalog import BHARAT_VISTAAR_CHAT_MODEL, BHARAT_VISTAAR_JWT_ISS
from .llm import extract_last_user_message


def build_chat_messages(context: LLMContext) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for message in context.get_messages():
        role = message.get("role")
        content = message.get("content", "")
        if role in ("system", "user", "assistant") and str(content).strip():
            messages.append({"role": str(role), "content": str(content)})
    return messages


def parse_bharat_vistaar_voice_delta(content: str) -> tuple[str, bool]:
    """Extract spoken text from Bharat Vistaar SSE delta.content.

    Production returns JSON objects like
    ``{"audio": "...", "end_interaction": false, "language": "en"}``.
    The API may also send plain text deltas; accept both shapes.
    """
    text = (content or "").strip()
    if not text:
        return "", False
    if not text.startswith("{"):
        return text, False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text, False
    if not isinstance(payload, dict):
        return text, False
    audio = str(payload.get("audio") or "").strip()
    end_interaction = bool(payload.get("end_interaction"))
    return audio, end_interaction


def bharat_vistaar_audio_suffix(audio_text: str, last_audio: str) -> tuple[str, str]:
    """Return only the new spoken suffix from cumulative Bharat Vistaar audio."""
    if not audio_text:
        return "", last_audio
    if not last_audio:
        return audio_text, audio_text
    if audio_text.startswith(last_audio):
        return audio_text[len(last_audio) :], audio_text
    if audio_text == last_audio:
        return "", last_audio
    logger.warning(
        "Bharat Vistaar audio reset mid-stream | previous_len={} new_len={}",
        len(last_audio),
        len(audio_text),
    )
    return audio_text, audio_text


class BharatVistaarLLMService(LLMService):
    """Kenpath Bharat Vistaar — OpenAI-style SSE chat completions."""

    def __init__(
        self,
        *,
        private_key: str,
        base_url: str,
        model: str,
        completions_path: str,
        source_lang: str = "en",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not private_key.strip():
            raise ValueError("Bharat Vistaar requires private_key")
        completions_path = completions_path.strip()
        if not completions_path:
            raise ValueError("Bharat Vistaar requires completions_path from catalog")

        self._private_key = private_key
        self._base_url = base_url.rstrip("/")
        self._completions_path = completions_path
        self._model = model
        self._source_lang = source_lang
        self._call_id: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._stream_end_interaction = False

        logger.info(
            "BharatVistaarLLMService initialized | model={} | url={}{} | lang={}",
            self._model,
            self._base_url,
            self._completions_path,
            self._source_lang,
        )

    def set_call_id(self, call_id: str | None) -> None:
        self._call_id = (call_id or "").strip() or None
        if self._call_id:
            logger.info("Bharat Vistaar session_id set to call_id={}", self._call_id)

    def _session_id(self) -> str:
        return self._call_id or str(uuid.uuid4())

    def _generate_jwt(self) -> str:
        now = int(time.time())
        call_id = self._session_id()
        payload = {
            "user_id": call_id,
            "tenant_id": call_id,
            "iss": BHARAT_VISTAAR_JWT_ISS,
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
            end_interaction = False
            try:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.start_processing_metrics()
                spoken_text, end_interaction = await self._process_context(context)
            except httpx.TimeoutException as exc:
                await self._call_event_handler("on_completion_timeout")
                await self.push_error(
                    error_msg="Bharat Vistaar LLM completion timeout",
                    exception=exc,
                )
            except Exception as exc:
                await self.push_error(
                    error_msg=f"Error during Bharat Vistaar completion: {exc}",
                    exception=exc,
                )
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())
                if end_interaction or response_requests_end_call(spoken_text):
                    await end_call(self)

    @traced_llm
    async def _process_context(self, context: LLMContext) -> tuple[str, bool]:
        messages = build_chat_messages(context)
        user_message = extract_last_user_message(context)
        if not user_message:
            logger.warning("Bharat Vistaar: no user message found in context")
            return "", False

        logger.info("Bharat Vistaar processing: '{}...'", user_message[:50])
        await self.start_ttfb_metrics()

        first_chunk = True
        chunk_count = 0
        parts: list[str] = []
        async for chunk in self._stream_chat(messages):
            if first_chunk:
                first_chunk = False
                await self.stop_ttfb_metrics()
            parts.append(chunk)
            tts_text = strip_goodbye_for_tts(chunk)
            if tts_text:
                await self._push_llm_text(tts_text)
            chunk_count += 1

        end_interaction = self._stream_end_interaction
        logger.info("Bharat Vistaar completed — {} chunks streamed", chunk_count)
        return "".join(parts), end_interaction

    async def _stream_chat(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        call_id = self._session_id()
        url = f"{self._base_url}{self._completions_path}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._generate_jwt()}",
            "X-Tenant-ID": call_id,
            "X-User-ID": call_id,
            "X-Session-ID": call_id,
            "X-Language": self._source_lang,
            "Accept": "text/event-stream",
        }
        body = {
            "model": BHARAT_VISTAAR_CHAT_MODEL,
            "messages": messages,
            "stream": True,
        }

        logger.info(
            "Bharat Vistaar API | call_id={} | X-Language={} | messages={}",
            call_id,
            self._source_lang,
            len(messages),
        )

        self._stream_end_interaction = False
        client = await self._get_client()
        async with client.stream(
            "POST",
            url,
            json=body,
            headers=headers,
            follow_redirects=True,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                logger.error(
                    "Bharat Vistaar API error {}: {}",
                    response.status_code,
                    error_text.decode("utf-8", errors="replace"),
                )
                raise RuntimeError(f"Bharat Vistaar API Error {response.status_code}")

            line_buffer = ""
            buffer = ""
            last_audio = ""
            final_audio = ""

            async for raw in response.aiter_bytes():
                line_buffer += raw.decode("utf-8", errors="replace")
                while "\n" in line_buffer:
                    line, line_buffer = line_buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if buffer.strip():
                            yield buffer.strip()
                        if final_audio:
                            logger.info(
                                "Bharat Vistaar final spoken text: {}",
                                final_audio[:200],
                            )
                        return

                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        logger.debug(
                            "Bharat Vistaar skipped non-JSON SSE line: {}",
                            data[:80],
                        )
                        continue

                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    content = (choices[0].get("delta") or {}).get("content")
                    if not content:
                        continue

                    audio_text, end_interaction = parse_bharat_vistaar_voice_delta(
                        content
                    )
                    if end_interaction:
                        self._stream_end_interaction = True
                        logger.info("Bharat Vistaar end_interaction=true")
                    if not audio_text:
                        continue

                    final_audio = audio_text
                    new_spoken, last_audio = bharat_vistaar_audio_suffix(
                        audio_text, last_audio
                    )
                    if not new_spoken:
                        continue

                    buffer += new_spoken
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
            if final_audio:
                logger.info(
                    "Bharat Vistaar final spoken text: {}",
                    final_audio[:200],
                )

    async def run_inference(
        self,
        context: LLMContext,
        max_tokens: Optional[int] = None,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        del max_tokens, system_instruction
        messages = build_chat_messages(context)
        if not extract_last_user_message(context):
            return None
        parts: list[str] = []
        async for chunk in self._stream_chat(messages):
            parts.append(chunk)
        return "".join(parts) if parts else None

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Bharat Vistaar httpx client closed")
