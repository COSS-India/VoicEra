"""Read a finished call's transcript with an OpenAI-compatible model.

Provider, model and key are settings (``CALL_OUTPUT_LLM_*``), so OpenAI's
``gpt-4.1-mini`` or a self-hosted OpenAI-compatible model both work. With
no settings the step still runs; the fields that need the transcript are
left None.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.services.call_output.bluedots.funnel import DROP_REASONS, Judgement

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You review a finished phone call between a Blue Dots job-matching voice agent "
    "and a job seeker. The call is in Hindi or another Indian language. "
    "Answer only with a JSON object."
)


def _format_transcript(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        who = "AGENT" if turn.get("speaker") == "agent" else "CALLER"
        lines.append(f"{who}: {turn.get('text', '')}")
    return "\n".join(lines)


def build_messages(
    turns: list[dict[str, Any]],
    *,
    facts: dict[str, Any],
    ask_jobs: bool,
    ask_drop: bool,
) -> list[dict[str, str]]:
    questions = []
    if ask_jobs:
        questions.append(
            '"jobs_read_out": true if the agent read out at least one specific job '
            "(employer or role with details) to the caller, false otherwise."
        )
    if ask_drop:
        questions.append(
            '"drop_reason": why the caller did not apply for a job, exactly one of: '
            + ", ".join(DROP_REASONS)
            + "."
        )
    user = (
        "Facts from the system: "
        + json.dumps(facts, ensure_ascii=False)
        + "\n\nTranscript:\n"
        + _format_transcript(turns)
        + "\n\nReturn a JSON object with these keys:\n- "
        + "\n- ".join(questions)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_judgement(content: str, *, model: str, ask_jobs: bool, ask_drop: bool) -> Judgement:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    data: dict[str, Any] = {}
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            data = {}
    jobs = data.get("jobs_read_out") if ask_jobs else None
    drop = data.get("drop_reason") if ask_drop else None
    if drop is not None:
        drop = str(drop).strip().lower()
        if drop not in DROP_REASONS:
            drop = "other"
    return Judgement(
        jobs_read_out=jobs if isinstance(jobs, bool) else None,
        drop_reason=drop or None,
        model=model,
    )


class TranscriptJudge:
    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float, json_mode: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.json_mode = json_mode

    async def judge(
        self,
        client: httpx.AsyncClient,
        turns: list[dict[str, Any]],
        *,
        facts: dict[str, Any],
        ask_jobs: bool,
        ask_drop: bool,
    ) -> Judgement:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": build_messages(turns, facts=facts, ask_jobs=ask_jobs, ask_drop=ask_drop),
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = await client.post(
            f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        content = ((response.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return parse_judgement(content, model=self.model, ask_jobs=ask_jobs, ask_drop=ask_drop)


def judge_from_settings() -> TranscriptJudge | None:
    base_url = (settings.CALL_OUTPUT_LLM_BASE_URL or "").strip()
    model = (settings.CALL_OUTPUT_LLM_MODEL or "").strip()
    if not base_url or not model:
        return None
    return TranscriptJudge(
        base_url=base_url,
        model=model,
        api_key=(settings.CALL_OUTPUT_LLM_API_KEY or "").strip(),
        timeout=settings.CALL_OUTPUT_LLM_TIMEOUT_SECONDS,
        json_mode=settings.CALL_OUTPUT_LLM_JSON_MODE,
    )
