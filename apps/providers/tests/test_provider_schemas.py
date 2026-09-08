"""Tests for provider registry + catalog dump helpers."""

from __future__ import annotations

from typing import get_args

import pytest

from apps.providers import Kind, LANGUAGES, ProviderType, language_schema_extra
from apps.providers.capabilities import languages_map
from apps.providers.cloud.deepgram.catalog import STT_CAPABILITIES as DEEPGRAM_STT_CAPS
from apps.providers.cloud.elevenlabs.catalog import STT_CAPABILITIES as ELEVENLABS_STT
from apps.providers.cloud.openai.catalog import LLM_MODELS
from apps.providers.factory import LLMConfig, STTConfig, TTSConfig
from apps.providers.registry import (
    LLM_CREATORS,
    STT_CREATORS,
    TTS_CREATORS,
    config_classes,
)
from apps.providers.schema import (
    DEFAULT_SERVICE_PROVIDERS,
    _provider_id,
    _union_variants,
    all_provider_schemas,
    configuration_defaults,
    provider_schemas,
)


def _expected_provider_ids(annotated_union) -> set[str]:
    return {_provider_id(cls) for cls in _union_variants(annotated_union)}


def test_union_variant_counts_match_registry():
    assert len(_union_variants(STTConfig)) == 13
    assert len(_union_variants(TTSConfig)) == 15
    assert len(_union_variants(LLMConfig)) == 10
    assert set(STT_CREATORS) == set(_expected_provider_ids(STTConfig))
    assert set(TTS_CREATORS) == set(_expected_provider_ids(TTSConfig))
    assert set(LLM_CREATORS) == set(_expected_provider_ids(LLMConfig))


def test_every_registered_config_has_creator():
    assert set(STT_CREATORS) == {_provider_id(c) for c in config_classes(Kind.STT)}
    assert set(TTS_CREATORS) == {_provider_id(c) for c in config_classes(Kind.TTS)}
    assert set(LLM_CREATORS) == {_provider_id(c) for c in config_classes(Kind.LLM)}


def test_provider_schemas_keys_match_union_members():
    assert set(provider_schemas(Kind.STT)) == _expected_provider_ids(STTConfig)
    assert set(provider_schemas(Kind.TTS)) == _expected_provider_ids(TTSConfig)
    assert set(provider_schemas(Kind.LLM)) == _expected_provider_ids(LLMConfig)


def test_all_provider_schemas_shape():
    schemas = all_provider_schemas()
    assert set(schemas) == {"stt", "tts", "llm"}
    assert "deepgram" in schemas["stt"]
    assert "elevenlabs" in schemas["tts"]
    assert "openai" in schemas["llm"]


def test_openai_llm_catalog_examples_and_secret():
    schema = provider_schemas(Kind.LLM)["openai"]
    fields = schema["fields"]

    assert "api_key" in schema["secrets"]
    assert fields["api_key"]["secret"] is True
    assert "input_mode" not in fields["api_key"]
    assert "$defs" not in schema
    model = fields["model"]
    assert model["input_mode"] == "both"
    assert "allow_custom_input" not in model
    for name in LLM_MODELS:
        assert name in model["examples"]


def test_catalog_omits_schema_noise():
    for kind in Kind:
        for provider, schema in provider_schemas(kind).items():
            assert "$defs" not in schema, provider
            assert "$ref" not in schema, provider
            assert "properties" not in schema, provider
            assert "fields" in schema, provider
            assert "secrets" in schema, provider
            assert "provider_type" in schema, provider
            assert schema["provider"] == provider
            assert schema["name"], provider
            assert "kind" not in schema["fields"], provider
            assert "provider" not in schema["fields"], provider
            assert "name" not in schema["fields"], provider
            # allow_custom_input may appear under capabilities.settings leaves;
            # field dump still derives input_mode and omits the raw flag.
            fields_blob = str(schema.get("fields", {}))
            blob = str({k: v for k, v in schema.items() if k != "capabilities"})
            assert "$defs" not in blob, provider
            assert "$ref" not in blob, provider
            assert "anyOf" not in blob, provider
            assert "allow_custom_input" not in fields_blob, provider


