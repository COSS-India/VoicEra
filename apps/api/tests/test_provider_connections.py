"""Provider connection routes, URL guard, and endpoint probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import provider_connections
from app.services import provider_connection_service as svc

app = FastAPI()
app.include_router(provider_connections.router, prefix="/api/v1")

client = TestClient(app)

_ADMIN = {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}
_MEMBER = {"email": "member@example.com", "org_id": "org-1", "role": "member"}


def _as(user: dict) -> None:
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def _default_admin():
    _as(_ADMIN)
    yield
    app.dependency_overrides.clear()


_STORED = {
    "id": "conn-1",
    "org_id": "org-1",
    "kind": "llm",
    "provider": "openai_compatible",
    "name": "Local vLLM",
    "slug": "local-vllm",
    "base_url": "http://vllm.internal:8000/v1",
    "api_key": "****ktop",
    "models": ["Qwen/Qwen3-8B-Instruct"],
    "default_model": "Qwen/Qwen3-8B-Instruct",
    "supports_tools": True,
    "enabled": True,
}


# ---------------------------------------------------------------------------
# URL guard
# ---------------------------------------------------------------------------


def test_base_url_requires_scheme_and_is_trimmed():
    assert (
        svc.normalise_base_url("  http://vllm.internal:8000/v1/  ")
        == "http://vllm.internal:8000/v1"
    )
    with pytest.raises(svc.ProviderConnectionError):
        svc.normalise_base_url("vllm.internal:8000/v1")
    with pytest.raises(svc.ProviderConnectionError):
        svc.normalise_base_url("")


def test_cloud_metadata_address_is_refused():
    """The API fetches this URL server-side, so the metadata IP stays blocked."""
    with pytest.raises(svc.ProviderConnectionError) as exc:
        svc.normalise_base_url("http://169.254.169.254/latest/meta-data")
    assert "blocked address" in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:169.254.169.254]/v1",  # IPv4-mapped form of the same host
        "http://169.254.169.253/v1",  # anything else link-local
        "http://[fd00:ec2::254]/v1",  # AWS IPv6 metadata, not link-local
    ],
)
def test_metadata_address_cannot_be_spelled_around(url):
    """Blocking one literal is not enough — the address is matched, not its text."""
    with pytest.raises(svc.ProviderConnectionError) as exc:
        svc.normalise_base_url(url)
    assert "blocked address" in str(exc.value)


def test_private_lan_host_is_allowed():
    """Self-hosted models on the LAN are the point — do not block RFC1918."""
    assert svc.normalise_base_url("http://192.168.1.50:8000/v1").endswith(":8000/v1")


def test_allowlist_narrows_hosts_when_configured():
    with patch.object(
        svc.settings, "PROVIDER_CONNECTION_ALLOWED_HOSTS", "vllm.internal"
    ):
        assert svc.normalise_base_url("http://vllm.internal:8000/v1")
        with pytest.raises(svc.ProviderConnectionError):
            svc.normalise_base_url("http://elsewhere.example.com/v1")


def test_only_connection_based_providers_are_accepted():
    assert svc.validate_provider("openai_compatible") == "openai_compatible"
    with pytest.raises(svc.ProviderConnectionError) as exc:
        svc.validate_provider("openai")
    assert "POST /auth" in str(exc.value)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_list_returns_masked_keys():
    with patch.object(svc, "list_connections", return_value=[_STORED]) as mocked:
        response = client.get("/api/v1/provider-connections")
    assert response.status_code == 200
    assert response.json()[0]["api_key"] == "****ktop"
    mocked.assert_called_once()


def test_create_requires_admin():
    _as(_MEMBER)
    response = client.post(
        "/api/v1/provider-connections",
        json={
            "name": "Local vLLM",
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
        },
    )
    assert response.status_code == 403


def test_create_passes_payload_through():
    with patch.object(svc, "create_connection", return_value=_STORED) as mocked:
        response = client.post(
            "/api/v1/provider-connections",
            json={
                "name": "Local vLLM",
                "base_url": "http://vllm.internal:8000/v1",
                "api_key": "sk-local",
                "models": ["Qwen/Qwen3-8B-Instruct"],
                "supports_tools": True,
            },
        )
    assert response.status_code == 201
    payload = mocked.call_args.args[1]
    assert payload["provider"] == "openai_compatible"
    assert payload["api_key"] == "sk-local"


def test_create_rejects_vendor_provider():
    with patch.object(
        svc,
        "create_connection",
        side_effect=svc.ProviderConnectionError("nope, use POST /auth"),
    ):
        response = client.post(
            "/api/v1/provider-connections",
            json={
                "provider": "openai",
                "name": "x",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-x",
            },
        )
    assert response.status_code == 422


def test_duplicate_name_is_409():
    with patch.object(
        svc,
        "create_connection",
        side_effect=svc.ProviderConnectionConflictError("Local vLLM"),
    ):
        response = client.post(
            "/api/v1/provider-connections",
            json={
                "name": "Local vLLM",
                "base_url": "http://vllm.internal:8000/v1",
                "api_key": "sk-local",
            },
        )
    assert response.status_code == 409


def test_missing_connection_is_404():
    with patch.object(
        svc, "get_connection", side_effect=svc.ProviderConnectionNotFoundError("nope")
    ):
        response = client.get("/api/v1/provider-connections/nope")
    assert response.status_code == 404


def test_delete_blocked_while_an_agent_uses_it():
    with patch.object(
        svc,
        "delete_connection",
        side_effect=svc.ProviderConnectionInUseError("conn-1", ["Support bot"]),
    ):
        response = client.delete("/api/v1/provider-connections/conn-1")
    assert response.status_code == 409
    assert "Support bot" in response.json()["detail"]


def test_patch_sends_only_supplied_fields():
    with patch.object(svc, "update_connection", return_value=_STORED) as mocked:
        response = client.patch(
            "/api/v1/provider-connections/conn-1", json={"enabled": False}
        )
    assert response.status_code == 200
    assert mocked.call_args.args[2] == {"enabled": False}


def test_patch_disable_blocked_while_an_agent_uses_it():
    with patch.object(
        svc,
        "update_connection",
        side_effect=svc.ProviderConnectionInUseError("conn-1", ["Support bot"]),
    ):
        response = client.patch(
            "/api/v1/provider-connections/conn-1", json={"enabled": False}
        )
    assert response.status_code == 409
    assert "Support bot" in response.json()["detail"]


def _mongo_returning(doc: dict) -> tuple[MagicMock, MagicMock]:
    collection = MagicMock()
    collection.find_one.return_value = doc
    database = MagicMock()
    database.__getitem__.return_value = collection
    return database, collection


def test_disabling_an_endpoint_an_agent_uses_is_refused():
    # An agent keeps its connection_id when the endpoint is disabled, so the
    # break would only show up as a failed call setup.
    database, collection = _mongo_returning({**_STORED, "enabled": True})
    with (
        patch.object(svc, "get_database", return_value=database),
        patch.object(svc, "agents_using", return_value=["Support bot"]),
        pytest.raises(svc.ProviderConnectionInUseError),
    ):
        svc.update_connection("org-1", "conn-1", {"enabled": False})
    collection.update_one.assert_not_called()


def test_disabling_an_unused_endpoint_is_written():
    database, collection = _mongo_returning({**_STORED, "enabled": True})
    with (
        patch.object(svc, "get_database", return_value=database),
        patch.object(svc, "agents_using", return_value=[]),
    ):
        svc.update_connection("org-1", "conn-1", {"enabled": False})
    assert collection.update_one.call_args.args[1]["$set"]["enabled"] is False


def test_other_fields_still_patch_on_a_connection_in_use():
    # Only the disable transition is guarded; renaming stays allowed.
    database, collection = _mongo_returning({**_STORED, "enabled": True})
    with (
        patch.object(svc, "get_database", return_value=database),
        patch.object(svc, "agents_using", return_value=["Support bot"]) as agents,
    ):
        svc.update_connection("org-1", "conn-1", {"name": "Renamed"})
    agents.assert_not_called()
    assert collection.update_one.call_args.args[1]["$set"]["name"] == "Renamed"


def test_system_prompt_mode_defaults_to_send_and_rejects_anything_else():
    with patch.object(svc, "create_connection", return_value=_STORED) as mocked:
        response = client.post(
            "/api/v1/provider-connections",
            json={
                "name": "Local vLLM",
                "base_url": "http://vllm.internal:8000/v1",
                "api_key": "sk-local",
            },
        )
    assert response.status_code == 201
    assert mocked.call_args.args[1]["system_prompt_mode"] == "send"

    response = client.post(
        "/api/v1/provider-connections",
        json={
            "name": "Local vLLM",
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
            "system_prompt_mode": "strip",
        },
    )
    assert response.status_code == 422


def test_system_prompt_mode_patches_like_any_other_field():
    database, collection = _mongo_returning({**_STORED, "enabled": True})
    with (
        patch.object(svc, "get_database", return_value=database),
        patch.object(svc, "agents_using", return_value=[]),
    ):
        svc.update_connection("org-1", "conn-1", {"system_prompt_mode": "omit"})
    assert collection.update_one.call_args.args[1]["$set"]["system_prompt_mode"] == "omit"


def test_history_mode_defaults_to_full_and_rejects_anything_else():
    with patch.object(svc, "create_connection", return_value=_STORED) as mocked:
        response = client.post(
            "/api/v1/provider-connections",
            json={
                "name": "Local vLLM",
                "base_url": "http://vllm.internal:8000/v1",
                "api_key": "sk-local",
            },
        )
    assert response.status_code == 201
    assert mocked.call_args.args[1]["history_mode"] == "full"

    response = client.post(
        "/api/v1/provider-connections",
        json={
            "name": "Local vLLM",
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
            "history_mode": "one_message",
        },
    )
    assert response.status_code == 422


def test_history_mode_patches_like_any_other_field():
    database, collection = _mongo_returning({**_STORED, "enabled": True})
    with (
        patch.object(svc, "get_database", return_value=database),
        patch.object(svc, "agents_using", return_value=[]),
    ):
        svc.update_connection("org-1", "conn-1", {"history_mode": "current_turn"})
    assert collection.update_one.call_args.args[1]["$set"]["history_mode"] == "current_turn"


def test_resolved_is_admin_only():
    _as(_MEMBER)
    response = client.get("/api/v1/provider-connections/conn-1/resolved")
    assert response.status_code == 403


def test_resolved_returns_endpoint_and_key_for_the_runtime():
    resolved = {
        "base_url": "http://vllm.internal:8000/v1",
        "api_key": "sk-local",
        "endpoint_history_mode": "full",
        "endpoint_system_prompt_mode": "send",
    }
    with patch.object(svc, "resolve_auth", return_value=resolved):
        response = client.get("/api/v1/provider-connections/conn-1/resolved")
    assert response.status_code == 200
    assert response.json() == resolved


def test_resolved_carries_the_endpoint_defaults():
    """Prefixed apart from the agent's own fields so the merge cannot clash."""
    database, _ = _mongo_returning(
        {**_STORED, "history_mode": "current_turn", "system_prompt_mode": "omit"}
    )
    with patch.object(svc, "get_database", return_value=database):
        resolved = svc.resolve_auth("org-1", "conn-1")
    assert resolved["endpoint_history_mode"] == "current_turn"
    assert resolved["endpoint_system_prompt_mode"] == "omit"
    assert "history_mode" not in resolved
    assert "system_prompt_mode" not in resolved


