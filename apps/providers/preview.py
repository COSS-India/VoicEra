"""Registry and shared helpers for direct (non-Pipecat) TTS voice preview.

Voice preview never runs through ``apps/runtime`` or Pipecat: it is a short,
one-shot synthesis call made straight from the API so it can never compete
with a live call for the runtime's event loop, CPU or GPU. Each vendor's
``preview.py`` (e.g. ``cloud/sarvam/preview.py``) registers a plain async
function here with :func:`register_preview`. Keep these modules free of
``pipecat`` and ``app`` imports — ``apps/providers`` is shared with
``apps/runtime`` and must not depend on either.
"""

from __future__ import annotations

import wave
from collections.abc import Awaitable, Callable
from io import BytesIO

import httpx
from loguru import logger
from pydantic import BaseModel

PreviewFn = Callable[[BaseModel, str, httpx.AsyncClient], Awaitable[bytes]]

PREVIEW_ADAPTERS: dict[str, PreviewFn] = {}

# Web-call quality (matches apps/runtime.constants.websocket_sample_rate()),
# requested from every adapter whose vendor supports it. OpenAI, indic_orpheus
# and bhashini Parler stay at their native rate instead (no resampling).
# A constant, not an env var: it never varies per deployment, and parsing an
# env var at import time here could crash apps/runtime (which shares this
# package) on a bad value.
PREVIEW_SAMPLE_RATE_HZ = 16000


def resolve_preview_sample_rate(cfg: BaseModel) -> int:
    """Return the sample rate an adapter should request for ``cfg``.

    Verified against every TTS provider's ``service.py``/``catalog.py``:
    ``smallest`` is the only one with a per-config, user-selectable
    ``sample_rate`` field (its live-call service uses ``cfg.sample_rate``
    rather than a fixed constant) — preview must match that choice instead
    of silently overriding it with the shared default. Every other provider
    that accepts a rate in its request (sarvam, elevenlabs, cartesia,
    deepgram, google, azure_speech, rime, inworld, camb, xai) has no such
    field, so this falls back to the shared 16kHz default for all of them.

    Do NOT call this for OpenAI, indic_orpheus or bhashini: none of them take
    a request-time sample-rate parameter to negotiate. indic_orpheus and
    OpenAI are fixed at their catalog-declared native rate (24kHz). Bhashini
    Parler's gRPC response can report its own rate per chunk
    (``response.meta.sample_rate`` — see ``adapters/bhashini/tts.py``) and
    falls back to 44.1kHz only when the response doesn't say; its preview
    adapter must read the response the same way, not assume 44100. Never
    resample in any case — always pass the vendor's own rate to
    :func:`pcm_to_wav`.
    """
    rate = getattr(cfg, "sample_rate", None)
    return rate if rate is not None else PREVIEW_SAMPLE_RATE_HZ


class PreviewProviderError(RuntimeError):
    """Raised by an adapter when the vendor call fails or is misconfigured.

    The message is written to server logs, so it must never contain the
    preview text or credentials: status codes and error classes only.
    """


def register_preview(provider: str) -> Callable[[PreviewFn], PreviewFn]:
    """Register ``fn`` as the preview adapter for ``provider``.

    ``fn(cfg, text, client) -> wav_bytes``, where ``cfg`` is the provider's
    typed config (secrets merged in) and ``client`` is a shared
    ``httpx.AsyncClient`` the caller owns and closes.
    """

    def decorator(fn: PreviewFn) -> PreviewFn:
        PREVIEW_ADAPTERS[provider] = fn
        return fn

    return decorator


def has_preview_adapter(provider: str) -> bool:
    """Return whether ``provider`` has a registered preview adapter."""
    return provider in PREVIEW_ADAPTERS


async def synthesize_preview(
    provider: str,
    cfg: BaseModel,
    text: str,
    client: httpx.AsyncClient,
) -> bytes:
    """Dispatch to the registered adapter for ``provider``.

    Raises :class:`PreviewProviderError` if no adapter is registered; callers
    should check :func:`has_preview_adapter` first to return a clean 422
    instead of relying on this exception for control flow.
    """
    fn = PREVIEW_ADAPTERS.get(provider)
    if fn is None:
        raise PreviewProviderError(f"No preview adapter registered for {provider!r}")
    return await fn(cfg, text, client)


def pcm_to_wav(pcm: bytes, *, sample_rate: int, num_channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM16 bytes in a WAV container using the stdlib ``wave`` module.

    Several vendors (indic_orpheus, bhashini Parler) return headerless PCM;
    everything else already returns a WAV or is asked to via the request
    params. Never transcode — always pass the vendor's own sample rate.

    For a vendor whose response can report its own rate (e.g. bhashini
    Parler's gRPC ``response.meta.sample_rate`` — the live-call service reads
    this per chunk rather than assuming a fixed value, see
    ``adapters/bhashini/tts.py``), the preview adapter must read it from the
    response the same way and pass that value here, not a guessed constant.
    A hardcoded default is only correct when the vendor's response never
    carries its own rate.
    """
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buffer.getvalue()


def import_vendor_previews() -> None:
    """Import every vendor ``preview`` module so ``@register_preview`` runs.

    Mirrors ``registry.load_providers()``'s discovery, but only pulls in
    ``preview`` submodules (never ``service``, which imports pipecat).
    """
    import importlib
    import pkgutil

    package_root = __package__
    for area in ("cloud", "adapters", "local"):
        try:
            area_pkg = importlib.import_module(f"{package_root}.{area}")
        except ModuleNotFoundError:
            continue
        for _finder, vendor_name, is_pkg in pkgutil.iter_modules(area_pkg.__path__):
            if not is_pkg:
                continue
            module_name = f"{package_root}.{area}.{vendor_name}.preview"
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 - never let one broken vendor block the rest
                if isinstance(exc, ModuleNotFoundError) and exc.name == module_name:
                    # This vendor has no preview.py yet — expected until its PR lands.
                    continue
                # The vendor's preview.py exists but failed to import (e.g. a
                # bad import inside it). Log loudly: otherwise the adapter
                # silently never registers and callers just see a generic
                # "not available" 422 with no clue why.
                logger.warning(f"Failed to import preview adapter {module_name}: {exc}")