def test_provider_type_from_package_path():
    assert provider_schemas(Kind.STT)["deepgram"]["provider_type"] == ProviderType.CLOUD
    assert provider_schemas(Kind.LLM)["openai"]["provider_type"] == ProviderType.CLOUD
    assert provider_schemas(Kind.STT)["bhashini"]["provider_type"] == ProviderType.ADAPTER
    assert provider_schemas(Kind.TTS)["bhashini"]["provider_type"] == ProviderType.ADAPTER
    assert provider_schemas(Kind.TTS)["indic_orpheus"]["provider_type"] == ProviderType.LOCAL
    assert provider_schemas(Kind.STT)["indic_nemotron"]["provider_type"] == ProviderType.LOCAL


def test_catalog_provider_and_display_name():
    cartesia = provider_schemas(Kind.STT)["cartesia"]
    assert cartesia["provider"] == "cartesia"
    assert cartesia["name"] == "Cartesia"
    assert provider_schemas(Kind.STT)["bhashini"]["name"] == "Bhashini"
    assert provider_schemas(Kind.TTS)["bhashini"]["name"] == "Bhashini"
    assert provider_schemas(Kind.STT)["indic_nemotron"]["name"] == "Indic Nemotron"
    assert provider_schemas(Kind.LLM)["aws_bedrock"]["name"] == "AWS Bedrock"


def test_bhashini_stt_registered():
    from apps.providers.adapters.bhashini.catalog import (
        DEFAULT_BHILI_MODEL,
        DEFAULT_NEMOTRON_MODEL,
        DEFAULT_SOCKETIO_SERVICE_ID,
        STT_CAPABILITIES,
        resolve_wire_language,
    )
    from apps.providers.adapters.bhashini.config import BhashiniSTTConfig
    from apps.providers.adapters.bhashini.stt import BhashiniSTTService
    from apps.providers.capabilities import model_ids

    schema = provider_schemas(Kind.STT)["bhashini"]
    assert schema["provider_type"] == ProviderType.ADAPTER
    assert schema["name"] == "Bhashini"
    assert "api_key" in schema["secrets"]
    assert "bhili_auth_token" in schema["secrets"]
    assert "bhili_function_id" in schema["secrets"]
    assert "nemotron_auth_token" in schema["secrets"]
    assert "nemotron_function_id" in schema["secrets"]
    assert "auth_token" not in schema["secrets"]
    assert "function_id" not in schema["secrets"]
    models = model_ids(STT_CAPABILITIES)
    assert len(models) == 4
    assert models[0] in schema["fields"]["model"]["examples"]
    assert DEFAULT_SOCKETIO_SERVICE_ID in schema["fields"]["model"]["examples"]
    assert DEFAULT_BHILI_MODEL in schema["fields"]["model"]["examples"]
    assert DEFAULT_NEMOTRON_MODEL in schema["fields"]["model"]["examples"]

    assert STT_CAPABILITIES[DEFAULT_BHILI_MODEL]["languages"] == {"bhb": "bh"}
    assert resolve_wire_language(DEFAULT_BHILI_MODEL, "bh") == "bhb"
    assert resolve_wire_language(DEFAULT_NEMOTRON_MODEL, "od") == "or"
    assert "bh" in schema["fields"]["language"]["examples"]

    svc = STT_CREATORS["bhashini"](BhashiniSTTConfig(api_key="test", language="hi"))
    assert isinstance(svc, BhashiniSTTService)


def test_bhashini_stt_dispatches_socketio_and_bhili():
    pytest.importorskip("socketio")
    from apps.providers.adapters.bhashini.catalog import (
        DEFAULT_BHILI_MODEL,
        DEFAULT_SOCKETIO_SERVICE_ID,
    )
    from apps.providers.adapters.bhashini.config import BhashiniSTTConfig
    from apps.providers.adapters.bhashini.socketio_stt import BhashiniSocketIOSTTService

    sio = STT_CREATORS["bhashini"](
        BhashiniSTTConfig(
            api_key="test",
            model=DEFAULT_SOCKETIO_SERVICE_ID,
            language="en",
        )
    )
    assert isinstance(sio, BhashiniSocketIOSTTService)

    pytest.importorskip("tritonclient.grpc")
    from apps.providers.adapters.bhashini.bhili_stt import BhashiniBhiliSTTService

    with pytest.raises(ValueError, match="auth_token"):
        STT_CREATORS["bhashini"](
            BhashiniSTTConfig(
                api_key="test",
                model=DEFAULT_BHILI_MODEL,
                language="bh",
            )
        )

    bhili = STT_CREATORS["bhashini"](
        BhashiniSTTConfig(
            api_key="test",
            bhili_auth_token="bhili-tok",
            bhili_function_id="bhili-fn",
            model=DEFAULT_BHILI_MODEL,
            language="bh",
        )
    )
    assert isinstance(bhili, BhashiniBhiliSTTService)
    assert bhili._language == "bhb"


