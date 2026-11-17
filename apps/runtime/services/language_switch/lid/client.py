"""Async HTTP client for Nemotron LID ``POST /identify``."""

from __future__ import annotations

from typing import Protocol

import httpx
from loguru import logger

from apps.runtime.services.language_switch.lid.types import LidResult


class LidClient(Protocol):
    """Identify language from a 16 kHz mono WAV payload."""

    async def identify(self, wav_bytes: bytes) -> LidResult | None: ...

    async def aclose(self) -> None: ...


class NemotronLidClient:
    """Call ``{base_url}/identify`` with multipart audio."""

    def __init__(self, base_url: str, *, timeout_s: float = 2.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_s)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def identify(self, wav_bytes: bytes) -> LidResult | None:
        if not wav_bytes:
            return None
        url = f"{self._base_url}/identify"
        try:
            client = await self._get_client()
            response = await client.post(
                url,
                files={"audio": ("utterance.wav", wav_bytes, "audio/wav")},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Nemotron LID identify failed: {}", exc)
            return None

        code = str(data.get("language_code") or "").strip().lower()
        if not code:
            logger.warning("Nemotron LID identify returned no language_code: {}", data)
            return None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        try:
            duration_sec = float(data.get("duration_sec") or 0.0)
        except (TypeError, ValueError):
            duration_sec = 0.0
        probs = data.get("probabilities")
        return LidResult(
            language_code=code.split("-")[0],
            confidence=confidence,
            duration_sec=duration_sec,
            detected_language=data.get("detected_language"),
            probabilities=probs if isinstance(probs, dict) else None,
        )

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
