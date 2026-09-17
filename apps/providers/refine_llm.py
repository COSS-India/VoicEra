"""Non-OpenAI-compatible LLM dispatchers used by the prompt-refine endpoint.

Each function here drives a single completion through a protocol the plain
``openai.OpenAI`` client can't speak (Kenpath's JWT-signed Vistaar/Bharat
Vistaar APIs, AWS Bedrock's Converse API, Google Vertex's google-genai SDK).
``resolve_auth`` is injected by the caller (``app.routers.prompt_refine``)
rather than imported, since org-scoped stored-credential lookup is api-layer
concern (``app.services.auth_service``) that this module must not depend on.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from apps.providers.adapters.kenpath.catalog import (
    BHARAT_VISTAAR_CHAT_MODEL,
    BHARAT_VISTAAR_JWT_ISS,
    resolve_auth_secret as kenpath_resolve_auth_secret,
    resolve_backend as kenpath_resolve_backend,
    resolve_base_url as kenpath_resolve_base_url,
    resolve_completions_path as kenpath_resolve_completions_path,
)

REQUEST_TIMEOUT_SECONDS = 30.0

ResolveAuth = Callable[[str, str], dict[str, Any]]


class PromptRefineError(RuntimeError):
    """Raised for expected prompt-refinement failures."""


def _kenpath_generate_jwt(private_key: str, *, model: str) -> str:
    """Mirror apps/providers/adapters/kenpath/{llm,bharat_vistaar_llm}.py's
    own _generate_jwt() — same payload shape, reused here via python-jose
    (already in apps/api/requirements.txt) instead of adding PyJWT as a
    second JWT library for one call site."""
    from jose import jwt as jose_jwt

    now = int(time.time())
    if kenpath_resolve_backend(model) == "bharatvistaar":
        payload = {
            "user_id": "prompt-refine",
            "tenant_id": "prompt-refine",
            "iss": BHARAT_VISTAAR_JWT_ISS,
            "iat": now,
            "exp": now + 3600,
        }
    else:
        payload = {"sub": "prompt-refine", "iss": "voice-provider", "iat": now, "exp": now + 3600}
    return jose_jwt.encode(payload, private_key, algorithm="RS256")


def call_kenpath(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
) -> tuple[str, str]:
    """Call Kenpath's Vistaar or Bharat Vistaar backend for a single completion.

    Kenpath isn't OpenAI-compatible — two genuinely different protocols live
    under one provider id (see apps/providers/adapters/kenpath/{llm,
    bharat_vistaar_llm}.py): Bharat Vistaar is an OpenAI-styled chat/
    completions API (messages array), while Vistaar/Voice-Bhili is a
    single-turn query API with no messages concept at all — built for live
    voice translation, not general prompt rewriting. Forcing both through
    refine means: Bharat Vistaar gets a real messages array; Vistaar/
    Voice-Bhili gets system+user concatenated into its one `query` param,
    which is a low-fidelity fit for an open-ended rewrite task but is what
    was explicitly requested rather than skipping this backend.

    Uses a plain sync httpx.Client, not the streaming/SSE Pipecat services
    those files implement — refine needs one full response, not a live
    token stream.
    """
    from apps.providers.adapters.kenpath.catalog import DEFAULT_LLM_MODEL as KENPATH_DEFAULT_MODEL

    model = requested_model or KENPATH_DEFAULT_MODEL
    backend = kenpath_resolve_backend(model)
    auth = resolve_auth(org_id, "kenpath")
    auth_secret_field = kenpath_resolve_auth_secret(model)
    private_key = str(auth.get(auth_secret_field) or "").strip()
    if not private_key:
        raise PromptRefineError(
            f"Provider 'kenpath' has no {auth_secret_field!r} on file for model {model!r}"
        )

    if backend == "bharatvistaar":
        base_url = kenpath_resolve_base_url(model)
        completions_path = kenpath_resolve_completions_path(model)
        url = f"{base_url}{completions_path}"
        token = _kenpath_generate_jwt(private_key, model=model)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        request_body = {
            "model": BHARAT_VISTAAR_CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        try:
            response = httpx.post(
                url, json=request_body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PromptRefineError(f"kenpath (bharatvistaar) request failed: {exc}") from exc

        data = response.json()
        # Non-streaming response contract isn't documented in this repo —
        # tolerate the two shapes that make sense for an OpenAI-styled API:
        # a plain OpenAI chat/completions shape, or a bare {"response": ...}.
        refined = ""
        if isinstance(data, dict):
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                refined = str((message or {}).get("content") or "").strip()
            if not refined:
                refined = str(data.get("response") or "").strip()
        if not refined:
            raise PromptRefineError("kenpath (bharatvistaar) returned an empty response")
        return refined, model

    # vistaar / voice_bhili: single `query` param, no messages array — force
    # system+user into one string, matching how the streaming service reads
    # extract_last_user_message() but with system instructions prepended
    # since there's no separate system-message slot in this protocol.
    query = f"{system}\n\n{user}"
    # Marathi ("mr") is Vistaar's prod default (apps/providers/adapters/kenpath/
    # config.py's own source_lang/target_lang default) — refine has no
    # language input for kenpath, so this always targets the prod default.
    source_lang = "mr"
    token = _kenpath_generate_jwt(private_key, model=model)
    url = f"{kenpath_resolve_base_url(model)}/api/voice/"
    params = {
        "query": query,
        "source_lang": source_lang,
        "target_lang": source_lang,
        "session_id": "prompt-refine",
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PromptRefineError(f"kenpath (vistaar) request failed: {exc}") from exc

    text = response.text.strip()
    if not text:
        raise PromptRefineError("kenpath (vistaar) returned an empty response")
    return text, model


def call_bedrock(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
) -> tuple[str, str]:
    """Call AWS Bedrock's Converse API for a single completion.

    boto3 is imported lazily (not at module top level) so the API process's
    import-time footprint and cold start are unaffected for the common case
    (most requests use an OpenAI-compatible provider) — see
    apps/providers/cloud/aws_bedrock/config.py for the AWSBedrockAuth shape
    this reads (aws_access_key, aws_secret_key, aws_region).
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    auth = resolve_auth(org_id, "aws_bedrock")
    access_key = str(auth.get("aws_access_key") or "")
    secret_key = str(auth.get("aws_secret_key") or "")
    region = str(auth.get("aws_region") or "us-east-1")
    if not access_key or not secret_key:
        raise PromptRefineError("Provider 'aws_bedrock' has no aws_access_key/aws_secret_key on file")

    model = requested_model or "us.amazon.nova-pro-v1:0"

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    try:
        response = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"temperature": 0.1},
        )
    except (BotoCoreError, ClientError) as exc:
        raise PromptRefineError(f"aws_bedrock request failed: {exc}") from exc

    try:
        content = response["output"]["message"]["content"]
        refined = "".join(block.get("text", "") for block in content).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise PromptRefineError(f"aws_bedrock returned an unexpected response shape: {exc}") from exc

    if not refined:
        raise PromptRefineError("aws_bedrock returned an empty response")
    return refined, model