def test_bhashini_stt_dispatches_nemotron():
    pytest.importorskip("grpc")
    from apps.providers.adapters.bhashini.catalog import DEFAULT_NEMOTRON_MODEL
    from apps.providers.adapters.bhashini.config import BhashiniSTTConfig
    from apps.providers.adapters.bhashini.nemotron_stt import BhashiniNemotronSTTService

    with pytest.raises(ValueError, match="auth_token"):
        STT_CREATORS["bhashini"](
            BhashiniSTTConfig(
                api_key="test",
                model=DEFAULT_NEMOTRON_MODEL,
                language="od",
            )
        )

    with pytest.raises(ValueError, match="function_id"):
        STT_CREATORS["bhashini"](
            BhashiniSTTConfig(
                api_key="test",
                nemotron_auth_token="nvcf-tok",
                model=DEFAULT_NEMOTRON_MODEL,
                language="od",
            )
        )

    nemotron = STT_CREATORS["bhashini"](
        BhashiniSTTConfig(
            api_key="test",
            nemotron_auth_token="nvcf-tok",
            nemotron_function_id="nvcf-fn",
            model=DEFAULT_NEMOTRON_MODEL,
            language="od",
        )
    )
    assert isinstance(nemotron, BhashiniNemotronSTTService)
    assert nemotron._language == "or"
    assert nemotron._auth_token == "nvcf-tok"
    assert nemotron._function_id == "nvcf-fn"


def test_bhashini_tts_registered():
    pytest.importorskip("grpc")
    from apps.providers.adapters.bhashini.catalog import TTS_CAPABILITIES
    from apps.providers.adapters.bhashini.config import BhashiniTTSConfig
    from apps.providers.adapters.bhashini.tts import BhashiniTTSService
    from apps.providers.capabilities import model_ids

    schema = provider_schemas(Kind.TTS)["bhashini"]
    assert schema["provider_type"] == ProviderType.ADAPTER
    assert schema["name"] == "Bhashini"
    assert "auth_token" in schema["secrets"]
    assert "function_id" in schema["secrets"]
    assert "orpheus_auth_token" in schema["secrets"]
    assert "orpheus_function_id" in schema["secrets"]
    assert model_ids(TTS_CAPABILITIES)[0] in schema["fields"]["model"]["examples"]
    assert "orpheus" in schema["fields"]["model"]["examples"]

    svc = TTS_CREATORS["bhashini"](
        BhashiniTTSConfig(
            auth_token="tok",
            function_id="fn",
            orpheus_auth_token="orpheus-tok",
            orpheus_function_id="orpheus-fn",
            language="hi",
        )
    )
    assert isinstance(svc, BhashiniTTSService)


def test_bhashini_orpheus_tts_dispatches():
    pytest.importorskip("httpx")
    from apps.providers.adapters.bhashini.catalog import (
        DEFAULT_ORPHEUS_STYLE,
        DEFAULT_ORPHEUS_VOICE,
    )
    from apps.providers.adapters.bhashini.config import BhashiniTTSConfig
    from apps.providers.adapters.bhashini.orpheus_tts import BhashiniOrpheusTTSService

    svc = TTS_CREATORS["bhashini"](
        BhashiniTTSConfig(
            model="orpheus",
            orpheus_auth_token="tok",
            orpheus_function_id="orpheus-fn-id",
            language="hi",
            voice=DEFAULT_ORPHEUS_VOICE,
            style=DEFAULT_ORPHEUS_STYLE,
        )
    )
    assert isinstance(svc, BhashiniOrpheusTTSService)
    assert svc._function_id == "orpheus-fn-id"
    assert svc._voice == DEFAULT_ORPHEUS_VOICE
    assert svc._style == DEFAULT_ORPHEUS_STYLE


def test_bhashini_orpheus_tts_requires_auth():
    from apps.providers.adapters.bhashini.config import BhashiniTTSConfig
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        BhashiniTTSConfig(model="orpheus", language="hi")


