"""Bhashini NVCF gRPC TTS service for Pipecat."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import grpc
import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

from . import tts_pb2, tts_pb2_grpc


class BhashiniTTSService(TTSService):
    """NVCF gRPC TTS client for Bhashini Indic speech synthesis."""

    def __init__(
        self,
        *,
        auth_token: str,
        function_id: str,
        grpc_url: str = "grpc.nvcf.nvidia.com:443",
        voice: str = "Divya",
        description: str = "A clear, natural voice with good audio quality.",
        language: str = "hi",
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._auth_token = auth_token.strip()
        self._function_id = function_id.strip()
        if not self._auth_token:
            raise ValueError("BhashiniTTSService requires auth_token")
        if not self._function_id:
            raise ValueError("BhashiniTTSService requires function_id")

        self._grpc_url = grpc_url.strip()
        self._voice = voice.strip()
        self._description = description.strip()
        self._language = language

        logger.info(
            "Bhashini TTS initialized | grpc_url={} function_id={} language={} voice={}",
            self._grpc_url,
            self._function_id,
            self._language,
            self._voice,
        )

    def _full_description(self) -> str:
        if self._voice:
            return f"{self._voice} {self._description}"
        return self._description

    def can_generate_metrics(self) -> bool:
        return True

    @staticmethod
    def _to_pcm16_bytes(audio_chunk: np.ndarray) -> bytes:
        if np.issubdtype(audio_chunk.dtype, np.floating):
            return (np.clip(audio_chunk, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        if audio_chunk.dtype == np.int16:
            return audio_chunk.tobytes()
        if np.issubdtype(audio_chunk.dtype, np.integer):
            return (
                np.clip(audio_chunk, np.iinfo(np.int16).min, np.iinfo(np.int16).max)
                .astype(np.int16)
                .tobytes()
            )
        return (
            (np.clip(audio_chunk.astype(np.float32), -1.0, 1.0) * 32767.0)
            .astype(np.int16)
            .tobytes()
        )

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        metadata = [
            ("authorization", f"Bearer {self._auth_token}"),
            ("function-id", self._function_id),
        ]

        first_audio = True
        sample_rate = self.sample_rate or 44100

        logger.info(
            "Bhashini TTS stream | start | context_id={} language={} text='{}'",
            context_id,
            self._language,
            text[:120],
        )

        try:
            credentials = grpc.ssl_channel_credentials()
            async with grpc.aio.secure_channel(self._grpc_url, credentials) as channel:
                stub = tts_pb2_grpc.TTSServiceStub(channel)
                request = tts_pb2.SynthesizeRequest(
                    prompt=text,
                    description=self._full_description(),
                    language=self._language,
                )

                async for response in stub.Synthesize(request, metadata=metadata):
                    which = response.WhichOneof("payload")

                    if which == "meta":
                        sample_rate = response.meta.sample_rate
                        logger.debug(
                            "Bhashini TTS stream | meta | context_id={} sample_rate={}",
                            context_id,
                            sample_rate,
                        )

                    elif which == "audio":
                        if first_audio:
                            first_audio = False
                            await self.stop_ttfb_metrics()
                        arr = np.frombuffer(response.audio.pcm_data, dtype=np.float32)
                        audio_bytes = self._to_pcm16_bytes(arr)
                        logger.info(
                            "Bhashini TTS stream | audio | context_id={} bytes={} sample_rate={}",
                            context_id,
                            len(audio_bytes),
                            sample_rate,
                        )
                        yield TTSAudioRawFrame(
                            audio_bytes,
                            sample_rate,
                            1,
                            context_id=context_id,
                        )

                    elif which == "done":
                        logger.info(
                            "Bhashini TTS stream | done | context_id={}",
                            context_id,
                        )
                        break

        except grpc.aio.AioRpcError as e:
            logger.error(
                "Bhashini TTS gRPC error | context_id={} code={} details={}",
                context_id,
                e.code(),
                e.details(),
            )
            yield ErrorFrame(f"gRPC error [{e.code()}]: {e.details()}")
        except Exception as e:
            logger.error("Bhashini TTS error | context_id={} error={}", context_id, e)
            yield ErrorFrame(f"TTS error: {e}")
