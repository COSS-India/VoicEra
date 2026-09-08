"""Build Pipecat STT and TTS services from Bhashini configs."""

from __future__ import annotations

from ...registry import register_stt, register_tts
from .catalog import (
    resolve_bhili_model,
    resolve_grpc_url,
    resolve_socket_url,
    resolve_socketio_service_id,
    resolve_stt_backend,
    resolve_tts_backend,
    resolve_wire_language,
    resolve_ws_service_id,
    resolve_ws_url,
)
from .config import BhashiniSTTConfig, BhashiniTTSConfig


@register_stt
def create_stt(cfg: BhashiniSTTConfig):
    backend = resolve_stt_backend(cfg.model)
    language = resolve_wire_language(cfg.model, cfg.language)

    if backend == "socketio":
        from .socketio_stt import BhashiniSocketIOSTTService

        return BhashiniSocketIOSTTService(
            api_key=cfg.api_key,
            socket_url=resolve_socket_url(),
            service_id=resolve_socketio_service_id(cfg.model),
            language=language,
            suppress_vad_frames=True,
        )

    if backend == "bhili":
        from .bhili_stt import BhashiniBhiliSTTService

        return BhashiniBhiliSTTService(
            auth_token=cfg.bhili_auth_token,
            function_id=cfg.bhili_function_id,
            grpc_host=resolve_grpc_url(),
            model=resolve_bhili_model(cfg.model),
            language=language,
            suppress_vad_frames=True,
        )

    if backend == "nemotron":
        from .nemotron_stt import BhashiniNemotronSTTService

        return BhashiniNemotronSTTService(
            auth_token=cfg.nemotron_auth_token,
            function_id=cfg.nemotron_function_id,
            grpc_host=resolve_grpc_url(),
            language=language,
        )

    from .stt import BhashiniSTTService

    return BhashiniSTTService(
        api_key=cfg.api_key,
        ws_url=resolve_ws_url(),
        service_id=resolve_ws_service_id(cfg.model),
        language=language,
        suppress_vad_frames=True,
    )


@register_tts
def create_tts(cfg: BhashiniTTSConfig):
    backend = resolve_tts_backend(cfg.model)
    language = resolve_wire_language(cfg.model, cfg.language)

    if backend == "orpheus":
        from .orpheus_tts import BhashiniOrpheusTTSService

        return BhashiniOrpheusTTSService(
            auth_token=cfg.orpheus_auth_token,
            function_id=cfg.orpheus_function_id,
            voice=cfg.voice,
            style=cfg.style,
        )

    from .tts import BhashiniTTSService

    return BhashiniTTSService(
        auth_token=cfg.auth_token,
        function_id=cfg.function_id,
        grpc_url=resolve_grpc_url(),
        voice=cfg.voice,
        description=cfg.description,
        language=language,
    )