def test_resolved_defaults_a_row_written_before_the_modes_existed():
    database, _ = _mongo_returning(dict(_STORED))
    with patch.object(svc, "get_database", return_value=database):
        resolved = svc.resolve_auth("org-1", "conn-1")
    assert resolved["endpoint_history_mode"] == "full"
    assert resolved["endpoint_system_prompt_mode"] == "send"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _response(status_code: int, json_body: object) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_body
    mock.text = str(json_body)
    return mock


def test_pasted_completions_url_is_trimmed_to_the_base():
    """Vendors document the full completions path; the client appends it itself."""
    assert (
        svc.normalise_base_url("http://45.194.2.154:8080/v1/chat/completions")
        == "http://45.194.2.154:8080/v1"
    )
    assert (
        svc.normalise_base_url("https://host/v1/completions/") == "https://host/v1"
    )


def test_probe_lists_models():
    body = {"data": [{"id": "qwen3-8b"}, {"id": "llama-3.1-8b"}]}
    with patch.object(svc.httpx, "get", return_value=_response(200, body)) as mocked:
        result = svc.probe_endpoint("http://vllm.internal:8000/v1", "sk-local")
    assert result["ok"] is True
    assert result["models"] == ["llama-3.1-8b", "qwen3-8b"]
    assert mocked.call_args.kwargs["follow_redirects"] is False
    assert mocked.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-local"


