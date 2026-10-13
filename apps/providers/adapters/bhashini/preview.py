"""Direct (non-Pipecat) TTS preview for Bhashini: Indic Parler (gRPC) and Orpheus (NVCF HTTP)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import grpc
import httpx
import numpy as np

from ...preview import PreviewProviderError, pcm_to_wav, register_preview, send_to_vendor
from . import tts_pb2, tts_pb2_grpc
from .catalog import (
    ORPHEUS_SAMPLE_RATE,
    ORPHEUS_SPEECH_PATH,
    ORPHEUS_STATUS_BASE,
    ORPHEUS_WIRE_MODEL,
    resolve_grpc_url,
    resolve_orpheus_base_url,
    resolve_tts_backend,
    resolve_wire_language,
)
from .config import BhashiniTTSConfig

# Used only if the stream sends no meta frame; the live call assumes the same.
_PARLER_DEFAULT_SAMPLE_RATE = 44100
_PCM16_MAX = 32767.0
_FLOAT32_BYTES = 4
# NVCF answers 202 while the function is still running; poll its status URL.
# The service's overall preview timeout bounds the loop.
_NVCF_POLL_INTERVAL_S = 0.5


async def _collect_parler_stream(responses: AsyncIterator) -> tuple[int, bytes]:
    """Read a Parler stream into (sample_rate, float32 PCM), taking the rate from its meta frame."""
    sample_rate, chunks = _PARLER_DEFAULT_SAMPLE_RATE, []
    async for response in responses:
        which = response.WhichOneof("payload")
        if which == "done":
            break
        # proto3 reads a missing rate as 0, which no WAV header can carry: keep the default.
        if which == "meta" and response.meta.sample_rate > 0:
            sample_rate = response.meta.sample_rate
        elif which == "audio":
            chunks.append(response.audio.pcm_data)
    return sample_rate, b"".join(chunks)


async def _synthesize_parler(cfg: BhashiniTTSConfig, text: str) -> bytes:
    """Stream Indic Parler over gRPC and return WAV at the rate the stream reports."""
    request = tts_pb2.SynthesizeRequest(
        prompt=text,
        description=f"{cfg.voice} {cfg.description}".strip(),
        language=resolve_wire_language(cfg.model, cfg.language),
    )
    metadata = (("authorization", f"Bearer {cfg.auth_token.strip()}"), ("function-id", cfg.function_id.strip()))
    try:
        async with grpc.aio.secure_channel(resolve_grpc_url(), grpc.ssl_channel_credentials()) as channel:
            stream = tts_pb2_grpc.TTSServiceStub(channel).Synthesize(request, metadata=metadata)
            sample_rate, float_pcm = await _collect_parler_stream(stream)
    except grpc.aio.AioRpcError as exc:
        raise PreviewProviderError(f"Bhashini Parler preview failed: {exc.code().name}") from exc
    if not float_pcm:
        raise PreviewProviderError("Bhashini Parler preview returned no audio")
    if len(float_pcm) % _FLOAT32_BYTES:
        raise PreviewProviderError("Bhashini Parler preview returned truncated float32 audio")
    samples = np.frombuffer(float_pcm, dtype=np.float32)
    pcm = (np.clip(samples, -1.0, 1.0) * _PCM16_MAX).astype(np.int16).tobytes()
    return pcm_to_wav(pcm, sample_rate=sample_rate)


def _require_function_id(cfg: BhashiniTTSConfig) -> str:
    """Return the Orpheus NVCF function id, refusing anything but a UUID (it becomes the URL host)."""
    try:
        # Canonical form: uuid.UUID also accepts braces and "urn:uuid:", which are not host-safe.
        return str(uuid.UUID(cfg.orpheus_function_id.strip()))
    except ValueError as exc:
        raise PreviewProviderError("Bhashini Orpheus preview: function id must be a UUID") from exc


async def _await_nvcf_result(client: httpx.AsyncClient, response: httpx.Response, headers: dict) -> httpx.Response:
    """Poll NVCF's status URL while the invocation answers 202; return the final response."""
    if response.status_code != 202:
        return response
    # Only the invoke reply must carry the id; status replies may omit it (the live call reads it once too).
    request_id = response.headers.get("NVCF-REQID")
    if not request_id:
        raise PreviewProviderError("Bhashini Orpheus preview: 202 without NVCF-REQID")
    status = client.build_request("GET", ORPHEUS_STATUS_BASE + request_id, headers=headers)
    while response.status_code == 202:
        await asyncio.sleep(_NVCF_POLL_INTERVAL_S)
        response = await send_to_vendor(client, "Bhashini Orpheus", status)
    return response


async def _synthesize_orpheus(cfg: BhashiniTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """POST to the NVCF Orpheus function, waiting out any 202, and wrap the PCM as WAV."""
    url = resolve_orpheus_base_url(_require_function_id(cfg)) + ORPHEUS_SPEECH_PATH
    headers = {"Authorization": f"Bearer {cfg.orpheus_auth_token.strip()}"}
    body = {"input": text, "model": ORPHEUS_WIRE_MODEL, "voice": cfg.voice, "response_format": "pcm"}
    if style := cfg.style.strip():
        body["style"] = style  # NVCF Orpheus takes ``style``, not ``instructions``.
    invoke = client.build_request("POST", url, json=body, headers=headers)
    response = await _await_nvcf_result(client, await send_to_vendor(client, "Bhashini Orpheus", invoke), headers)
    if not response.content:
        raise PreviewProviderError("Bhashini Orpheus preview returned no audio")
    return pcm_to_wav(response.content, sample_rate=ORPHEUS_SAMPLE_RATE)


@register_preview("bhashini")
async def synthesize(cfg: BhashiniTTSConfig, text: str, client: httpx.AsyncClient) -> bytes:
    """Return WAV bytes for ``text`` from the model's backend; raise :class:`PreviewProviderError` on failure."""
    try:
        backend = resolve_tts_backend(cfg.model)
    except ValueError as exc:
        raise PreviewProviderError("Bhashini preview: unknown model") from exc
    if backend == "orpheus":
        return await _synthesize_orpheus(cfg, text, client)
    return await _synthesize_parler(cfg, text)