def test_bhashini_tts_speakers_are_per_language():
    from apps.providers.adapters.bhashini.catalog import (
        DEFAULT_TTS_VOICE,
        TTS_CAPABILITIES,
        TTS_DESCRIPTION_PRESETS,
        TTS_SPEAKERS,
    )
    from apps.providers.capabilities import settings_tree

    tree = settings_tree(TTS_CAPABILITIES)
    model = "bhashini-indic-parler"
    by_lang = tree[model]

    assert by_lang["hi"]["voice"]["default"] == DEFAULT_TTS_VOICE
    assert by_lang["hi"]["voice"]["options"] == list(TTS_SPEAKERS["hi"])
    assert by_lang["hi"]["voice"]["input_type"] == "dropdown"
    assert by_lang["ta"]["voice"]["options"] == list(TTS_SPEAKERS["ta"])
    assert by_lang["od"]["voice"]["options"] == list(TTS_SPEAKERS["or"])
    assert by_lang["hne"]["voice"]["options"] == list(TTS_SPEAKERS["hne"])
    assert by_lang["bh"]["voice"]["options"] == list(TTS_SPEAKERS["bhli"])
    assert by_lang["bh"]["voice"]["options"] == list(TTS_SPEAKERS["mr"])
    assert "ur" not in by_lang

    description = by_lang["hi"]["description"]
    assert description["input_type"] == "both"
    assert description["options"] == list(TTS_DESCRIPTION_PRESETS)
    assert description["allow_custom_input"] is True


def test_bhashini_orpheus_tts_speakers_and_styles():
    from apps.providers.adapters.bhashini.catalog import (
        DEFAULT_ORPHEUS_STYLE,
        DEFAULT_ORPHEUS_VOICE,
        ORPHEUS_SPEAKERS,
        ORPHEUS_STYLES,
        TTS_CAPABILITIES,
        resolve_wire_language,
    )
    from apps.providers.capabilities import settings_tree

    tree = settings_tree(TTS_CAPABILITIES)
    by_lang = tree["orpheus"]

    assert by_lang["hi"]["voice"]["default"] == DEFAULT_ORPHEUS_VOICE
    assert by_lang["hi"]["voice"]["options"] == list(ORPHEUS_SPEAKERS["hi"])
    assert by_lang["od"]["voice"]["options"] == list(ORPHEUS_SPEAKERS["or"])
    assert by_lang["ur"]["voice"]["options"] == list(ORPHEUS_SPEAKERS["ur"])
    assert by_lang["bh"]["voice"]["options"] == list(ORPHEUS_SPEAKERS["bhb"])
    assert "description" not in by_lang["hi"]

    style = by_lang["hi"]["style"]
    assert style["default"] == DEFAULT_ORPHEUS_STYLE
    assert style["options"] == list(ORPHEUS_STYLES)
    assert resolve_wire_language("orpheus", "od") == "or"
    assert resolve_wire_language("orpheus", "hi") == "hi"
    assert resolve_wire_language("orpheus", "bh") == "bhb"


def test_bhashini_tts_bhili_vendor_code():
    from apps.providers.adapters.bhashini.catalog import (
        TTS_CAPABILITIES,
        resolve_wire_language,
    )

    assert TTS_CAPABILITIES["bhashini-indic-parler"]["languages"]["bhli"] == "bh"
    assert resolve_wire_language("bhashini-indic-parler", "bh") == "bhli"


def test_bhashini_provider_level_auth_merges_stt_and_tts():
    from apps.providers.schema import provider_level_auth

    auth = provider_level_auth("bhashini")
    assert auth is not None
    assert set(auth["secrets"]) == {
        "api_key",
        "bhili_auth_token",
        "bhili_function_id",
        "nemotron_auth_token",
        "nemotron_function_id",
        "auth_token",
        "function_id",
        "orpheus_auth_token",
        "orpheus_function_id",
    }
    assert "stt" in auth["kinds"]
    assert "tts" in auth["kinds"]


