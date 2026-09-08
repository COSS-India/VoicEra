"""Optional live telephony integration tests (org 86fee4).

Run only when the API stack, Mongo/FerretDB, and real provider credentials are
available:

    RUN_TELEPHONY_INTEGRATION=1 \\
    TEST_ORG_ID=86fee4 \\
    VOICE_SERVER_BASE_URL=https://voice.example.com \\
    python3 -m pytest apps/api/tests/test_agent_telephony_integration.py -q -p no:flake8
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest

RUN_INTEGRATION = os.getenv("RUN_TELEPHONY_INTEGRATION", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
TEST_ORG_ID = os.getenv("TEST_ORG_ID", "86fee4")
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="Set RUN_TELEPHONY_INTEGRATION=1 to run live telephony tests",
)


def _valid_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "prompts": {
            "system_prompt": "Integration test agent.",
            "greeting_message": "Hello from integration test.",
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
    }


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    if not INTERNAL_API_KEY:
        pytest.skip("INTERNAL_API_KEY is required for integration tests")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{API_BASE}/users/bot/token",
            headers={"X-API-Key": INTERNAL_API_KEY},
            json={"org_id": TEST_ORG_ID},
        )
        response.raise_for_status()
        token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def unique_name() -> str:
    return f"integration-{uuid.uuid4().hex[:8]}"


def test_live_telephony_lifecycle(auth_headers: dict[str, str], unique_name: str) -> None:
    created_ids: list[str] = []
    with httpx.Client(timeout=60.0) as client:
        try:
            # Create vobiz telephony agent
            create = client.post(
                f"{API_BASE}/agents",
                headers=auth_headers,
                json={
                    "name": unique_name,
                    "agent_category": "telephony",
                    "telephony_provider": "vobiz",
                    "config": _valid_config(),
                },
            )
            assert create.status_code == 201, create.text
            agent = create.json()
            agent_id = agent["agent_id"]
            created_ids.append(agent_id)
            assert agent["telephony"] is not None
            assert agent["telephony"]["provider"] == "vobiz"
            assert agent["telephony"]["application_id"]

            # Switch provider to plivo
            patch = client.patch(
                f"{API_BASE}/agents/{agent_id}",
                headers=auth_headers,
                json={"telephony_provider": "plivo"},
            )
            assert patch.status_code == 200, patch.text
            switched = patch.json()
            assert switched["telephony"]["provider"] == "plivo"
            assert switched["telephony"]["application_id"]

            # Switch to websocket (delete telephony app)
            patch_ws = client.patch(
                f"{API_BASE}/agents/{agent_id}",
                headers=auth_headers,
                json={"agent_category": "websocket"},
            )
            assert patch_ws.status_code == 200, patch_ws.text
            assert patch_ws.json()["telephony"] is None

            # Switch back to telephony
            patch_tel = client.patch(
                f"{API_BASE}/agents/{agent_id}",
                headers=auth_headers,
                json={
                    "agent_category": "telephony",
                    "telephony_provider": "vobiz",
                },
            )
            assert patch_tel.status_code == 200, patch_tel.text
            assert patch_tel.json()["telephony"]["provider"] == "vobiz"

            # Create websocket agent (no telephony)
            ws_name = f"{unique_name}-ws"
            ws_create = client.post(
                f"{API_BASE}/agents",
                headers=auth_headers,
                json={
                    "name": ws_name,
                    "agent_category": "websocket",
                    "config": _valid_config(),
                },
            )
            assert ws_create.status_code == 201, ws_create.text
            ws_agent = ws_create.json()
            created_ids.append(ws_agent["agent_id"])
            assert ws_agent["telephony"] is None
        finally:
            for agent_id in created_ids:
                deleted = client.delete(
                    f"{API_BASE}/agents/{agent_id}",
                    headers=auth_headers,
                )
                assert deleted.status_code == 200, deleted.text
