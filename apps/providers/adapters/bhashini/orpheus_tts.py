"""Bhashini Orpheus NVCF HTTP TTS — local Indic Orpheus shape + NVCF stream_pcm."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import httpx
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from .catalog import (
    DEFAULT_ORPHEUS_STYLE,
    DEFAULT_ORPHEUS_VOICE,
    ORPHEUS_SAMPLE_RATE,
    ORPHEUS_SPEECH_PATH,
    ORPHEUS_STATUS_BASE,
    ORPHEUS_WIRE_MODEL,
    resolve_orpheus_base_url,
)


class BhashiniOrpheusTTSService(TTSService):
    """Stream PCM from NVCF Orpheus ``POST /v1/audio/speech`` (client ``stream_pcm``)."""

    def __init__(
        self,
        *,
        auth_token: str,
        function_id: str,
        voice: str = DEFAULT_ORPHEUS_VOICE,
        style: str | None = DEFAULT_ORPHEUS_STYLE,
        sample_rate: int | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.5,
        **kwargs,
    ):
        rate = sample_rate if sample_rate is not None else ORPHEUS_SAMPLE_RATE
        if rate != ORPHEUS_SAMPLE_RATE:
            logger.warning(
                "Orpheus TTS only supports {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                ORPHEUS_SAMPLE_RATE,
                rate,
            )

        super().__init__(
            sample_rate=rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )

        self._auth_token = auth_token.strip()
        self._function_id = function_id.strip()
        if not self._auth_token:
            raise ValueError("BhashiniOrpheusTTSService requires auth_token")
        if not self._function_id:
            raise ValueError("BhashiniOrpheusTTSService requires function_id")

        self._base_url = resolve_orpheus_base_url(self._function_id)
        self._voice = voice
        self._style = style.strip() if style else None
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "Bhashini Orpheus TTS initialized | base_url={} function_id={} voice={} style={}",
            self._base_url,
            self._function_id,
            self._voice,
            self._style,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame):
        await super().start(frame)
        if self.sample_rate != ORPHEUS_SAMPLE_RATE:
            logger.warning(
                "Orpheus TTS requires {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                ORPHEUS_SAMPLE_RATE,
                self.sample_rate,
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_s))
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth_token}",
            "Content-Type": "application/json",
        }

    def _build_body(self, text: str) -> dict:
        # Same shape as local Indic Orpheus create_params; NVCF uses ``style`` (not instructions).
        body: dict = {
            "input": text,
            "model": ORPHEUS_WIRE_MODEL,
            "voice": self._voice,
            "response_format": "pcm",
        }
        if self._style:
            body["style"] = self._style
        return body

    async def _stream_pcm_frames(
        self, response: httpx.Response, context_id: str
    ) -> AsyncGenerator[Frame, None]:
        async for chunk in response.aiter_bytes(self.chunk_size):
            if len(chunk) > 0:
                await self.stop_ttfb_metrics()
                yield TTSAudioRawFrame(
                    chunk,
                    self.sample_rate,
                    1,
                    context_id=context_id,
                )

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        if not self._voice:
            yield ErrorFrame(error="Orpheus TTS voice must be specified")
            return

        body = self._build_body(text)
        url = self._base_url + ORPHEUS_SPEECH_PATH

        try:
            client = await self._get_client()

            # NVCF client: invoke(..., stream=True) + stream_pcm iter_content.
            req_id: str | None = None
            async with client.stream(
                "POST", url, headers=self._headers(), json=body
            ) as response:
                if response.status_code == 202:
                    req_id = response.headers.get("NVCF-REQID") or response.headers.get(
                        "nvcf-reqid"
                    )
                    if not req_id:
                        yield ErrorFrame(
                            error="HTTP 202 with no NVCF-REQID header to poll with"
                        )
                        return
                elif response.status_code >= 400:
                    error = (await response.aread()).decode("utf-8", errors="replace")
                    logger.error(
                        "{} error getting audio (status: {}, error: {})",
                        self,
                        response.status_code,
                        error,
                    )
                    yield ErrorFrame(
                        error=(
                            f"Error getting audio (status: {response.status_code}, "
                            f"error: {error})"
                        )
                    )
                    return
                else:
                    await self.start_tts_usage_metrics(text)
                    async for frame in self._stream_pcm_frames(response, context_id):
                        yield frame
                    return

            status_url = ORPHEUS_STATUS_BASE + req_id
            deadline = asyncio.get_running_loop().time() + self._timeout_s
            auth_headers = {"Authorization": f"Bearer {self._auth_token}"}
            while True:
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError("timed out waiting for async invocation")
                await asyncio.sleep(self._poll_interval_s)
                async with client.stream(
                    "GET", status_url, headers=auth_headers
                ) as response:
                    if response.status_code == 202:
                        continue
                    if response.status_code >= 400:
                        error = (await response.aread()).decode(
                            "utf-8", errors="replace"
                        )
                        logger.error(
                            "{} error getting audio (status: {}, error: {})",
                            self,
                            response.status_code,
                            error,
                        )
                        yield ErrorFrame(
                            error=(
                                f"Error getting audio (status: {response.status_code}, "
                                f"error: {error})"
                            )
                        )
                        return
                    await self.start_tts_usage_metrics(text)
                    async for frame in self._stream_pcm_frames(response, context_id):
                        yield frame
                    return

        except Exception as exc:
            logger.error(
                "Bhashini Orpheus TTS error | context_id={} error={}",
                context_id,
                exc,
            )
            yield ErrorFrame(error=f"TTS error: {exc}")

    async def cleanup(self):
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        await super().cleanup()