def test_probe_reports_unreachable_endpoint_without_raising():
    with (
        patch.object(svc.httpx, "get", side_effect=httpx.ConnectError("refused")),
        patch.object(svc.httpx, "post", side_effect=httpx.ConnectError("refused")),
    ):
        result = svc.probe_endpoint("http://vllm.internal:8000/v1", "sk-local")
    assert result["ok"] is False
    assert "refused" in result["error"]


def test_probe_reports_http_error_status():
    with (
        patch.object(svc.httpx, "get", return_value=_response(500, "boom")),
        patch.object(svc.httpx, "post", return_value=_response(500, "boom")),
    ):
        result = svc.probe_endpoint("http://vllm.internal:8000/v1", "sk-local")
    # A 5xx from /chat/completions still proves the URL is an OpenAI-shaped API.
    assert result["ok"] is True
    assert "500" in result["note"]


def test_probe_reports_a_redirect_rather_than_following_it():
    """Following one would move the request to a host the guard never checked."""
    response = _response(302, "")
    response.headers = {"location": "http://169.254.169.254/latest"}
    with (
        patch.object(svc.httpx, "get", return_value=response),
        patch.object(svc.httpx, "post", return_value=response),
    ):
        result = svc.probe_endpoint("http://vllm.internal:8000/v1", None)
    assert result["ok"] is False
    assert "redirect" in result["error"].lower()


