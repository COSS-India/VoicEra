"""Single point of truth for "which LLM can this org actually use right now",
plus one-shot (non-Pipecat, non-streaming) completion dispatch across every
provider family this repo supports.

Used by callers that need a single request/response completion instead of a
live Pipecat pipeline — e.g. transcript translation
(app.services.translation_service). Pipecat's LLM services
(apps/providers/cloud/*/service.py, via factory.create_llm_service) are built
to stream Frames inside a running pipeline; faking that just to get one
string back would be more complex than calling each provider directly, so
this module exists instead of reusing those services.

Reuses the exact primitives GET /configuration/llm already uses for its own
per-org "authenticated" flags (app.services.auth_service.list_configured_providers,
apps.providers.availability.is_authenticated) rather than building a second,
parallel availability system — injected by the caller (see ResolveAuth /
ListConfigured below) rather than imported directly, since apps/providers is
shared by apps/runtime too and must not depend on apps/api's `app` package.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

import httpx
from openai import OpenAI, OpenAIError

from .adapters.kenpath.catalog import (
    BHARAT_VISTAAR_CHAT_MODEL,
    DEFAULT_LLM_MODEL as KENPATH_DEFAULT_MODEL,
    generate_jwt as kenpath_generate_jwt,
    resolve_auth_secret as kenpath_resolve_auth_secret,
    resolve_backend as kenpath_resolve_backend,
    resolve_base_url as kenpath_resolve_base_url,
    resolve_completions_path as kenpath_resolve_completions_path,
)
from . import registry
from .availability import deployed_llm_model_ids, is_authenticated
from .cloud.aws_bedrock.catalog import DEFAULT_LLM_MODEL as BEDROCK_DEFAULT_MODEL
from .cloud.atlascloud.catalog import BASE_URL as ATLASCLOUD_BASE_URL, DEFAULT_LLM_MODEL as ATLASCLOUD_DEFAULT_MODEL
from .cloud.google_vertex.catalog import DEFAULT_LLM_MODEL as VERTEX_DEFAULT_MODEL
from .cloud.groq.catalog import BASE_URL as GROQ_BASE_URL, DEFAULT_LLM_MODEL as GROQ_DEFAULT_MODEL
from .cloud.openai.catalog import DEFAULT_LLM_MODEL as OPENAI_DEFAULT_MODEL
from .cloud.openrouter.catalog import BASE_URL as OPENROUTER_BASE_URL, DEFAULT_LLM_MODEL as OPENROUTER_DEFAULT_MODEL

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 60.0

# provider -> (base_url, default_model). None base_url means the OpenAI SDK
# default endpoint. azure_openai excluded: its base_url is a per-deployment
# path, not a flat one, so it doesn't fit this shape without extra handling.
OPENAI_COMPATIBLE_PROVIDERS: dict[str, tuple[str | None, str]] = {
    "openai": (None, OPENAI_DEFAULT_MODEL),
    "groq": (GROQ_BASE_URL, GROQ_DEFAULT_MODEL),
    "openrouter": (OPENROUTER_BASE_URL, OPENROUTER_DEFAULT_MODEL),
    "atlascloud": (ATLASCLOUD_BASE_URL, ATLASCLOUD_DEFAULT_MODEL),
}
NON_OPENAI_PROVIDERS = ("aws_bedrock", "google_vertex", "kenpath")
LOCAL_MODEL_SERVER_PROVIDER = "voicera_model_server"

ResolveAuth = Callable[[str, str], dict[str, Any]]
ListConfiguredProviders = Callable[[str], list[str]]


class OneShotLLMError(RuntimeError):
    """Raised for expected one-shot LLM call failures (config, provider, or network)."""


def available_providers(
    org_id: str, *, list_configured_providers: ListConfiguredProviders
) -> list[str]:
    """Every LLM provider this org can actually use right now, in priority
    order (OpenAI-compatible first, then the other SDK-driven providers,
    then the self-hosted model-server) — the full candidate list, not just
    the first hit, so a caller can fall through to the next one if a
    higher-priority provider fails at call time (e.g. Kenpath configured
    with a Vistaar/Voice-Bhili model, which can't serve arbitrary one-shot
    prompts — see call_kenpath).

    `list_configured_providers` is injected (e.g. app.services.auth_service
    .list_configured_providers) rather than imported directly — see module
    docstring for why.
    """
    configured = set(list_configured_providers(org_id))
    providers = [p for p in (*OPENAI_COMPATIBLE_PROVIDERS, *NON_OPENAI_PROVIDERS) if p in configured]
    if is_authenticated(LOCAL_MODEL_SERVER_PROVIDER, configured):
        providers.append(LOCAL_MODEL_SERVER_PROVIDER)
    return providers


def call_openai_compatible(
    api_key: str | None,
    base_url: str | None,
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
) -> str:
    """Single chat-completion via any OpenAI-compatible endpoint (OpenAI
    itself, Groq, OpenRouter, AtlasCloud, a self-hosted gateway, ...).

    max_tokens is None by default (provider's own default cap) — callers
    with a large expected output (e.g. transcript translation) must pass an
    explicit value, since a silently-truncated completion is worse than an
    explicit error: apps.api.app.services.translation_service compares
    input/output line counts and raises a "try again" error that cannot
    succeed if the real cause is output truncation, not a translation
    glitch.
    """
    client = OpenAI(api_key=api_key or "not-required", base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS)
    kwargs: dict[str, Any] = {}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    try:
        completion = client.chat.completions.create(
            model=model, temperature=0.1, messages=messages, **kwargs
        )
    except OpenAIError as exc:
        raise OneShotLLMError(f"request to {base_url!r} failed: {exc}") from exc

    choice = completion.choices[0]
    result = (choice.message.content or "").strip()
    if not result:
        raise OneShotLLMError(f"{base_url!r} returned an empty response")
    if choice.finish_reason == "length":
        raise OneShotLLMError(
            f"{base_url!r} truncated its response at max_tokens={max_tokens} "
            "(finish_reason=length) — output was cut off mid-completion, not corrupted"
        )
    return result


def call_via_openai_compatible_provider(
    org_id: str,
    provider: str,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    base_url, default_model = OPENAI_COMPATIBLE_PROVIDERS[provider]
    auth = resolve_auth(org_id, provider)
    try:
        api_key = registry.api_key(auth.get("api_key"))
    except ValueError:
        api_key = None
    if not api_key:
        raise OneShotLLMError(f"Provider {provider!r} has no api_key on file")
    resolved_model = model or default_model
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return (
        call_openai_compatible(api_key, base_url, resolved_model, messages, max_tokens=max_tokens),
        resolved_model,
    )


# qwen3.5-4b's serving context (model-server/models.yaml, mirrored by
# VLLM_MAX_MODEL_LEN in model-server/.env.example) — capped for telephony,
# not the model's native window. Input + max_tokens must fit inside it, or
# vLLM rejects the request outright (a generic 502, not an actionable error).
_LOCAL_MODEL_SERVER_CONTEXT_TOKENS = 8000

def call_local_model_server(
    system: str, user: str, *, model: str | None = None, max_tokens: int | None = None
) -> tuple[str, str]:
    """Zero-credential path: VoicEra's own self-hosted LLM behind
    model-server's OpenAI-compatible gateway, addressed via MODEL_SERVER_URL.

    model-server's deployed LLM slot is configured on model-server's own
    side (LLM_MODEL env var, a different process from this one) — not
    something this API process can read directly. model-server already
    reports the slot it deployed via GET /models (the same endpoint
    apps.providers.availability uses for readiness checks), so that's the
    source of truth here too. Raises rather than falling back to a
    hardcoded default when nothing is reported deployed — a stale/guessed
    model name would 404 against whatever's actually running, exactly the
    failure this resolution logic exists to prevent.
    """
    base_url = (os.getenv("MODEL_SERVER_URL") or "").strip().rstrip("/")
    if not base_url:
        raise OneShotLLMError("MODEL_SERVER_URL is not set")
    if model is not None:
        resolved_model = model
    else:
        deployed = deployed_llm_model_ids()
        if not deployed:
            # model-server is configured (base_url is set) but reports no
            # deployed LLM right now — falling back to a hardcoded literal
            # here would silently 404 against whatever's actually deployed,
            # reproducing the exact bug this model-resolution logic exists
            # to fix. Fail loudly instead so the real cause (model-server
            # still starting up, or its LLM slot not enabled) is visible.
            raise OneShotLLMError(
                f"model-server at {base_url!r} reports no deployed LLM model — it may still "
                "be starting up, or LLM_MODEL/COMPOSE_PROFILES may not include an llm slot"
            )
        # model-server serves exactly one LLM slot; sorted() makes the pick
        # deterministic (not frozenset's undefined iteration order) for the
        # rare instant where more than one entry is momentarily reported,
        # e.g. mid model swap.
        resolved_model = sorted(deployed)[0]
    # Worst case across scripts this product serves: BPE tokenizers commonly
    # split Devanagari/Tamil/etc. near 1 token per char, far worse than
    # Latin's ~4 — so 1 char of input is assumed to cost up to 1 token,
    # keeping this estimate conservative regardless of script.
    estimated_input_tokens = len(system) + len(user)
    remaining_tokens = _LOCAL_MODEL_SERVER_CONTEXT_TOKENS - estimated_input_tokens
    if remaining_tokens <= 0:
        raise OneShotLLMError(
            f"request (~{estimated_input_tokens} input tokens) exceeds the self-hosted "
            f"model's {_LOCAL_MODEL_SERVER_CONTEXT_TOKENS}-token context window — this "
            "transcript is too large for the zero-credential fallback; configure an LLM "
            "provider under Integrations instead"
        )
    # Cap the *requested* max_tokens to what's actually left in the context
    # window rather than rejecting outright — max_tokens is a ceiling on
    # output length, not a promise the model will use all of it, so a large
    # default (e.g. translation's MAX_OUTPUT_TOKENS) shouldn't blanket-reject
    # short requests just because it alone would theoretically exceed the cap.
    effective_max_tokens = min(max_tokens, remaining_tokens) if max_tokens is not None else remaining_tokens
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    result = call_openai_compatible(None, base_url, resolved_model, messages, max_tokens=effective_max_tokens)
    return result, resolved_model


def call_kenpath(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    jwt_subject: str = "one-shot-llm",
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Call Kenpath's Vistaar or Bharat Vistaar backend for a single completion.

    Kenpath isn't OpenAI-compatible — two genuinely different protocols live
    under one provider id (see apps/providers/adapters/kenpath/{llm,
    bharat_vistaar_llm}.py): Bharat Vistaar is an OpenAI-styled chat/
    completions API (messages array), while Vistaar/Voice-Bhili is a
    single-turn query API with no messages concept at all. Forcing both
    through this path means: Bharat Vistaar gets a real messages array;
    Vistaar/Voice-Bhili gets system+user concatenated into its one `query`
    param, a low-fidelity fit but the only option this protocol offers.

    Uses a plain sync httpx client, not the streaming/SSE Pipecat services
    those files implement — this needs one full response, not a live token
    stream.
    """
    model = requested_model or KENPATH_DEFAULT_MODEL
    backend = kenpath_resolve_backend(model)
    auth = resolve_auth(org_id, "kenpath")
    auth_secret_field = kenpath_resolve_auth_secret(model)
    private_key = str(auth.get(auth_secret_field) or "").strip()
    if not private_key:
        raise OneShotLLMError(
            f"Provider 'kenpath' has no {auth_secret_field!r} on file for model {model!r}"
        )

    if backend == "bharatvistaar":
        base_url = kenpath_resolve_base_url(model)
        completions_path = kenpath_resolve_completions_path(model)
        url = f"{base_url}{completions_path}"
        token = kenpath_generate_jwt(private_key, backend=backend, subject=jwt_subject)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        request_body: dict[str, Any] = {
            "model": BHARAT_VISTAAR_CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if max_tokens is not None:
            request_body["max_tokens"] = max_tokens
        try:
            response = httpx.post(url, json=request_body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise OneShotLLMError(f"kenpath (bharatvistaar) request failed: {exc}") from exc
        except ValueError as exc:
            # response.json() raises the stdlib json module's JSONDecodeError
            # (a ValueError subclass), not httpx.HTTPError — a malformed body
            # must still surface as OneShotLLMError so call_first_available's
            # fallback loop advances to the next provider instead of dying.
            raise OneShotLLMError(f"kenpath (bharatvistaar) returned a non-JSON response: {exc}") from exc
        # Non-streaming response contract isn't documented in this repo —
        # tolerate the two shapes that make sense for an OpenAI-styled API:
        # a plain OpenAI chat/completions shape, or a bare {"response": ...}.
        result = ""
        finish_reason = None
        if isinstance(data, dict):
            choices = data.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                message = choices[0].get("message")
                result = str((message or {}).get("content") or "").strip()
                finish_reason = choices[0].get("finish_reason")
            if not result:
                result = str(data.get("response") or "").strip()
        if not result:
            raise OneShotLLMError("kenpath (bharatvistaar) returned an empty response")
        if finish_reason == "length":
            raise OneShotLLMError(
                f"kenpath (bharatvistaar) truncated its response at max_tokens={max_tokens} "
                "(finish_reason=length) — output was cut off mid-completion, not corrupted"
            )
        return result, model

    # vistaar / voice_bhili: this is Kenpath's fixed-pair (source_lang/
    # target_lang) translation API, not a general chat-completion backend —
    # it has no way to honor an arbitrary system+user prompt (e.g. a
    # caller-requested target language embedded in the prompt text). Faking
    # a completion through it by hardcoding source_lang=target_lang="mr"
    # would silently mistranslate any request that isn't actually Marathi,
    # so this path refuses instead of guessing.
    raise OneShotLLMError(
        "kenpath (vistaar/voice_bhili) does not support one-shot completions "
        "with arbitrary prompts; only Bharat Vistaar models are supported here"
    )


def call_bedrock(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """Call AWS Bedrock's Converse API for a single completion.

    boto3 is imported lazily so the API process's import-time footprint and
    cold start are unaffected for the common case (most requests use an
    OpenAI-compatible provider) — see apps/providers/cloud/aws_bedrock/config.py
    for the AWSBedrockAuth shape this reads (aws_access_key, aws_secret_key,
    aws_region).
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    auth = resolve_auth(org_id, "aws_bedrock")
    access_key = str(auth.get("aws_access_key") or "")
    secret_key = str(auth.get("aws_secret_key") or "")
    region = str(auth.get("aws_region") or "us-east-1")
    if not access_key or not secret_key:
        raise OneShotLLMError("Provider 'aws_bedrock' has no aws_access_key/aws_secret_key on file")

    model = requested_model or BEDROCK_DEFAULT_MODEL

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    inference_config: dict[str, Any] = {"temperature": 0.1}
    if max_tokens is not None:
        inference_config["maxTokens"] = max_tokens
    try:
        response = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig=inference_config,
        )
    except (BotoCoreError, ClientError) as exc:
        raise OneShotLLMError(f"aws_bedrock request failed: {exc}") from exc

    try:
        content = response["output"]["message"]["content"]
        result = "".join(block.get("text", "") for block in content).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise OneShotLLMError(f"aws_bedrock returned an unexpected response shape: {exc}") from exc

    if not result:
        raise OneShotLLMError("aws_bedrock returned an empty response")
    if response.get("stopReason") == "max_tokens":
        raise OneShotLLMError(
            f"aws_bedrock truncated its response at max_tokens={max_tokens} "
            "(stopReason=max_tokens) — output was cut off mid-completion, not corrupted"
        )
    return result, model


def call_vertex(
    org_id: str,
    requested_model: str | None,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    max_tokens: int | None = None,
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
        raise OneShotLLMError("Provider 'google_vertex' has no project_id on file")

    model = requested_model or VERTEX_DEFAULT_MODEL

    client_kwargs: dict[str, Any] = {"vertexai": True, "project": project_id, "location": location}
    if credentials_json:
        try:
            info = _json.loads(str(credentials_json))
        except ValueError as exc:
            raise OneShotLLMError(f"google_vertex credentials is not valid JSON: {exc}") from exc
        client_kwargs["credentials"] = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    # Else: falls back to Application Default Credentials.

    generate_config: dict[str, Any] = {"system_instruction": system, "temperature": 0.1}
    if max_tokens is not None:
        generate_config["max_output_tokens"] = max_tokens

    client = genai.Client(**client_kwargs)
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=generate_config,
        )
    except genai_errors.APIError as exc:
        raise OneShotLLMError(f"google_vertex request failed: {exc}") from exc

    result = (response.text or "").strip()
    if not result:
        raise OneShotLLMError("google_vertex returned an empty response")
    candidates = response.candidates or []
    finish_reason = candidates[0].finish_reason if candidates else None
    if finish_reason is not None and finish_reason.value == "MAX_TOKENS":
        raise OneShotLLMError(
            f"google_vertex truncated its response at max_tokens={max_tokens} "
            "(finish_reason=MAX_TOKENS) — output was cut off mid-completion, not corrupted"
        )
    return result, model


def _dispatch(
    provider: str,
    org_id: str,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    jwt_subject: str,
    max_tokens: int | None,
) -> tuple[str, str]:
    """Calls a single provider and returns (model, result). Raises
    OneShotLLMError on failure — callers decide whether to try the next
    candidate or give up."""
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        result, model = call_via_openai_compatible_provider(
            org_id, provider, system, user, resolve_auth=resolve_auth, max_tokens=max_tokens
        )
        return model, result

    if provider == "aws_bedrock":
        result, model = call_bedrock(org_id, None, system, user, resolve_auth=resolve_auth, max_tokens=max_tokens)
        return model, result

    if provider == "google_vertex":
        result, model = call_vertex(org_id, None, system, user, resolve_auth=resolve_auth, max_tokens=max_tokens)
        return model, result

    if provider == "kenpath":
        result, model = call_kenpath(
            org_id,
            None,
            system,
            user,
            resolve_auth=resolve_auth,
            jwt_subject=jwt_subject,
            max_tokens=max_tokens,
        )
        return model, result

    if provider == LOCAL_MODEL_SERVER_PROVIDER:
        result, model = call_local_model_server(system, user, max_tokens=max_tokens)
        return model, result

    raise OneShotLLMError(f"No dispatch implemented for provider {provider!r}")


def call_first_available(
    org_id: str,
    system: str,
    user: str,
    *,
    resolve_auth: ResolveAuth,
    list_configured_providers: ListConfiguredProviders,
    jwt_subject: str = "one-shot-llm",
    max_tokens: int | None = None,
) -> tuple[str, str, str] | None:
    """Tries every provider available_providers() returns, in priority
    order, falling through to the next candidate if one raises
    OneShotLLMError — e.g. an org whose only configured provider is Kenpath
    Vistaar/Voice-Bhili (which can't serve arbitrary one-shot prompts, see
    call_kenpath) still reaches a self-hosted model-server fallback if one
    is reachable, instead of failing outright on the first candidate.

    Returns (provider, model, result), or None if no provider is
    available at all. If every available provider fails, raises a single
    OneShotLLMError whose message lists every provider tried and its own
    failure reason — not just the last one — so a higher-priority
    provider's real, fixable problem (e.g. a revoked key) isn't hidden
    behind a lower-priority provider's unrelated failure."""
    providers = available_providers(org_id, list_configured_providers=list_configured_providers)
    if not providers:
        return None

    errors: list[tuple[str, OneShotLLMError]] = []
    for provider in providers:
        try:
            model, result = _dispatch(
                provider,
                org_id,
                system,
                user,
                resolve_auth=resolve_auth,
                jwt_subject=jwt_subject,
                max_tokens=max_tokens,
            )
        except OneShotLLMError as exc:
            logger.warning("one-shot LLM provider %r failed, trying next: %s", provider, exc)
            errors.append((provider, exc))
            continue
        return provider, model, result

    summary = "; ".join(f"{provider}: {exc}" for provider, exc in errors)
    raise OneShotLLMError(f"every available LLM provider failed — {summary}")
