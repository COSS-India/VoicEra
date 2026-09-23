"""Raya Bakbak WebSocket STT service (SegmentedSTTService) for Pipecat 1.8.1."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt

from apps.providers.runtime_language import update_stt_settings_with_language

from .catalog import resolve_stt_ws_url

try:
    import websockets
    from websockets.protocol import State
except ModuleNotFoundError as e:
    logger.error("Exception: {}", e)
    logger.error("Install with: pip install websockets")
    raise Exception(f"Missing module: {e}") from e


def _to_language(code: str | None) -> Language | None:
    if not code:
        return None
    try:
        return Language(code)
    except (ValueError, KeyError, TypeError):
        return None


class RayaSTTService(SegmentedSTTService):
    """Utterance STT over ``wss://hub.getraya.app/transcribe``.

    ``SegmentedSTTService`` buffers on VAD and passes WAV bytes to ``run_stt``.
    Each segment is base64-encoded and sent as one JSON message on a persistent
    WebSocket; the API returns a single final transcript (no interim results).
    """

    def __init__(
        self,
        *,
        api_key: str,
        language: str = "hi",
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._api_key = api_key.strip()
        if not self._api_key:
            raise ValueError("RayaSTTService requires api_key")

        self._ws_url = resolve_stt_ws_url()
        self._language = language
        self._websocket: Any = None
        self._send_lock = asyncio.Lock()

        logger.info(
            "Raya STT initialized | ws_url={} language={}",
            self._ws_url,
            self._language,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def _update_settings(self, delta: STTSettings) -> dict[str, Any]:
        return await update_stt_settings_with_language(
            self, delta, super_update=super()._update_settings
        )

    async def set_language(self, language: Language | str):
        code = language.value if isinstance(language, Language) else str(language)
        self._language = code
        logger.info("Raya STT language set to {}", self._language)

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    def _ws_open(self) -> bool:
        ws = self._websocket
        if ws is None:
            return False
        state = getattr(ws, "state", None)
        if state is not None:
            return state is State.OPEN
        return not getattr(ws, "closed", True)

    async def _connect(self):
        if self._ws_open():
            return
        await self._disconnect()
        try:
            self._websocket = await websockets.connect(
                self._ws_url,
                additional_headers={"X-API-Key": self._api_key},
                max_size=16 * 1024 * 1024,
            )
            logger.info("Raya STT WebSocket connected | url={}", self._ws_url)
        except Exception as e:
            self._websocket = None
            logger.error("Raya STT WebSocket connect failed: {}", e)
            raise

    async def _disconnect(self):
        ws = self._websocket
        self._websocket = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass
        logger.info("Raya STT WebSocket disconnected")

    async def _ensure_connected(self):
        if not self._ws_open():
            await self._connect()

    @traced_stt
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: str | None = None
    ):
        await self.stop_processing_metrics()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Transcribe one VAD segment (WAV bytes from SegmentedSTTService)."""
        if not audio:
            yield None
            return

        try:
            await self.start_processing_metrics()
            await self._ensure_connected()

            if self._websocket is None:
                yield ErrorFrame(error="Raya STT WebSocket unavailable")
                return

            payload = {
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "language": self._language,
            }

            async with self._send_lock:
                await self._websocket.send(json.dumps(payload))
                raw = await asyncio.wait_for(self._websocket.recv(), timeout=60.0)

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                yield ErrorFrame(error=f"Raya STT invalid JSON response: {raw[:200]}")
                return

            if "detail" in data and data.get("status") != "success":
                yield ErrorFrame(error=f"Raya STT error: {data.get('detail')}")
                return

            status = data.get("status")
            if status == "error":
                yield ErrorFrame(
                    error=f"Raya STT error: {data.get('detail') or data.get('transcript') or data}"
                )
                return

            text = (data.get("transcript") or "").strip()
            if not text:
                await self.stop_processing_metrics()
                yield None
                return

            await self._handle_transcription(text, True, self._language)
            logger.debug("Raya STT transcription: [{}]", text)
            yield TranscriptionFrame(
                text,
                self._user_id,
                time_now_iso8601(),
                _to_language(self._language),
                result=data,
            )

        except asyncio.TimeoutError:
            logger.error("Raya STT timed out waiting for transcript")
            yield ErrorFrame(error="Raya STT timed out waiting for transcript")
            await self._disconnect()
        except Exception as e:
            logger.error("Raya STT error: {}", e)
            yield ErrorFrame(error=f"Raya STT error: {e}")
            await self._disconnect()
