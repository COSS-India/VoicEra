"""Run Raya's KKB Slim output prompt over a finished call.

The prompt is ``kkb_slim_output.md`` verbatim (Blue Dots' spec). What the
call gives it: the input variables, the AI DPG tool calls and phases from
Loki, and the VoicEra transcript. Provider, model and key are settings
(``CALL_OUTPUT_LLM_*``): any OpenAI-compatible endpoint works.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import httpx

from app.config import settings
from app.services.call_output.bluedots.schema import SPEC_FILE

logger = logging.getLogger(__name__)

SYSTEM_PREAMBLE = (
    "You analyse one finished phone call between the Blue Dots job-seeker voice agent "
    "and a caller. The conversation may be in Kannada, Hindi or English. "
    "Follow the output specification below exactly and answer with one JSON object "
    "and nothing else.\n\n"
    "Notes on this system (they override tool names in the specification):\n"
    "- Tool names: `fetch_jobs` is the job search (the specification's get_jobs; there is no "
    "get_recommended_jobs), `save_profile` is create_profile, `update_profile` updates a "
    "profile, `fetch_services` is get_services, `connect_service` registers a service request, "
    "`apply_job` applies to a job.\n"
    "- Tool calls come without their results; an apply_job call comes with the job_id it "
    "applied to, when logged. "
    "Fill job objects only from what was said in the call, with \"NA\" for any part not said. "
    "The one exception is job_id: an apply_job call's arguments carry the job_id it applied to, "
    "so use it for that job in jobs_applied / jobs_failed_to_apply when it is clear which "
    "spoken job was applied to; otherwise job_id is \"NA\". Never invent a job_id. For "
    "failure_reason use the tool error given in the tool calls.\n"
    "- Transcript lines are speech-to-text and may contain recognition errors.\n\n"
    "OUTPUT SPECIFICATION\n====================\n"
)


@lru_cache(maxsize=1)
def spec_text() -> str:
    return SPEC_FILE.read_text(encoding="utf-8")


def _format_transcript(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        who = "AGENT" if turn.get("speaker") == "agent" else "CALLER"
        lines.append(f"{who}: {turn.get('text', '')}")
    return "\n".join(lines)


def build_messages(
    turns: list[dict[str, Any]],
    *,
    inputs: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    phases: list[str],
) -> list[dict[str, str]]:
    user = (
        "CALL INPUT VARIABLES\n"
        + json.dumps(inputs, ensure_ascii=False)
        + "\n\nTOOL CALLS (in order)\n"
        + json.dumps(tool_calls, ensure_ascii=False)
        + "\n\nCONVERSATION PHASES (in order)\n"
        + json.dumps(phases, ensure_ascii=False)
        + "\n\nTRANSCRIPT\n"
        + _format_transcript(turns)
    )
    return [
        {"role": "system", "content": SYSTEM_PREAMBLE + spec_text()},
        {"role": "user", "content": user},
    ]


class OutputParseError(ValueError):
    """The model did not answer with a JSON object."""


def parse_output(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise OutputParseError("no JSON object in the model's answer")
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise OutputParseError(f"invalid JSON from the model: {exc}") from exc
    if not isinstance(data, dict):
        raise OutputParseError("the model's answer is not a JSON object")
    return data


class OutputExtractor:
    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float, json_mode: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.json_mode = json_mode

    async def extract(
        self,
        client: httpx.AsyncClient,
        turns: list[dict[str, Any]],
        *,
        inputs: dict[str, Any],
        tool_calls: list[dict[str, Any]],
        phases: list[str],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": build_messages(turns, inputs=inputs, tool_calls=tool_calls, phases=phases),
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = await client.post(
            f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        content = ((response.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return parse_output(content)


def extractor_from_settings() -> OutputExtractor | None:
    base_url = (settings.CALL_OUTPUT_LLM_BASE_URL or "").strip()
    model = (settings.CALL_OUTPUT_LLM_MODEL or "").strip()
    if not base_url or not model:
        return None
    return OutputExtractor(
        base_url=base_url,
        model=model,
        api_key=(settings.CALL_OUTPUT_LLM_API_KEY or "").strip(),
        timeout=settings.CALL_OUTPUT_LLM_TIMEOUT_SECONDS,
        json_mode=settings.CALL_OUTPUT_LLM_JSON_MODE,
    )
