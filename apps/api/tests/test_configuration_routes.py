"""HTTP mapping for configuration catalog routes (lists + settings only)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import configuration, languages

app = FastAPI()
app.include_router(languages.router, prefix="/api/v1")
app.include_router(configuration.router, prefix="/api/v1")
app.dependency_overrides[get_current_user] = lambda: {
    "email": "test@example.com",
    "org_id": "org-1",
}

client = TestClient(app)


def test_languages_includes_hindi():
    response = client.get("/api/v1/languages")
    assert response.status_code == 200
    body = response.json()
    assert body["languages"]["hi"] == "Hindi"


def test_stt_unknown_language_is_400():
    response = client.get("/api/v1/configuration/stt", params={"languages": "hi,not-a-lang"})
    assert response.status_code == 400
    assert "not-a-lang" in response.json()["detail"]


def test_stt_unknown_provider_settings_is_404():
    response = client.get("/api/v1/configuration/stt/setting/not-a-provider")
    assert response.status_code == 404


def test_stt_list_and_setting_ok():
    with patch(
        "app.routers.configuration.auth_service.list_configured_providers",
        return_value=["deepgram"],
    ):
        listed = client.get("/api/v1/configuration/stt", params={"languages": "hi"})
        assert listed.status_code == 200
        body = listed.json()
        assert "deepgram" in body
        assert body["deepgram"] == {
            "provider": "deepgram",
            "name": "Deepgram",
            "provider_type": "cloud",
            "authenticated": True,
        }
        assert "models" not in body["deepgram"]
        assert "language" not in body["deepgram"]
        unauth = next(p for p in body if p != "deepgram")
        assert body[unauth]["authenticated"] is False

        settings = client.get(
            "/api/v1/configuration/stt/setting/deepgram",
            params={"languages": "hi"},
        )
        assert settings.status_code == 200
        payload = settings.json()
        assert payload["authenticated"] is True
        fields = payload["fields"]
        assert "api_key" not in fields
        assert "model_options" not in fields["language"]
        assert "flux-general-en" not in fields["model"]["examples"]
        assert "capabilities" in payload
        caps = payload["capabilities"]
        assert "flux-general-en" not in caps
        assert set(caps) <= set(fields["model"]["examples"])
        for entry in caps.values():
            assert "languages" in entry and "settings" in entry
            assert "hi" in entry["languages"]


def test_tts_setting_includes_scoped_tree():
    with patch(
        "app.routers.configuration.auth_service.list_configured_providers",
        return_value=[],
    ):
        response = client.get("/api/v1/configuration/tts/setting/sarvam")
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is False
    assert "capabilities" in payload
    caps = payload["capabilities"]
    assert "bulbul:v2" in caps
    assert "languages" in caps["bulbul:v2"]
    assert "settings" in caps["bulbul:v2"]
    assert "hi" in caps["bulbul:v2"]["languages"]
    assert "hi" in caps["bulbul:v2"]["settings"]
    assert "voice" in caps["bulbul:v2"]["settings"]["hi"]


def test_llm_and_telephony_authenticated_flag():
    with patch(
        "app.routers.configuration.auth_service.list_configured_providers",
        return_value=["openai", "plivo"],
    ):
        llm = client.get("/api/v1/configuration/llm")
        telephony = client.get("/api/v1/configuration/telephony")
        openai_settings = client.get("/api/v1/configuration/llm/setting/openai")
        plivo_settings = client.get("/api/v1/configuration/telephony/setting/plivo")
    assert llm.status_code == 200
    assert llm.json()["openai"]["authenticated"] is True
    assert telephony.json()["plivo"]["authenticated"] is True
    assert openai_settings.json()["authenticated"] is True
    assert plivo_settings.json()["authenticated"] is True


def test_local_authenticated_from_model_server_probe():
    from apps.providers.availability import register_local
    from apps.providers.local.indic_nemotron.catalog import (
        GATEWAY_MODEL_ID as NEMO_ID,
    )
    from apps.providers.local.indic_orpheus.catalog import (
        GATEWAY_MODEL_ID as ORPHEUS_ID,
    )

    register_local("indic_nemotron", NEMO_ID)
    register_local("indic_orpheus", ORPHEUS_ID)
    with (
        patch(
            "app.routers.configuration.auth_service.list_configured_providers",
            return_value=[],
        ),
        patch(
            "apps.providers.availability._deployed_ids",
            return_value=frozenset({NEMO_ID, ORPHEUS_ID}),
        ),
    ):
        stt = client.get("/api/v1/configuration/stt")
        tts = client.get("/api/v1/configuration/tts")
        nemotron = client.get("/api/v1/configuration/stt/setting/indic_nemotron")
        orpheus = client.get("/api/v1/configuration/tts/setting/indic_orpheus")
    assert stt.status_code == 200
    assert stt.json()["indic_nemotron"]["authenticated"] is True
    assert tts.json()["indic_orpheus"]["authenticated"] is True
    assert nemotron.json()["authenticated"] is True
    assert orpheus.json()["authenticated"] is True
    assert stt.json()["deepgram"]["authenticated"] is False


def test_local_authenticated_false_when_model_missing():
    from apps.providers.availability import register_local
    from apps.providers.local.indic_nemotron.catalog import (
        GATEWAY_MODEL_ID as NEMO_ID,
    )
    from apps.providers.local.indic_orpheus.catalog import (
        GATEWAY_MODEL_ID as ORPHEUS_ID,
    )

    register_local("indic_nemotron", NEMO_ID)
    register_local("indic_orpheus", ORPHEUS_ID)
    with (
        patch(
            "app.routers.configuration.auth_service.list_configured_providers",
            return_value=[],
        ),
        patch(
            "apps.providers.availability._deployed_ids",
            return_value=frozenset({"indic-conformer"}),
        ),
    ):
        stt = client.get("/api/v1/configuration/stt")
        tts = client.get("/api/v1/configuration/tts")
    assert stt.json()["indic_nemotron"]["authenticated"] is False
    assert tts.json()["indic_orpheus"]["authenticated"] is False


def test_configuration_auth_routes_removed():
    assert client.get("/api/v1/configuration/auth").status_code == 404
    assert client.get("/api/v1/configuration/stt/auth/deepgram").status_code == 404