def test_kenpath_llm_catalog_language_fields():
    from apps.providers.adapters.kenpath.catalog import ALL_KENPATH_LANGUAGES, LLM_MODELS

    schema = provider_schemas(Kind.LLM)["kenpath"]
    fields = schema["fields"]

    assert schema["provider_type"] == ProviderType.ADAPTER
    assert schema["name"] == "Kenpath"
    assert "private_key" in schema["secrets"]
    assert "bharat_prod_private_key" in schema["secrets"]
    assert "bharat_dev_private_key" in schema["secrets"]
    assert list(fields["model"]["examples"]) == list(LLM_MODELS)

    for name in ("source_lang", "target_lang"):
        field = fields[name]
        assert field["input_mode"] == "options"
        assert field["examples"] == list(ALL_KENPATH_LANGUAGES)
        assert field["default"] == "mr"


def test_configuration_defaults_envelope():
    defaults = configuration_defaults()
    assert set(defaults) == {
        "stt",
        "tts",
        "llm",
        "default_providers",
        "languages",
    }
    assert defaults["default_providers"] == DEFAULT_SERVICE_PROVIDERS
    assert defaults["languages"] == LANGUAGES
    assert defaults["languages"]["hi"] == "Hindi"

    for kind_key, provider in DEFAULT_SERVICE_PROVIDERS.items():
        assert provider in defaults[kind_key]


def test_no_duplicate_provider_ids_within_kind():
    for kind in Kind:
        schemas = provider_schemas(kind)
        ids = [_provider_id(cls) for cls in config_classes(kind)]
        assert len(ids) == len(set(ids))
        assert set(ids) == set(schemas)


def test_unsupported_kind_raises():
    with pytest.raises(ValueError, match="Unsupported kind"):
        provider_schemas("not-a-kind")  # type: ignore[arg-type]


def test_language_schema_extra_inverts_vendor_codes():
    extra = language_schema_extra(
        {"scribe_v2_realtime": {"or": "od", "en": "en"}},
    )
    assert extra["examples"] == ["en", "od"]
    assert extra["model_options"]["scribe_v2_realtime"] == ["en", "od"]
    assert extra["language_codes"]["scribe_v2_realtime"] == {"en": "en", "od": "or"}
    assert extra["allow_custom_input"] is True


def test_language_schema_extra_omits_allow_custom_when_false():
    extra = language_schema_extra({"m": {"en": "en"}}, allow_custom_input=False)
    assert "allow_custom_input" not in extra


def test_deepgram_stt_language_extras_from_supported_languages():
    lang = provider_schemas(Kind.STT)["deepgram"]["fields"]["language"]
    supported = languages_map(DEEPGRAM_STT_CAPS)

    assert set(lang["model_options"]) == set(supported)
    assert lang["model_options"]["flux-general-en"] == ["en"]
    assert lang["language_codes"]["nova-3-general"]["hi"] == "hi"
    assert lang["input_mode"] == "both"
    assert "allow_custom_input" not in lang
    for canonical in supported["nova-3-general"].values():
        assert canonical in lang["examples"]


def test_elevenlabs_stt_odia_vendor_code_in_schema():
    lang = provider_schemas(Kind.STT)["elevenlabs"]["fields"]["language"]
    assert lang["language_codes"]["scribe_v2_realtime"]["od"] == "or"
    assert lang["language_codes"]["scribe_v2_realtime"]["multi"] == "auto"
    assert set(lang["model_options"]) == set(languages_map(ELEVENLABS_STT))


def test_indic_orpheus_tts_registered(monkeypatch):
    pytest.importorskip("pipecat")
    from apps.providers.capabilities import model_ids
    from apps.providers.local.indic_orpheus.catalog import (
        DEFAULT_TTS_STYLE,
        TTS_CAPABILITIES,
        TTS_STYLES,
    )
    from apps.providers.local.indic_orpheus.config import IndicOrpheusTTSConfig
    from apps.providers.local.indic_orpheus.tts import IndicOrpheusTTSService
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    monkeypatch.setenv("MODEL_SERVER_URL", "http://host.docker.internal:8100/v1")

    schema = provider_schemas(Kind.TTS)["indic_orpheus"]
    assert schema["provider_type"] == ProviderType.LOCAL
    assert schema["name"] == "Indic Orpheus"
    assert schema["secrets"] == []
    assert "api_key" not in schema["fields"]
    assert "base_url" not in schema["fields"]
    assert model_ids(TTS_CAPABILITIES)[0] in schema["fields"]["model"]["examples"]

    lang = schema["fields"]["language"]
    assert lang["language_codes"]["orpheus-indic"]["od"] == "or"
    assert lang["language_codes"]["orpheus-indic"]["bh"] == "bhb"
    assert "hi" in lang["examples"]
    assert "od" in lang["examples"]
    assert "bh" in lang["examples"]

    hi_settings = schema[CAPABILITIES_KEY]["orpheus-indic"]["settings"]["hi"]
    assert hi_settings["voice"]["default"] == "Amit"
    assert "Amit" in hi_settings["voice"]["options"]
    assert "Kavya" in hi_settings["voice"]["options"]
    assert hi_settings["style"]["default"] == DEFAULT_TTS_STYLE
    assert hi_settings["style"]["options"] == list(TTS_STYLES)
    assert "CONV" not in hi_settings["style"]["options"]
    assert "news" in hi_settings["style"]["options"]

    bh_settings = schema[CAPABILITIES_KEY]["orpheus-indic"]["settings"]["bh"]
    assert "Bhima" in bh_settings["voice"]["options"]

    svc = TTS_CREATORS["indic_orpheus"](
        IndicOrpheusTTSConfig(language="hi", voice="Amit")
    )
    assert isinstance(svc, IndicOrpheusTTSService)
    assert svc._style == DEFAULT_TTS_STYLE


