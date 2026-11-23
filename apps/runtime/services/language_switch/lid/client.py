"""Async HTTP client for Nemotron ASR ``POST /transcribe`` (model-server LID slot)."""

from __future__ import annotations

from typing import Protocol

import httpx
from loguru import logger


class NemotronClient(Protocol):
    """Transcribe a 16 kHz mono WAV utterance with Nemotron ASR."""

    async def transcribe(self, wav_bytes: bytes) -> str: ...

    async def aclose(self) -> None: ...


class NemotronLidClient:
    """Call ``{base_url}/transcribe`` with multipart audio."""

    def __init__(self, base_url: str, *, timeout_s: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_s)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def transcribe(self, wav_bytes: bytes) -> str:
        """Return the transcript, or ``""`` on any failure."""
        if not wav_bytes:
            return ""
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self._base_url}/transcribe",
                files={"audio": ("utterance.wav", wav_bytes, "audio/wav")},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Nemotron transcribe failed: {}", exc)
            return ""
        return str(data.get("transcript") or "").strip()

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
