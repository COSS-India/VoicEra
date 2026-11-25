"""Kenpath Vistaar LLM Pipecat service (``/api/voice/`` and Voice Bhili)."""

from __future__ import annotations

import codecs
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
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

from apps.providers.call_session import ParticipantPhoneMixin

from .call_ending import KenpathCallEndingMixin, response_requests_end_call, strip_goodbye_for_tts
from .vistaar_jwt import build_vistaar_payload, sign_vistaar_token

ADVISORY_TEXT_PARAM = "advisory_text"


@dataclass
class _AdvisoryTextState:
    enabled: bool
    sent: bool = False


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


def extract_initial_spoken_greeting(context: LLMContext) -> str | None:
    """First assistant message before any user turn (Pipecat ``LLMMessagesAppendFrame`` greeting)."""
    for message in context.get_messages():
        role = message.get("role")
        if role == "user":
            break
        if role == "assistant":
            text = str(message.get("content") or "").strip()
            if text:
                return text
    return None


def extract_last_user_message(context: LLMContext) -> str:
    """Text for Vistaar ``query=``: trailing user turns since last assistant reply."""
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


class KenpathLLMService(ParticipantPhoneMixin, KenpathCallEndingMixin, LLMService):
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
        send_greeting_to_llm: bool = False,
        use_participant_phone: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not private_key.strip():
            raise ValueError("Kenpath requires private_key")

        self._use_participant_phone = use_participant_phone
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
        self._advisory_text = _AdvisoryTextState(enabled=send_greeting_to_llm)
        self._spoken_greeting: str | None = None
        self._kenpath_init_call_ending()

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

    def set_spoken_greeting(self, text: str | None) -> None:
        """Spoken greeting for first Vistaar ``advisory_text`` when enabled in agent config."""
        if not self._advisory_text.enabled:
            return
        self._spoken_greeting = (text or "").strip() or None

    def _session_id(self) -> str:
        return self._call_id or str(uuid.uuid4())

    def _vistaar_jwt_bundle(self) -> tuple[str, dict[str, int | str]]:
        sub = self._participant_phone or self._jwt_sub
        payload = build_vistaar_payload(sub=sub, now=int(time.time()))
        return sign_vistaar_token(payload, self._private_key), payload

    def _generate_jwt(self) -> str:
        token, _ = self._vistaar_jwt_bundle()
        return token

    def _log_kenpath_outbound(
        self,
        *,
        label: str,
        url: str,
        params: dict[str, Any],
        jwt_payload: dict[str, int | str] | None = None,
    ) -> None:
        sub_source = None
        if jwt_payload is not None:
            sub_source = "participant" if self._participant_phone else "jwt_sub"
        logger.info(
            "Kenpath outbound | {} | url={} | params={} | jwt_sub_source={} | jwt_claims={}",
            label,
            url,
            params,
            sub_source,
            jwt_payload,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    def can_generate_metrics(self) -> bool:
        return True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self._kenpath_on_call_ending_frame(frame)

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
                await self._kenpath_finish_turn_if_end(
                    end_requested=response_requests_end_call(spoken_text),
                )

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
        self._kenpath_begin_assistant_turn()
        async for chunk in self._iter_completions(user_message, context=context):
            if first_chunk:
                first_chunk = False
                await self.stop_ttfb_metrics()
            parts.append(chunk)
            tts_text = strip_goodbye_for_tts(chunk)
            if tts_text:
                self._kenpath_had_tts = True
                await self._push_llm_text(tts_text)
            chunk_count += 1

        logger.info("Kenpath completed — {} chunks streamed", chunk_count)
        return "".join(parts)

    async def _iter_completions(
        self,
        query: str,
        *,
        context: LLMContext | None = None,
    ) -> AsyncIterator[str]:
        if self._use_voice_bhili:
            async for chunk in self._iter_voice_bhili_text(query):
                yield chunk
        else:
            async for chunk in self._stream_vistaar_completions(
                query,
                context=context,
            ):
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
        jwt_payload: dict[str, int | str] | None = None
        if self._is_prod:
            token, jwt_payload = self._vistaar_jwt_bundle()
            headers["Authorization"] = f"Bearer {token}"
        self._log_kenpath_outbound(
            label="voice_bhili",
            url=self._voice_bhili_url,
            params=params,
            jwt_payload=jwt_payload,
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
        context: LLMContext | None = None,
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
        state = self._advisory_text
        if state.enabled and not state.sent:
            advisory = self._spoken_greeting
            if not advisory and context is not None:
                advisory = extract_initial_spoken_greeting(context)
            if advisory:
                params[ADVISORY_TEXT_PARAM] = advisory
                state.sent = True
        token, jwt_payload = self._vistaar_jwt_bundle()
        headers = {"Authorization": f"Bearer {token}"}
        self._log_kenpath_outbound(
            label="vistaar",
            url=url,
            params=params,
            jwt_payload=jwt_payload,
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
        async for chunk in self._iter_completions(user_message, context=context):
            parts.append(chunk)
        return "".join(parts) if parts else None

    async def cleanup(self) -> None:
        self._kenpath_cleanup_call_ending()
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Kenpath httpx client closed")