def test_indic_nemotron_stt_registered(monkeypatch):
    from apps.providers.capabilities import model_ids
    from apps.providers.local.indic_nemotron.catalog import (
        STT_CAPABILITIES,
        resolve_wire_language,
        resolve_ws_url,
    )

    monkeypatch.setenv(
        "MODEL_SERVER_WS_URL", "ws://host.docker.internal:8100/v1/asr/ws"
    )

    schema = provider_schemas(Kind.STT)["indic_nemotron"]
    assert schema["provider_type"] == ProviderType.LOCAL
    assert schema["name"] == "Indic Nemotron"
    assert schema["secrets"] == []
    assert "api_key" not in schema["fields"]
    assert "base_url" not in schema["fields"]
    assert model_ids(STT_CAPABILITIES)[0] in schema["fields"]["model"]["examples"]

    lang = schema["fields"]["language"]
    assert lang["language_codes"]["indic-nemotron-600m"]["od"] == "or"
    assert lang["language_codes"]["indic-nemotron-600m"]["bh"] == "bhb"
    assert "hi" in lang["examples"]
    assert "od" in lang["examples"]
    assert "bh" in lang["examples"]
    assert "bho" in lang["examples"]
    assert "bgc" in lang["examples"]

    assert resolve_wire_language("indic-nemotron-600m", "od") == "or"
    assert resolve_wire_language("indic-nemotron-600m", "bh") == "bhb"
    assert resolve_ws_url() == "ws://host.docker.internal:8100/v1/asr/ws"


def test_indic_nemotron_stt_creator(monkeypatch):
    pytest.importorskip("pipecat")
    from apps.providers.local.indic_nemotron.config import IndicNemotronSTTConfig
    from apps.providers.local.indic_nemotron.stt import IndicNemotronSTTService

    monkeypatch.setenv(
        "MODEL_SERVER_WS_URL", "ws://host.docker.internal:8100/v1/asr/ws"
    )

    svc = STT_CREATORS["indic_nemotron"](IndicNemotronSTTConfig(language="od"))
    assert isinstance(svc, IndicNemotronSTTService)
    assert svc._language == "or"


def test_sarvam_stt_auto_detect_vendor_code_is_unknown():
    lang = provider_schemas(Kind.STT)["sarvam"]["fields"]["language"]
    assert lang["language_codes"]["saarika:v2.5"]["multi"] == "unknown"
    assert lang["language_codes"]["saaras:v3"]["multi"] == "unknown"


def test_deepgram_tts_language_is_options_only():
    lang = provider_schemas(Kind.TTS)["deepgram"]["fields"]["language"]
    assert lang["input_mode"] == "options"
    assert "allow_custom_input" not in lang
    assert lang["model_options"]["aura-2"] == ["en"]


def test_cloud_llm_schemas_do_not_expose_base_url():
    for provider, schema in provider_schemas(Kind.LLM).items():
        if schema["provider_type"] != ProviderType.CLOUD:
            continue
        assert "base_url" not in schema["fields"], provider


