"""Knowledge base API and agent validation tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user, verify_api_key
from app.models.schemas import AgentConfigPayload, AgentKnowledgeBase
from app.routers import knowledge, rag
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)


def _admin_user() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


def _agent_config(**kb_overrides: Any) -> AgentConfigPayload:
    kb = {
        "enabled": False,
        "mode": "context",
        "document_ids": [],
        "top_k": 5,
    }
    kb.update(kb_overrides)
    return AgentConfigPayload.model_validate(
        {
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
            "knowledge_base": kb,
        }
    )


@pytest.fixture
def knowledge_client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    return TestClient(app)


@pytest.fixture
def rag_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "INTERNAL_API_KEY", "test-internal-key")
    app = FastAPI()
    app.include_router(rag.router, prefix="/api/v1")
    return TestClient(app)


def test_validate_kb_requires_document_ids_when_enabled():
    config = _agent_config(enabled=True, document_ids=[])
    with pytest.raises(AgentConfigValidationError, match="document_ids"):
        validate_agent_config(config, org_id="org-1")


@patch("app.services.knowledge_service.assert_documents_ready")
def test_validate_kb_checks_ready_documents(mock_assert):
    config = _agent_config(
        enabled=True,
        document_ids=["doc-1"],
        mode="context",
    )
    validate_agent_config(config, org_id="org-1")
    mock_assert.assert_called_once_with("org-1", ["doc-1"])


def test_validate_kb_tool_mode_rejects_unsupported_llm():
    config = _agent_config(
        enabled=True,
        document_ids=["doc-1"],
        mode="tool",
    )
    config = config.model_copy(
        update={
            "models": config.models.model_copy(
                update={
                    "llm_config": {
                        "provider": "openrouter",
                        "model": "gpt-4o-mini",
                    }
                }
            )
        }
    )
    with pytest.raises(AgentConfigValidationError, match="function calling"):
        validate_agent_config(config, org_id="org-1")


@patch("app.services.knowledge_service.list_documents", return_value=[])
def test_list_knowledge_documents(_mock_list, knowledge_client: TestClient):
    response = knowledge_client.get("/api/v1/knowledge")
    assert response.status_code == 200
    assert response.json() == []


@patch("app.services.knowledge_service.upload_pdf_to_minio", return_value="k/key.pdf")
@patch("app.services.knowledge_service.create_document_pending", return_value="doc-1")
@patch("app.services.knowledge_service.update_document")
@patch("app.services.knowledge_service.run_ingest_job")
def test_upload_knowledge_pdf(
    _mock_ingest,
    _mock_update,
    _mock_create,
    _mock_upload,
    knowledge_client: TestClient,
):
    response = knowledge_client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("manual.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["document_id"] == "doc-1"
    assert body["status"] == "processing"


def test_upload_rejects_non_pdf(knowledge_client: TestClient):
    response = knowledge_client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


@patch("app.services.knowledge_service.delete_knowledge_document")
def test_delete_knowledge_document(mock_delete, knowledge_client: TestClient):
    response = knowledge_client.delete("/api/v1/knowledge/doc-1")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    mock_delete.assert_called_once_with("org-1", "doc-1")


@patch(
    "app.services.knowledge_service.retrieve_chunks_for_query",
    return_value=[
        {
            "chunk_id": "doc-1_0",
            "document_id": "doc-1",
            "source_filename": "manual.pdf",
            "text": "Return policy is 30 days.",
            "distance": 0.12,
        }
    ],
)
def test_rag_retrieve_requires_api_key(mock_retrieve, rag_client: TestClient):
    missing = rag_client.post(
        "/api/v1/rag/retrieve",
        json={
            "org_id": "org-1",
            "question": "What is the return policy?",
            "document_ids": ["doc-1"],
        },
    )
    assert missing.status_code == 401

    ok = rag_client.post(
        "/api/v1/rag/retrieve",
        json={
            "org_id": "org-1",
            "question": "What is the return policy?",
            "document_ids": ["doc-1"],
        },
        headers={"X-API-Key": "test-internal-key"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert len(body["chunks"]) == 1
    assert body["chunks"][0]["text"] == "Return policy is 30 days."
    mock_retrieve.assert_called_once()


@patch("app.services.knowledge_service.retrieve_chunks_for_query", return_value=[])
def test_rag_retrieve_empty_document_ids_filter(mock_retrieve, rag_client: TestClient):
    rag_client.post(
        "/api/v1/rag/retrieve",
        json={
            "org_id": "org-1",
            "question": "hello",
            "document_ids": [],
        },
        headers={"X-API-Key": "test-internal-key"},
    )
    mock_retrieve.assert_called_once_with(
        org_id="org-1",
        question="hello",
        document_ids=[],
        top_k=5,
    )


def test_agent_knowledge_base_schema_defaults():
    kb = AgentKnowledgeBase()
    assert kb.enabled is False
    assert kb.mode == "context"
    assert kb.top_k == 5
