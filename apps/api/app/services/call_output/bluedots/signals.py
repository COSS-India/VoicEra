"""Turn a call's AI DPG log lines into signals.

Only structured lines are read, as Blue Dots asked:

* ``orchestrator.stream_turn_complete`` (agent_core): one per turn, with
  ``next_subagent_id`` (the phase the call moved to), ``intent`` and
  ``tool_used``. Some turns (first turn, fixed lines, goodbye) only have a
  free-text line today; Blue Dots is adding the structured line to every
  turn, so the free text is deliberately ignored.
* ``RestApiAdapter.execute`` (action_gateway): several lines per tool call
  share this ``operation``: a DEBUG ``rest_api_request`` (``status``
  ``pending``), a DEBUG ``rest_api_response`` (``received``), an INFO
  ``rest_api_session_values`` (``success``) and the final INFO
  ``rest_api_execute`` (``success``) or a ``failure`` line such as WARN
  ``rest_api_http_error``. Only the final line counts, so one call is one
  ``ToolCall`` whatever the log level.

  When AI DPG logs at DEBUG, the request line's ``params`` (or the URL's
  query) and the response line's ``body`` (cut at 2,000 characters by AI DPG)
  are kept on the ``ToolCall`` as ``arguments`` and ``result``, matched by
  trace id. They feed the Raya-format transcript only; no ``call_output``
  rule reads them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlparse

from app.services.call_output.bluedots.loki import LogLine

TURN_COMPLETE = "orchestrator.stream_turn_complete"
TOOL_OPERATION = "RestApiAdapter.execute"
TOOL_SUCCESS_BODY = "rest_api_execute"


def tool_outcome(line: LogLine) -> bool | None:
    """True/False for a tool call's final line, None for its other lines."""
    attrs = line.attributes
    if attrs.get("operation") != TOOL_OPERATION or not attrs.get("tool_name"):
        return None
    status = str(attrs.get("status") or "").lower()
    if status == "failure":
        return False
    if status == "success" and line.record.get("body") == TOOL_SUCCESS_BODY:
        return True
    return None  # request, response, session values: not an outcome


@dataclass
class Turn:
    ts_ns: int
    trace_id: str | None
    phase: str | None
    intent: str | None
    tool_used: bool | None


@dataclass
class ToolCall:
    ts_ns: int
    trace_id: str | None
    tool: str
    ok: bool
    error: str | None = None
    # From AI DPG's DEBUG request/response lines, when logged.
    arguments: dict[str, Any] | None = None
    result: str | None = None


def _request_arguments(attrs: dict[str, Any]) -> dict[str, Any]:
    params = attrs.get("params")
    if isinstance(params, dict) and params:
        return dict(params)
    query = urlparse(str(attrs.get("url") or "")).query
    return dict(parse_qsl(query)) if query else {}


def _tool_details(lines: list[LogLine]) -> dict[tuple[str, str], dict[str, Any]]:
    """Request arguments and response body per (trace id, tool name)."""
    details: dict[tuple[str, str], dict[str, Any]] = {}
    for line in lines:
        attrs = line.attributes
        if attrs.get("operation") != TOOL_OPERATION or not attrs.get("tool_name"):
            continue
        key = (str(line.record.get("traceid") or ""), str(attrs["tool_name"]))
        status = str(attrs.get("status") or "").lower()
        if status == "pending":
            details.setdefault(key, {})["arguments"] = _request_arguments(attrs)
        elif status == "received" and attrs.get("body") is not None:
            details.setdefault(key, {})["result"] = str(attrs["body"])
    return details


@dataclass
class CallSignals:
    turns: list[Turn] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)

    @property
    def phases(self) -> list[str]:
        return [turn.phase for turn in self.turns if turn.phase]

    @property
    def last_phase(self) -> str | None:
        phases = self.phases
        return phases[-1] if phases else None

    def reached(self, *phases: str) -> bool:
        wanted = set(phases)
        return any(phase in wanted for phase in self.phases)

    def succeeded(self, tool: str) -> int:
        return sum(1 for call in self.tools if call.tool == tool and call.ok)

    def failed(self, tool: str) -> int:
        return sum(1 for call in self.tools if call.tool == tool and not call.ok)

    @property
    def empty(self) -> bool:
        return not self.turns and not self.tools

    def to_dict(self) -> dict[str, Any]:
        return {
            "phases": self.phases,
            "turns": [asdict(turn) for turn in self.turns],
            "tools": [asdict(call) for call in self.tools],
        }


def extract(lines: list[LogLine]) -> CallSignals:
    signals = CallSignals()
    ordered = sorted(lines, key=lambda item: item.ts_ns)
    details = _tool_details(ordered)
    for line in ordered:
        attrs = line.attributes
        trace_id = line.record.get("traceid")
        if line.record.get("body") == TURN_COMPLETE:
            tool_used = attrs.get("tool_used")
            signals.turns.append(
                Turn(
                    ts_ns=line.ts_ns,
                    trace_id=trace_id,
                    phase=(str(attrs["next_subagent_id"]) if attrs.get("next_subagent_id") else None),
                    intent=(str(attrs["intent"]) if attrs.get("intent") else None),
                    tool_used=bool(tool_used) if tool_used is not None else None,
                )
            )
        elif (outcome := tool_outcome(line)) is not None:
            tool = str(attrs["tool_name"])
            detail = details.get((str(trace_id or ""), tool), {})
            signals.tools.append(
                ToolCall(
                    ts_ns=line.ts_ns,
                    trace_id=trace_id,
                    tool=tool,
                    ok=outcome,
                    error=(str(attrs["error"]) if attrs.get("error") else None),
                    arguments=detail.get("arguments"),
                    result=detail.get("result"),
                )
            )
    return signals