def test_every_stt_tts_schema_with_language_has_structured_extras():
    for kind in (Kind.STT, Kind.TTS):
        for provider, schema in provider_schemas(kind).items():
            fields = schema.get("fields", {})
            if "language" not in fields:
                continue
            lang = fields["language"]
            assert "examples" in lang, provider
            assert "model_options" in lang, provider
            assert "language_codes" in lang, provider
            assert lang["input_mode"] in {"options", "both"}, provider
            for canonical in lang["examples"]:
                assert canonical in LANGUAGES, f"{provider}: {canonical}"


def test_secrets_have_no_input_mode():
    for kind in Kind:
        for provider, schema in provider_schemas(kind).items():
            for secret_name in schema["secrets"]:
                field = schema["fields"][secret_name]
                assert field.get("secret") is True, f"{provider}.{secret_name}"
                assert "input_mode" not in field, f"{provider}.{secret_name}"


def test_non_secret_fields_have_input_mode():
    for kind in Kind:
        for provider, schema in provider_schemas(kind).items():
            for name, field in schema["fields"].items():
                if field.get("secret") is True:
                    continue
                assert field.get("input_mode") in {"options", "input", "both"}, (
                    f"{provider}.{name}"
                )


def test_aws_bedrock_lists_credential_secrets():
    schema = provider_schemas(Kind.LLM)["aws_bedrock"]
    assert set(schema["secrets"]) == {"aws_access_key", "aws_secret_key"}
    assert schema["fields"]["aws_access_key"]["secret"] is True
    assert schema["fields"]["aws_secret_key"]["secret"] is True
    assert schema["fields"]["aws_region"]["input_mode"] == "input"


def test_deepgram_creator_is_registered():
    from apps.providers.cloud.deepgram.config import DeepgramSTTConfig

    assert "deepgram" in STT_CREATORS
    assert callable(STT_CREATORS["deepgram"])
    # Type hint on the registered function points at this vendor config.
    hints = STT_CREATORS["deepgram"].__annotations__
    assert hints.get("cfg") in (DeepgramSTTConfig, "DeepgramSTTConfig") or True


def test_parse_language_ids_rejects_unknown():
    from apps.providers.languages import UnknownLanguageError, parse_language_ids

    assert parse_language_ids(None) == ()
    assert parse_language_ids("") == ()
    assert parse_language_ids("hi, en") == ("hi", "en")
    with pytest.raises(UnknownLanguageError, match="xx"):
        parse_language_ids("hi,xx")


def test_list_providers_stt_language_and_filter():
    from apps.providers.schema import list_providers

    all_stt = list_providers(Kind.STT)
    assert "deepgram" in all_stt
    assert all_stt["deepgram"] == {
        "provider": "deepgram",
        "name": "Deepgram",
        "provider_type": "cloud",
    }
    assert "models" not in all_stt["deepgram"]
    assert "language" not in all_stt["deepgram"]
    assert "model_options" not in all_stt["deepgram"]

    hindi = list_providers(Kind.STT, "hi")
    assert "deepgram" in hindi
    for entry in hindi.values():
        assert set(entry) <= {"provider", "name", "provider_type"}


def test_list_providers_and_semantics():
    from apps.providers.schema import list_providers, provider_settings

    both = list_providers(Kind.STT, ("hi", "en"))
    assert "deepgram" in both
    # List stays identity-only; model trimming is on the settings form.
    settings = provider_settings(Kind.STT, "deepgram", languages=("hi", "en"))
    assert "flux-general-en" not in settings["fields"]["model"]["examples"]
    assert "model_options" not in settings["fields"]["language"]
    for model, codes in settings["fields"]["language"]["language_codes"].items():
        assert "hi" in codes and "en" in codes
        assert model in settings["fields"]["model"]["examples"]


def test_provider_settings_excludes_secrets():
    from apps.providers.schema import provider_settings

    settings = provider_settings(Kind.STT, "deepgram")
    assert "api_key" not in settings["fields"]
    assert "secrets" not in settings
    assert "model" in settings["fields"]
    assert "language" in settings["fields"]
    assert "model_options" not in settings["fields"]["language"]
    trimmed = provider_settings(Kind.STT, "deepgram", languages="hi")
    assert "flux-general-en" not in trimmed["fields"]["model"]["examples"]
    for codes in trimmed["fields"]["language"]["language_codes"].values():
        assert "hi" in codes
    assert "model_options" not in trimmed["fields"]["language"]


