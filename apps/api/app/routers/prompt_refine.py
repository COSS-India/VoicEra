"""Refine a voice-agent system prompt using the agent's own configured LLM."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIError, OpenAI
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services import auth_service

router = APIRouter(prefix="/prompts", tags=["prompts"])

# provider id -> OpenAI-compatible chat/completions base URL.
# Providers not listed here (azure_openai, aws_bedrock, google, google_vertex)
# use a non-OpenAI-compatible SDK/auth shape and are rejected explicitly below.
_OPENAI_COMPATIBLE_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "sarvam": "https://api.sarvam.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "atlascloud": "https://api.atlascloud.ai/v1",
}

_REFINE_SYSTEM_INSTRUCTION = """You rewrite system prompts for real-time voice AI agents. \
Keep the original persona, goal, and guardrails intent unchanged, but rewrite the prompt so it \
performs well when read aloud by a text-to-speech engine and driven by a live, turn-taking \
conversation:

- Responses the agent produces should stay to 1-3 short sentences per turn, one question at a time.
- Never instruct the agent to use markdown, bullet lists, or URLs in its spoken responses.
- Instruct the agent to speak numbers, dates, currency, and phone numbers in natural spoken-word \
form (to avoid TTS mispronunciation).
- Prefer natural spoken connectors over lists when presenting options (at most ~3 options).
- State guardrails as rules that override everything else in the prompt.
- If relevant, include guidance on handling interruptions and backchannel words \
("um", "mm-hmm") without treating them as end-of-turn.
- Keep the prompt itself concise; avoid padding that adds no behavioral guidance.

Return ONLY the rewritten prompt text. Do not include any commentary, headings, or explanation."""


class PromptRefineRequest(BaseModel):
    """Refine request: prompt draft plus the agent's own LLM provider/model."""

    prompt: str = Field(..., min_length=1)
    llm_provider: str = Field(..., min_length=1)
    llm_model: str = Field(..., min_length=1)


class PromptRefineResponse(BaseModel):
    """Rewritten prompt text."""

    refined_prompt: str


class PromptRefineError(RuntimeError):
    """Raised when the configured provider cannot be used to refine a prompt."""


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _resolve_api_key(org_id: str, provider: str) -> str:
    stored = auth_service.get_provider_auth(org_id, provider, mask_secrets=False)
    if stored is None:
        raise PromptRefineError(
            f"No stored credentials for provider {provider!r}. "
            "Configure this provider's API key before refining prompts."
        )
    api_key = stored["auth"].get("api_key")
    if isinstance(api_key, list):
        api_key = api_key[0] if api_key else None
    if not api_key:
        raise PromptRefineError(f"Provider {provider!r} has no api_key on file")
    return str(api_key)


def refine_prompt(
    *,
    org_id: str,
    prompt: str,
    llm_provider: str,
    llm_model: str,
) -> str:
    """Call the agent's own configured LLM to rewrite ``prompt`` for voice."""
    base_url = _OPENAI_COMPATIBLE_BASE_URLS.get(llm_provider)
    if base_url is None:
        raise PromptRefineError(
            f"Prompt refinement is not supported for provider {llm_provider!r} yet."
        )

    api_key = _resolve_api_key(org_id, llm_provider)
    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        completion = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": _REFINE_SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
        )
    except APIError as exc:
        raise PromptRefineError(f"{llm_provider} request failed: {exc}") from exc

    refined = (completion.choices[0].message.content or "").strip()
    if not refined:
        raise PromptRefineError(f"{llm_provider} returned an empty response")
    return refined


@router.post("/refine", response_model=PromptRefineResponse)
async def refine_agent_prompt(
    body: PromptRefineRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> PromptRefineResponse:
    """Rewrite a draft system prompt for voice delivery, via the agent's own LLM."""
    org_id = _require_active_org(current_user)
    try:
        refined = refine_prompt(
            org_id=org_id,
            prompt=body.prompt,
            llm_provider=body.llm_provider,
            llm_model=body.llm_model,
        )
    except PromptRefineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return PromptRefineResponse(refined_prompt=refined)
