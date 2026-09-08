"""HTTP client for Voicera API (bot token, agents, provider auth)."""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

# Refresh bot JWT a bit before expiry (default API token is 30 minutes).
_TOKEN_TTL_SECONDS = 25 * 60


class BackendError(RuntimeError):
    """Raised when the Voicera API request fails."""


class BackendClient:
    """Thin async client with per-org cached bot JWTs."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}
        self._token_expires_at: dict[str, float] = {}

    def _base(self) -> str:
        return (os.getenv("API_BASE_URL") or "http://localhost:8000/api/v1").rstrip("/")

    async def get_bot_token(self, org_id: str, *, force: bool = False) -> str:
        normalized_org = (org_id or "").strip()
        if not normalized_org:
            raise BackendError("org_id is required")

        now = time.monotonic()
        cached = self._tokens.get(normalized_org)
        expires_at = self._token_expires_at.get(normalized_org, 0.0)
        if not force and cached and now < expires_at:
            return cached

        internal_api_key = os.getenv("INTERNAL_API_KEY", "")
        if not internal_api_key:
            raise BackendError("INTERNAL_API_KEY is not configured")

        url = f"{self._base()}/users/bot/token"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={"X-API-Key": internal_api_key},
                json={"org_id": normalized_org},
            )
        if response.status_code >= 400:
            raise BackendError(
                f"bot/token failed ({response.status_code}): {response.text}"
            )
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise BackendError("bot/token response missing access_token")
        self._tokens[normalized_org] = str(token)
        self._token_expires_at[normalized_org] = now + _TOKEN_TTL_SECONDS
        logger.info("Obtained bot JWT for org_id={}", normalized_org)
        return self._tokens[normalized_org]

    async def _auth_headers(self, org_id: str) -> dict[str, str]:
        token = await self.get_bot_token(org_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def get_agent(self, agent_id: str, org_id: str) -> dict[str, Any]:
        """Fetch one agent document in ``org_id``."""
        url = f"{self._base()}/agents/{agent_id}"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
        if response.status_code == 404:
            raise BackendError(f"Agent not found: {agent_id}")
        if response.status_code >= 400:
            raise BackendError(
                f"GET agent failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def create_inbound_call(
        self,
        org_id: str,
        agent_id: str,
        *,
        provider_call_sid: str,
        from_number: str,
        to_number: str,
    ) -> dict[str, Any]:
        """Register an inbound CallLog when the answer webhook fires."""
        url = f"{self._base()}/calls/inbound"
        headers = await self._auth_headers(org_id)
        payload = {
            "agent_id": agent_id,
            "provider_call_sid": provider_call_sid,
            "from_number": from_number,
            "to_number": to_number,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise BackendError(
                f"POST calls/inbound failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def create_web_call(
        self,
        org_id: str,
        agent_id: str,
        *,
        custom_variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a browser websocket CallLog session."""
        url = f"{self._base()}/calls/web"
        headers = await self._auth_headers(org_id)
        payload: dict[str, Any] = {"agent_id": agent_id}
        if custom_variables:
            payload["custom_variables"] = custom_variables
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise BackendError(
                f"POST calls/web failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def get_call(self, call_id: str, org_id: str) -> dict[str, Any]:
        """Fetch one CallLog document in ``org_id``."""
        url = f"{self._base()}/calls/{call_id}"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
        if response.status_code == 404:
            raise BackendError(f"Call log not found: {call_id}")
        if response.status_code >= 400:
            raise BackendError(
                f"GET call failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def update_call(
        self,
        call_id: str,
        org_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch fields on a CallLog document in ``org_id``."""
        url = f"{self._base()}/calls/{call_id}"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(url, headers=headers, json=patch)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.patch(url, headers=headers, json=patch)
        if response.status_code == 404:
            raise BackendError(f"Call log not found: {call_id}")
        if response.status_code >= 400:
            raise BackendError(
                f"PATCH call failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def upsert_call_metrics(
        self,
        call_id: str,
        org_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT metrics for a call into the CallMetrics collection."""
        url = f"{self._base()}/calls/{call_id}/metrics"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(url, headers=headers, json=body)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.put(url, headers=headers, json=body)
        if response.status_code == 404:
            raise BackendError(f"Call log not found: {call_id}")
        if response.status_code >= 400:
            raise BackendError(
                f"PUT call metrics failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def update_call_by_provider_sid(
        self,
        org_id: str,
        provider_call_sid: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch a CallLog located by provider call SID."""
        sid = quote(provider_call_sid.strip(), safe="")
        url = f"{self._base()}/calls/by-provider-sid/{sid}"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(url, headers=headers, json=patch)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.patch(url, headers=headers, json=patch)
        if response.status_code == 404:
            raise BackendError(f"Call log not found for provider sid: {provider_call_sid}")
        if response.status_code >= 400:
            raise BackendError(
                f"PATCH call by sid failed ({response.status_code}): {response.text}"
            )
        return response.json()

    async def get_provider_auth(self, provider: str, org_id: str) -> dict[str, Any]:
        """Return decrypted auth secrets for ``provider`` (bot JWT is admin)."""
        url = f"{self._base()}/auth/{provider}"
        headers = await self._auth_headers(org_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 401:
            await self.get_bot_token(org_id, force=True)
            headers = await self._auth_headers(org_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
        if response.status_code == 404:
            raise BackendError(
                f"No auth stored for provider '{provider}' in org {org_id}"
            )
        if response.status_code >= 400:
            raise BackendError(
                f"GET auth/{provider} failed ({response.status_code}): {response.text}"
            )
        data = response.json()
        auth = data.get("auth")
        if not isinstance(auth, dict):
            raise BackendError(f"Invalid auth payload for provider '{provider}'")
        return auth

    async def notify_campaign_call_status(
        self,
        org_id: str,
        call_id: str,
        call_response: str | None,
    ) -> None:
        """Notify API campaign processor of terminal call disposition."""
        internal_api_key = os.getenv("INTERNAL_API_KEY", "")
        if not internal_api_key:
            return
        url = f"{self._base()}/campaign/internal/call-status"
        payload = {
            "org_id": org_id,
            "call_id": call_id,
            "call_response": call_response,
        }
        headers = {
            "X-API-Key": internal_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise BackendError(
                f"POST campaign/call-status failed ({response.status_code}): {response.text}"
            )

    async def retrieve_knowledge_chunks(
        self,
        *,
        org_id: str,
        question: str,
        document_ids: list[str] | None = None,
        top_k: int = 5,
        timeout: float = 0.8,
    ) -> list[dict]:
        """Retrieve top-k knowledge chunks for runtime RAG (fail-open)."""
        internal_api_key = os.getenv("INTERNAL_API_KEY", "")
        if not internal_api_key:
            logger.debug("Knowledge retrieval skipped: INTERNAL_API_KEY not set")
            return []

        url = f"{self._base()}/rag/retrieve"
        payload = {
            "org_id": org_id,
            "question": question,
            "top_k": top_k,
            "document_ids": document_ids or [],
        }
        headers = {
            "X-API-Key": internal_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            chunks = data.get("chunks") if isinstance(data, dict) else []
            return chunks if isinstance(chunks, list) else []
        except Exception as exc:
            logger.debug("Knowledge retrieval failed: {}", exc)
            return []


backend_client = BackendClient()