def test_probe_rejects_blocked_url_before_any_request():
    with patch.object(svc.httpx, "get") as mocked:
        result = svc.probe_endpoint("http://169.254.169.254/v1", None)
    assert result["ok"] is False
    mocked.assert_not_called()


def test_probe_falls_back_to_chat_when_models_is_absent():
    """/models is optional — plenty of servers implement only /chat/completions."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _response(404, {"detail": "Not Found"})

    def fake_post(url, **kwargs):
        calls.append(url)
        assert kwargs["json"]["model"] == "qwen3"
        assert kwargs["json"]["max_tokens"] == 1
        return _response(200, {"choices": [{"message": {"content": "pong"}}]})

    with patch.object(svc.httpx, "get", fake_get), patch.object(svc.httpx, "post", fake_post):
        result = svc.probe_endpoint("http://host:8080/v1", "sk", model="qwen3")

    assert result["ok"] is True
    assert result["models"] == []
    assert "publishes no model list" in result["note"]
    assert calls == ["http://host:8080/v1/models", "http://host:8080/v1/chat/completions"]


def test_probe_reports_a_rejected_key_rather_than_a_generic_failure():
    with (
        patch.object(svc.httpx, "get", return_value=_response(404, "")),
        patch.object(svc.httpx, "post", return_value=_response(401, {"error": "bad key"})),
    ):
        result = svc.probe_endpoint("http://host:8080/v1", "sk")
    assert result["ok"] is False
    assert "rejected the API key" in result["error"]


def test_probe_404_on_both_paths_points_at_the_base_url():
    with (
        patch.object(svc.httpx, "get", return_value=_response(404, "")),
        patch.object(svc.httpx, "post", return_value=_response(404, {"detail": "Not Found"})),
    ):
        result = svc.probe_endpoint("http://host:8080/nope", "sk", model="qwen3")
    assert result["ok"] is False
    assert "No /models and no /chat/completions" in result["error"]


def test_probe_counts_a_rejected_body_as_reachable():
    """A structured complaint still proves the URL is an OpenAI-shaped API."""
    with (
        patch.object(svc.httpx, "get", return_value=_response(404, "")),
        patch.object(
            svc.httpx, "post", return_value=_response(422, {"detail": "model required"})
        ),
    ):
        result = svc.probe_endpoint("http://host:8080/v1", "sk")
    assert result["ok"] is True
    assert "rejected" in result["note"]