def call_vertex(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
) -> tuple[str, str]:
    """Call Google Vertex AI's Gemini models for a single completion.

    google-genai (the unified Google GenAI SDK, Vertex mode) is imported
    lazily for the same cold-start reason as call_bedrock's boto3 import —
    see apps/providers/cloud/google_vertex/config.py for the GoogleVertexAuth
    shape this reads (project_id, location, optional credentials JSON).
    """
    import json as _json

    from google import genai
    from google.genai import errors as genai_errors
    from google.oauth2 import service_account

    auth = resolve_auth(org_id, "google_vertex")
    project_id = str(auth.get("project_id") or "")
    location = str(auth.get("location") or "us-central1")
    credentials_json = auth.get("credentials")
    if not project_id:
        raise PromptRefineError("Provider 'google_vertex' has no project_id on file")

    model = requested_model or "gemini-2.0-flash"

    client_kwargs: dict[str, Any] = {"vertexai": True, "project": project_id, "location": location}
    if credentials_json:
        try:
            info = _json.loads(str(credentials_json))
        except ValueError as exc:
            raise PromptRefineError(f"google_vertex credentials is not valid JSON: {exc}") from exc
        client_kwargs["credentials"] = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    # Else: falls back to Application Default Credentials, matching
    # GoogleVertexLLMConfig.credentials' own documented default.

    client = genai.Client(**client_kwargs)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config={"system_instruction": system, "temperature": 0.1},
        )
    except genai_errors.APIError as exc:
        raise PromptRefineError(f"google_vertex request failed: {exc}") from exc

    refined = (response.text or "").strip()
    if not refined:
        raise PromptRefineError("google_vertex returned an empty response")
    return refined, model