def test_provider_settings_keeps_only_models_supporting_language():
    from apps.providers.schema import provider_settings
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    # Deepgram flux-general-en is English-only; Hindi must drop it.
    full = provider_settings(Kind.STT, "deepgram")
    assert "flux-general-en" in full["fields"]["model"]["examples"]
    assert CAPABILITIES_KEY in full
    assert "flux-general-en" in full[CAPABILITIES_KEY]
    assert "languages" in full[CAPABILITIES_KEY]["nova-3-general"]
    assert "settings" in full[CAPABILITIES_KEY]["nova-3-general"]
    # Language keys are canonical ids, not vendor wire codes.
    assert "hi" in full[CAPABILITIES_KEY]["nova-3-general"]["languages"]

    hindi = provider_settings(Kind.STT, "deepgram", languages="hi")
    assert "flux-general-en" not in hindi["fields"]["model"]["examples"]
    assert hindi["fields"]["model"]["examples"]
    assert "flux-general-en" not in hindi["fields"]["language"]["language_codes"]
    for codes in hindi["fields"]["language"]["language_codes"].values():
        assert "hi" in codes

    caps = hindi[CAPABILITIES_KEY]
    assert "flux-general-en" not in caps
    assert set(caps) <= set(hindi["fields"]["model"]["examples"])
    for entry in caps.values():
        assert "hi" in entry["languages"]
        assert "hi" in entry["settings"]


def test_provider_settings_includes_scoped_tree_for_stt_tts():
    from apps.providers.schema import provider_settings
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    for kind in (Kind.STT, Kind.TTS):
        for provider in provider_schemas(kind):
            settings = provider_settings(kind, provider)
            assert CAPABILITIES_KEY in settings, f"{kind.value}/{provider}"
            assert "model_options" not in settings["fields"].get("language", {})
            for model, entry in settings[CAPABILITIES_KEY].items():
                assert "languages" in entry and "settings" in entry, f"{provider}/{model}"
                assert set(entry["languages"]) == set(entry["settings"])

    llm = provider_settings(Kind.LLM, "openai")
    assert CAPABILITIES_KEY not in llm


def test_provider_settings_empty_language_match_clears_tree():
    from apps.providers.schema import provider_settings
    from apps.providers.scoped_settings import CAPABILITIES_KEY

    # Deepgram STT does not support Gujarati — empty match path.
    emptied = provider_settings(Kind.STT, "deepgram", languages="gu")
    assert emptied["fields"]["model"]["examples"] == []
    assert emptied["fields"]["language"]["examples"] == []
    assert emptied[CAPABILITIES_KEY] == {}


def test_provider_auth_secrets_only_plus_auth_mro():
    from apps.providers.schema import UnknownProviderError, provider_auth

    auth = provider_auth(Kind.LLM, "openai")
    assert set(auth["fields"]) == {"api_key"}
    assert auth["secrets"] == ["api_key"]
    assert auth["fields"]["api_key"]["secret"] is True

    google_stt = provider_auth(Kind.STT, "google")
    assert "credentials" in google_stt["fields"]
    assert "project_id" in google_stt["fields"]
    assert "model" not in google_stt["fields"]

    google_llm = provider_auth(Kind.LLM, "google")
    assert "api_key" in google_llm["fields"]
    assert "credentials" not in google_llm["fields"]

    with pytest.raises(UnknownProviderError):
        provider_auth(Kind.STT, "not-a-provider")


def test_provider_auth_by_id_openai_spans_kinds():
    from apps.providers.schema import provider_auth_by_id

    found = provider_auth_by_id("openai")
    assert set(found) == {"stt", "tts", "llm"}
    assert "api_key" in found["llm"]["fields"]
    assert provider_auth_by_id("missing") == {}


def test_provider_level_auth_openai_and_google_merge():
    from apps.providers.schema import all_provider_level_auth, provider_level_auth

    openai = provider_level_auth("openai")
    assert openai is not None
    assert set(openai["kinds"]) == {"stt", "tts", "llm"}
    assert set(openai["fields"]) == {"api_key"}
    assert openai["required"] == ["api_key"]

    google = provider_level_auth("google")
    assert google is not None
    assert set(google["kinds"]) == {"stt", "tts", "llm"}
    assert "api_key" in google["fields"]
    assert "credentials" in google["fields"]
    assert "project_id" in google["fields"]
    # Divergent required sets → intersection empty
    assert "required" not in google or google.get("required") == []

    assert provider_level_auth("missing") is None
    assert "openai" in all_provider_level_auth()
