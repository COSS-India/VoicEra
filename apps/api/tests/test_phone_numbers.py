"""Phone number inventory / attach / detach API and service tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user, verify_api_key
from app.routers import agents, phone_numbers
from app.services import phone_number_service
from app.services.agent_telephony_service import AgentTelephonyError
from app.services.phone_number_service import PhoneNumberError, PhoneNumberNotFoundError

_PHONE_STORE: dict[str, dict[str, Any]] = {}
_AGENT_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }


def _telephony_agent(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "name": "Tel Agent",
        "status": "active",
        "agent_category": "telephony",
        "created_by": "admin@example.com",
        "linked_phone_number": None,
        "telephony": {
            "provider": "vobiz",
            "application_id": "app-123",
            "answer_url": "https://voice.example.com/answer?agent_id=agent-1&org_id=org-1",
        },
        "config": {
            "schema_version": 1,
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Hello!",
            },
            "behaviour": {},
            "language": {"primary": "en", "secondary": []},
            "models": {
                "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
                "tts_config": {
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "voice": "alloy",
                },
                "llm_config": {"provider": "openai", "model": "gpt-4o-mini"},
            },
            "knowledge_base": {"enabled": False, "document_ids": [], "top_k": 5},
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


class _FakeCollection:
    def __init__(self, store: dict[Any, dict[str, Any]], key_fn) -> None:
        self._store = store
        self._key_fn = key_fn

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self._store.values():
            if all(doc.get(k) == v for k, v in query.items() if k != "$ne" and not isinstance(v, dict)):
                ok = True
                for k, v in query.items():
                    if isinstance(v, dict) and "$ne" in v:
                        if doc.get(k) == v["$ne"]:
                            ok = False
                            break
                    elif isinstance(v, dict) and "$nin" in v:
                        if doc.get(k) in v["$nin"]:
                            ok = False
                            break
                    elif doc.get(k) != v:
                        ok = False
                        break
                if ok:
                    return dict(doc)
        return None

    def find(self, query: dict[str, Any]):
        results = [
            dict(doc)
            for doc in self._store.values()
            if all(doc.get(k) == v for k, v in query.items())
        ]

        class _Cursor:
            def sort(self, *_args, **_kwargs):
                return self

            def __iter__(self):
                return iter(results)

        return _Cursor()

    def insert_one(self, doc: dict[str, Any]) -> None:
        key = self._key_fn(doc)
        self._store[key] = dict(doc)

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> MagicMock:
        doc = self.find_one(query)
        result = MagicMock()
        if not doc:
            result.modified_count = 0
            return result
        key = self._key_fn(doc)
        updated = dict(doc)
        if "$set" in update:
            updated.update(update["$set"])
        if "$unset" in update:
            for field in update["$unset"]:
                updated.pop(field, None)
        self._store[key] = updated
        # Re-key if phone_number is the key and still present
        new_key = self._key_fn(updated)
        if new_key != key:
            del self._store[key]
            self._store[new_key] = updated
        result.modified_count = 1
        return result

    def delete_one(self, query: dict[str, Any]) -> MagicMock:
        doc = self.find_one(query)
        result = MagicMock()
        if not doc:
            result.deleted_count = 0
            return result
        del self._store[self._key_fn(doc)]
        result.deleted_count = 1
        return result


def _fake_db() -> dict[str, Any]:
    return {
        "PhoneNumbers": _FakeCollection(
            _PHONE_STORE,
            lambda d: d["phone_number"],
        ),
        "Agents": _FakeCollection(
            _AGENT_STORE,
            lambda d: (d["org_id"], d["agent_id"]),
        ),
    }


def _make_phone_client() -> TestClient:
    app = FastAPI()
    app.include_router(phone_numbers.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[verify_api_key] = lambda: True
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_stores() -> None:
    _PHONE_STORE.clear()
    _AGENT_STORE.clear()


@pytest.mark.asyncio
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_attach_inventory_only(_db: MagicMock) -> None:
    result = await phone_number_service.attach(
        "org-1",
        "+15551234567",
        "vobiz",
        member_email="admin@example.com",
    )
    assert result["status"] == "success"
    assert "+15551234567" in _PHONE_STORE
    assert _PHONE_STORE["+15551234567"]["org_id"] == "org-1"
    assert "agent_id" not in _PHONE_STORE["+15551234567"]


@pytest.mark.asyncio
@patch(
    "app.services.phone_number_service.agent_telephony_service.link_number",
    new_callable=AsyncMock,
)
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_attach_to_agent_links_provider(
    _db: MagicMock,
    link_mock: AsyncMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    result = await phone_number_service.attach(
        "org-1",
        "+15551234567",
        "vobiz",
        agent_id="agent-1",
        member_email="admin@example.com",
    )
    assert result["status"] == "success"
    link_mock.assert_awaited_once_with(
        "org-1", "vobiz", "+15551234567", "app-123"
    )
    assert _PHONE_STORE["+15551234567"]["agent_id"] == "agent-1"
    assert _AGENT_STORE[("org-1", "agent-1")]["linked_phone_number"] == "+15551234567"


@pytest.mark.asyncio
@patch(
    "app.services.phone_number_service.agent_telephony_service.unlink_number",
    new_callable=AsyncMock,
)
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_detach_unlinks_provider(
    _db: MagicMock,
    unlink_mock: AsyncMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(
        linked_phone_number="+15551234567"
    )
    _PHONE_STORE["+15551234567"] = {
        "phone_number": "+15551234567",
        "provider": "vobiz",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    result = await phone_number_service.detach(
        "org-1",
        "+15551234567",
        member_email="admin@example.com",
    )
    assert result["status"] == "success"
    unlink_mock.assert_awaited_once_with("org-1", "vobiz", "+15551234567")
    assert "agent_id" not in _PHONE_STORE["+15551234567"]
    assert _AGENT_STORE[("org-1", "agent-1")]["linked_phone_number"] is None


@pytest.mark.asyncio
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_attach_rejects_provider_mismatch(_db: MagicMock) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    with pytest.raises(PhoneNumberError, match="does not match"):
        await phone_number_service.attach(
            "org-1",
            "+15551234567",
            "plivo",
            agent_id="agent-1",
        )


@pytest.mark.asyncio
@patch(
    "app.services.phone_number_service.agent_telephony_service.link_number",
    new_callable=AsyncMock,
)
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_agent_already_has_number(
    _db: MagicMock,
    _link: AsyncMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(
        linked_phone_number="+15550000001"
    )
    _PHONE_STORE["+15550000001"] = {
        "phone_number": "+15550000001",
        "provider": "vobiz",
        "org_id": "org-1",
        "agent_id": "agent-1",
    }
    with pytest.raises(PhoneNumberError, match="already has a phone number"):
        await phone_number_service.attach(
            "org-1",
            "+15551234567",
            "vobiz",
            agent_id="agent-1",
        )


@patch(
    "app.services.phone_number_service.agent_telephony_service.link_number",
    new_callable=AsyncMock,
)
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
def test_attach_route(_db: MagicMock, link_mock: AsyncMock) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent()
    client = _make_phone_client()
    response = client.post(
        "/api/v1/phone-numbers/attach",
        json={
            "phone_number": "+15551234567",
            "provider": "vobiz",
            "agent_id": "agent-1",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "success"
    link_mock.assert_awaited_once()


@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
def test_list_and_get_by_agent(_db: MagicMock) -> None:
    _PHONE_STORE["+15551234567"] = {
        "phone_number": "+15551234567",
        "provider": "vobiz",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    client = _make_phone_client()
    listed = client.get("/api/v1/phone-numbers")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    by_agent = client.get("/api/v1/phone-numbers/agent/agent-1")
    assert by_agent.status_code == 200
    assert by_agent.json()["phone_number"] == "+15551234567"


@patch(
    "app.routers.phone_numbers.agent_telephony_service.list_provider_numbers",
    new_callable=AsyncMock,
    return_value=["+15551111111", "+15552222222"],
)
def test_provider_inventory_route(list_mock: AsyncMock) -> None:
    client = _make_phone_client()
    response = client.get("/api/v1/phone-numbers/providers/vobiz/inventory")
    assert response.status_code == 200
    assert response.json()["numbers"] == ["+15551111111", "+15552222222"]
    list_mock.assert_awaited_once_with("org-1", "vobiz")


@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
def test_by_phone_route(_db: MagicMock) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(
        linked_phone_number="+15551234567"
    )
    client = _make_phone_client()
    response = client.get("/api/v1/agents/by-phone/+15551234567")
    assert response.status_code == 200
    assert response.json()["agent_id"] == "agent-1"


@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
def test_by_phone_not_found(_db: MagicMock) -> None:
    client = _make_phone_client()
    response = client.get("/api/v1/agents/by-phone/+15550000000")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch(
    "app.services.phone_number_service.agent_telephony_service.unlink_number",
    new_callable=AsyncMock,
)
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_detach_from_agent_clears_link(
    _db: MagicMock,
    unlink_mock: AsyncMock,
) -> None:
    _AGENT_STORE[("org-1", "agent-1")] = _telephony_agent(
        linked_phone_number="+15551234567"
    )
    _PHONE_STORE["+15551234567"] = {
        "phone_number": "+15551234567",
        "provider": "vobiz",
        "org_id": "org-1",
        "agent_id": "agent-1",
    }
    await phone_number_service.detach_from_agent("org-1", "agent-1")
    unlink_mock.assert_awaited_once()
    assert "agent_id" not in _PHONE_STORE["+15551234567"]
    assert _AGENT_STORE[("org-1", "agent-1")]["linked_phone_number"] is None


@pytest.mark.asyncio
@patch(
    "app.services.agent_telephony_service.load_telephony_client",
)
async def test_list_provider_numbers_wrapper(load_client_mock: MagicMock) -> None:
    from app.services.agent_telephony_service import list_provider_numbers

    client = AsyncMock()
    client.list_numbers.return_value = {
        "status": "success",
        "numbers": ["+1"],
    }
    load_client_mock.return_value = client
    numbers = await list_provider_numbers("org-1", "vobiz")
    assert numbers == ["+1"]


@pytest.mark.asyncio
@patch(
    "app.services.agent_telephony_service.load_telephony_client",
)
async def test_link_number_wrapper_raises(load_client_mock: MagicMock) -> None:
    from app.services.agent_telephony_service import link_number

    client = AsyncMock()
    client.link_number.return_value = {"status": "fail", "message": "bad"}
    load_client_mock.return_value = client
    with pytest.raises(AgentTelephonyError, match="bad"):
        await link_number("org-1", "vobiz", "+1555", "app-1")


@pytest.mark.asyncio
@patch("app.services.phone_number_service.get_database", side_effect=_fake_db)
async def test_get_by_agent_not_found(_db: MagicMock) -> None:
    with pytest.raises(PhoneNumberNotFoundError):
        phone_number_service.get_by_agent("org-1", "agent-missing")
